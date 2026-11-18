"""Carga, validacion y dedupe del corpus (fuente de verdad = JSONL)."""
from __future__ import annotations
import hashlib, json, pathlib
from dataclasses import dataclass, field
from .paths import CORPUS_FILE

REQUIRED = ["operation_id","name","intent","aliases","source_lang","target_lang","zig_version","python_version","platform","py_ref","zig_impl","apis_used","constraints","provenance"]

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

    def to_dict(self) -> dict:
        return self.raw

def canonical(e: dict) -> str:
    return json.dumps({k: e.get(k) for k in sorted(e)}, ensure_ascii=False, sort_keys=True)

def content_hash(e: dict) -> str:
    return hashlib.sha256(canonical(e).encode("utf-8")).hexdigest()

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
