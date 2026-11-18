"""Pruebas del warden F3: admit, regress y deteccion de deriva."""
from __future__ import annotations

import pathlib
import tempfile
import unittest
from unittest import mock

from pyzig import corpus as corpus_mod
from pyzig.fuzz import assembler, warden
from test_assembler import _fixture


class WardenTest(unittest.TestCase):
    def test_admit_then_regress(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            run, corpus_path = _fixture(tmp)
            assembler.assemble(run, None, "case_fixture", 1, False, corpus_path)
            self.assertEqual(warden._run("admit", corpus_path, False), 0)
            e = corpus_mod.load(corpus_path)[-1]
            self.assertEqual(e.evidence["status"], "ADMITTED")
            self.assertEqual(corpus_mod.verify_chain(corpus_path), [])

            self.assertEqual(warden._run("regress", corpus_path, False), 0)
            e = corpus_mod.load(corpus_path)[-1]
            self.assertEqual(e.evidence["status"], "ADMITTED")

    def test_driver_drift_is_regressed(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            run, corpus_path = _fixture(tmp)
            ids = assembler.assemble(run, None, "case_fixture", 1, False, corpus_path)
            warden._run("admit", corpus_path, False)
            with mock.patch.object(warden, "_driver_sha", return_value="0" * 64):
                code = warden._run("regress", corpus_path, True)
            self.assertEqual(code, 1)
            e = [x for x in corpus_mod.load(corpus_path) if x.operation_id == ids[0]][0]
            self.assertEqual(e.evidence["status"], "REGRESSED")
            self.assertIn("I6 CLEAN_RUN", e.evidence["warden"]["failed_invariants"])

    def test_tampered_case_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            run, corpus_path = _fixture(tmp)
            ids = assembler.assemble(run, None, "case_fixture", 1, False, corpus_path)
            def tamper(row: dict) -> None:
                row["fuzz"]["case_fixture"]["case_hex"] = "00"
            corpus_mod.update_entry(ids[0], tamper, path=corpus_path)
            code = warden._run("admit", corpus_path, True)
            self.assertEqual(code, 1)
            e = [x for x in corpus_mod.load(corpus_path) if x.operation_id == ids[0]][0]
            self.assertEqual(e.evidence["status"], "REJECTED")
            self.assertIn("I4 FIXTURE_INTEGRITY", e.evidence["warden"]["failed_invariants"])


if __name__ == "__main__":
    unittest.main()
