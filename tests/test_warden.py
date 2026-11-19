"""Pruebas del warden F3: admit, regress, deriva e idempotencia."""
from __future__ import annotations

import json
import pathlib
import tempfile

from pyzig import corpus as corpus_mod
from pyzig.fuzz import assembler, drivers, warden

from _hermetic import HermeticCase, fake_driver
from test_assembler import _fixture


class WardenTest(HermeticCase):
    def _admitted(self, tmp: pathlib.Path) -> tuple[pathlib.Path, list[str]]:
        run, corpus_path = _fixture(tmp)
        ids = assembler.assemble(run, None, "case_fixture", 1, False, corpus_path)
        self.assertEqual(warden._run("admit", corpus_path, False), 0)
        return corpus_path, ids

    def _set_manifest(self, **changes) -> None:
        drivers.write_manifest("0.16.0", {"sha256": dict(fake_driver(), **changes)},
                               replace=True, path=self.manifest)

    def test_admit_then_regress(self):
        with tempfile.TemporaryDirectory() as d:
            corpus_path, _ = self._admitted(pathlib.Path(d))
            e = corpus_mod.load(corpus_path)[-1]
            self.assertEqual(e.evidence["status"], "ADMITTED")
            self.assertEqual(corpus_mod.verify_chain(corpus_path), [])
            self.assertEqual(warden._run("regress", corpus_path, False), 0)
            self.assertEqual(corpus_mod.load(corpus_path)[-1].evidence["status"], "ADMITTED")

    def test_source_drift_is_regressed(self):
        with tempfile.TemporaryDirectory() as d:
            corpus_path, ids = self._admitted(pathlib.Path(d))
            self._set_manifest(source_sha256="0" * 64)
            self.assertEqual(warden._run("regress", corpus_path, True), 1)
            e = [x for x in corpus_mod.load(corpus_path) if x.operation_id == ids[0]][0]
            self.assertEqual(e.evidence["status"], "REGRESSED")
            self.assertIn("I6 CLEAN_RUN", e.evidence["warden"]["failed_invariants"])

    def test_zig_upgrade_is_regressed(self):
        with tempfile.TemporaryDirectory() as d:
            corpus_path, _ = self._admitted(pathlib.Path(d))
            self._set_manifest(zig_version="0.17.0")
            self.assertEqual(warden._run("regress", corpus_path, True), 1)

    def test_rebuild_same_source_is_not_regressed(self):
        # zig build-exe no es reproducible: otro binario del MISMO fuente no
        # cambia el comportamiento y no debe regresar lo admitido.
        with tempfile.TemporaryDirectory() as d:
            corpus_path, _ = self._admitted(pathlib.Path(d))
            self._set_manifest(binary_sha256="9" * 64)
            self.assertEqual(warden._run("regress", corpus_path, True), 0)

    def test_missing_manifest_is_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            corpus_path, _ = self._admitted(pathlib.Path(d))
            self.manifest.unlink()
            self.assertEqual(warden._run("regress", corpus_path, True), 1)

    def test_admit_and_regress_are_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            corpus_path, _ = self._admitted(pathlib.Path(d))
            before = corpus_path.read_bytes()
            self.assertEqual(warden._run("admit", corpus_path, False), 0)
            self.assertEqual(warden._run("admit", corpus_path, True), 0)
            self.assertEqual(warden._run("regress", corpus_path, False), 0)
            self.assertEqual(corpus_path.read_bytes(), before)

    def test_tampered_case_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            run, corpus_path = _fixture(pathlib.Path(d))
            ids = assembler.assemble(run, None, "case_fixture", 1, False, corpus_path)

            def tamper(row: dict) -> None:
                row["fuzz"]["case_fixture"]["case_hex"] = "00"
            corpus_mod.update_entry(ids[0], tamper, path=corpus_path)
            self.assertEqual(warden._run("admit", corpus_path, True), 1)
            e = [x for x in corpus_mod.load(corpus_path) if x.operation_id == ids[0]][0]
            self.assertEqual(e.evidence["status"], "REJECTED")
            self.assertIn("I4 FIXTURE_INTEGRITY", e.evidence["warden"]["failed_invariants"])

    def test_reports_stay_out_of_real_var(self):
        with tempfile.TemporaryDirectory() as d:
            self._admitted(pathlib.Path(d))
            self.assertTrue((self.var / "warden" / "admit.json").exists())

    def test_same_case_in_another_op_is_not_duplicate(self):
        with tempfile.TemporaryDirectory() as d:
            corpus_path, ids = self._admitted(pathlib.Path(d))
            twin = corpus_mod.load(corpus_path)[-1].raw
            twin = dict(twin, operation_id=ids[0].replace("sha256-bytes", "otro-op"))
            seen: set = set()
            by_id = {e.operation_id: e for e in corpus_mod.load(corpus_path)}
            first = warden.check_entry(by_id[ids[0]], by_id, seen, set())
            other = corpus_mod.Entry(**{**corpus_mod.load(corpus_path)[-1].__dict__,
                                        "operation_id": twin["operation_id"]})
            again = warden.check_entry(other, by_id, seen, set())
            self.assertNotIn("I7 NO_DUPLICATE_CASE", first)
            self.assertNotIn("I7 NO_DUPLICATE_CASE", again)

    def test_duplicate_of_admitted_is_rejected_by_admit(self):
        with tempfile.TemporaryDirectory() as d:
            corpus_path, ids = self._admitted(pathlib.Path(d))
            dup = dict(corpus_mod.load(corpus_path)[-1].raw)
            dup["operation_id"] = ids[0] + "-dup"
            dup["evidence"] = dict(dup["evidence"], status="FUZZ_EQUIV")
            corpus_mod.append_entry(dup, path=corpus_path)
            self.assertEqual(warden._run("admit", corpus_path, False), 1)
            e = corpus_mod.load(corpus_path)[-1]
            self.assertEqual(e.evidence["status"], "REJECTED")
            self.assertIn("I7 NO_DUPLICATE_CASE", e.evidence["warden"]["failed_invariants"])


class ManifestTest(HermeticCase):
    def test_prepare_only_merges_instead_of_replacing(self):
        kv = dict(fake_driver("kv"), source_sha256="d" * 64)
        drivers.write_manifest("0.16.0", {"kv": kv}, replace=False, path=self.manifest)
        data = json.loads(self.manifest.read_text(encoding="utf-8"))
        self.assertEqual(sorted(data["drivers"]), ["kv", "sha256"])
        drivers.write_manifest("0.16.0", {"kv": kv}, replace=True, path=self.manifest)
        data = json.loads(self.manifest.read_text(encoding="utf-8"))
        self.assertEqual(sorted(data["drivers"]), ["kv"])
