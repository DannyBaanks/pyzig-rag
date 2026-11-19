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

Fuentes (todas solo lectura y streaming): Claude `.jsonl`, Codex `.jsonl`/`.jsonl.zst`
(con `/usr/bin/zstd -dc`), OpenCode sqlite (`file:...?mode=ro`), Gemini/AGY `.jsonl` y
Qwen `.jsonl`. Cada raiz se puede sustituir con su flag.

Uso:  python3 scripts/mine_sessions.py [--claude DIR] [--codex DIR] [--opencode DIR]
                                        [--gemini DIR] [--qwen DIR] [--out DIR] [--corpus F]
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote

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
    r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}|"
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
    # Fuera de comillas (p.ej. textos de @compileError): cadenas con punto cuyo primer
    # segmento no es de la std son nombres de modulos/tipos propios -> se enmascaran.
    sig = re.sub(r"(?<!['\w.])([A-Za-z_]\w*)((?:\.[A-Za-z_]\w*)+)",
                 lambda mm: mm.group(0) if _keep_word(mm.group(1))
                 else "_" + "._" * mm.group(2).count("."), sig)
    sig = re.sub(r"(missing struct field|no field named|struct field): \w+", r"\1: _", sig)
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
    if isinstance(content, dict):
        for k in ("output", "text", "result", "content", "aggregated_output"):
            if content.get(k):
                return result_text(content[k])
        return ""
    if isinstance(content, list):
        return "\n".join(result_text(c) for c in content)
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


def events_codex_lines(lines):
    """Codex (.jsonl o lineas descomprimidas de .zst). response_item manda;
    los event_msg CommandExecution solo se usan si el fichero no trae response_item
    de herramientas, para no contar dos veces la misma ejecucion."""
    zig_ids: set = set()
    seen_response = False
    pending: list[tuple] = []
    for line in lines:
        if "zig" not in line and not (
            zig_ids and ("_output" in line or "item_completed" in line)
            and any(i in line for i in zig_ids)
        ):
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        p = d.get("payload")
        if not isinstance(p, dict):
            continue
        if d.get("type") == "response_item":
            pt = p.get("type")
            if pt in ("custom_tool_call", "function_call"):
                body = str(p.get("input") or p.get("arguments") or "")
                if ZIG_CMD.search(body):
                    cid = p.get("call_id") or p.get("id")
                    zig_ids.add(cid)
                    seen_response = True
                    yield ("zigcall", cid)
            elif pt in ("custom_tool_call_output", "function_call_output"):
                yield ("zigout", p.get("call_id") or p.get("id"), result_text(p.get("output")))
        elif d.get("type") == "event_msg" and p.get("type") == "item_completed":
            item = p.get("item")
            if not isinstance(item, dict) or item.get("type") != "CommandExecution":
                continue
            cmd = item.get("command")
            cmd = " ".join(str(x) for x in cmd) if isinstance(cmd, (list, tuple)) else str(cmd or "")
            if not ZIG_CMD.search(cmd):
                continue
            cid = item.get("id") or p.get("id")
            out = item.get("aggregated_output") or item.get("output") or ""
            pending.append((cid, out))
    if not seen_response:
        for cid, out in pending:
            yield ("zigcall", cid)
            yield ("zigout", cid, result_text(out))


def events_codex(path: Path):
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        yield from events_codex_lines(fh)


ZSTD = Path("/usr/bin/zstd")


def iter_zst_lines(path: Path):
    """Descomprime en streaming con zstd; nunca escribe el contenido a disco."""
    if not ZSTD.exists():
        raise OSError("zstd no disponible en /usr/bin/zstd")
    proc = subprocess.Popen(
        [str(ZSTD), "-dc", str(path)], stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True, errors="replace",
    )
    try:
        yield from proc.stdout
    finally:
        if proc.stdout is not None:
            proc.stdout.close()
    rc = proc.wait()
    if rc:
        raise OSError(f"zstd rc={rc}")


def events_codex_zst(path: Path):
    yield from events_codex_lines(iter_zst_lines(path))


def _first(obj, *keys):
    if isinstance(obj, dict):
        for k in keys:
            v = obj.get(k)
            if v not in (None, ""):
                return v
    return ""


def _cmd_of(args) -> str:
    cmd = _first(args, "command", "cmd", "command_line", "commandLine")
    return str(cmd) if cmd else ""


def edit_event(args, tool: str = ""):
    """Evento ('edit', base, old, new) si unos argumentos de herramienta editan .zig."""
    fp = _first(args, "file_path", "filePath", "path", "file", "filename")
    if not str(fp).endswith(".zig"):
        return None
    old = _first(args, "old_string", "oldString", "old")
    new = _first(args, "new_string", "newString", "new")
    if not new:
        new = _first(args, "content", "text")
    return ("edit", os.path.basename(str(fp)), str(old), str(new))


def events_opencode_rows(rows):
    """OpenCode guarda cada herramienta como un `part` JSON en sqlite."""
    for p in rows:
        if not isinstance(p, dict) or p.get("type") != "tool":
            continue
        tool = str(p.get("tool", "")).lower()
        state = p.get("state") or {}
        if not isinstance(state, dict):
            continue
        cid = p.get("callID") or p.get("callId") or p.get("id")
        args = state.get("input") or {}
        if tool in ("bash", "shell", "exec", "execute", "run"):
            if ZIG_CMD.search(_cmd_of(args)):
                yield ("zigcall", cid)
                out = state.get("output")
                if not out:
                    out = (state.get("metadata") or {}).get("output", "")
                yield ("zigout", cid, result_text(out))
        else:
            ev = edit_event(args, tool)
            if ev:
                yield ev


def events_gemini_lines(lines):
    """Gemini CLI/AGY: functionCall + functionResponse dentro de `content`/`parts`."""
    zig_ids: set = set()
    for line in lines:
        if "zig" not in line and not (zig_ids and ("functionResponse" in line or "toolResult" in line)):
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if not isinstance(d, dict):
            continue
        parts = d.get("content")
        if not isinstance(parts, list):
            msg = d.get("message")
            parts = msg.get("parts") if isinstance(msg, dict) else None
        if not isinstance(parts, list):
            continue
        for p in parts:
            if not isinstance(p, dict):
                continue
            fc = p.get("functionCall") or p.get("toolCall")
            if isinstance(fc, dict):
                name = str(fc.get("name") or fc.get("function") or "")
                args = fc.get("args") or fc.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except ValueError:
                        args = {"command": args}
                if ZIG_CMD.search(_cmd_of(args)):
                    cid = _first(fc, "id", "callId", "call_id") or _first(d, "id")
                    zig_ids.add(cid)
                    yield ("zigcall", cid)
                else:
                    ev = edit_event(args, name)
                    if ev:
                        yield ev
            fr = p.get("functionResponse") or p.get("toolResult")
            if isinstance(fr, dict):
                cid = _first(fr, "id", "callId", "call_id")
                resp = fr.get("response")
                out = resp.get("output") if isinstance(resp, dict) else resp
                if out is None:
                    out = _first(fr, "output", "result", "text")
                yield ("zigout", cid, result_text(out))


def events_qwen_lines(lines):
    """Qwen Code: `functionCall` en assistant y `functionResponse` en tool_result."""
    zig_ids: set = set()
    for line in lines:
        if "zig" not in line and not (zig_ids and ("functionResponse" in line or "tool_result" in line)):
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if not isinstance(d, dict):
            continue
        msg = d.get("message") or {}
        parts = msg.get("parts") if isinstance(msg, dict) else None
        if not isinstance(parts, list):
            continue
        if d.get("type") in ("assistant", "tool_result") or msg.get("role") in ("model", "user"):
            for p in parts:
                if not isinstance(p, dict):
                    continue
                fc = p.get("functionCall")
                if isinstance(fc, dict):
                    args = fc.get("args") or fc.get("arguments") or {}
                    if ZIG_CMD.search(_cmd_of(args)):
                        cid = _first(fc, "id", "callId", "call_id")
                        zig_ids.add(cid)
                        yield ("zigcall", cid)
                    else:
                        ev = edit_event(args, str(fc.get("name", "")))
                        if ev:
                            yield ev
                fr = p.get("functionResponse")
                if isinstance(fr, dict):
                    cid = _first(fr, "id", "callId", "call_id")
                    if d.get("type") == "tool_result":
                        cid = _first(d.get("toolCallResult"), "callId") or cid
                    resp = fr.get("response")
                    out = resp.get("output") if isinstance(resp, dict) else resp
                    if out is None:
                        out = _first(fr, "output", "result", "text")
                    yield ("zigout", cid, result_text(out))


def session_stream(path: Path, source: str):
    if source == "claude":
        return events_claude(path)
    if source == "codex":
        return events_codex(path)
    if source == "codex_zst":
        return events_codex_zst(path)
    if source == "gemini":
        return events_gemini(path)
    if source == "qwen":
        return events_qwen(path)
    raise ValueError(f"fuente desconocida: {source}")


def events_gemini(path: Path):
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        yield from events_gemini_lines(fh)


def events_qwen(path: Path):
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        yield from events_qwen_lines(fh)


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

def signature_key(sig: str) -> str:
    """Clave comparable de una linea `error: ...` del corpus y de una firma minada."""
    s = str(sig).strip()
    if s.lower().startswith("error: "):
        s = s[7:]
    return normalize_msg(s)[0]


class CorpusCoverage:
    """Indice de cobertura: apis_used + aliases + texto de error_signatures -> operation_id."""

    def __init__(self) -> None:
        self.apis: set[str] = set()
        self.words: set[str] = set()
        self.api_ops: dict[str, str] = {}
        self.alias_ops: dict[str, str] = {}
        self.sig_ops: dict[str, str] = {}
        self.sig_api_ops: dict[str, str] = {}

    def add_apis(self, op: str, apis) -> None:
        for a in apis or []:
            c = _canon(a)
            self.apis.add(c)
            self.api_ops.setdefault(c, op)

    def add_alias(self, op: str, alias) -> None:
        s = str(alias).strip()
        if not s:
            return
        self.words.add(s.lower())
        c = _canon(s).replace("()", "")
        parts = c.split(".")
        for i in range(2, len(parts) + 1):
            self.alias_ops.setdefault(".".join(parts[:i]), op)

    def add_signature(self, op: str, sig) -> None:
        self.sig_ops.setdefault(signature_key(sig), op)
        for a in normalize_msg(str(sig))[1]:
            self.sig_api_ops.setdefault(a, op)

    def locate(self, api: str, mined_sigs=()) -> str | None:
        """operation_id que cubre `api`, o None. Las firmas minadas se comprueban primero."""
        for s in mined_sigs or ():
            op = self.sig_ops.get(signature_key(s))
            if op:
                return op
        c = _canon(api)
        if not c:
            return None
        for mapping in (self.api_ops, self.alias_ops, self.sig_api_ops):
            if c in mapping:
                return mapping[c]
        # Io.File.Writer.interface cubre Io.File.Writer; y un metodo del mismo tipo a la inversa.
        for mapping in (self.api_ops, self.alias_ops, self.sig_api_ops):
            for k in sorted(mapping):
                if k.startswith(c + ".") or c.startswith(k + "."):
                    return mapping[k]
        return None


def load_corpus_apis(corpus: Path) -> CorpusCoverage:
    cov = CorpusCoverage()
    if not corpus.exists():
        return cov
    with open(corpus, encoding="utf-8") as fh:
        for ln in fh:
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            op = str(r.get("operation_id") or r.get("name") or "<sin operation_id>")
            cov.add_apis(op, r.get("apis_used", []))
            for a in r.get("aliases", []):
                cov.add_alias(op, a)
            for s in r.get("error_signatures", []):
                cov.add_signature(op, s)
    return cov


def _canon(a: str) -> str:
    a = str(a).strip()
    if a.startswith("std."):
        return a
    parts = a.split(".")
    if parts and parts[0] in STD_ROOTS:
        return "std." + a
    return a


def covered(api: str, corpus_apis, mined_sigs=()) -> bool:
    """Cubierta por apis_used, aliases, error_signatures o por firma minada emparejada."""
    if isinstance(corpus_apis, CorpusCoverage):
        return corpus_apis.locate(api, mined_sigs) is not None
    tmp = CorpusCoverage()
    for c in corpus_apis:
        tmp.api_ops.setdefault(_canon(c), "<corpus>")
        tmp.apis.add(_canon(c))
    return tmp.locate(api, mined_sigs) is not None


def annotate_coverage(records: list[dict], cov: CorpusCoverage) -> None:
    """Anade `covered_by` (operation_ids) a cada firma, sin tocar su texto normalizado.

    Una firma solo queda cubierta por (a) emparejamiento de su texto normalizado con
    una `error_signatures` del corpus, o (b) APIs fuertes: las que el mensaje del
    compilador nombra (`apis_msg`) o las que anadio la edicion que arreglo el error
    (`fix_added_apis`). Las APIs de `apis` (linea de codigo bajo el error) solo
    comparten contexto: se guardan en `context_ops`, pero no cuentan como cobertura.
    """
    for r in records:
        ops = set()
        op = cov.locate("", [r["signature"]])
        if op:
            ops.add(op)
        for a in list(r["apis_msg"]) + list(r["fix_added_apis"]):
            op = cov.locate(a)
            if op:
                ops.add(op)
        r["covered_by"] = sorted(ops)
        context_ops = set()
        for a in r["apis"]:
            op = cov.locate(a)
            if op:
                context_ops.add(op)
        r["context_ops"] = sorted(context_ops - ops)


def candidates(records: list[dict], cov: CorpusCoverage, limit: int = 15) -> list[dict]:
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
        e["covered_by"] = cov.locate(e["api"]) or ""
        e["covered"] = bool(e["covered_by"])
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
              "| # | firma | n | sesiones | APIs | ediciones siguientes (antes -> despues) | operation_id que la cubre | solo comparte API de contexto (no cubre) |",
              "|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(records[:30], 1):
        apis = ", ".join(f"`{a}`" for a in r["apis"][:3]) or "-"
        rem = ", ".join(r["fix_removed_apis"][:2])
        add = ", ".join(r["fix_added_apis"][:2])
        fix = f"{rem or '-'} -> {add or '-'} ({r['fix_edits']} ed., {r['fix_then_compiled']} compilan)" if r["fix_edits"] else "-"
        sig = r["signature"].replace("|", "\\|")
        ops = ", ".join(f"`{o}`" for o in r.get("covered_by", [])) or "-"
        ctx = ", ".join(f"`{o}`" for o in r.get("context_ops", [])) or "-"
        lines.append(f"| {i} | `{sig}` | {r['count']} | {r['sessions']} | {apis} | {fix} | {ops} | {ctx} |")
    lines += ["", "## 15 recetas candidatas", "",
              "Ordenadas: primero las NO cubiertas por el corpus, luego las que el propio mensaje del compilador o el arreglo nombran (`arregla el error`; `usa la API` = solo aparece en la linea de codigo del error), luego por sesiones distintas. En esta tabla la cobertura es POR API (`apis_used`, `aliases`, texto de `error_signatures`); en la tabla de firmas, en cambio, solo cuenta el emparejamiento de la firma o una API fuerte del mensaje/fix.", "",
              "| # | API | sesiones (suma) | firmas | evidencia | cubierta por el corpus | operation_id |", "|---|---|---|---|---|---|---|"]
    for i, c in enumerate(cands, 1):
        evidencia = "arregla el error" if c["strong"] else "usa la API"
        lines.append(f"| {i} | `{c['api']}` | {c['sessions']} | {c['sigs']} | {evidencia} | {'si' if c['covered'] else 'NO'} | {c.get('covered_by') or '-'} |")
    lines.append("")
    (out_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")


def iter_files(base: Path, suffix: str):
    if base.is_file():
        if base.name.endswith(suffix):
            yield base
        return
    for dp, _dn, fn in os.walk(base):
        for f in sorted(fn):
            if f.endswith(suffix):
                yield Path(dp) / f


def iter_jsonl(base: Path):
    yield from iter_files(base, ".jsonl")


def iter_codex_files(base: Path):
    seen = set()
    for suffix in (".jsonl", ".zst"):
        for f in iter_files(base, suffix):
            r = f.resolve()
            if r not in seen:
                seen.add(r)
                yield f


def iter_sqlite_files(base: Path):
    seen = set()
    candidates = list(base.glob("*.db")) + list(base.glob("*.sqlite"))
    storage = base / "storage"
    if storage.exists():
        candidates += list(storage.rglob("*.db")) + list(storage.rglob("*.sqlite"))
    for f in sorted(candidates):
        r = f.resolve()
        if r not in seen:
            seen.add(r)
            yield f


def claude_sessions(base, stat_cb=None):
    for f in iter_jsonl(base):
        if stat_cb:
            stat_cb(f)
        yield str(f), events_claude(f)


def codex_sessions(base, stat_cb=None):
    for f in iter_codex_files(base):
        if stat_cb:
            stat_cb(f)
        source = "codex_zst" if f.name.endswith(".zst") else "codex"
        yield str(f), session_stream(f, source)


def opencode_sessions(base, stat_cb=None):
    files = list(iter_sqlite_files(base))
    if not files:
        raise OSError("sin sqlite .db/.sqlite en la raiz ni en storage/")
    for db in files:
        if stat_cb:
            stat_cb(db)
        con = None
        try:
            uri = "file:" + quote(str(db)) + "?mode=ro"
            con = sqlite3.connect(uri, uri=True)
            tables = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
            if "part" not in tables:
                continue
            ids = [r[0] for r in con.execute("select distinct session_id from part order by session_id")]
            for sid in ids:
                cur = con.execute(
                    "select data from part where session_id=? order by time_created,id", (sid,))
                def rows(cur=cur):
                    for (data,) in cur:
                        try:
                            yield json.loads(data)
                        except ValueError:
                            continue
                yield str(sid), events_opencode_rows(rows())
        except sqlite3.Error as e:
            raise OSError(f"sqlite {db.name}: {e}") from e
        finally:
            if con is not None:
                con.close()


def iter_gemini_files(base: Path):
    if base.is_file():
        if base.name.endswith(".jsonl"):
            yield base
        return
    for f in sorted(base.rglob("chats/*.jsonl")):
        yield f
    hist = base / "antigravity-cli" / "history.jsonl"
    if hist.exists():
        yield hist


def gemini_sessions(base, stat_cb=None):
    for f in iter_gemini_files(base):
        if stat_cb:
            stat_cb(f)
        yield str(f), session_stream(f, "gemini")


def qwen_sessions(base, stat_cb=None):
    for f in iter_files(base, ".jsonl"):
        if stat_cb:
            stat_cb(f)
        yield str(f), session_stream(f, "qwen")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--claude", default=str(Path.home() / ".claude" / "projects"))
    ap.add_argument("--codex", default=str(Path.home() / ".codex" / "sessions"))
    ap.add_argument("--opencode", default=str(Path.home() / ".local" / "share" / "opencode"))
    ap.add_argument("--gemini", default=str(Path.home() / ".gemini"))
    ap.add_argument("--qwen", default=str(Path.home() / ".qwen"))
    ap.add_argument("--out", default=str(ROOT / "var" / "mined"))
    ap.add_argument("--corpus", default=str(ROOT / "corpus" / "pyzig.corpus.jsonl"))
    args = ap.parse_args(argv)

    t0 = time.time()
    agg = Agg()
    nbytes = nsessions = 0
    found: dict[str, str] = {}
    unparsed: list[str] = []

    def note_file(f):
        nonlocal nbytes
        try:
            nbytes += Path(f).stat().st_size
        except OSError:
            pass

    def consume(source, base, sessions):
        nonlocal nsessions
        base = Path(base)
        if not base.exists():
            found[source] = "no encontrado"
            unparsed.append(f"{source}: raiz no encontrada")
            return
        n = 0
        try:
            for _fid, events in sessions(base, note_file):
                n += 1
                nsessions += 1

                def guarded(events=events, source=source, n=n):
                    try:
                        yield from events
                    except Exception as e:  # un transcript ilegible no tumba el minado
                        unparsed.append(
                            f"{source}: sesion {n} ilegible ({type(e).__name__}: {str(e)[:90]})")

                try:
                    agg.add_session(f"{source}:{n}", source, guarded())
                except Exception as e:
                    unparsed.append(f"{source}: sesion {n} omitida ({type(e).__name__})")
        except Exception as e:
            unparsed.append(f"{source}: {type(e).__name__}: {str(e)[:140]}")
        found[source] = f"{n} transcripts"

    consume("claude", args.claude, claude_sessions)
    consume("codex", args.codex, codex_sessions)
    consume("opencode", args.opencode, opencode_sessions)
    consume("gemini", args.gemini, gemini_sessions)
    consume("qwen", args.qwen, qwen_sessions)

    records = agg.records()
    cov = load_corpus_apis(Path(args.corpus))
    if not unparsed and cov.apis:
        unparsed.append("ninguna")
    if not cov.apis:
        unparsed.append("corpus: sin apis cargadas (cobertura no demonstrable)")
    annotate_coverage(records, cov)
    cands = candidates(records, cov)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "signatures.jsonl", "w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    dur = time.time() - t0
    meta = {
        "fuentes": "; ".join(f"{k}: {v}" for k, v in found.items()),
        "no parseadas": "; ".join(unparsed),
        "transcripts leidos": nsessions,
        "volumen": f"{nbytes / 1e6:.0f} MB",
        "sesiones con zig": agg.stats["sessions_with_zig"],
        "ejecuciones zig": agg.stats["zig_runs"],
        "ejecuciones con errores": agg.stats["zig_runs_with_errors"],
        "firmas distintas": len(records),
        "firmas con operation_id": sum(1 for r in records if r["covered_by"]),
        "duracion": f"{dur:.1f} s",
    }
    write_report(out, records, cands, meta)
    print(json.dumps(meta, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
