"""Pruebas del control de campana F4 (cola, politica y presupuesto)."""
from __future__ import annotations

import hashlib
import json
import pathlib
import tempfile
import subprocess
import unittest
from unittest import mock

from pyzig import corpus as corpus_mod
from pyzig.fuzz import campaign, drivers

from _hermetic import HermeticCase, fake_driver
from test_assembler import _fixture


class CampaignTest(HermeticCase):
    def test_queue_prioriza_ops_sin_artefactos(self):
        ops = ("zig0.16/parse-kv-config", "zig0.16/sha256-bytes")
        entries = corpus_mod.load()
        cfg = campaign.CampaignConfig(ops=ops)
        q = campaign.build_queue(cfg, entries)

        counts = {op: 0 for op in ops}
        for e in entries:
            parent = e.operation_id.rsplit("/", 1)[0]
            if (parent in counts and e.entry_type in campaign.warden.AUTO_ADMISSIBLE
                    and e.evidence.get("status") == "ADMITTED"):
                counts[parent] += 1
        expected = sorted(ops, key=lambda op: (counts[op], op))
        self.assertEqual([x["op"] for x in q], expected)
        self.assertEqual([x["admitted_artifacts"] for x in q],
                         [counts[op] for op in expected])

    def test_queue_rechaza_ops_desconocidos(self):
        with self.assertRaises(ValueError):
            campaign.build_queue(campaign.CampaignConfig(ops=("no/existe",)))

    def test_merge_decision_fail_closed(self):
        clean = {"status": "CLEAN", "divergences": 0,
                 "counts": {"EQUIV": 10, "DIVERGENT": 0}}
        self.assertTrue(campaign.merge_decision(clean, True, "case_fixture"))
        known = dict(clean, status="DIVERGENCES_FOUND", divergences=2)
        self.assertTrue(campaign.merge_decision(known, True, "pipeline_entry"))
        self.assertFalse(campaign.merge_decision(known, False, "case_fixture"))
        self.assertFalse(campaign.merge_decision(known, True, "operation"))
        crash = dict(clean, counts={"EQUIV": 9, "CRASH": 1})
        self.assertFalse(campaign.merge_decision(crash, True, "case_fixture"))

    def test_dry_run_sello_y_presupuesto(self):
        cfg = campaign.CampaignConfig(dry_run=True, seed=99, iterations=10,
                                      ops=("zig0.16/sha256-bytes",))
        self.assertEqual(campaign.run_campaign(cfg), 0)
        dirs = sorted(campaign.CAMPAIGN_DIR.glob(f"*-{cfg.seed}"))
        self.assertTrue(dirs)
        report = json.loads((dirs[-1] / "campaign.json").read_text(encoding="utf-8"))
        self.assertEqual(report["summary"]["runs"], 1)
        self.assertTrue(report["results"][0]["plan"])
        digest = (dirs[-1] / "campaign.sha256").read_text(encoding="utf-8").split()[0]
        self.assertEqual(hashlib.sha256((dirs[-1] / "campaign.json").read_bytes()).hexdigest(),
                         digest)

    def test_stage_and_merge_admitted(self):
        with tempfile.TemporaryDirectory() as d:
            run, corpus_path = _fixture(pathlib.Path(d))
            before = len(corpus_mod.load(corpus_path))
            merged, rejected = campaign.stage_and_merge(
                run, "zig0.16/sha256-bytes", ["case_fixture", "pipeline_entry"], 1, corpus_path)
            self.assertEqual(len(merged), 2)
            self.assertEqual(rejected, {})
            entries = corpus_mod.load(corpus_path)
            self.assertEqual(len(entries), before + 2)
            self.assertTrue(all(e.evidence["status"] == "ADMITTED" for e in entries[-2:]))
            self.assertEqual(corpus_mod.verify_chain(corpus_path), [])

    def test_stage_and_merge_never_writes_rejected(self):
        # el warden rechaza (driver con otro fuente): el corpus real no cambia
        with tempfile.TemporaryDirectory() as d:
            run, corpus_path = _fixture(pathlib.Path(d))
            drivers.write_manifest("0.16.0",
                                   {"sha256": dict(fake_driver(), source_sha256="0" * 64)},
                                   replace=True, path=self.manifest)
            before = corpus_path.read_bytes()
            merged, rejected = campaign.stage_and_merge(
                run, "zig0.16/sha256-bytes", ["case_fixture"], 1, corpus_path)
            self.assertEqual(merged, [])
            self.assertEqual(len(rejected), 1)
            self.assertIn("I6 CLEAN_RUN", next(iter(rejected.values())))
            self.assertEqual(corpus_path.read_bytes(), before)

    def _fake_engine(self, returncode: int, status: str | None):
        def run(args, timeout=None):
            if args[0] == "triage":   # todas las divergencias son conocidas
                return subprocess.CompletedProcess(args, 0, "", "")
            run_dir = pathlib.Path(args[args.index("--run-dir") + 1])
            run_dir.mkdir(parents=True, exist_ok=True)
            if status is not None:
                (run_dir / "summary.json").write_text(json.dumps({
                    "status": status, "divergences": 3 if returncode else 0,
                    "counts": {"EQUIV": 7, "DIVERGENT": 3 if returncode else 0}}))
            return subprocess.CompletedProcess(args, returncode, "", "")
        return run

    def _campaign(self, returncode: int, status: str | None) -> dict:
        cfg = campaign.CampaignConfig(seed=5, iterations=10, auto_merge=False,
                                      ops=("zig0.16/sha256-bytes",))
        with mock.patch.object(campaign, "_run_cmd", side_effect=self._fake_engine(returncode, status)):
            campaign.run_campaign(cfg)
        report = sorted(campaign.CAMPAIGN_DIR.glob("*-5"))[-1] / "campaign.json"
        return json.loads(report.read_text(encoding="utf-8"))["results"][0]

    def test_exit_1_with_divergences_is_not_engine_failure(self):
        # el motor sale con 1 cuando hay divergencias (aunque sean conocidas)
        rec = self._campaign(1, "DIVERGENCES_FOUND")
        self.assertNotEqual(rec["verdict"], "ENGINE_FAILED")
        self.assertIn("triage_ok", rec)

    def test_incoherent_or_missing_summary_is_engine_failure(self):
        self.assertEqual(self._campaign(1, "CLEAN")["verdict"], "ENGINE_FAILED")
        self.assertEqual(self._campaign(2, None)["verdict"], "ENGINE_FAILED")


if __name__ == "__main__":
    unittest.main()
