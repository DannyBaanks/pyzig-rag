"""Regla de admision del modo hybrid (pyzig/search.py::admits).

Unit tests puros (hermeticos). El test de integracion usa el indice real
var/pyzig.db solo si existe; si no, se salta (no lo construye ni lo escribe).
"""
from __future__ import annotations

import pathlib
import unittest

from pyzig import search as s

ROOT = pathlib.Path(__file__).resolve().parents[1]


class AdmitsRule(unittest.TestCase):
    def test_cobertura_basta_sin_coseno(self):
        self.assertTrue(s.admits(0.40, 0.0))
        self.assertTrue(s.admits(0.60, 0.10))

    def test_coseno_solo_no_admite(self):
        # MiniLM da 0.35-0.59 a negativas (calib); sin respaldo lexico no entra
        self.assertFalse(s.admits(0.0, 0.59))
        self.assertFalse(s.admits(0.20, 0.55))

    def test_coseno_con_respaldo_lexico_admite(self):
        self.assertTrue(s.admits(0.33, 0.40))
        self.assertTrue(s.admits(0.50, 0.41))

    def test_coseno_bajo_umbral_no_admite(self):
        self.assertFalse(s.admits(0.35, 0.39))
        self.assertFalse(s.admits(0.32, 0.45))

    def test_constantes_calibradas(self):
        self.assertEqual(s.COV_MIN, 0.40)
        self.assertEqual(s.COS_MIN, 0.40)
        self.assertEqual(s.COS_COV_MIN, 0.33)


@unittest.skipUnless((ROOT / "var" / "pyzig.db").exists(),
                     "sin var/pyzig.db: integracion omitida (scripts/build_index.py la crea)")
class HybridRejectsCalibNegatives(unittest.TestCase):
    """Negativas de eval/calib_queries.tsv que la regla nueva rechaza (NO_RESULTS)."""

    QUERIES = [
        "pandas agrupar un dataframe por columna y sumar los valores de cada grupo",
        "dibujar un grafico de lineas con matplotlib y su leyenda",
        "entrenar un modelo de regresion logistica con scikit-learn y medir su precision",
        "fine-tuning de un transformer con pytorch usando la gpu",
        "consultas de django orm con select_related y prefetch_related",
    ]

    def test_rechaza(self):
        for q in self.QUERIES:
            with self.subTest(q=q):
                with self.assertRaises(s.NoResults):
                    s.search(q, zig_version="0.16.0", platform="linux", limit=3, mode="hybrid")


if __name__ == "__main__":
    unittest.main()
