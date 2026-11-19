#!/usr/bin/env python3
"""Evalua la cobertura de firmas de error minadas contra el corpus de pyzig.

Lee `eval/mined_labels.tsv` y, para cada firma, comprueba si existe una entrada
del corpus cuyas `error_signatures` coincidan con la firma (normalizada con
comodines: strings entre comillas, numeros, @Builtin, tipos uN/iN y '_' se
convierten en `*`).

Guarda `eval/mined_coverage.json` con el resumen y el detalle por fila.
"""
from __future__ import annotations

import csv
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from pyzig import corpus as corpus_mod
from pyzig.paths import EVAL

LABELS = EVAL / "mined_labels.tsv"
COVERAGE = EVAL / "mined_coverage.json"

FIELDNAMES = ["firma_raw", "patron_normalizado", "operation_id_esperado", "nivel"]

# Tokens que se normalizan a comodin para el emparejamiento difuso.
_WILDCARD_STR = re.compile(r"'(?:[^']*)'")   # 'cwd' -> '*'
_AT_BUILTIN = re.compile(r"@[A-Za-z_][A-Za-z0-9_]*")  # @Type -> @*
_ZIG_TYPE = re.compile(r"\b[uijf][0-9]+\b")            # u32 -> *
_NUMBER = re.compile(r"\b\d+\b")                       # 4 -> *
_UNDER = re.compile(r"\b_\b")                          # _ -> *


def normalize(sig: str) -> str:
    """Convierte una firma de error en un patron con comodines."""
    s = _WILDCARD_STR.sub("'*'", sig)
    s = _AT_BUILTIN.sub("@*", s)
    s = _ZIG_TYPE.sub("*", s)
    s = _NUMBER.sub("*", s)
    s = _UNDER.sub("*", s)
    return s


def load_entries():
    return corpus_mod.load()


def match_signature(message: str, entries) -> list[str]:
    """Devuelve operation_ids cuyas error_signatures coincidan con el mensaje."""
    pat = normalize(message)
    hits: list[str] = []
    seen: set[str] = set()
    for e in entries:
        for sig in (e.error_signatures or []):
            if normalize(sig) == pat and e.operation_id not in seen:
                seen.add(e.operation_id)
                hits.append(e.operation_id)
    return hits


def main() -> int:
    entries = load_entries()
    rows: list[dict] = []
    with open(LABELS, encoding="utf-8") as f:
        # Saltar lineas de comentario (#) antes de leer el TSV.
        lines = [ln for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
    reader = csv.DictReader(lines, fieldnames=FIELDNAMES, delimiter="\t")
    for row in reader:
        firma = (row.get("firma_raw") or "").strip()
        if not firma:
            continue
        esperado = (row.get("operation_id_esperado") or "").strip()
        nivel = (row.get("nivel") or "").strip()
        hits = match_signature(firma, entries)
        ok = bool(esperado) and esperado in hits
        rows.append({
            "firma": firma,
            "patron": normalize(firma),
            "esperado": esperado or None,
            "nivel": nivel,
            "hits": hits,
            "ok": ok,
        })

    total = len(rows)
    ok_count = sum(1 for r in rows if r["ok"])
    coverage: dict = {
        "total": total,
        "resueltas": ok_count,
        "cobertura": round(ok_count / total, 4) if total else 0.0,
        "por_nivel": {},
        "detalle": rows,
    }
    for nivel in ("alta", "media", "baja"):
        sub = [r for r in rows if r["nivel"] == nivel]
        if sub:
            coverage["por_nivel"][nivel] = {
                "n": len(sub),
                "resueltas": sum(1 for r in sub if r["ok"]),
                "cobertura": round(sum(1 for r in sub if r["ok"]) / len(sub), 4),
            }

    COVERAGE.write_text(json.dumps(coverage, ensure_ascii=False, indent=2), encoding="utf-8")
    resumen = {k: v for k, v in coverage.items() if k != "detalle"}
    print(json.dumps(resumen, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
