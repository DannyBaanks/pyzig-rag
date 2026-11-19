"""Tests pequenos y hermeticos del conjunto held-out y de las opciones nuevas de run_eval."""
from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
HELD_OUT = ROOT / "eval" / "heldout_queries.tsv"


def _load_run_eval():
    spec = importlib.util.spec_from_file_location("run_eval_heldout", ROOT / "scripts" / "run_eval.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class HeldOutQueriesTest(unittest.TestCase):
    def test_formato_y_cuotas(self) -> None:
        lines = [ln for ln in HELD_OUT.read_text(encoding="utf-8").splitlines() if ln.strip()]
        self.assertGreaterEqual(len(lines), 60)
        rows = [ln.split("\t") for ln in lines]
        self.assertTrue(all(len(r) == 5 for r in rows), "cada fila debe tener 5 columnas")
        qids = [r[0] for r in rows]
        self.assertEqual(len(qids), len(set(qids)))
        self.assertTrue(all(r[4] in {"POS", "NONE", "VERSION", "STATUS"} for r in rows))
        self.assertGreaterEqual(sum(r[4] == "NONE" for r in rows), 10)
        self.assertGreaterEqual(sum(r[2] and "error:" in r[2] for r in rows), 5)
        self.assertTrue(all(r[3] for r in rows if r[4] == "POS"))
        self.assertTrue(all(not r[3] for r in rows if r[4] == "NONE"))

    def test_expected_ids_existen_en_corpus(self) -> None:
        # Solo leemos operation_id: el resto de campos del corpus quedan fuera.
        ids = set()
        for line in (ROOT / "corpus" / "pyzig.corpus.jsonl").read_text(encoding="utf-8").splitlines():
            if line.strip():
                ids.add(json.loads(line)["operation_id"])
        for ln in HELD_OUT.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                expected = ln.split("\t")[3]
                if expected:
                    self.assertIn(expected, ids)


class RunEvalOptionsTest(unittest.TestCase):
    def test_run_queries_acepta_tsv_externo(self) -> None:
        run_eval = _load_run_eval()
        with tempfile.TemporaryDirectory(prefix="pyzig-heldout-test-") as tmp:
            tsv = pathlib.Path(tmp) / "mini.tsv"
            tsv.write_text("x1\tdirect\tconsulta uno\top/a\tPOS\nx2\tnegative\tconsulta dos\t\tNONE\n",
                           encoding="utf-8")

            def fake_search(q, **kwargs):
                self.assertEqual(kwargs["mode"], "hybrid")
                if q == "consulta uno":
                    return [{"operation_id": "op/a", "status": "DEMONSTRATED"}]
                raise run_eval.s.NoResults(q)

            with mock.patch.object(run_eval.s, "search", side_effect=fake_search):
                rows = run_eval.run_queries("hybrid", tsv)
        self.assertEqual([r["qid"] for r in rows], ["x1", "x2"])
        self.assertTrue(rows[0]["ok_top1"] and rows[0]["ok_top3"])
        self.assertTrue(rows[1]["ok_top1"] and rows[1]["error"] == "NO_RESULTS")
        self.assertEqual(run_eval.summarize(rows)["negativas_correctas"], "1/1")

    def test_cli_expone_flags(self) -> None:
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "run_eval.py"), "--help"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--queries", r.stdout)
        self.assertIn("--out", r.stdout)


if __name__ == "__main__":
    unittest.main()
