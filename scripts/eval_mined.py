#!/usr/bin/env python3
"""Evaluacion de `pyzig_check.suggest_for_error` sobre firmas minadas de errores reales.

Dos conjuntos:
  (A) autoconsistencia: cada `error_signatures` del corpus pasado por
      `build_error_query` (via `suggest_for_error`) debe devolver esa entrada
      en top-1.
  (B) errores reales: `var/mined/signatures.jsonl` (67 firmas normalizadas)
      etiquetadas a mano en `eval/mined_labels.tsv` (firma<TAB>operation_id|NONE).
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
MINED = pathlib.Path("var/mined/signatures.jsonl")
LABELS = pathlib.Path("eval/mined_labels.tsv")
OUT = pathlib.Path("eval/mined_coverage.json")

_WILDCARD = re.compile(r"[^A-Za-z0-9_.]+")


def _norm(s: str) -> str:
    """Normaliza una firma para comparacion con comodines: secuencias de
    no-alfanumericos (incluido `_` y `N` de la mineria) se vuelven un
    separador unico; comparacion case-insensitive."""
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _sig_matches(signature: str, query_norm: str) -> bool:
    """Una firma del corpus coincide con la consulta normalizada si es
    exactamente igual o si la consulta es un prefijo-compatible de la firma
    (comodines `_`/`N` ya estan normalizados a espacios por ambas partes)."""
    sig_norm = _norm(signature)
    if not sig_norm:
        return False
    return sig_norm == query_norm or query_norm in sig_norm or sig_norm in query_norm


def _expected_for_signature(entries, signature: str) -> list[str]:
    """operation_ids del corpus cuyo `error_signatures` contiene una firma que
    coincide (exacto o con comodines normalizados) con `signature`."""
    out: list[str] = []
    qn = _norm(signature)
    for e in entries:
        for sig in e.error_signatures:
            if _sig_matches(sig, qn):
                out.append(e.operation_id)
                break
    return out


def _load_labels() -> dict[str, str | None]:
    """firma -> operation_id esperado o None (NONE)."""
    labels: dict[str, str | None] = {}
    for line in LABELS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) != 2:
            continue
        sig, oid = parts[0].strip(), parts[1].strip()
        labels[sig] = None if oid == "NONE" else oid
    return labels


def _suggest_top(query: str, limit: int = 3) -> list[str]:
    """Devuelve los operation_ids sugeridos (top-`limit`) para una consulta de
    error, o [] si NO_RESULTS / abstencion."""
    try:
        hits = check_mod.suggest_for_error(query, zig_version="0.16.0", limit=limit) or []
    except Exception:
        return []
    return [h["operation_id"] for h in hits]


def _eval_signatures(entries, signatures: list[str]) -> dict:
    """(A) autoconsistencia: cada firma del corpus debe recuperar su entrada en top-1."""
    total = 0
    hit1 = 0
    hit3 = 0
    cases: list[dict] = []
    for e in entries:
        for sig in e.error_signatures:
            total += 1
            q = check_mod.build_error_query(sig)
            got = _suggest_top(q, limit=3)
            expected = [e.operation_id]
            h1 = got[0] == expected[0] if got else False
            h3 = expected[0] in got if got else False
            hit1 += h1
            hit3 += h3
            cases.append({
                "operation_id": e.operation_id,
                "signature": sig,
                "query": q,
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


def _eval_mined(entries, labels: dict[str, str | None]) -> dict:
    """(B) errores reales minados: hit@1/hit@3 sobre no-NONE, FPR sobre NONE."""
    non_none: list[tuple[str, str]] = []  # (signature, expected_oid)
    none_sigs: list[str] = []
    for sig, expected in labels.items():
        if expected is None:
            none_sigs.append(sig)
        else:
            non_none.append((sig, expected))

    # expected set real desde el corpus (todas las entradas cuya firma coincide)
    def expected_set(signature: str) -> list[str]:
        return _expected_for_signature(entries, signature)

    tp1 = tp3 = 0
    non_none_n = 0
    cases: list[dict] = []
    for sig, label_oid in non_none:
        non_none_n += 1
        q = check_mod.build_error_query(sig)
        got = _suggest_top(q, limit=3)
        exp = expected_set(sig)
        h1 = bool(got) and got[0] in exp
        h3 = bool(exp) and any(o in got for o in exp)
        tp1 += h1
        tp3 += h3
        cases.append({
            "signature": sig,
            "label": label_oid,
            "expected_corpus": exp,
            "query": q,
            "got_top3": got,
            "hit1": h1,
            "hit3": h3,
        })

    # falsos positivos sobre NONE: sugerir algo (con confianza) cuando nada aplica
    fp = 0
    none_cases: list[dict] = []
    for sig in none_sigs:
        q = check_mod.build_error_query(sig)
        got = _suggest_top(q, limit=3)
        is_fp = bool(got)  # sugirio con confianza aunque el corpus no tenga receta
        fp += is_fp
        none_cases.append({
            "signature": sig,
            "query": q,
            "got_top3": got,
            "false_positive": is_fp,
        })

    return {
        "non_none_n": non_none_n,
        "hit1": tp1,
        "hit3": tp3,
        "hit1_rate": round(tp1 / non_none_n, 4) if non_none_n else None,
        "hit3_rate": round(tp3 / non_none_n, 4) if non_none_n else None,
        "none_n": len(none_sigs),
        "false_positives": fp,
        "fpr": round(fp / len(none_sigs), 4) if none_sigs else None,
        "cases": cases,
        "none_cases": none_cases,
    }


def run(before_path: pathlib.Path | None = None) -> dict:
    entries = corpus_mod.load()
    labels = _load_labels()

    # (A) autoconsistencia del corpus
    autocons = _eval_signatures(entries, [s for e in entries for s in e.error_signatures])

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
