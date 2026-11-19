#!/usr/bin/env python3
"""Mineria de transcripts: que APIs de Zig 0.16 hacen fallar de verdad a los agentes.

Lee (SOLO LECTURA, streaming linea a linea) los transcripts de Claude Code
(`~/.claude/projects/**/*.jsonl`) y de Codex (`~/.codex/sessions/**/*.jsonl`),
extrae los errores del compilador de los resultados de `zig build|test|run|...`,
los normaliza a una FIRMA, y escribe:

    var/mined/signatures.jsonl   una linea por firma
    var/mined/report.md          top 30 firmas + 15 recetas candidatas

PRIVACIDAD (obligatoria): la salida solo contiene firmas de error del compilador
normalizadas, nombres de API de la std (`std.X.y`) y conteos. Nunca texto de
usuario, prompts, rutas, codigo de proyectos ni tokens. Los identificadores
propios se reducen a `_`; los nombres de archivo solo se usan en memoria para
emparejar error -> edicion y no se guardan.

Uso:  python3 scripts/mine_sessions.py [--claude DIR] [--codex DIR] [--out DIR] [--corpus F]
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get("PYZIG_ROOT") or Path(__file__).resolve().parent.parent)

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
ZIG_CMD = re.compile(r"\bzig\s+(build|test|run|build-exe|build-lib|build-obj|ast-check)\b")
ERR_LINE = re.compile(r"^(?P<file>[^\s:][^:\n]*\.zig):(?P<l>\d+):(?P<c>\d+): (?P<kind>error|note): (?P<msg>.*)$")

#: raices de namespace de la std que se aceptan como "API" (con o sin prefijo `std.`).
STD_ROOTS = {
    "std", "Io", "fs", "mem", "fmt", "heap", "process", "math", "json", "testing", "ArrayList",
    "array_list", "hash_map", "HashMap", "AutoHashMap", "StringHashMap", "ArrayHashMap",
    "StringArrayHashMap", "AutoArrayHashMap", "net", "time", "crypto", "unicode", "ascii",
    "sort", "Thread", "debug", "log", "posix", "os", "meta", "enums", "Random", "Uri", "http",
    "tar", "zip", "base64", "hex", "BufferedReader", "Allocator", "File", "Dir", "Writer",
    "Reader", "Timestamp", "Duration", "Limit", "Timeout", "Clock", "Child", "ArenaAllocator",
    "DynamicBitSet", "PriorityQueue", "SinglyLinkedList", "DoublyLinkedList", "MultiArrayList",
    "BoundedArray", "Progress", "Build", "builtin", "Target", "Io.Writer", "Io.Reader",
}
#: palabras que pueden aparecer dentro de comillas sin ser identificadores propios.
PRIMS = {
    "u8", "u16", "u32", "u64", "u128", "usize", "i8", "i16", "i32", "i64", "i128", "isize",
    "f16", "f32", "f64", "f80", "f128", "bool", "void", "type", "anyerror", "noreturn",
    "comptime_int", "comptime_float", "anytype", "anyopaque", "c_int", "c_uint", "c_char",
    "c_long", "const", "volatile", "align", "comptime", "error", "null", "undefined", "true",
    "false", "fn", "struct", "union", "enum", "opaque", "pub", "var", "try", "catch", "orelse",
    "if", "else", "while", "for", "switch", "return", "break", "continue", "defer", "errdefer",
    "test", "inline", "noinline", "export", "extern", "packed", "callconv", "unreachable",
    "usingnamespace", "async", "await", "suspend", "resume", "nosuspend", "and", "or", "N",
    "_", "anyframe", "allowzero", "linksection", "addrspace", "threadlocal", "asm",
}
ALIAS_OK = {"std", "Io", "fs", "mem", "fmt", "heap", "process", "math", "json", "testing", "posix", "crypto", "unicode", "time", "net", "http"}
WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
QUOTED = re.compile(r"'([^'\n]*)'|`([^`\n]*)`|\"([^\"\n]*)\"")
#: cadena de API: std.a.b.C o raiz conocida .a.b
CHAIN = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+")
# patrones de secretos (por si alguno cuela en una firma o identificador)
SECRET = re.compile(
    r"(sk-[A-Za-z0-9_\-]{10,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{12,}|xox[abp]-[A-Za-z0-9\-]{10,}|"
    r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}|Bearer\s+\S+|[A-Fa-f0-9]{32,}|[A-Za-z0-9+/_\-]{40,}={0,2}|"
    r"(?i:password|passwd|secret|token|api[_-]?key)\s*[=:]\s*\S+|/home/[^\s/]+)"
)


def redact(s: str) -> str:
    return SECRET.sub("<redacted>", s)


# ---------------------------------------------------------------- normalizacion

def _keep_word(w: str) -> bool:
    return w in PRIMS or w in STD_ROOTS


def _norm_quoted(inner: str, keep_names: bool) -> str:
    """Reduce lo de dentro de unas comillas a tipos primitivos y nombres de la std."""
    if "/" in inner or "\\" in inner:
        return "<path>"

    def sub(m: re.Match) -> str:
        w = m.group(0)
        if _keep_word(w) or keep_names or w.isdigit():
            return w
        return "_"
    out = WORD.sub(sub, inner)
    out = re.sub(r"\d+", "N", out)
    return out[:80]


def normalize_msg(msg: str) -> tuple[str, list[str]]:
    """(firma normalizada, apis std mencionadas en el mensaje)."""
    msg = ANSI.sub("", msg).strip()
    apis: list[str] = []
    # tipos T en "named 'X' in 'T'": X se conserva solo si T es de la std.
    m = re.search(r"named '([^']*)' in '([^']*)'", msg)
    keep_member = None
    if m:
        t_words = WORD.findall(m.group(2))
        if t_words and all(_keep_word(w) for w in t_words):
            keep_member = m.group(1)
            apis.append(_apify(m.group(2) + "." + m.group(1)))
    m2 = re.search(r"(?:struct|union|enum) '([^']*)' has no member named '([^']*)'", msg)
    if m2 and keep_member is None:
        t_words = WORD.findall(m2.group(1))
        if t_words and all(_keep_word(w) for w in t_words):
            keep_member = m2.group(2)  # miembro de un namespace de la std: es nombre de API
            apis.append(_apify(m2.group(1) + "." + m2.group(2)) or f"std.{m2.group(2)}")

    def qsub(mm: re.Match) -> str:
        inner = next(g for g in mm.groups() if g is not None)
        if mm.group(3) is not None:
            return '"<str>"'
        if keep_member is not None and inner == keep_member:
            return f"'{inner}'"
        words = WORD.findall(inner)
        if words and not any(_keep_word(w) for w in words):
            return "'_'"  # solo identificadores propios
        q = _norm_quoted(inner, False)
        for ch in CHAIN.findall(inner):
            a = _apify(ch)
            if a:
                apis.append(a)
        return f"'{q}'"

    sig = QUOTED.sub(qsub, msg)
    sig = re.sub(r"\S*/\S*", "<path>", sig)
    sig = re.sub(r"\b\d+\b", "N", sig)
    sig = re.sub(r"\s+", " ", sig).strip()
    sig = redact(sig)
    return sig[:240], [a for a in dict.fromkeys(apis) if a]


def _apify(chain: str) -> str:
    """Canoniza una cadena a `std.<...>` si empieza por una raiz conocida de la std."""
    chain = chain.strip(".")
    parts = chain.split(".")
    if len(parts) < 2 or parts[0] not in STD_ROOTS:
        return ""
    if parts[0] != "std":
        parts = ["std"] + parts
    if len(parts) < 3:
        return ""
    return ".".join(parts)


def snippet_apis(line: str) -> list[str]:
    """Cadenas `std.*` de la linea de codigo que zig imprime bajo el error (el codigo no se guarda)."""
    out = []
    for ch in CHAIN.findall(line):
        a = _apify(ch)
        if a and ch.split(".")[0] == "std":
            out.append(a)
    return out


def parse_zig_output(text: str) -> list[dict]:
    """Errores (no notes sueltas) de una salida de zig. Devuelve dicts con sig, apis, file(basename)."""
    text = ANSI.sub("", text)
    lines = text.splitlines()
    errs: list[dict] = []
    for i, ln in enumerate(lines):
        m = ERR_LINE.match(ln.strip())
        if not m:
            continue
        sig, apis = normalize_msg(m.group("msg"))
        if "<redacted>" in sig:
            continue
        apis_msg = list(apis)
        apis = list(apis)
        if i + 1 < len(lines) and not ERR_LINE.match(lines[i + 1].strip()):
            apis += snippet_apis(lines[i + 1])
        errs.append({
            "kind": m.group("kind"),
            "sig": sig,
            "apis": list(dict.fromkeys(a for a in apis if a)),
            "apis_msg": list(dict.fromkeys(a for a in apis_msg if a)),
            "base": os.path.basename(m.group("file")),
        })
    return errs


def api_idents(code: str) -> set[str]:
    """Identificadores de API `std.*` (solo nombres, nunca codigo) que aparecen en un fragmento."""
    return {a for ch in CHAIN.findall(code) if ch.split(".")[0] in ALIAS_OK for a in [_apify(ch)] if a}


# ---------------------------------------------------------------- lectura de transcripts

def result_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            c.get("text", "") if isinstance(c, dict) else str(c) for c in content
        )
    return ""


def events_claude(path: Path):
    """Eventos ordenados de un transcript de Claude Code: ('zigcall', id) ('zigout', id, text) ('edit', base, old, new)."""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        zig_ids: set = set()
        for line in fh:
            # una salida de zig que compila bien puede no contener la palabra "zig":
            # se parsea tambien si la linea cita el id de una llamada zig ya vista.
            if "zig" not in line and not (zig_ids and "tool_result" in line and any(i in line for i in zig_ids)):
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            msg = d.get("message")
            if not isinstance(msg, dict) or not isinstance(msg.get("content"), list):
                continue
            for c in msg["content"]:
                if not isinstance(c, dict):
                    continue
                t = c.get("type")
                if t == "tool_use":
                    inp = c.get("input") or {}
                    name = c.get("name")
                    if name == "Bash" and ZIG_CMD.search(str(inp.get("command", ""))):
                        zig_ids.add(c.get("id"))
                        yield ("zigcall", c.get("id"))
                    elif name in ("Edit", "MultiEdit", "Write"):
                        fp = str(inp.get("file_path", ""))
                        if not fp.endswith(".zig"):
                            continue
                        base = os.path.basename(fp)
                        if name == "Edit":
                            yield ("edit", base, str(inp.get("old_string", "")), str(inp.get("new_string", "")))
                        elif name == "MultiEdit":
                            olds = "\n".join(str(e.get("old_string", "")) for e in inp.get("edits", []) if isinstance(e, dict))
                            news = "\n".join(str(e.get("new_string", "")) for e in inp.get("edits", []) if isinstance(e, dict))
                            yield ("edit", base, olds, news)
                        else:
                            yield ("edit", base, "", str(inp.get("content", "")))
                elif t == "tool_result":
                    yield ("zigout", c.get("tool_use_id"), result_text(c.get("content")))


def events_codex(path: Path):
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        zig_ids: set = set()
        for line in fh:
            if "zig" not in line and not (zig_ids and "_output" in line and any(i in line for i in zig_ids)):
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("type") != "response_item":
                continue
            p = d.get("payload") or {}
            pt = p.get("type")
            if pt in ("custom_tool_call", "function_call"):
                body = str(p.get("input") or p.get("arguments") or "")
                if ZIG_CMD.search(body):
                    zig_ids.add(p.get("call_id"))
                    yield ("zigcall", p.get("call_id"))
            elif pt in ("custom_tool_call_output", "function_call_output"):
                yield ("zigout", p.get("call_id"), result_text(p.get("output")))


def session_stream(path: Path, source: str):
    return events_claude(path) if source == "claude" else events_codex(path)


# ---------------------------------------------------------------- agregacion

class Agg:
    def __init__(self) -> None:
        self.sig: dict[str, dict] = {}
        self.stats = collections.Counter()

    def add_session(self, sid: str, source: str, events) -> None:
        zig_ids: set = set()
        timeline: list[tuple] = []  # ('run', errs) | ('edit', base, removed, added)
        for ev in events:
            if ev[0] == "zigcall":
                zig_ids.add(ev[1])
            elif ev[0] == "zigout":
                if ev[1] not in zig_ids:
                    continue
                errs = [e for e in parse_zig_output(ev[2]) if e["kind"] == "error"]
                self.stats["zig_runs"] += 1
                if errs:
                    self.stats["zig_runs_with_errors"] += 1
                timeline.append(("run", errs))
            elif ev[0] == "edit":
                old, new = api_idents(ev[2]), api_idents(ev[3])
                timeline.append(("edit", ev[1], sorted(old - new)[:8], sorted(new - old)[:8]))
        if not timeline:
            return
        self.stats["sessions_with_zig"] += 1
        for i, item in enumerate(timeline):
            if item[0] != "run" or not item[1]:
                continue
            seen = set()
            for e in item[1]:
                s = self.sig.setdefault(e["sig"], {
                    "count": 0, "sessions": set(), "sources": collections.Counter(),
                    "apis": collections.Counter(), "apis_msg": collections.Counter(), "fix_removed": collections.Counter(),
                    "fix_added": collections.Counter(), "fixed_runs": 0, "fix_compiled": 0,
                })
                s["count"] += 1
                s["sessions"].add(sid)
                s["sources"][source] += 1
                for a in e["apis"]:
                    s["apis"][a] += 1
                for a in e["apis_msg"]:
                    s["apis_msg"][a] += 1
                if e["sig"] in seen:
                    continue
                seen.add(e["sig"])
                # siguiente edicion del mismo archivo (basename) en una ventana corta
                bases = {x["base"] for x in item[1]}
                for j in range(i + 1, min(len(timeline), i + 40)):
                    nxt = timeline[j]
                    if nxt[0] == "run" and j > i + 25:
                        break
                    if nxt[0] == "edit" and nxt[1] in bases:
                        s["fixed_runs"] += 1
                        for a in nxt[2]:
                            s["fix_removed"][a] += 1
                        for a in nxt[3]:
                            s["fix_added"][a] += 1
                        # compila despues? primera ejecucion zig posterior sin errores visibles
                        for k in range(j + 1, len(timeline)):
                            if timeline[k][0] == "run":
                                if not timeline[k][1]:
                                    s["fix_compiled"] += 1
                                break
                        break

    def records(self) -> list[dict]:
        out = []
        for sig, s in self.sig.items():
            out.append({
                "signature": sig,
                "count": s["count"],
                "sessions": len(s["sessions"]),
                "sources": dict(s["sources"]),
                "apis": [a for a, _ in s["apis"].most_common(8)],
                "apis_msg": [a for a, _ in s["apis_msg"].most_common(8)],
                "fix_edits": s["fixed_runs"],
                "fix_then_compiled": s["fix_compiled"],
                "fix_removed_apis": [a for a, _ in s["fix_removed"].most_common(5)],
                "fix_added_apis": [a for a, _ in s["fix_added"].most_common(5)],
            })
        out.sort(key=lambda r: (-r["sessions"], -r["count"], r["signature"]))
        return out


# ---------------------------------------------------------------- corpus y candidatas

def load_corpus_apis(corpus: Path) -> tuple[set[str], set[str]]:
    apis: set[str] = set()
    words: set[str] = set()
    if not corpus.exists():
        return apis, words
    with open(corpus, encoding="utf-8") as fh:
        for ln in fh:
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            for a in r.get("apis_used", []):
                apis.add(_canon(a))
            for a in r.get("aliases", []):
                words.add(a.lower())
    return apis, words


def _canon(a: str) -> str:
    a = a.strip()
    return a if a.startswith("std.") else "std." + a


def covered(api: str, corpus_apis: set[str]) -> bool:
    """El corpus cubre `api` si hay una entrada con esa API o un prefijo/extension directa."""
    if api in corpus_apis:
        return True
    # Io.File.Writer.interface cubre Io.File.Writer; y a la inversa, un metodo del mismo tipo.
    for c in corpus_apis:
        if c.startswith(api + ".") or api.startswith(c + "."):
            return True
    return False


def candidates(records: list[dict], corpus_apis: set[str], limit: int = 15) -> list[dict]:
    """APIs por sesiones distintas. `strong` = el propio mensaje del compilador nombra la API
    (o fue lo que la edicion arreglada anadio); lo demas solo aparece en la linea de codigo del error."""
    agg: dict[str, dict] = {}
    for r in records:
        strong = set(r["apis_msg"]) | set(r["fix_added_apis"])
        for a in dict.fromkeys(list(r["apis"]) + list(r["fix_added_apis"])):
            e = agg.setdefault(a, {"api": a, "count": 0, "sessions": 0, "sigs": 0, "strong": False})
            e["count"] += r["count"]
            e["sessions"] += r["sessions"]
            e["sigs"] += 1
            e["strong"] = e["strong"] or a in strong
    rows = list(agg.values())
    for e in rows:
        e["covered"] = covered(e["api"], corpus_apis)
    rows.sort(key=lambda e: (e["covered"], not e["strong"], -e["sessions"], -e["count"], e["api"]))
    return rows[:limit]


def write_report(out_dir: Path, records: list[dict], cands: list[dict], meta: dict) -> None:
    lines = ["# Mineria de transcripts: fallos de Zig 0.16", ""]
    lines += [
        "Generado por `scripts/mine_sessions.py`. Solo firmas de error del compilador, nombres de API y conteos "
        "(sin prompts, rutas, codigo ni tokens).", "",
        "## Volumen", "",
    ]
    for k, v in meta.items():
        lines.append(f"- {k}: {v}")
    lines += ["", "## Top 30 firmas", "",
              "| # | firma | n | sesiones | APIs | ediciones siguientes (antes -> despues) |",
              "|---|---|---|---|---|---|"]
    for i, r in enumerate(records[:30], 1):
        apis = ", ".join(f"`{a}`" for a in r["apis"][:3]) or "-"
        rem = ", ".join(r["fix_removed_apis"][:2])
        add = ", ".join(r["fix_added_apis"][:2])
        fix = f"{rem or '-'} -> {add or '-'} ({r['fix_edits']} ed., {r['fix_then_compiled']} compilan)" if r["fix_edits"] else "-"
        sig = r["signature"].replace("|", "\\|")
        lines.append(f"| {i} | `{sig}` | {r['count']} | {r['sessions']} | {apis} | {fix} |")
    lines += ["", "## 15 recetas candidatas", "",
              "Ordenadas: primero las NO cubiertas por el corpus, luego las que el propio mensaje del compilador o el arreglo nombran (`mensaje/fix`; `contexto` = solo aparecen en la linea de codigo del error), luego por sesiones distintas.", "",
              "| # | API | sesiones (suma) | firmas | evidencia | cubierta por el corpus |", "|---|---|---|---|---|---|"]
    for i, c in enumerate(cands, 1):
        lines.append(f"| {i} | `{c['api']}` | {c['sessions']} | {c['sigs']} | {'mensaje/fix' if c['strong'] else 'contexto'} | {'si' if c['covered'] else 'NO'} |")
    lines.append("")
    (out_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")


def iter_jsonl(base: Path):
    if base.is_file():
        yield base
        return
    for dp, _dn, fn in os.walk(base):
        for f in sorted(fn):
            if f.endswith(".jsonl"):
                yield Path(dp) / f


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--claude", default=str(Path.home() / ".claude" / "projects"))
    ap.add_argument("--codex", default=str(Path.home() / ".codex" / "sessions"))
    ap.add_argument("--out", default=str(ROOT / "var" / "mined"))
    ap.add_argument("--corpus", default=str(ROOT / "corpus" / "pyzig.corpus.jsonl"))
    args = ap.parse_args(argv)

    t0 = time.time()
    agg = Agg()
    nfiles = nbytes = 0
    found = {}
    for source, base in (("claude", Path(args.claude)), ("codex", Path(args.codex))):
        if not base.exists():
            found[source] = "no encontrado"
            continue
        n = 0
        for f in iter_jsonl(base):
            try:
                nbytes += f.stat().st_size
            except OSError:
                continue
            nfiles += 1
            n += 1
            sid = f"{source}:{n}"  # id anonimo, no el nombre del archivo
            agg.add_session(sid, source, session_stream(f, source))
        found[source] = f"{n} transcripts"
    records = agg.records()
    corpus_apis, _ = load_corpus_apis(Path(args.corpus))
    cands = candidates(records, corpus_apis)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "signatures.jsonl", "w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    dur = time.time() - t0
    meta = {
        "fuentes": "; ".join(f"{k}: {v}" for k, v in found.items()),
        "no parseadas": "codex *.zst (comprimidos), opencode (sqlite), gemini y qwen (otros formatos)",
        "transcripts leidos": nfiles,
        "volumen": f"{nbytes / 1e6:.0f} MB",
        "sesiones con zig": agg.stats["sessions_with_zig"],
        "ejecuciones zig": agg.stats["zig_runs"],
        "ejecuciones con errores": agg.stats["zig_runs_with_errors"],
        "firmas distintas": len(records),
        "duracion": f"{dur:.1f} s",
    }
    write_report(out, records, cands, meta)
    print(json.dumps(meta, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
