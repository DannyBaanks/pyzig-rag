#!/usr/bin/env python3
"""Evaluacion de `pyzig.check.suggest_for_message` (camino de `pyzig_check`) sobre firmas minadas de errores reales.

Dos conjuntos:
  (A) autoconsistencia: cada `error_signatures` del corpus pasado por
      `check.suggest_for_message` (el camino de `check_zig`) debe devolver en
      top-1 una entrada que declare esa firma.
  (B) errores reales: `var/mined/signatures.jsonl` (firmas normalizadas por
      `scripts/mine_sessions.py`) etiquetadas a mano en `eval/mined_labels.tsv`
      (firma<TAB>op_id[,op_id...]|NONE; varias = cualquiera es correcta).
      Metricas: hit@1, hit@3 (sobre las no-NONE), tasa de falsos positivos
      sobre NONE (sugerir con confianza cuando nada aplica).

Salida: `eval/mined_coverage.json` (metricas antes/despues de un cambio en
`pyzig/check.py`). No se escriben cifras a mano en otro sitio.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from pyzig import check as check_mod
from pyzig import corpus as corpus_mod

CORPUS = pathlib.Path("corpus/pyzig.corpus.jsonl")
LABELS = pathlib.Path("eval/mined_labels.tsv")
OUT = pathlib.Path("eval/mined_coverage.json")

def _expected_autocons(entries, signature: str) -> set[str]:
    """(A) Entradas que declaran una firma equivalente (misma plantilla y huecos
    normalizados): una firma compartida por dos recetas acepta cualquiera."""
    key = check_mod.signature_key(signature)
    return {e.operation_id for e in entries
            for sig in (e.error_signatures or []) if check_mod.signature_key(sig) == key}


def _load_labels() -> dict[str, set[str] | None]:
    """firma -> operation_ids aceptables (separados por coma) o None (NONE)."""
    labels: dict[str, set[str] | None] = {}
    for line in LABELS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) != 2:
            raise ValueError(f"{LABELS}: linea mal formada (se esperan 2 campos): {line!r}")
        sig, oid = parts[0].strip(), parts[1].strip()
        labels[sig] = None if oid == "NONE" else {o.strip() for o in oid.split(",") if o.strip()}
    return labels


def _suggest_top(message: str, limit: int = 3) -> list[str]:
    """operation_ids que `check_zig` sugeriria para este mensaje de error (el
    mismo camino: `suggest_for_message`), o [] si se abstiene."""
    hits = check_mod.suggest_for_message(message, zig_version="0.16.0", limit=limit) or []
    return [h["operation_id"] for h in hits]


def _eval_signatures(entries) -> dict:
    """(A) autoconsistencia: cada firma del corpus debe recuperar su entrada en top-1."""
    total = 0
    hit1 = 0
    hit3 = 0
    cases: list[dict] = []
    for e in entries:
        for sig in e.error_signatures:
            total += 1
            got = _suggest_top(sig, limit=3)
            expected = _expected_autocons(entries, sig)
            h1 = bool(got) and got[0] in expected
            h3 = any(o in expected for o in got)
            hit1 += h1
            hit3 += h3
            cases.append({
                "operation_id": e.operation_id,
                "signature": sig,
                "got_top3": got,
                "hit1": h1,
                "hit3": h3,
            })
    return {
        "total": total,
        "hit1": hit1,
        "hit3": hit3,
        "hit1_rate": round(hit1 / total, 4) if total else None,
        "hit3_rate": round(hit3 / total, 4) if total else None,
        "cases": cases,
    }


def _eval_mined(entries, labels: dict[str, set[str] | None]) -> dict:
    """(B) errores reales minados: hit@1/hit@3 contra la ETIQUETA humana (no
    contra lo que el emparejador cree), FPR = sugerir algo cuando la etiqueta
    es NONE. Etiquetas que nombran recetas inexistentes se reportan aparte."""
    known = {e.operation_id for e in entries}
    tp1 = tp3 = 0
    cases: list[dict] = []
    none_cases: list[dict] = []
    unknown_labels: list[str] = []
    fp = 0
    for sig, expected in labels.items():
        got = _suggest_top(sig, limit=3)
        if expected is None:
            fp += bool(got)
            none_cases.append({"signature": sig, "got_top3": got, "false_positive": bool(got)})
            continue
        unknown_labels += sorted(expected - known)
        h1 = bool(got) and got[0] in expected
        h3 = any(o in expected for o in got)
        tp1 += h1
        tp3 += h3
        cases.append({"signature": sig, "label": sorted(expected), "got_top3": got,
                      "hit1": h1, "hit3": h3})
    n = len(cases)
    return {
        "non_none_n": n,
        "hit1": tp1,
        "hit3": tp3,
        "hit1_rate": round(tp1 / n, 4) if n else None,
        "hit3_rate": round(tp3 / n, 4) if n else None,
        "none_n": len(none_cases),
        "false_positives": fp,
        "fpr": round(fp / len(none_cases), 4) if none_cases else None,
        "unknown_labels": unknown_labels,
        "cases": cases,
        "none_cases": none_cases,
    }


def run(before_path: pathlib.Path | None = None) -> dict:
    entries = corpus_mod.load()
    labels = _load_labels()

    # (A) autoconsistencia del corpus
    autocons = _eval_signatures(entries)

    # (B) errores reales minados
    mined = _eval_mined(entries, labels)

    report = {
        "autoconsistencia": autocons,
        "mined_reales": mined,
    }

    if before_path is not None and before_path.exists():
        report["antes"] = json.loads(before_path.read_text(encoding="utf-8"))

    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "autoconsistencia_hit1": autocons["hit1_rate"],
        "autoconsistencia_hit3": autocons["hit3_rate"],
        "mined_hit1": mined["hit1_rate"],
        "mined_hit3": mined["hit3_rate"],
        "mined_fpr": mined["fpr"],
        "mined_non_none": mined["non_none_n"],
        "mined_none": mined["none_n"],
        "mined_false_positives": mined["false_positives"],
    }, ensure_ascii=False))
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--antes", help="ruta a mined_coverage.json previo (antes) para comparar")
    a = ap.parse_args()
    run(pathlib.Path(a.antes) if a.antes else None)
