"""Los artefactos de fuzzing son evidence, no documentos de busqueda."""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pyzig import corpus as corpus_mod
from pyzig import index as idx
from pyzig import search as search_mod


class IndexTest(unittest.TestCase):
    def test_artifacts_are_gettable_but_not_searchable(self):
        entries = corpus_mod.load()
        artifacts = [e.operation_id for e in entries
                     if e.entry_type in ("case_fixture", "pipeline_entry")]
        self.assertTrue(artifacts, "el corpus debe tener artefactos cosechados")

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "index.db"
            with mock.patch.object(idx, "DB", db), mock.patch.object(idx, "VAR", Path(tmp)):
                idx.build(embed=None)
                con = sqlite3.connect(db)
                n_ops = con.execute("SELECT count(*) FROM ops").fetchone()[0]
                n_fts = con.execute("SELECT count(*) FROM ops_fts").fetchone()[0]
                self.assertEqual(n_ops, len(entries))
                self.assertEqual(n_fts, sum(1 for e in entries
                                            if e.entry_type in idx.SEARCHABLE_TYPES))
                for oid in artifacts:
                    row = con.execute("SELECT payload FROM ops WHERE operation_id=?",
                                      (oid,)).fetchone()
                    self.assertIsNotNone(row, f"pyzig_get debe ver {oid}")
                    self.assertEqual(con.execute(
                        "SELECT count(*) FROM ops_fts WHERE operation_id=?",
                        (oid,)).fetchone()[0], 0)
                con.close()

                # Denominador de coverage = documentos indexados, no `ops`.
                hits = search_mod.search("f-string formateo en Zig", mode="lexical")
                self.assertEqual(hits[0]["operation_id"],
                                 "zig0.16/string-split-strip-format")


if __name__ == "__main__":
    unittest.main()
