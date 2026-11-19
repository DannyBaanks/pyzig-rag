#!/usr/bin/env python3
"""Extraccion ciega para escribir eval/heldout_queries.tsv.

Imprime SOLO operation_id + name + intent de corpus/pyzig.corpus.jsonl.
No lee aliases, error_signatures, eval/queries.tsv ni consultas de recipes.
"""
import json
import pathlib

CORPUS = pathlib.Path(__file__).resolve().parents[1] / "corpus" / "pyzig.corpus.jsonl"

for line in CORPUS.read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    e = json.loads(line)
    print("\t".join([e.get("operation_id", ""), e.get("name", ""), e.get("intent", "")]))
