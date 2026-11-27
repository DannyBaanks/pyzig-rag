#!/usr/bin/env python3
"""Uso REAL de pyzig por los agentes en los transcripts locales.

Pregunta: los agentes que escriben o compilan Zig, ¿consultan pyzig por
iniciativa propia y les sirve? Este script recorre las mismas fuentes que
`scripts/mine_sessions.py` (que se importa, no se modifica) y escribe solo
AGREGADOS en `eval/usage.json`:

  - sesiones Zig totales y cuantas hicieron alguna llamada a pyzig;
  - llamadas por herramienta (`pyzig_search/get/catalog/check`), por origen
    (pedidas: un mensaje del usuario menciona pyzig antes de la llamada;
    espontaneas: sin mencion) y por resultado (results/NO_RESULTS/error);
  - errores de compilacion Zig vistos sin consultar pyzig cuando el corpus
    tiene receta para la firma (cruce con `corpus/` y las firmas de
    `var/mined/`), y si la siguiente ejecucion zig paso.

PRIVACIDAD (obligatoria, el repo es publico): nunca se escribe texto de
mensajes, consultas literales, rutas, ids de sesion ni nombres de proyecto.
Las consultas a pyzig no se guardan; las firmas de error se normalizan con
`mine_sessions.normalize_msg` (igual que el minero). El JSON solo lleva
conteos, nombres de herramienta, estados y firmas normalizadas.

Uso:
    python3 scripts/usage_sessions.py [--out eval/usage.json] [--jobs N]
        [--claude DIR] [--codex DIR] [--opencode DIR] [--gemini DIR]
        [--qwen DIR] [--corpus F]

El descubrimiento de ficheros es el del minero (`iter_jsonl`,
`iter_codex_files`, `iter_sqlite_files`, `iter_gemini_files`). El propio
minero no recorre los `brain/*/.system_generated/logs/transcript.jsonl` de
AGY; se declara como limitacion en `eval/USAGE.md`.
"""
from __future__ import annotations

import argparse
import ast
import collections
import json
import os
import re
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mine_sessions as mine  # noqa: E402  (se reutiliza su descubrimiento y normalizacion)

PYZIG_TOOLS = ("pyzig_search", "pyzig_get", "pyzig_catalog", "pyzig_check")
PYZIG_SERVER = "pyzig-rag"

#: cobertura del corpus cargada una vez en el padre (fork la hereda en los workers).
COVERAGE = mine.CorpusCoverage()
#: etiquetas humanas de `eval/mined_labels.tsv`: firma normalizada -> operation_id.
LABELS: dict[str, str] = {}


# ---------------------------------------------------------------- utilidades

def _lines(path: Path):
    """Lineas de un transcript; descomprime .zst en streaming (nunca escribe a disco)."""
    if str(path).endswith(".zst"):
        yield from mine.iter_zst_lines(path)
    else:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            yield from fh


def _texts(content) -> list[str]:
    """Textos de un contenido tipo mensaje (nunca resultados de herramienta)."""
    if isinstance(content, str):
        return [content]
    if not isinstance(content, list):
        return []
    out = []
    for c in content:
        if isinstance(c, str):
            out.append(c)
        elif isinstance(c, dict) and c.get("type") in ("text", "input_text"):
            t = c.get("text")
            if isinstance(t, str):
                out.append(t)
    return out


def mentions_pyzig(text: str) -> bool:
    return "pyzig" in (text or "").lower()


def _as_dict(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        s = value.strip()
        for loader in (json.loads, ast.literal_eval):
            try:
                got = loader(s)
            except (ValueError, SyntaxError):
                continue
            if isinstance(got, dict):
                return got
    return {}


def _tool_base(name: str) -> str:
    """`mcp__isymcp-hub__hub_execute` / `pyzig-rag_pyzig_search` -> ultimo segmento."""
    n = str(name or "").strip().lower().replace("-", "_")
    if "__" in n:
        n = n.split("__")[-1]
    return n


def pyzig_call(name: str, args) -> tuple[str, str] | None:
    """(herramienta pyzig, 'hub'|'direct') si la llamada consulta pyzig; si no, None.

    Cubre las tres formas observadas:
      - tool directa: `pyzig_search`, `mcp__pyzig-rag__pyzig_search`, ...
      - hub: `hub_execute(server="pyzig-rag", tool="pyzig_search", ...)`
      - MCP generico de AGY: `call_mcp_tool(ServerName="pyzig-rag", ToolName="pyzig_search")`
    """
    base = _tool_base(name)
    a = _as_dict(args)
    if "hub_execute" in base or base == "call_mcp_tool":
        server = str(a.get("server") or a.get("ServerName") or "")
        tool = str(a.get("tool") or a.get("ToolName") or "").strip()
        if "pyzig" in server.lower() and tool in PYZIG_TOOLS:
            return tool, "hub"
        return None
    for tool in PYZIG_TOOLS:
        if base == tool or base.endswith("_" + tool):
            return tool, "direct"
    return None


def pyzig_call_from_text(body: str) -> tuple[str, str] | None:
    """pyzig invocado dentro de un `exec` JavaScript de Codex (texto suelto).

    Exige que el servidor declarado sea pyzig-rag; un texto que solo mencione
    pyzig (p. ej. la descripcion del hub o una ruta del repo) NO es una llamada.
    """
    b = str(body or "")
    if "hub_execute" not in b and "call_mcp_tool" not in b:
        return None
    if not re.search(r"(?:server|servername)\s*[:=]\s*['\"]?pyzig(?:[-_]rag)?\b", b, re.I):
        return None
    m = re.search(r"['\"]?(pyzig_search|pyzig_get|pyzig_catalog|pyzig_check)['\"]?", b)
    if not m:
        return None
    return m.group(1), "hub"


STATUS_KEYS = ("results", "no_results", "version_mismatch", "compile_fail", "error", "unknown")


def classify_result(tool: str, text: str) -> str:
    """Estado de una respuesta de pyzig, sin guardar su contenido."""
    t = text or ""
    u = t.lower()
    if not t.strip():
        return "unknown"
    if "no_results" in u:
        return "no_results"
    if "version_mismatch" in u:
        return "version_mismatch"
    if "sandbox_unavailable" in u or "index_unavailable" in u:
        return "error"
    if "traceback (most recent call last)" in u:
        return "error"
    if re.search(r'"ok"\s*:\s*false', u) or re.search(r"\bok\s*=\s*false\b", u):
        return "error"
    if tool == "pyzig_check":
        if re.search(r'"compiled"\s*:\s*false', u):
            return "compile_fail"
        if re.search(r'"compiled"\s*:\s*true', u):
            return "results"
    if tool == "pyzig_search":
        m = re.search(r'"?count"?\s*[:=]\s*(\d+)', u)
        if m and int(m.group(1)) == 0:
            return "no_results"
    return "results"


# ---------------------------------------------------------------- parsers por fuente
# Todos devuelven una lista de eventos ordenados:
#   ("usermark",)                  mensaje del usuario que menciona pyzig
#   ("zigcall", id) ("zigout", id, texto)
#   ("pyzigcall", id, tool) ("pyzigout", id, texto)
#   ("edit",)                      edicion/escritura de un .zig

def parse_claude(path: Path):
    events: list[tuple] = []
    pending: dict[str, str] = {}
    for line in _lines(path):
        low = line.lower()
        if "zig" not in low and not ("tool_result" in low and pending):
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if not isinstance(d, dict):
            continue
        msg = d.get("message")
        if not isinstance(msg, dict):
            continue
        cont = msg.get("content")
        if msg.get("role") == "user":
            if any(mentions_pyzig(t) for t in _texts(cont)):
                events.append(("usermark",))
        if not isinstance(cont, list):
            continue
        for c in cont:
            if not isinstance(c, dict):
                continue
            kind = c.get("type")
            if kind == "tool_use":
                cid = c.get("id")
                inp = c.get("input") or {}
                pc = pyzig_call(str(c.get("name", "")), inp)
                if pc:
                    events.append(("pyzigcall", cid, pc[0]))
                    pending[cid] = "pyzig"
                elif str(c.get("name")) == "Bash" and mine.ZIG_CMD.search(str(inp.get("command", ""))):
                    events.append(("zigcall", cid))
                    pending[cid] = "zig"
                elif str(c.get("name")) in ("Edit", "MultiEdit", "Write"):
                    if mine.edit_event(inp, str(c.get("name"))):
                        events.append(("edit",))
            elif kind == "tool_result":
                cid = c.get("tool_use_id")
                p = pending.pop(cid, None)
                if p == "zig":
                    events.append(("zigout", cid, mine.result_text(c.get("content"))))
                elif p == "pyzig":
                    events.append(("pyzigout", cid, mine.result_text(c.get("content"))))
    return events


def _codex_tool(name, body, cid, pending, events):
    pc = pyzig_call(name, body)
    if pc is None:
        pc = pyzig_call_from_text(body)
    if pc:
        events.append(("pyzigcall", cid, pc[0]))
        pending[cid] = "pyzig"
    elif mine.ZIG_CMD.search(str(body)):
        events.append(("zigcall", cid))
        pending[cid] = "zig"


def parse_codex(path: Path):
    events: list[tuple] = []
    pending: dict[str, str] = {}
    seen_response = False
    event_calls: list[tuple] = []
    for line in _lines(path):
        low = line.lower()
        if "zig" not in low and not pending:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if not isinstance(d, dict):
            continue
        p = d.get("payload")
        if not isinstance(p, dict):
            continue
        if d.get("type") == "response_item":
            pt = p.get("type")
            if pt == "message" and p.get("role") == "user":
                if any(mentions_pyzig(t) for t in _texts(p.get("content"))):
                    events.append(("usermark",))
            elif pt in ("custom_tool_call", "function_call"):
                seen_response = True
                cid = p.get("call_id") or p.get("id")
                body = p.get("input") if p.get("input") is not None else p.get("arguments")
                _codex_tool(str(p.get("name", "")), body, cid, pending, events)
            elif pt in ("custom_tool_call_output", "function_call_output"):
                cid = p.get("call_id") or p.get("id")
                kind = pending.pop(cid, None)
                if kind == "zig":
                    events.append(("zigout", cid, mine.result_text(p.get("output"))))
                elif kind == "pyzig":
                    events.append(("pyzigout", cid, mine.result_text(p.get("output"))))
        elif d.get("type") == "event_msg" and p.get("type") == "item_completed":
            item = p.get("item")
            if not isinstance(item, dict) or item.get("type") != "CommandExecution":
                continue
            cmd = item.get("command")
            cmd = " ".join(str(x) for x in cmd) if isinstance(cmd, (list, tuple)) else str(cmd or "")
            if not mine.ZIG_CMD.search(cmd):
                continue
            cid = item.get("id") or p.get("id")
            event_calls.append((cid, mine.result_text(
                item.get("aggregated_output") or item.get("output") or "")))
    if not seen_response:
        for cid, out in event_calls:
            events.append(("zigcall", cid))
            events.append(("zigout", cid, out))
    return events


def _parse_opencode_part(p, roles) -> list[tuple]:
    events: list[tuple] = []
    if not isinstance(p, dict):
        return events
    typ = p.get("type")
    if typ == "text":
        if roles.get(str(p.get("message_id") or "")) == "user" and mentions_pyzig(p.get("text", "")):
            events.append(("usermark",))
        return events
    if typ != "tool":
        return events
    tool = str(p.get("tool", ""))
    state = p.get("state") or {}
    if not isinstance(state, dict):
        return events
    cid = p.get("callID") or p.get("callId") or p.get("id")
    args = state.get("input") or {}
    output = mine.result_text(
        state.get("output") or (state.get("metadata") or {}).get("output", ""))
    pc = pyzig_call(tool, args)
    if pc:
        events.append(("pyzigcall", cid, pc[0]))
        events.append(("pyzigout", cid, output))
    elif mine.ZIG_CMD.search(mine._cmd_of(args) if isinstance(args, dict) else ""):
        events.append(("zigcall", cid))
        events.append(("zigout", cid, output))
    elif isinstance(args, dict) and mine.edit_event(args, tool):
        events.append(("edit",))
    return events


def summarize_opencode(path: Path) -> dict:
    """Un fichero sqlite puede tener muchas sesiones; se resume cada una.

    Una sola pasada por `part` agrupando por `session_id` (evita una consulta
    por sesion, que sobre 180k partes era el cuello de botella) y solo se pide
    `role` a la tabla de mensajes con `json_extract` (no el JSON completo).
    """
    import sqlite3
    from urllib.parse import quote

    out = _blank_summary()
    uri = "file:" + quote(str(path)) + "?mode=ro"
    con = None
    try:
        con = sqlite3.connect(uri, uri=True)
        tables = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
        if "part" not in tables:
            return out
        roles: dict[str, str] = {}
        if "message" in tables:
            for mid, role in con.execute(
                    "select id, json_extract(data, '$.role') from message"):
                roles[str(mid)] = str(role or "")
        cur_sid = None
        events: list[tuple] = []
        nsessions = 0
        for sid, data in con.execute(
                "select session_id,data from part order by session_id,time_created,id"):
            if sid != cur_sid:
                if cur_sid is not None:
                    _merge_summary(out, summarize_events(events))
                    nsessions += 1
                cur_sid, events = sid, []
            try:
                p = json.loads(data)
            except ValueError:
                continue
            events.extend(_parse_opencode_part(p, roles))
        if cur_sid is not None:
            _merge_summary(out, summarize_events(events))
            nsessions += 1
        out["sessions"] = nsessions
    finally:
        if con is not None:
            con.close()
    return out


def _parse_gemini_like(lines, user_types: set[str]):
    events: list[tuple] = []
    pending: dict[str, str] = {}
    for line in lines:
        low = line.lower()
        if "zig" not in low and not pending:
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
        is_user = d.get("type") in user_types or (
            isinstance(d.get("message"), dict) and d["message"].get("role") == "user")
        if is_user:
            if any(mentions_pyzig(p.get("text", "")) for p in parts if isinstance(p, dict)):
                events.append(("usermark",))
        for p in parts:
            if not isinstance(p, dict):
                continue
            fc = p.get("functionCall") or p.get("toolCall")
            if isinstance(fc, dict):
                name = str(fc.get("name") or fc.get("function") or "")
                args = fc.get("args") or fc.get("arguments") or {}
                cid = mine._first(fc, "id", "callId", "call_id") or mine._first(d, "id")
                pc = pyzig_call(name, args)
                if pc is None and isinstance(args, str):
                    pc = pyzig_call_from_text(args)
                if pc:
                    events.append(("pyzigcall", cid, pc[0]))
                    pending[cid] = "pyzig"
                elif mine.ZIG_CMD.search(mine._cmd_of(args) if isinstance(args, dict) else str(args)):
                    events.append(("zigcall", cid))
                    pending[cid] = "zig"
                elif isinstance(args, dict) and mine.edit_event(args, name):
                    events.append(("edit",))
            fr = p.get("functionResponse") or p.get("toolResult")
            if isinstance(fr, dict):
                cid = mine._first(fr, "id", "callId", "call_id")
                if d.get("type") == "tool_result":
                    cid = mine._first(d.get("toolCallResult"), "callId") or cid
                kind = pending.pop(cid, None)
                if kind:
                    resp = fr.get("response")
                    out = resp.get("output") if isinstance(resp, dict) else resp
                    if out is None:
                        out = mine._first(fr, "output", "result", "text")
                    events.append(("zigout" if kind == "zig" else "pyzigout", cid, mine.result_text(out)))
    return events


def parse_gemini(path: Path):
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return _parse_gemini_like(fh, {"user", "human"})


def parse_qwen(path: Path):
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return _parse_gemini_like(fh, {"user", "human"})


def parse_session(source: str, path: Path):
    if source == "claude":
        return parse_claude(path)
    if source in ("codex", "codex_zst"):
        return parse_codex(path)
    if source == "gemini":
        return parse_gemini(path)
    if source == "qwen":
        return parse_qwen(path)
    raise ValueError(f"fuente desconocida: {source}")


# ---------------------------------------------------------------- agregacion

def _blank_summary() -> dict:
    return {
        "sessions": 0,
        "sessions_with_zig": 0,
        "sessions_with_pyzig": 0,
        "zig_runs": 0,
        "zig_runs_with_errors": 0,
        "calls_total": 0,
        "calls_requested": 0,
        "calls_spontaneous": 0,
        "by_tool": collections.Counter(),
        "by_tool_origin": collections.Counter(),
        "by_tool_status": collections.Counter(),
        "opportunities": collections.Counter(),
        "signatures": {},
        "unparsed": 0,
    }


def _merge_summary(dst: dict, src: dict) -> None:
    for k in ("sessions", "sessions_with_zig", "sessions_with_pyzig", "zig_runs",
              "zig_runs_with_errors", "calls_total", "calls_requested", "calls_spontaneous",
              "unparsed"):
        dst[k] += src.get(k, 0)
    for k in ("by_tool", "by_tool_origin", "by_tool_status", "opportunities"):
        dst[k].update(src.get(k) or {})
    for sig, rec in (src.get("signatures") or {}).items():
        cur = dst["signatures"].setdefault(
            sig, {"count": 0, "sessions": 0, "recipe": rec.get("recipe") or "",
                  "consulted": 0, "passed": 0})
        cur["count"] += rec.get("count", 0)
        cur["sessions"] += rec.get("sessions", 0)
        cur["consulted"] += rec.get("consulted", 0)
        cur["passed"] += rec.get("passed", 0)
        if not cur["recipe"]:
            cur["recipe"] = rec.get("recipe") or ""


def _recipe_for(err: dict) -> str:
    """operation_id del corpus (o etiqueta humana) para esta firma/API, o ''."""
    op = COVERAGE.locate("", [err.get("sig", "")])
    if op:
        return op
    for api in err.get("apis_msg") or []:
        op = COVERAGE.locate(api)
        if op:
            return op
    return LABELS.get(err.get("sig", ""), "")


def load_labels(path: Path) -> dict[str, str]:
    """firma normalizada -> primer operation_id de `eval/mined_labels.tsv` (NONE se ignora)."""
    labels: dict[str, str] = {}
    if not path.exists():
        return labels
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        if len(parts) != 2:
            continue
        sig, oid = parts[0].strip(), parts[1].strip()
        if not sig or oid == "NONE":
            continue
        labels.setdefault(sig, oid.split(",")[0].strip())
    return labels


def summarize_events(events) -> dict:
    s = _blank_summary()
    s["sessions"] = 1
    timeline: list[tuple] = []
    index: dict[str, int] = {}

    for ev in events:
        kind = ev[0]
        if kind == "usermark":
            timeline.append(("user",))
        elif kind == "edit":
            timeline.append(("edit",))
        elif kind == "zigcall":
            timeline.append(("run", []))
            index[ev[1]] = len(timeline) - 1
        elif kind == "zigout":
            i = index.get(ev[1])
            if i is not None and timeline[i][0] == "run" and timeline[i][1] == []:
                errs = [e for e in mine.parse_zig_output(ev[2]) if e["kind"] == "error"]
                timeline[i] = ("run", errs)
        elif kind == "pyzigcall":
            timeline.append(("pyzig", ev[2], "unknown"))
            index[ev[1]] = len(timeline) - 1
        elif kind == "pyzigout":
            i = index.get(ev[1])
            if i is not None and timeline[i][0] == "pyzig":
                timeline[i] = ("pyzig", timeline[i][1], classify_result(timeline[i][1], ev[2]))

    has_zig = any(t[0] in ("run", "edit") for t in timeline)
    if not has_zig:
        return s
    s["sessions_with_zig"] = 1

    pyzig_positions = [i for i, t in enumerate(timeline) if t[0] == "pyzig"]
    if pyzig_positions:
        s["sessions_with_pyzig"] = 1

    for i in pyzig_positions:
        _, tool, status = timeline[i]
        requested = any(t[0] == "user" for t in timeline[:i])
        s["calls_total"] += 1
        s["calls_requested" if requested else "calls_spontaneous"] += 1
        s["by_tool"][tool] += 1
        s["by_tool_origin"][f"{tool}:{'requested' if requested else 'spontaneous'}"] += 1
        s["by_tool_status"][f"{tool}:{status if status in STATUS_KEYS else 'unknown'}"] += 1

    run_positions = [i for i, t in enumerate(timeline) if t[0] == "run"]
    s["zig_runs"] = len(run_positions)
    seen_sigs: set[str] = set()
    for pos in run_positions:
        errs = timeline[pos][1]
        if not errs:
            continue
        s["zig_runs_with_errors"] += 1
        next_run = next((j for j in run_positions if j > pos), None)
        end = next_run if next_run is not None else len(timeline)
        consulted = any(t[0] == "pyzig" for t in timeline[pos + 1:end])
        passed = next_run is not None and not timeline[next_run][1]
        reported = set()
        for err in errs:
            sig = err.get("sig", "")
            if not sig or sig in reported:
                continue
            reported.add(sig)
            recipe = _recipe_for(err)
            rec = s["signatures"].setdefault(
                sig, {"count": 0, "sessions": 0, "recipe": recipe, "consulted": 0, "passed": 0})
            rec["count"] += 1
            rec["consulted"] += int(consulted)
            rec["passed"] += int(bool(recipe) and passed)
            if sig not in seen_sigs:
                seen_sigs.add(sig)
                rec["sessions"] += 1
                if recipe:
                    s["opportunities"]["with_recipe"] += 1
                    if consulted:
                        s["opportunities"]["consulted"] += 1
                    else:
                        s["opportunities"]["not_consulted"] += 1
                        if passed:
                            s["opportunities"]["not_consulted_passed"] += 1
    return s


def process_file(job):
    source, path = job
    try:
        return summarize_events(parse_session(source, Path(path)))
    except Exception:
        out = _blank_summary()
        out["unparsed"] = 1
        return out


def process_opencode(path):
    try:
        return summarize_opencode(Path(path))
    except Exception:
        out = _blank_summary()
        out["unparsed"] = 1
        return out


# ---------------------------------------------------------------- descubrimiento (el del minero)

def discover(args) -> tuple[list, list, dict]:
    jobs: list[tuple[str, str]] = []
    dbs: list[str] = []
    found: dict[str, str] = {}

    def add_files(source: str, base: Path, iterator):
        if not base.exists():
            found[source] = "no encontrado"
            return
        n = 0
        for f in iterator(base):
            jobs.append((source, str(f)))
            n += 1
        found[source] = f"{n} transcripts"

    add_files("claude", Path(args.claude), mine.iter_jsonl)
    if Path(args.codex).exists():
        n = 0
        for f in mine.iter_codex_files(Path(args.codex)):
            jobs.append(("codex_zst" if str(f).endswith(".zst") else "codex", str(f)))
            n += 1
        found["codex"] = f"{n} transcripts"
    else:
        found["codex"] = "no encontrado"
    if Path(args.gemini).exists():
        n = 0
        for f in mine.iter_gemini_files(Path(args.gemini)):
            jobs.append(("gemini", str(f)))
            n += 1
        found["gemini"] = f"{n} transcripts"
    else:
        found["gemini"] = "no encontrado"
    add_files("qwen", Path(args.qwen), lambda b: mine.iter_files(b, ".jsonl"))
    if Path(args.opencode).exists():
        dbs = [str(f) for f in mine.iter_sqlite_files(Path(args.opencode))]
        found["opencode"] = f"{len(dbs)} sqlite"
    else:
        found["opencode"] = "no encontrado"
    return jobs, dbs, found


# ---------------------------------------------------------------- salida

def build_report(summary: dict, found: dict, elapsed: float, nbytes: int) -> dict:
    by_tool = dict(sorted(summary["by_tool"].items()))
    origin = {}
    for tool in by_tool:
        origin[tool] = {
            "requested": summary["by_tool_origin"].get(f"{tool}:requested", 0),
            "spontaneous": summary["by_tool_origin"].get(f"{tool}:spontaneous", 0),
        }
    status = {}
    for tool in by_tool:
        status[tool] = {k: summary["by_tool_status"].get(f"{tool}:{k}", 0) for k in STATUS_KEYS}
    nores_rate = {}
    for tool in by_tool:
        total = by_tool[tool]
        nores_rate[tool] = round(status[tool]["no_results"] / total, 4) if total else None

    opps = summary["opportunities"]
    top = []
    for sig, rec in sorted(summary["signatures"].items(),
                           key=lambda kv: (-kv[1]["count"], kv[0]))[:25]:
        top.append({
            "signature": sig,
            "count": rec["count"],
            "sessions": rec["sessions"],
            "recipe": rec["recipe"] or None,
            "consulted": rec["consulted"],
            "with_recipe_next_run_passed": rec["passed"],
        })

    return {
        "generated_by": "scripts/usage_sessions.py",
        "privacy": ("solo agregados y firmas de error normalizadas; sin texto de "
                    "mensajes, consultas literales, rutas, ids de sesion ni proyectos"),
        "sources": found,
        "labels_loaded": len(LABELS),
        "transcripts": 0,  # lo rellena main con el numero real de ficheros/sesiones leidos
        "volume_mb": round(nbytes / 1e6, 1),
        "duration_s": round(elapsed, 2),
        "sessions_total": summary["sessions"],
        "sessions_with_zig": summary["sessions_with_zig"],
        "sessions_with_pyzig": summary["sessions_with_pyzig"],
        "pyzig_calls_total": summary["calls_total"],
        "pyzig_calls_requested": summary["calls_requested"],
        "pyzig_calls_spontaneous": summary["calls_spontaneous"],
        "pyzig_calls_by_tool": by_tool,
        "pyzig_calls_by_origin": origin,
        "pyzig_status_by_tool": status,
        "no_results_rate_by_tool": nores_rate,
        "zig_runs": summary["zig_runs"],
        "zig_runs_with_errors": summary["zig_runs_with_errors"],
        "compile_error_opportunities": {
            "with_recipe": opps.get("with_recipe", 0),
            "consulted_pyzig": opps.get("consulted", 0),
            "not_consulted_with_recipe": opps.get("not_consulted", 0),
            "not_consulted_with_recipe_and_next_run_passed": opps.get("not_consulted_passed", 0),
        },
        "top_error_signatures": top,
        "unparsed_sessions": summary["unparsed"],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--claude", default=str(Path.home() / ".claude" / "projects"))
    ap.add_argument("--codex", default=str(Path.home() / ".codex" / "sessions"))
    ap.add_argument("--opencode", default=str(Path.home() / ".local" / "share" / "opencode"))
    ap.add_argument("--gemini", default=str(Path.home() / ".gemini"))
    ap.add_argument("--qwen", default=str(Path.home() / ".qwen"))
    ap.add_argument("--corpus", default=str(mine.ROOT / "corpus" / "pyzig.corpus.jsonl"))
    ap.add_argument("--labels", default=str(mine.ROOT / "eval" / "mined_labels.tsv"))
    ap.add_argument("--out", default=str(mine.ROOT / "eval" / "usage.json"))
    ap.add_argument("--jobs", type=int, default=min(16, max(1, (os.cpu_count() or 2))))
    args = ap.parse_args(argv)

    global COVERAGE, LABELS
    COVERAGE = mine.load_corpus_apis(Path(args.corpus))
    LABELS = load_labels(Path(args.labels))

    t0 = time.time()
    jobs, dbs, found = discover(args)
    nbytes = 0
    for _src, path in jobs:
        try:
            nbytes += Path(path).stat().st_size
        except OSError:
            pass
    for db in dbs:
        try:
            nbytes += Path(db).stat().st_size
        except OSError:
            pass

    summary = _blank_summary()
    workers = max(1, args.jobs)
    if workers == 1:
        results = [process_file(j) for j in jobs] + [process_opencode(db) for db in dbs]
    else:
        import multiprocessing as mp
        ctx = mp.get_context("fork")
        with ProcessPoolExecutor(max_workers=workers, mp_context=ctx) as ex:
            futures = [ex.submit(process_file, j) for j in jobs]
            futures += [ex.submit(process_opencode, db) for db in dbs]
            results = [f.result() for f in futures]
    for r in results:
        _merge_summary(summary, r)

    report = build_report(summary, found, time.time() - t0, nbytes)
    report["transcripts"] = len(jobs)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
                   encoding="utf-8")
    print(json.dumps({
        "sessions_with_zig": report["sessions_with_zig"],
        "sessions_with_pyzig": report["sessions_with_pyzig"],
        "pyzig_calls_total": report["pyzig_calls_total"],
        "pyzig_calls_spontaneous": report["pyzig_calls_spontaneous"],
        "duration_s": report["duration_s"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
