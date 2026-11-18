#!/usr/bin/env python3
"""Eval fija: compara recuperacion lexical vs hibrida sobre eval/queries.tsv."""
import json, pathlib, statistics, sys, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from pyzig import search as s
from pyzig.paths import EVAL

def run_queries(mode: str) -> list[dict]:
    out = []
    for line in (EVAL / "queries.tsv").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        qid, kind, q, expected, expect = line.split("\t")
        zv = "0.13" if kind == "version" else "0.16.0"
        t0 = time.perf_counter()
        try:
            rs = s.search(q, zig_version=zv, platform="linux", limit=3, mode=mode)
            got, err = [r["operation_id"] for r in rs], None
            top_status = rs[0]["status"] if rs else None
        except s.NoResults as e:
            got, err, top_status = [], "NO_RESULTS", None
        except s.VersionMismatch as e:
            got, err, top_status = [], "VERSION_MISMATCH", None
        dt = (time.perf_counter() - t0) * 1000
        ok = False
        if expect == "POS":
            ok = bool(got) and got[0] == expected
            ok3 = expected in got
        elif expect == "NONE":
            ok = err == "NO_RESULTS"
            ok3 = ok
        elif expect == "VERSION":
            ok = err == "VERSION_MISMATCH"
            ok3 = ok
        elif expect == "STATUS":
            ok = bool(got) and got[0] == expected and top_status != "DEMONSTRATED"
            ok3 = ok
        out.append({"qid": qid, "kind": kind, "query": q, "expect": expect,
                    "expected": expected or None, "got_top3": got,
                    "error": err, "ok_top1": ok, "ok_top3": ok3, "ms": round(dt, 1)})
    return out

def summarize(rows: list[dict]) -> dict:
    pos = [r for r in rows if r["expect"] == "POS"]
    neg = [r for r in rows if r["expect"] in ("NONE", "VERSION")]
    st = [r for r in rows if r["expect"] == "STATUS"]
    return {
        "n": len(rows),
        "precision_at_1": round(sum(r["ok_top1"] for r in pos) / len(pos), 3) if pos else None,
        "recall_at_3": round(sum(r["ok_top3"] for r in pos) / len(pos), 3) if pos else None,
        "negativas_correctas": f"{sum(r['ok_top1'] for r in neg)}/{len(neg)}",
        "status_correcto": f"{sum(r['ok_top1'] for r in st)}/{len(st)}",
        "latencia_ms_media": round(statistics.mean(r["ms"] for r in rows), 1),
        "por_tipo": _per_kind(rows),
    }

def _per_kind(rows: list[dict]) -> dict:
    out = {}
    for kind in sorted({r["kind"] for r in rows}):
        sub = [r for r in rows if r["kind"] == kind]
        out[kind] = {"n": len(sub), "aciertos_top1": sum(r["ok_top1"] for r in sub),
                     "aciertos_top3": sum(r["ok_top3"] for r in sub)}
    return out

if __name__ == "__main__":
    report = {}
    for mode in ("lexical", "hybrid"):
        rows = run_queries(mode)
        report[mode] = {"summary": summarize(rows), "rows": rows}
        print(f"== {mode} ==", json.dumps(report[mode]["summary"], ensure_ascii=False))
    cat = s.catalog()
    out = EVAL / "results.json"
    out.write_text(json.dumps({"embed_mode": cat["embed_mode"],
                               "embed_model": cat.get("embed_model"),
                               "entries": cat["entries"],
                               "modes": report}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("resultados:", out)
