"""Pruebas del assembler F2: verificacion fail-closed y append-only."""
from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
import tempfile
import unittest

from pyzig import corpus as corpus_mod
from pyzig.fuzz import assembler


def _fixture(tmp: pathlib.Path, *, tamper: bool = False) -> tuple[pathlib.Path, pathlib.Path]:
    run = tmp / "run"
    run.mkdir()
    corpus_path = tmp / "corpus.jsonl"
    shutil.copyfile(corpus_mod.CORPUS_FILE, corpus_path)

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
        "subject_sha256": "a" * 64,
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


class AssemblerTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
