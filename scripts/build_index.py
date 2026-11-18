#!/usr/bin/env python3
"""Reconstruye el indice desde corpus/pyzig.corpus.jsonl (idempotente)."""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from pyzig import index
from pyzig.embed import Embedder

if __name__ == "__main__":
    verbose = "-q" not in sys.argv
    emb = Embedder()
    if emb.degraded:
        print(f"AVISO: backend de embeddings no disponible ({emb.mode}); "
              "el indice queda solo lexical (no es busqueda semantica)")
    index.build(emb, verbose=verbose)
