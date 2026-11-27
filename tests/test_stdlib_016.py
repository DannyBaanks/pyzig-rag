"""Contracts and evidence for the focused Zig 0.16 stdlib recipes."""
from __future__ import annotations

import importlib.util
import pathlib
import unittest

from pyzig import check as check_mod
from pyzig import corpus as corpus_mod

ROOT = pathlib.Path(__file__).resolve().parents[1]
PREFIX = "zig0.16/stdlib016-"
PTRCAST_SIGNATURE = "@ptrCast must have a known result type"
ARRAY_LIST_SIGNATURE = "no field named '_' in struct 'array_list._(uN,null)'"
PTRCAST_RECIPE = "zig0.16/stdlib016-ptrcast-result-type"


def _load_recipes_module():
    path = ROOT / "scripts" / "recipes" / "stdlib_016.py"
    spec = importlib.util.spec_from_file_location("pyzig_recipes_stdlib_016_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ids(hits):
    return [hit["operation_id"] for hit in (hits or [])]


class Stdlib016RecipesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.entries = corpus_mod.load()
        cls.by_id = {entry.operation_id: entry for entry in cls.entries}

    def test_ocho_recetas_nuevas_y_contratos(self) -> None:
        mod = _load_recipes_module()
        ids = [entry["operation_id"] for entry in mod.ENTRIES]
        self.assertEqual(len(ids), 8)
        self.assertEqual(len(set(ids)), 8)
        self.assertTrue(all(operation_id.startswith(PREFIX) for operation_id in ids))
        self.assertEqual(sorted(ids), sorted(mod.CONTRACTS))
        self.assertTrue(all(entry["zig_test"] and entry["aliases"] for entry in mod.ENTRIES))

    def test_ocho_recetas_tienen_evidencia_demostrada(self) -> None:
        targeted = [entry for entry in self.entries if entry.operation_id.startswith(PREFIX)]
        self.assertEqual(len(targeted), 8, "regenera el corpus y corre scripts/run_gates.py")
        for entry in targeted:
            with self.subTest(operation_id=entry.operation_id):
                self.assertEqual(entry.zig_version, "0.16.0")
                self.assertEqual(entry.status, "DEMONSTRATED")
                self.assertTrue(entry.evidence["runs"])
                self.assertTrue(all(run["exit"] == 0 for run in entry.evidence["runs"]))
                self.assertTrue(all(run["zig_version"] == "0.16.0" for run in entry.evidence["runs"]))

    def test_firma_real_ptrcast_resuelve_a_la_receta_y_arraylist_se_abstiene(self) -> None:
        labels = {}
        for line in (ROOT / "eval" / "mined_labels.tsv").read_text(encoding="utf-8").splitlines():
            signature, operation_ids = line.split("\t")
            labels[signature] = operation_ids
        self.assertEqual(labels[PTRCAST_SIGNATURE], PTRCAST_RECIPE)
        self.assertEqual(labels[ARRAY_LIST_SIGNATURE], "NONE")
        self.assertEqual(_ids(check_mod.suggest_for_message(PTRCAST_SIGNATURE)), [PTRCAST_RECIPE])
        self.assertIsNone(check_mod.suggest_for_message(ARRAY_LIST_SIGNATURE))


if __name__ == "__main__":
    unittest.main()
