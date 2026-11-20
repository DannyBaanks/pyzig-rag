"""Recetas de diagnóstico minadas (ola 5): evidencia, firmas y abstención.

Comprueba tres cosas que no cubre `test_signatures.py`:
  1. las 13 recetas nuevas y la PIC están en el corpus con evidencia DEMONSTRATED;
  2. las firmas minadas reetiquetadas resuelven a su receta (y la firma PIC
     genérica, añadida a la receta existente, también);
  3. las cuatro plantillas 100% comodín siguen sin emparejar: se documenta el
     método en las recetas, pero no se falsifica la autoconsistencia.
"""
from __future__ import annotations

import importlib.util
import pathlib
import unittest

from pyzig import check as check_mod
from pyzig import corpus as corpus_mod

ROOT = pathlib.Path(__file__).resolve().parents[1]
NEW_PREFIX = "zig0.16/diag-mined-"
PIC_ID = "zig0.16/build-dynamic-library-pic"
MINED_PIC = (
    "dependency on dynamic library '_' requires enabling Position Independent "
    "Code; fixed by '_' or '_'"
)
# Plantillas con TODOS los huecos comodín: comparten plantilla con recetas
# antiguas. `check.match_signature` se abstiene a propósito.
GENERIC = [
    "root source file struct '_' has no member named '_'",
    "use of undeclared identifier '_'",
    "expected type '_', found '_'",
    "no field or member function named '_' in '_'",
]


def _load_recipes_module():
    path = ROOT / "scripts" / "recipes" / "diag_mined.py"
    spec = importlib.util.spec_from_file_location("pyzig_recipes_diag_mined_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ids(hits):
    return [h["operation_id"] for h in (hits or [])]


class DiagMinedRecipesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.entries = corpus_mod.load()
        cls.by_id = {e.operation_id: e for e in cls.entries}

    def test_13_recetas_nuevas_en_fuente_y_corpus(self) -> None:
        mod = _load_recipes_module()
        ids = [e["operation_id"] for e in mod.ENTRIES]
        self.assertEqual(len(ids), 13)
        self.assertEqual(len(set(ids)), 13)
        self.assertTrue(all(i.startswith(NEW_PREFIX) for i in ids))
        self.assertEqual(sorted(ids), sorted(mod.CONTRACTS))
        self.assertTrue(set(ids).issubset(self.by_id), "faltan recetas en el corpus regenerado")
        # Ninguna de las nuevas debiera tener aliases de búsqueda vacíos.
        self.assertTrue(all(e["aliases"] and e["intent"] for e in mod.ENTRIES))

    def test_evidencia_demonstrated_y_gate_correcto(self) -> None:
        targeted = [e for e in self.entries
                    if e.operation_id.startswith(NEW_PREFIX)
                    or e.operation_id == PIC_ID]
        self.assertEqual(len(targeted), 14)
        for e in targeted:
            with self.subTest(oid=e.operation_id):
                self.assertEqual(e.zig_version, "0.16.0")
                self.assertEqual(e.status, "DEMONSTRATED")
                runs = e.evidence["runs"]
                self.assertTrue(runs)
                self.assertTrue(all(r["exit"] == 0 for r in runs))
                self.assertTrue(all(r["zig_version"] == "0.16.0" for r in runs))
                self.assertFalse(e.fuzz.get("fuzzable"))
                cmd = " ".join(r["cmd"] for r in runs)
                if e.raw.get("gate_mode") == "build":
                    self.assertIn("zig build", cmd)
                    self.assertTrue(e.raw.get("build_files"))
                else:
                    self.assertIn("zig test", cmd)

    def test_etiquetas_minadas_resuelven_a_su_receta(self) -> None:
        labels = (ROOT / "eval" / "mined_labels.tsv").read_text(encoding="utf-8")
        checked = 0
        for line in labels.splitlines():
            sig, oid = line.split("\t")
            if NEW_PREFIX not in oid:
                continue
            checked += 1
            with self.subTest(sig=sig):
                got = _ids(check_mod.suggest_for_message(sig, limit=3))
                self.assertEqual(got[0], oid, f"{sig!r} -> {got}")
        self.assertEqual(checked, 20)

    def test_firma_pic_minada_empareja_la_receta_existente(self) -> None:
        self.assertEqual(_ids(check_mod.match_signature(MINED_PIC)), [PIC_ID])
        self.assertEqual(_ids(check_mod.suggest_for_message(MINED_PIC)), [PIC_ID])
        añadidas = [s for s in self.by_id[PIC_ID].error_signatures
                    if "dependency on dynamic library" in s and "fixed by" in s]
        self.assertEqual(len(añadidas), 1,
                         "la PIC debe declarar una firma concreta del mensaje minado")

    def test_firmas_genericas_se_abstienen(self) -> None:
        for sig in GENERIC:
            with self.subTest(sig=sig):
                self.assertEqual(check_mod.match_signature(sig), [])
                self.assertIsNone(check_mod.suggest_for_message(sig))


if __name__ == "__main__":
    unittest.main()
