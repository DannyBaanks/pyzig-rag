"""Indice derivado (SQLite FTS5 + vectores). Reconstruible desde el corpus."""
from __future__ import annotations
import json, re as _re, sqlite3, time, pathlib
import numpy as np
from .paths import DB, VAR
from . import corpus as corpus_mod
from .embed import Embedder, DIM

#: Los artefactos derivados por fuzzing son evidencia, no recetas buscables.
#: Siguen en `ops` (pyzig_get los ve) pero NO entran en FTS/vectores: si lo
#: hicieran, duplicarian el texto de su padre y falsearian la frecuencia de
#: documentos de la admision lexica.
SEARCHABLE_TYPES = ("recipe", "gap")

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS ops(
  operation_id TEXT PRIMARY KEY,
  name TEXT, intent TEXT, zig_version TEXT, platform TEXT,
  status TEXT, constraints_json TEXT, summary TEXT, payload TEXT);
CREATE VIRTUAL TABLE IF NOT EXISTS ops_fts USING fts5(
  operation_id UNINDEXED, name, intent, body);
CREATE TABLE IF NOT EXISTS vectors(operation_id TEXT PRIMARY KEY, dim INTEGER, vec BLOB);
"""

def build(embed: Embedder | None = None, verbose: bool = False) -> pathlib.Path:
    VAR.mkdir(parents=True, exist_ok=True)
    entries = corpus_mod.load()
    warns = corpus_mod.dedupe_report(entries)
    if warns:
        raise ValueError("corpus con duplicados: " + "; ".join(warns))
    if DB.exists():
        DB.unlink()
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)
    vecs = None
    mode = "unavailable"
    if embed is not None and not embed.degraded:
        vecs = embed.encode([corpus_mod.search_text(e) for e in entries])
        mode = embed.mode
    for i, e in enumerate(entries):
        payload = e.to_dict()
        con.execute(
            "INSERT INTO ops(operation_id,name,intent,zig_version,platform,status,constraints_json,summary,payload) VALUES(?,?,?,?,?,?,?,?,?)",
            (e.operation_id, e.name, e.intent, e.zig_version, e.platform, e.status,
             json.dumps(e.constraints, ensure_ascii=False), e.zig_impl.splitlines()[0], json.dumps(payload, ensure_ascii=False)),
        )
        if e.entry_type not in SEARCHABLE_TYPES:
            continue
        con.execute("INSERT INTO ops_fts(operation_id,name,intent,body) VALUES(?,?,?,?)",
                    (e.operation_id, e.name, e.intent, corpus_mod.search_text(e)))
        if vecs is not None:
            v = np.asarray(vecs[i], dtype=np.float32)
            con.execute("INSERT INTO vectors(operation_id,dim,vec) VALUES(?,?,?)",
                        (e.operation_id, int(v.shape[0]), sqlite3.Binary(v.tobytes())))
    meta = {
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "entries": str(len(entries)),
        "searchable": str(sum(1 for e in entries if e.entry_type in SEARCHABLE_TYPES)),
        "fts": "fts5",
        "embed_mode": mode,
        **({"embed": embed.model_meta()} if embed is not None else {"embed": {"mode": "unavailable"}}),
    }
    for k, v in meta.items():
        if isinstance(v, dict):
            v = json.dumps(v, ensure_ascii=False)
        con.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)", (k, v))
    con.commit(); con.close()
    if verbose:
        print(f"indice: {DB} entradas={len(entries)} embeddings={mode}")
    return DB

def connect_ro() -> sqlite3.Connection:
    if not DB.exists():
        raise FileNotFoundError(str(DB))
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con

def lexical(con: sqlite3.Connection, q: str, limit: int = 10) -> list[tuple[str, float]]:
    rows = con.execute(
        "SELECT operation_id, bm25(ops_fts, 0.0, 1.0, 2.0) AS score FROM ops_fts WHERE ops_fts MATCH ? ORDER BY score LIMIT ?",
        (_fts_query(q), limit * 4),
    ).fetchall()
    return [(r["operation_id"], -float(r["score"])) for r in rows]

def vector(con: sqlite3.Connection, qv: np.ndarray, limit: int = 10) -> list[tuple[str, float]]:
    rows = con.execute("SELECT operation_id, dim, vec FROM vectors").fetchall()
    scored: list[tuple[str, float]] = []
    for r in rows:
        v = np.frombuffer(bytes(r["vec"]), dtype=np.float32)
        if v.shape[0] != qv.shape[0]:
            continue
        scored.append((r["operation_id"], float(np.dot(qv, v))))
    scored.sort(key=lambda t: -t[1])
    return scored[:limit]

def _fts_query(q: str) -> str:
    """Tokens alfanumericos entrecomillados (evita sintaxis FTS5 con . o -)."""
    toks = _re.findall(r"[A-Za-z0-9_]+", q)
    return " OR ".join(f'"{t}"*' for t in toks) if toks else '""'

# ---- senales de admision (evitan falsos positivos) -------------------------
_TOKEN = _re.compile(r"[a-z0-9_]+")

# palabras vaces es/en: no discriminan nada y falsean la cobertura lexica
STOPWORDS = frozenset("""
el la los las un una unos unas de del que al y o e ni en con por para sin sobre entre
hasta desde segun como cuando donde cual quien cuyo pero mas menos muy ya aun asi si no
lo le les me te se nos os mi tu su sus nuestro vuestro este esta estos estas ese esa
es son ser fue era hay haber hacer hace puede deben debe cual otro mismos todo tambien
the a an of to in on for with without and or but is are be been from by at as it its
how do does i my me you your we our
""".split())

def tokens(q: str) -> list[str]:
    return [t for t in _TOKEN.findall(q.lower())
            if len(t) > 2 and t not in STOPWORDS]

def doc_freq(con: sqlite3.Connection, tok: str) -> int:
    r = con.execute("SELECT count(*) AS n FROM ops_fts WHERE ops_fts MATCH ?", (f'"{tok}"',)).fetchone()
    return int(r["n"]) if r else 0

def coverage(con: sqlite3.Connection, q: str, max_df_ratio: float = 0.6) -> tuple[float, list[str]]:
    """Cobertura lexica: fraccion de tokens discriminativos del query que
    aparecen en el mejor documento. Descarta tokens ubicuos (df alto)."""
    #: El denominator debe ser el numero de documentos INDEXADOS, no el de
    #: `ops`: los artefactos derivados viven en `ops` para `pyzig_get` pero
    #: estan fuera del FTS, y contarlos infla el umbral de tokens ubicuos.
    n_docs = int(con.execute("SELECT count(*) AS n FROM ops_fts").fetchone()["n"]) or 1
    toks = tokens(q)
    if not toks:
        return 0.0, []
    disc = [t for t in toks if doc_freq(con, t) < max(1, int(n_docs * max_df_ratio))]
    if not disc:
        disc = toks
    per_doc: dict[str, int] = {}
    for d in disc:
        rows = con.execute("SELECT operation_id FROM ops_fts WHERE ops_fts MATCH ?", (f'"{d}"',)).fetchall()
        for r in rows:
            per_doc[r["operation_id"]] = per_doc.get(r["operation_id"], 0) + 1
    if not per_doc:
        return 0.0, disc
    best = max(per_doc.values())
    return best / len(disc), disc
