"""Carga, validacion, dedupe y ESCRITURA del corpus (fuente de verdad = JSONL).

Regla del repo: el corpus tiene UN SOLO ESCRIBOR (este modulo). Toda escritura
recalcula `content_sha256` a partir del canonico de la entrada (el propio hash
queda fuera del canonico) y se hace de forma atomica (tmp + os.replace).
`scripts/make_corpus.py` y `pyzig/gates.py` pasan por aqui; nadie escribe el
JSONL a mano.
"""
from __future__ import annotations
import hashlib, json, os, pathlib, tempfile
from dataclasses import dataclass, field
from .paths import CORPUS_FILE, ROOT

REQUIRED = ["operation_id","name","intent","aliases","source_lang","target_lang","zig_version","python_version","platform","py_ref","zig_impl","apis_used","constraints","provenance"]

#: Claves que no entran en el canonico (el hash se calcula sobre el resto).
CANON_SKIP = ("content_sha256",)

@dataclass
class Entry:
    operation_id: str
    name: str
    intent: str
    aliases: list[str]
    source_lang: str
    target_lang: str
    zig_version: str
    python_version: str
    platform: str
    py_ref: str
    zig_impl: str
    zig_test: str | None
    apis_used: list[str]
    constraints: list[str]
    preconditions: list[str]
    postconditions: list[str]
    side_effects: list[str]
    error_behavior: str
    ownership_memory: str
    differences: list[str]
    tests: list[dict]
    provenance: str
    evidence: dict
    entry_type: str
    content_sha256: str
    raw: dict = field(default_factory=dict)

    @property
    def status(self) -> str:
        return self.evidence.get("status", "UNVERIFIED")

    @property
    def fuzz(self) -> dict:
        """Contrato de fuzzing de la entrada ({} si la entrada no es fuzzable)."""
        return self.raw.get("fuzz", {})

    @property
    def type_signature(self) -> dict:
        return self.raw.get("type_signature", {})

    def to_dict(self) -> dict:
        return self.raw

def canonical(e: dict) -> str:
    """Canonico de una entrada: JSON ordenado, sin `content_sha256`."""
    return json.dumps({k: e.get(k) for k in sorted(e) if k not in CANON_SKIP},
                      ensure_ascii=False, sort_keys=True)

def content_hash(e: dict) -> str:
    return hashlib.sha256(canonical(e).encode("utf-8")).hexdigest()

def _sanitize_text(s: str) -> str:
    """Quita rutas absolutas del home: el corpus es portable y publicable."""
    root = str(ROOT)
    if root and root in s:
        s = s.replace(root + "/", "").replace(root, "")
    home = str(pathlib.Path.home())
    if home and home in s:
        s = s.replace(home, "~")
    return s

def _sanitize(obj):
    """Aplica `_sanitize_text` a todas las cadenas de una estructura."""
    if isinstance(obj, str):
        return _sanitize_text(obj)
    if isinstance(obj, list):
        return [_sanitize(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    return obj

def seal(e: dict) -> dict:
    """Copia de la entrada con `content_sha256` recalculado (regla: siempre)."""
    out = _sanitize({k: v for k, v in e.items() if k not in CANON_SKIP})
    out["content_sha256"] = content_hash(out)
    return out

def load(path: pathlib.Path | None = None) -> list[Entry]:
    p = pathlib.Path(path or CORPUS_FILE)
    out: list[Entry] = []
    ids: set[str] = set()
    for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        d = json.loads(line)
        missing = [k for k in REQUIRED if k not in d]
        if missing:
            raise ValueError(f"{p}:{n} falta(n) {missing}")
        if d["operation_id"] in ids:
            raise ValueError(f"{p}:{n} duplicado {d['operation_id']}")
        ids.add(d["operation_id"])
        out.append(Entry(
            operation_id=d["operation_id"], name=d["name"], intent=d["intent"],
            aliases=d["aliases"], source_lang=d["source_lang"], target_lang=d["target_lang"],
            zig_version=d["zig_version"], python_version=d["python_version"], platform=d["platform"],
            py_ref=d["py_ref"], zig_impl=d["zig_impl"], zig_test=d.get("zig_test"),
            apis_used=d["apis_used"], constraints=d["constraints"],
            preconditions=d.get("preconditions", []), postconditions=d.get("postconditions", []),
            side_effects=d.get("side_effects", []), error_behavior=d.get("error_behavior", ""),
            ownership_memory=d.get("ownership_memory", ""), differences=d.get("differences", []),
            tests=d.get("tests", []), provenance=d["provenance"], evidence=d.get("evidence", {"status":"UNVERIFIED","runs":[]}),
            entry_type=d.get("entry_type", "recipe"),
            content_sha256=d.get("content_sha256",""), raw=d,
        ))
    return out

def search_text(e: Entry) -> str:
    """Texto indexado (FTS): intencion + alias + APIs + diferencias."""
    parts = [e.name, e.intent, *e.aliases, *e.apis_used, *e.differences, e.zig_impl]
    return " ".join(parts)

def dedupe_report(entries: list[Entry]) -> list[str]:
    """Avisos de duplicado semantico por content_sha256."""
    seen: dict[str, str] = {}
    warn = []
    for e in entries:
        h = e.content_sha256 or content_hash(e.raw)
        if h in seen:
            warn.append(f"DUPLICADO por hash: {e.operation_id} == {seen[h]}")
        seen[h] = e.operation_id
    return warn

# --------------------------------------------------------------------------
# ESCRITURA (unico escritor del corpus)
# --------------------------------------------------------------------------

def _atomic_write(p: pathlib.Path, entries: list[dict]) -> None:
    """Escribe el JSONL de forma atomica: tmp en el mismo dir + os.replace."""
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n"
    home = str(pathlib.Path.home())
    if home and home in payload:
        raise ValueError(f"{p}: el corpus no puede contener rutas absolutas del home")
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=p.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise

def _read_raw(p: pathlib.Path) -> list[dict]:
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]

def write_all(entries: list[dict], path: pathlib.Path | None = None,
              preserve_evidence: bool = True) -> list[dict]:
    """Reescribe el corpus completo desde la especificacion `entries`.

    - siempre recalcula `content_sha256` de cada entrada;
    - conserva la evidencia previa SOLO si el contenido probado no cambio
      (`zig_test` e `zig_impl` identicos): si cambio, la evidencia queda
      invalida (UNVERIFIED) porque describe un codigo que ya no existe;
    - rechaza `operation_id` duplicados.
    """
    p = pathlib.Path(path or CORPUS_FILE)
    old = {d["operation_id"]: d for d in _read_raw(p)} if preserve_evidence else {}
    out: list[dict] = []
    seen: set[str] = set()
    for raw in entries:
        e = dict(raw)
        oid = e.get("operation_id")
        if not oid:
            raise ValueError("entrada sin operation_id")
        if oid in seen:
            raise ValueError(f"DUPLICADO {oid}")
        seen.add(oid)
        e.setdefault("evidence", {"status": e.get("status", "UNVERIFIED"), "runs": []})
        prev = old.get(oid)
        if prev is not None:
            same_code = (prev.get("zig_test") == e.get("zig_test")
                         and prev.get("zig_impl") == e.get("zig_impl"))
            if preserve_evidence and same_code:
                e["evidence"] = prev.get("evidence", e["evidence"])
            else:
                e["evidence"] = {"status": "UNVERIFIED", "runs": []}
        out.append(seal(e))
    _atomic_write(p, out)
    return out

def append_entry(entry: dict, path: pathlib.Path | None = None) -> dict:
    """Anade una entrada nueva al final del corpus (append-only)."""
    p = pathlib.Path(path or CORPUS_FILE)
    rows = _read_raw(p)
    oid = entry.get("operation_id")
    if any(r.get("operation_id") == oid for r in rows):
        raise ValueError(f"operation_id ya presente: {oid}")
    sealed = seal(entry)
    rows.append(sealed)
    _atomic_write(p, rows)
    return sealed

def update_entry(op_id: str, mutate, path: pathlib.Path | None = None) -> dict:
    """Actualiza una entrada existente; `mutate` recibe el dict y lo muta.

    El hash se recalcula siempre, incluso si `mutate` no toca nada.
    """
    p = pathlib.Path(path or CORPUS_FILE)
    rows = _read_raw(p)
    for i, row in enumerate(rows):
        if row.get("operation_id") == op_id:
            new = dict(row)
            mutate(new)
            sealed = seal(new)
            rows[i] = sealed
            _atomic_write(p, rows)
            return sealed
    raise KeyError(f"operation_id no encontrado: {op_id}")

def verify_chain(path: pathlib.Path | None = None) -> list[str]:
    """Problemas del corpus: hash roto, ids duplicados, campos obligatorios."""
    p = pathlib.Path(path or CORPUS_FILE)
    problems: list[str] = []
    seen: dict[str, int] = {}
    for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        d = json.loads(line)
        oid = d.get("operation_id", f"linea{n}")
        missing = [k for k in REQUIRED if k not in d]
        if missing:
            problems.append(f"{p}:{n} {oid}: falta(n) {missing}")
        if oid in seen:
            problems.append(f"{p}:{n} {oid}: id duplicado (primera vez linea {seen[oid]})")
        seen[oid] = n
        want = content_hash(d)
        if d.get("content_sha256") != want:
            problems.append(f"{p}:{n} {oid}: content_sha256 roto "
                            f"(guardado={d.get('content_sha256')} esperado={want})")
    return problems
