#!/usr/bin/env python3
"""Eval fija: compara recuperacion lexical vs hibrida (eval/queries.tsv por defecto).

--queries permite correr un conjunto independiente (p. ej. eval/heldout_queries.tsv)
y --out elige el JSON de salida; sin ellos el comportamiento es el de siempre.
"""
import argparse, json, os, pathlib, resource, statistics, subprocess, sys, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from pyzig import search as s
from pyzig.paths import EVAL

def run_queries(mode: str, queries: pathlib.Path = EVAL / "queries.tsv") -> list[dict]:
    out = []
    for line in pathlib.Path(queries).read_text(encoding="utf-8").splitlines():
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

def _eval_one(build: bool, queries: pathlib.Path = EVAL / "queries.tsv") -> dict:
    from pyzig import index as idx, embed
    name = embed.selected_model()
    info = {"model": name}
    if build:
        # indice por modelo, sin tocar var/pyzig.db
        out = pathlib.Path(os.environ.get("PYZIG_EVAL_DIR", str(idx.VAR / "eval")))
        out.mkdir(parents=True, exist_ok=True)
        idx.DB = out / f"{name}.db"
        t0 = time.perf_counter()
        emb = embed.Embedder()
        info["load_s"] = round(time.perf_counter() - t0, 2)
        t0 = time.perf_counter()
        idx.build(emb)
        info["build_s"] = round(time.perf_counter() - t0, 2)
        s._EMB = emb
    if not s._embedder().degraded:  # sin modelo: la eval hibrida degrada a lexical declarada
        s._embedder().encode_query(["warmup"])
    report = {}
    for mode in ("lexical", "hybrid"):
        rows = run_queries(mode, queries)
        report[mode] = {"summary": summarize(rows), "rows": rows}
        print(f"== {name} {mode} ==", json.dumps(report[mode]["summary"], ensure_ascii=False))
    info["peak_rss_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    info["modes"] = report
    return info

def _mrr(rows: list[dict]) -> float:
    pos = [r for r in rows if r["expect"] == "POS"]
    return round(sum((1 / (r["got_top3"].index(r["expected"]) + 1)) if r["expected"] in r["got_top3"] else 0
                     for r in pos) / len(pos), 3)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true", help="construir indice propio del modelo (var/eval/<modelo>.db)")
    ap.add_argument("--models", help="lista separada por comas; un subproceso por modelo (implica --build)")
    ap.add_argument("--queries", type=pathlib.Path, default=EVAL / "queries.tsv",
                    help="TSV de consultas (default: eval/queries.tsv)")
    ap.add_argument("--out", type=pathlib.Path, help="JSON de salida (default: eval/results.json)")
    a = ap.parse_args()
    if a.models and a.out:
        ap.error("--out no se usa con --models (cada modelo escribe su propio JSON)")
    if a.models:
        print("| modelo | modo | P@1 | R@3 | MRR@3 | neg | status | ms/q | build s | RSS MB |")
        print("|---|---|---|---|---|---|---|---|---|---|")
        for m in a.models.split(","):
            cmd = [sys.executable, __file__, "--build"]
            if a.queries != ap.get_default("queries"):
                cmd += ["--queries", str(a.queries)]
            r = subprocess.run(cmd, capture_output=True, text=True,
                               env={**os.environ, "PYZIG_EMBED_MODEL": m})
            if r.returncode != 0:
                print(f"| {m} | ERROR rc={r.returncode} | " + r.stderr.strip().splitlines()[-1] + " |"); continue
            info = json.loads(pathlib.Path(r.stdout.strip().splitlines()[-1].split("resultados:")[1].strip()).read_text())
            for mode, d in info["modes"].items():
                sm = d["summary"]
                print(f"| {m} | {mode} | {sm['precision_at_1']} | {sm['recall_at_3']} | {_mrr(d['rows'])} | "
                      f"{sm['negativas_correctas']} | {sm['status_correcto']} | {sm['latencia_ms_media']} | "
                      f"{info.get('build_s')} | {info['peak_rss_mb']} |")
        sys.exit(0)
    info = _eval_one(a.build, a.queries)
    for d in info["modes"].values():
        d["summary"]["mrr_at_3"] = _mrr(d["rows"])
    if a.build:
        out = pathlib.Path(os.environ.get("PYZIG_EVAL_DIR", str(EVAL.parent / "var" / "eval"))) / f"results-{info['model']}.json"
    else:
        out = EVAL / "results.json"
        cat = s.catalog()
        info.update({"embed_mode": cat["embed_mode"], "embed_model": cat.get("embed_model"), "entries": cat["entries"]})
    if a.out:
        out = a.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    print("resultados:", out)
