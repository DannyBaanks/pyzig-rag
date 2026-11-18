"""Rutas estables: raiz del tool (no /tmp para nada persistente)."""
from __future__ import annotations
import os, pathlib

ROOT = pathlib.Path(os.environ.get("PYZIG_ROOT", pathlib.Path(__file__).resolve().parents[1])).resolve()
CORPUS_FILE = ROOT / "corpus" / "pyzig.corpus.jsonl"
VAR = ROOT / "var"
DB = VAR / "pyzig.db"
MODELS = VAR / "models"
BUILD = VAR / "build"
EVAL = ROOT / "eval"
