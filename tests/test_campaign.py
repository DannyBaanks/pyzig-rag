"""Pruebas del control de campana F4 (cola, politica y presupuesto)."""
from __future__ import annotations

import hashlib
import json
import unittest

from pyzig import corpus as corpus_mod
from pyzig.fuzz import campaign


class CampaignTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
