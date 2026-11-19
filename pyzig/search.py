"""Recuperacion hibrida: filtros exactos + lexical/vectorial + admision + fusion RRF."""
from __future__ import annotations
import json, re, sqlite3
import numpy as np
from . import index as idx
from .embed import Embedder, Unavailable

RRF_K = 60
COV_MIN = 0.40   # cobertura lexica minima (tokens discriminativos)
COS_MIN = 0.35   # cosine minimo (all-MiniLM-L6-v2)
UNVERIFIED_PENALTY = 0.6  # entradas sin evidencia demostrada rankean por debajo
# Recetas de migracion Zig->Zig (source_lang "zig-...") ceden ante las Python->Zig cuando la
# consulta no trae marcas de Zig: "time.sleep equivalente" es una pregunta de Python.
MIGRATION_PENALTY = 0.5
_ZIG_MARKERS = re.compile(r"\bstd\.|error:|@[A-Za-z]|\.zig\b|\bzig\s*0\.1|\bmigra")

_EMB: Embedder | None = None

def _index_embed_model(con) -> str | None:
    """Modelo de embeddings con el que se construyo el indice (meta.embed.model)."""
    r = con.execute("SELECT value FROM meta WHERE key = 'embed'").fetchone()
    if r is None:
        return None
    try:
        return json.loads(r[0]).get("model")
    except (ValueError, AttributeError):
        return None

def _embedder() -> Embedder:
    global _EMB
    if _EMB is None:
        _EMB = Embedder()
    return _EMB

class NoResults(Exception):
    code = "NO_RESULTS"

class VersionMismatch(Exception):
    code = "VERSION_MISMATCH"

class IndexUnavailable(Exception):
    code = "INDEX_UNAVAILABLE"

def _per_doc_coverage(con, disc: list[str]) -> dict[str, float]:
    if not disc:
        return {}
    per: dict[str, int] = {}
    for d in disc:
        for r in con.execute("SELECT operation_id FROM ops_fts WHERE ops_fts MATCH ?", (f'"{d}"',)).fetchall():
            per[r["operation_id"]] = per.get(r["operation_id"], 0) + 1
    return {k: v / len(disc) for k, v in per.items()}

def _cos_of(con, oid: str, qv) -> float:
    if qv is None:
        return 0.0
    r = con.execute("SELECT vec FROM vectors WHERE operation_id = ?", (oid,)).fetchone()
    if r is None:
        return 0.0
    v = np.frombuffer(bytes(r["vec"]), dtype=np.float32)
    if v.shape[0] != qv.shape[0]:
        return 0.0
    return float(np.dot(qv, v))

def _fuse(lex, vec_res, mode: str, alpha: float = 0.5) -> dict[str, float]:
    if mode == "lexical":
        return {oid: (1 - alpha) / (RRF_K + i) for i, (oid, _) in enumerate(lex)}
    if mode == "vector":
        return {oid: alpha / (RRF_K + i) for i, (oid, _) in enumerate(vec_res)}
    out: dict[str, float] = {}
    for i, (oid, _) in enumerate(lex):
        out[oid] = out.get(oid, 0.0) + (1 - alpha) / (RRF_K + i)
    for i, (oid, _) in enumerate(vec_res):
        out[oid] = out.get(oid, 0.0) + alpha / (RRF_K + i)
    return out

def _status_of(con, oid: str) -> str:
    r = con.execute("SELECT status FROM ops WHERE operation_id = ?", (oid,)).fetchone()
    return r["status"] if r else "UNVERIFIED"

def _source_lang_of(con, oid: str) -> str:
    d = json.loads(con.execute("SELECT payload FROM ops WHERE operation_id = ?", (oid,)).fetchone()["payload"])
    return d.get("source_lang", "python")

def _type_of(con, oid: str) -> str:
    d = json.loads(con.execute("SELECT payload FROM ops WHERE operation_id = ?", (oid,)).fetchone()["payload"])
    return d.get("entry_type", "recipe")

def search(query: str, zig_version: str | None = None, platform: str | None = None,
           limit: int = 5, mode: str = "hybrid", require_status: str | None = None) -> list[dict]:
    try:
        con = idx.connect_ro()
    except FileNotFoundError as e:
        raise IndexUnavailable(f"indice no construido: {e}") from e
    with con:
        fsql, fargs = [], []
        if zig_version:
            fsql.append("zig_version = ?"); fargs.append(zig_version)
        if platform:
            fsql.append("platform = ?"); fargs.append(platform)
        where = (" WHERE " + " AND ".join(fsql)) if fsql else ""
        rows = con.execute(f"SELECT operation_id FROM ops{where}", fargs).fetchall()
        ids = {r["operation_id"] for r in rows}
        if not ids:
            raise VersionMismatch(f"sin entradas para zig={zig_version} platform={platform}")

        lex = [(o, s) for o, s in idx.lexical(con, query) if o in ids]
        vec_res: list[tuple[str, float]] = []
        qv = None
        embed_meta = {"mode": "unavailable"}
        if mode in ("hybrid", "vector"):
            try:
                emb = _embedder()
                embed_meta = emb.model_meta()
                built_with = _index_embed_model(con)
                if not emb.degraded and built_with and built_with != emb.model_name:
                    # vectores de otro modelo (misma dim) darian cosenos basura en silencio
                    embed_meta = {**embed_meta, "mode": f"unavailable: indice construido con "
                                  f"{built_with}, modelo activo {emb.model_name}; reconstruye el indice"}
                elif not emb.degraded:
                    qv = emb.encode_query([query])[0]
                    vec_res = [(o, s) for o, s in idx.vector(con, qv) if o in ids]
            except Unavailable as e:
                embed_meta = {"mode": f"unavailable: {e}"}

        cov, disc = idx.coverage(con, query)
        per_doc_cov = _per_doc_coverage(con, disc)
        cos_map = {o: _cos_of(con, o, qv) for o in ids}
        admitted = {o for o in ids if per_doc_cov.get(o, 0.0) >= COV_MIN or cos_map[o] >= COS_MIN}
        fused = _fuse(lex, vec_res, mode)
        # mejor cobertura entre entradas tipo receta admitidas
        best_recipe_cov = max(
            [per_doc_cov.get(o, 0.0) for o in admitted
             if _type_of(con, o) == "recipe"], default=0.0)

        zig_query = bool(_ZIG_MARKERS.search(query))

        def boost(o: str, base: float) -> float:
            st = _status_of(con, o)
            cov = per_doc_cov.get(o, 0.0)
            factor = 0.5 + 0.5 * max(cov, cos_map.get(o, 0.0))
            penalty = 1.0
            if st != "DEMONSTRATED":
                # una entrada tipo "gap" (documenta una limitacion) no se penaliza
                # si es EL mejor match de la query: entonces la respuesta honesta
                # es "no hay equivalencia demostrada para esto".
                is_gap = _type_of(con, o) == "gap"
                if not (is_gap and cov > best_recipe_cov):
                    penalty = UNVERIFIED_PENALTY
            if not zig_query and _source_lang_of(con, o).startswith("zig"):
                penalty *= MIGRATION_PENALTY
            return base * factor * penalty

        ranked = sorted(((o, boost(o, s)) for o, s in fused.items() if o in admitted),
                        key=lambda kv: -kv[1])[:limit]
        if not ranked:
            raise NoResults(
                f"sin coincidencias admisibles ({len(ids)} entradas tras filtros; "
                f"cobertura_max={max(per_doc_cov.values()) if per_doc_cov else 0:.2f}, "
                f"cos_max={max(cos_map.values()) if cos_map else 0:.2f}; "
                f"umbrales: cobertura>={COV_MIN}, cos>={COS_MIN})")
        out = []
        for oid, score in ranked:
            r = con.execute("SELECT payload FROM ops WHERE operation_id = ?", (oid,)).fetchone()
            if r is None:
                continue
            d = json.loads(r["payload"])
            st = d.get("evidence", {}).get("status", "UNVERIFIED")
            if require_status and st != require_status:
                continue
            reasons = []
            if any(o == oid for o, _ in lex):
                reasons.append(f"lexical(rank {[o for o, _ in lex].index(oid) + 1})")
            if any(o == oid for o, _ in vec_res):
                reasons.append(f"vectorial(rank {[o for o, _ in vec_res].index(oid) + 1})")
            if not reasons:
                reasons.append("solo-admitido")
            warn = [] if st == "DEMONSTRATED" else [f"evidencia {st}: no tratar como equivalencia verificada"]
            out.append({
                "operation_id": oid,
                "name": d["name"],
                "status": st,
                "zig_version": d["zig_version"],
                "platform": d["platform"],
                "reason": ", ".join(reasons),
                "score": round(float(score), 6),
                "signals": {"coverage": round(per_doc_cov.get(oid, 0.0), 3),
                            "cosine": round(cos_map.get(oid, 0.0), 3)},
                "summary": d["zig_impl"].splitlines()[0],
                "constraints": d["constraints"],
                "apis_used": d["apis_used"],
                "tests": d.get("tests", []),
                "provenance": d["provenance"],
                "differences": d.get("differences", []),
                "warnings": warn,
            })
        return out

def get(operation_id: str) -> dict:
    try:
        con = idx.connect_ro()
    except FileNotFoundError as e:
        raise IndexUnavailable(f"indice no construido: {e}") from e
    with con:
        r = con.execute("SELECT payload FROM ops WHERE operation_id = ?", (operation_id,)).fetchone()
    if r is None:
        raise NoResults(f"operacion desconocida: {operation_id}")
    return json.loads(r["payload"])

def catalog() -> dict:
    try:
        con = idx.connect_ro()
    except FileNotFoundError as e:
        raise IndexUnavailable(f"indice no construido: {e}") from e
    with con:
        meta = {r["key"]: r["value"] for r in con.execute("SELECT key,value FROM meta").fetchall()}
        rows = con.execute("SELECT operation_id, zig_version, platform, status, name FROM ops ORDER BY operation_id").fetchall()
        emb = json.loads(meta.get("embed", '{"mode":"unavailable"}'))
    return {"health": "ok" if meta else "index_unavailable",
            "entries": int(meta.get("entries", "0")), "built_at": meta.get("built_at"),
            "fts": meta.get("fts"), "embed_mode": emb.get("mode"), "embed_model": emb.get("model"),
            "embed_model_sha256": emb.get("model_sha256"),
            "zig_versions": sorted({r["zig_version"] for r in rows}),
            "operations": [{"operation_id": r["operation_id"], "name": r["name"],
                            "zig_version": r["zig_version"], "status": r["status"]} for r in rows]}
