"""Verificacion de codigo Zig 0.16 en sandbox bwrap aislado + sugerencias del corpus."""
from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess
import tempfile
from typing import Any

from . import search as search_mod
from .paths import BUILD

DEFAULT_TIMEOUT_S = 60
STDERR_TAIL_LIMIT = 4000
MAX_SUGGESTIONS = 2
ALLOWED_MODES = ("test", "ast")

#: Cache global de zig para `pyzig_check` (evita recompilar std en cada llamada).
#: En tests hermeticos se parchea a un directorio temporal.
CACHE_DIR: pathlib.Path | None = BUILD / "check-cache"

_BWRAP_PROBED = False
_BWRAP_BIN: str | None = None

_DIAG_RE = re.compile(r"^(.+?):(\d+):(\d+):\s+(error|note):\s+(.*)$")
_CARET_RE = re.compile(r"^\s*[~^]+\s*$")
_STD_CHAIN_RE = re.compile(r"\bstd(?:\.[A-Za-z_][A-Za-z0-9_]*)+\b")
_MEMBER_RE = re.compile(r"\.([A-Za-z_][A-Za-z0-9_]*)\b")
_QUOTED_ID_RE = re.compile(r"'([A-Za-z_][A-Za-z0-9_.]*)'")
_TEST_FAILED_RE = re.compile(
    r"(?m)(?:^\d+ passed; \d+ skipped; \d+ failed\.|^FAIL \(|error: the following test command (?:failed|terminated))"
)

_STOP_IDENTIFIERS = frozenset({
    "std", "testing", "allocator", "test", "try", "const", "var", "pub", "fn",
    "void", "error", "true", "false", "null", "self", "Self", "comptime",
    "struct", "enum", "union", "type", "anytype", "usize", "u8", "i32",
})


def _parse_raw_errors(stderr: str) -> list[dict[str, Any]]:
    """Parsea diagnosticos `archivo:linea:col: error|note: mensaje` conservando snippet interno."""
    errors: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    expecting_snippet = False

    for raw_line in stderr.splitlines():
        m = _DIAG_RE.match(raw_line)
        if m:
            _file, line_s, col_s, kind, msg = m.groups()
            msg = msg.strip()
            if kind == "error":
                current = {
                    "line": int(line_s),
                    "col": int(col_s),
                    "message": msg,
                    "notes": [],
                    "_snippet": "",
                }
                errors.append(current)
                expecting_snippet = True
            elif kind == "note":
                expecting_snippet = False
                if current is not None:
                    current["notes"].append(msg)
            continue

        if expecting_snippet and current is not None:
            stripped = raw_line.strip()
            if stripped and not _CARET_RE.match(raw_line):
                current["_snippet"] = stripped
                expecting_snippet = False
            elif _CARET_RE.match(raw_line):
                expecting_snippet = False

    return errors


def parse_zig_errors(stderr: str) -> list[dict[str, Any]]:
    """Devuelve lista de errores `{line, col, message, notes}` parseados de stderr de zig."""
    return [
        {
            "line": e["line"],
            "col": e["col"],
            "message": e["message"],
            "notes": list(e["notes"]),
        }
        for e in _parse_raw_errors(stderr)
    ]


def extract_api_identifiers(message: str, notes: list[str] | None = None,
                            source_line: str = "") -> list[str]:
    """Extrae identificadores de API (p.ej. `std.fs.cwd`, `readFileAlloc`, `writer`)."""
    found: list[str] = []
    seen: set[str] = set()

    def _add(tok: str) -> None:
        tok = tok.strip(".")
        if len(tok) < 2 or tok in _STOP_IDENTIFIERS or tok in seen:
            return
        seen.add(tok)
        found.append(tok)

    text_blocks = [source_line, message, *(notes or ())]
    for block in text_blocks:
        if not block:
            continue
        for m in _STD_CHAIN_RE.findall(block):
            _add(m)

    if source_line:
        for m in _MEMBER_RE.findall(source_line):
            _add(m)

    for block in (message, *(notes or ())):
        if not block:
            continue
        for m in _QUOTED_ID_RE.findall(block):
            _add(m)

    return found


def build_error_query(message: str, notes: list[str] | None = None,
                      source_line: str = "") -> str:
    """Construye una consulta para `pyzig.search.search` a partir de un error de compilacion."""
    parts = [message.strip()] if message.strip() else []
    msg_lower = message.lower()
    for ident in extract_api_identifiers(message, notes=notes, source_line=source_line):
        if ident.lower() not in msg_lower:
            parts.append(ident)
    return " ".join(parts)[:500]


def suggest_for_error(query: str, zig_version: str = "0.16.0",
                      limit: int = MAX_SUGGESTIONS) -> list[dict[str, Any]] | None:
    """Consulta el indice local y devuelve hasta `limit` recetas sugeridas, o None si NO_RESULTS."""
    if not query.strip():
        return None
    try:
        hits = search_mod.search(query, zig_version=zig_version or None, limit=limit)
    except (search_mod.NoResults, search_mod.VersionMismatch, search_mod.IndexUnavailable):
        return None
    if not hits:
        return None
    return [
        {
            "operation_id": h["operation_id"],
            "name": h["name"],
            "status": h["status"],
            "apis_used": h["apis_used"],
        }
        for h in hits[:limit]
    ]


def _base_bwrap_binds() -> list[str]:
    args = ["--ro-bind", "/usr", "/usr"]
    for lib_dir in ("/lib", "/lib64"):
        if os.path.exists(lib_dir):
            args.extend(["--ro-bind", lib_dir, lib_dir])
    return args


def probe_bwrap() -> str | None:
    """Comprueba una vez si `bwrap` existe y puede ejecutar `/usr/bin/true`; cachea el resultado."""
    global _BWRAP_PROBED, _BWRAP_BIN
    if _BWRAP_PROBED:
        return _BWRAP_BIN
    _BWRAP_PROBED = True
    bwrap_bin = shutil.which("bwrap")
    if not bwrap_bin:
        _BWRAP_BIN = None
        return None
    cmd = [
        bwrap_bin,
        "--unshare-all",
        "--die-with-parent",
        "--new-session",
        "--clearenv",
        *_base_bwrap_binds(),
        "--proc", "/proc",
        "--dev", "/dev",
        "--tmpfs", "/tmp",
        "--setenv", "PATH", "/usr/bin:/bin",
        "--",
        "/usr/bin/true",
    ]
    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=5,
        )
        _BWRAP_BIN = bwrap_bin if p.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        _BWRAP_BIN = None
    return _BWRAP_BIN


def _resolve_global_cache(tmp_path: pathlib.Path,
                          cache_dir: pathlib.Path | None) -> pathlib.Path:
    target = cache_dir if cache_dir is not None else CACHE_DIR
    if target is not None:
        try:
            target.mkdir(parents=True, exist_ok=True)
            return target
        except OSError:
            pass
    fallback = tmp_path / "global-cache"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def check_zig(zig_code: str, mode: str = "test",
              timeout_s: int = DEFAULT_TIMEOUT_S,
              zig_version: str = "0.16.0",
              cache_dir: pathlib.Path | None = None,
              suggest: bool = True) -> dict[str, Any]:
    """Ejecuta `zig ast-check` o `zig test` sobre `zig_code` dentro de `bwrap` sin red.

    Fail-closed: si `bwrap` no esta disponible o no es usable, devuelve
    `SANDBOX_UNAVAILABLE` y no ejecuta nada. No usa shell. Limpia el dir temporal.
    """
    if mode not in ALLOWED_MODES:
        return {
            "ok": False,
            "error": "INVALID_MODE",
            "message": f"mode invalido: {mode!r} (usa 'test' o 'ast')",
            "sandbox": None,
            "compiled": False,
            "tests_passed": None,
            "errors": [],
            "stderr_tail": "",
        }

    bwrap_bin = probe_bwrap()
    if not bwrap_bin:
        return {
            "ok": False,
            "error": "SANDBOX_UNAVAILABLE",
            "message": "sandbox bwrap no disponible o no usable; ejecucion denegada (fail-closed)",
            "sandbox": None,
            "compiled": False,
            "tests_passed": None,
            "errors": [],
            "stderr_tail": "",
        }

    zig_which = shutil.which("zig")
    if not zig_which:
        return {
            "ok": False,
            "error": "ZIG_NOT_FOUND",
            "message": "binario 'zig' no encontrado en PATH",
            "sandbox": "bwrap",
            "compiled": False,
            "tests_passed": None,
            "errors": [],
            "stderr_tail": "",
        }

    zig_real = pathlib.Path(os.path.realpath(zig_which))
    zig_dir = zig_real.parent
    zig_dir_str = str(zig_dir)
    if zig_dir_str == "/usr" or zig_dir_str.startswith("/usr/"):
        zig_in_sandbox = str(zig_real)
        zig_ro_bind: list[str] = []
        sandbox_path = "/usr/bin:/bin"
    else:
        zig_in_sandbox = f"/zig/{zig_real.name}"
        zig_ro_bind = ["--ro-bind", zig_dir_str, "/zig"]
        sandbox_path = "/usr/bin:/bin:/zig"

    source_lines = zig_code.splitlines()

    with tempfile.TemporaryDirectory(prefix="pyzig-check-") as tmp_dir:
        tmp_path = pathlib.Path(tmp_dir)
        src_file = tmp_path / "check.zig"
        src_file.write_text(zig_code, encoding="utf-8")

        def sandboxed(argv: list[str], with_cache: bool) -> subprocess.CompletedProcess:
            # Fase de compilacion: cache global RW (solo corre el compilador; el codigo del
            # check no se ejecuta). Fase de ejecucion: SIN cache montada, para que el binario
            # de test (codigo no confiable) no pueda envenenar artefactos de checks posteriores.
            cache_bind: list[str] = []
            cache_env = "/work/global-cache"
            if with_cache:
                cache_bind = ["--bind", str(_resolve_global_cache(tmp_path, cache_dir)), "/cache"]
                cache_env = "/cache"
            cmd = [
                bwrap_bin,
                "--unshare-all",
                "--die-with-parent",
                "--new-session",
                "--clearenv",
                *_base_bwrap_binds(),
                "--proc", "/proc",
                "--dev", "/dev",
                "--tmpfs", "/tmp",
                *zig_ro_bind,
                "--bind", tmp_dir, "/work",
                *cache_bind,
                "--chdir", "/work",
                "--setenv", "HOME", "/work",
                "--setenv", "TMPDIR", "/tmp",
                "--setenv", "PATH", sandbox_path,
                "--setenv", "ZIG_GLOBAL_CACHE_DIR", cache_env,
                "--setenv", "ZIG_LOCAL_CACHE_DIR", "/work/local-cache",
                "--",
                *argv,
            ]
            return subprocess.run(cmd, cwd=tmp_dir, capture_output=True, text=True,
                                  stdin=subprocess.DEVNULL, timeout=timeout_s)

        compiled_phase: bool | None = None
        try:
            if mode == "ast":
                proc = sandboxed([zig_in_sandbox, "ast-check", "--color", "off", src_file.name],
                                 with_cache=False)
            else:
                proc = sandboxed([
                    zig_in_sandbox, "test", "--color", "off", "--test-no-exec",
                    "-femit-bin=/work/check-test",
                    "--cache-dir", "/work/local-cache",
                    "--global-cache-dir", "/cache",
                    src_file.name,
                ], with_cache=True)
                compiled_phase = proc.returncode == 0
                if compiled_phase:
                    run = sandboxed(["/work/check-test"], with_cache=False)
                    proc = subprocess.CompletedProcess(
                        run.args, run.returncode, run.stdout,
                        (proc.stderr or "") + (run.stderr or ""))
        except subprocess.TimeoutExpired as exc:
            raw_err = exc.stderr or ""
            if isinstance(raw_err, bytes):
                raw_err = raw_err.decode("utf-8", errors="replace")
            return {
                "ok": False,
                "error": "TIMEOUT",
                "message": f"zig {mode} excedio timeout de {timeout_s}s",
                "sandbox": "bwrap",
                "compiled": False,
                "tests_passed": None,
                "errors": [],
                "stderr_tail": raw_err[-STDERR_TAIL_LIMIT:],
            }

    stderr = proc.stderr or ""
    stderr_tail = stderr[-STDERR_TAIL_LIMIT:]
    raw_errors = _parse_raw_errors(stderr)

    errors: list[dict[str, Any]] = []
    for err in raw_errors:
        snippet = err["_snippet"]
        if not snippet and 1 <= err["line"] <= len(source_lines):
            snippet = source_lines[err["line"] - 1].strip()
        suggestions = None
        if suggest:
            q = build_error_query(err["message"], notes=err["notes"], source_line=snippet)
            suggestions = suggest_for_error(q, zig_version=zig_version)
        errors.append({
            "line": err["line"],
            "col": err["col"],
            "message": err["message"],
            "notes": err["notes"],
            "suggestions": suggestions,
        })

    if mode == "ast":
        compiled = proc.returncode == 0
        tests_passed = None
        ok = compiled
    elif compiled_phase:
        # compilo en la fase 1; el resultado del binario decide (incluye muerte por senal)
        compiled = True
        tests_passed = proc.returncode == 0
        ok = tests_passed
    else:
        if proc.returncode == 0:
            compiled = True
            tests_passed = True
            ok = True
        elif errors:
            compiled = False
            tests_passed = None
            ok = False
        elif _TEST_FAILED_RE.search(stderr):
            compiled = True
            tests_passed = False
            ok = False
        else:
            compiled = False
            tests_passed = None
            ok = False

    return {
        "ok": ok,
        "sandbox": "bwrap",
        "compiled": compiled,
        "tests_passed": tests_passed,
        "errors": errors,
        "stderr_tail": stderr_tail,
    }
