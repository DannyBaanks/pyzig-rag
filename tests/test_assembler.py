"""Pruebas del assembler F2: verificacion fail-closed y append-only."""
from __future__ import annotations

import hashlib
import json
import pathlib
import tempfile
import unittest

from pyzig import corpus as corpus_mod
from pyzig.fuzz import assembler

from _hermetic import FAKE_BINARY, HermeticCase, fake_driver


def _fixture(tmp: pathlib.Path, *, tamper: bool = False,
             driver: dict | None = None) -> tuple[pathlib.Path, pathlib.Path]:
    """Run sintetico + copia del corpus SOLO con recetas (sin los artefactos
    reales: el test no depende del estado del corpus ni de var/)."""
    run = tmp / "run"
    run.mkdir()
    corpus_path = tmp / "corpus.jsonl"
    rows = [r for r in corpus_mod._read_raw(corpus_mod.CORPUS_FILE)
            if r.get("entry_type") in ("recipe", "gap")]
    corpus_path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                           encoding="utf-8")
    (run / "driver.json").write_text(json.dumps(driver or fake_driver()), encoding="utf-8")

    case = bytes.fromhex("0400000061626364")
    obs = bytes.fromhex("020000006f6b000000000400000061626364")
    rows = [{
        "i": 0,
        "case_sha256": hashlib.sha256(case).hexdigest(),
        "case": case.hex(),
        "status": "ok",
        "obs_sha256": hashlib.sha256(obs).hexdigest(),
        "obs": obs.hex(),
    }]
    equiv = ("\n".join(json.dumps(r) for r in rows) + "\n").encode()
    digest = hashlib.sha256(equiv).hexdigest()
    if tamper:
        equiv = equiv.replace(b"61626364", b"61626365")
    (run / "equiv.jsonl").write_bytes(equiv)
    (run / "harvest.json").write_text(json.dumps({
        "kind": "fuzz-harvest-v1",
        "op": "zig0.16/sha256-bytes",
        "schema": "sha256",
        "fields": "status,error,digest",
        "seed": 1337,
        "iterations": 10,
        "subject_sha256": FAKE_BINARY,
        "results_sha256": "b" * 64,
        "equiv_stored": 1,
        "equiv_sha256": digest,
        "equiv_file": "equiv.jsonl",
    }), encoding="utf-8")
    (run / "summary.json").write_text(json.dumps({
        "counts": {"EQUIV": 10, "DIVERGENT": 0, "CRASH": 0, "TIMEOUT": 0,
                   "INCONCLUSIVE": 0, "NONDETERMINISTIC": 0, "INVALID_ACCEPTED": 0},
    }), encoding="utf-8")
    (run / "meta.json").write_text(json.dumps({"sandbox": "bwrap"}), encoding="utf-8")
    return run, corpus_path


class AssemblerTest(HermeticCase):
    def test_append_only_and_hash_chain(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            run, corpus_path = _fixture(tmp)
            before = len(corpus_mod.load(corpus_path))
            ids = assembler.assemble(run, None, "case_fixture", 1, False, corpus_path)
            self.assertEqual(len(ids), 1)
            entries = corpus_mod.load(corpus_path)
            self.assertEqual(len(entries), before + 1)
            self.assertEqual(entries[-1].operation_id, ids[0])
            self.assertTrue(entries[-1].fuzz["auto_admissible"])
            self.assertEqual(entries[-1].evidence["status"], "FUZZ_EQUIV")
            self.assertEqual(corpus_mod.verify_chain(corpus_path), [])

            # idempotente: el mismo caso no se anade dos veces
            again = assembler.assemble(run, None, "case_fixture", 1, False, corpus_path)
            self.assertEqual(again, [])
            self.assertEqual(len(corpus_mod.load(corpus_path)), before + 1)

    def test_tampered_harvest_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            run, corpus_path = _fixture(tmp, tamper=True)
            before = len(corpus_mod.load(corpus_path))
            with self.assertRaises(assembler.HarvestError):
                assembler.assemble(run, None, "case_fixture", 1, False, corpus_path)
            self.assertEqual(len(corpus_mod.load(corpus_path)), before)

    def test_operation_is_not_auto_admissible(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            run, corpus_path = _fixture(tmp)
            ids = assembler.assemble(run, None, "operation", 1, False, corpus_path)
            e = corpus_mod.load(corpus_path)[-1]
            self.assertEqual(e.operation_id, ids[0])
            self.assertFalse(e.fuzz["auto_admissible"])

    def test_snapshot_records_stable_driver_identity(self):
        with tempfile.TemporaryDirectory() as d:
            run, corpus_path = _fixture(pathlib.Path(d))
            ids = assembler.assemble(run, None, "case_fixture", 1, False, corpus_path)
            snap = corpus_mod.load(corpus_path)[-1].evidence["runs"][0]["run_snapshot"]
            self.assertEqual(snap["driver_source_sha256"], fake_driver()["source_sha256"])
            self.assertEqual(snap["driver_zig_version"], fake_driver()["zig_version"])
            self.assertTrue(ids)

    def test_driver_json_must_match_binary_that_ran(self):
        with tempfile.TemporaryDirectory() as d:
            other = dict(fake_driver(), binary_sha256="f" * 64)
            run, corpus_path = _fixture(pathlib.Path(d), driver=other)
            assembler.assemble(run, None, "case_fixture", 1, False, corpus_path)
            snap = corpus_mod.load(corpus_path)[-1].evidence["runs"][0]["run_snapshot"]
            self.assertEqual(snap["driver_source_sha256"], "")

    def test_non_ok_equiv_rows_are_skipped_not_fatal(self):
        with tempfile.TemporaryDirectory() as d:
            run, corpus_path = _fixture(pathlib.Path(d))
            err_case, err_obs = b"\x00", b"\x03\x00\x00\x00err"
            rows = [json.loads(l) for l in (run / "equiv.jsonl").read_text().splitlines()]
            rows.insert(0, {"i": 9, "case": err_case.hex(), "obs": err_obs.hex(), "status": "err",
                            "case_sha256": hashlib.sha256(err_case).hexdigest(),
                            "obs_sha256": hashlib.sha256(err_obs).hexdigest()})
            equiv = ("\n".join(json.dumps(r) for r in rows) + "\n").encode()
            (run / "equiv.jsonl").write_bytes(equiv)
            meta = json.loads((run / "harvest.json").read_text())
            meta.update(equiv_stored=2, equiv_sha256=hashlib.sha256(equiv).hexdigest())
            (run / "harvest.json").write_text(json.dumps(meta))
            ids = assembler.assemble(run, None, "case_fixture", 1, False, corpus_path)
            self.assertEqual(len(ids), 1)   # el limite cuenta solo filas ok
            fx = corpus_mod.load(corpus_path)[-1].fuzz["case_fixture"]
            self.assertEqual(fx["status"], "ok")


if __name__ == "__main__":
    unittest.main()
