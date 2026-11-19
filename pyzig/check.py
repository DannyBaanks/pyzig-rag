"""Verificacion de codigo Zig 0.16 en sandbox bwrap aislado + sugerencias del corpus."""
from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess
import tempfile
from typing import Any

from . import corpus as corpus_mod
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
_RUNNER_ALL_RE = re.compile(r"^All (\d+) tests passed\.$", re.M)
_RUNNER_MIXED_RE = re.compile(r"^(\d+) passed; (\d+) skipped; (\d+) failed\.$", re.M)


def _runner_summary_ok(stderr: str) -> bool:
    """El binario de test de zig 0.16 imprime su resumen al final
    (lib/compiler/test_runner.zig). Sin resumen no hay evidencia de que los
    tests corrieran."""
    m = _RUNNER_ALL_RE.search(stderr)
    if m:
        return int(m.group(1)) >= 1
    m = _RUNNER_MIXED_RE.search(stderr)
    return bool(m) and int(m.group(1)) >= 1 and int(m.group(3)) == 0


_TEST_FAILED_RE = re.compile(
    r"(?m)(?:^\d+ passed; \d+ skipped; \d+ failed\.|^FAIL \(|error: the following test command (?:failed|terminated))"
)

_STOP_IDENTIFIERS = frozenset({
    "std", "testing", "allocator", "test", "try", "const", "var", "pub", "fn",
    "void", "error", "true", "false", "null", "self", "Self", "comptime",
    "struct", "enum", "union", "type", "anytype", "usize", "u8", "i32",
})

def _load_corpus_entries() -> list[dict]:
    """Carga las entradas del corpus (con cache simple en modulo)."""
    if not hasattr(_load_corpus_entries, "_cache"):
        _load_corpus_entries._cache = corpus_mod.load()
    return _load_corpus_entries._cache


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
                    run_stderr = run.stderr or ""
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
            suggestions = suggest_for_message(
                err["message"], notes=err["notes"], source_line=snippet,
                zig_version=zig_version)
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
        # exit 0 no basta: un test que llama a exit(0) se salta el resumen del
        # test runner sin haber comprobado nada. Exige el resumen con >=1 test
        # pasado y 0 fallidos.
        compiled = True
        tests_passed = proc.returncode == 0 and _runner_summary_ok(run_stderr)
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



# --- Emparejamiento de firmas de error (plantilla + huecos) -------------------
#
# Una firma se parte en PLANTILLA (texto con cada '...' sustituido por un hueco)
# y HUECOS (el contenido de cada '...'). Numeros y tipos enteros/float se
# normalizan en ambos (`4`->`N`, `u32`->`uN`) porque la mineria ya los reduce asi.
# `_` dentro de un hueco es el comodin de la mineria (identificador propio).
#
# Una plantilla que en el corpus solo aparece en UNA receta identifica la receta
# por si sola (los huecos son nombres del usuario: 'limite', 'cuenta'...). Si
# aparece en varias recetas, los huecos distinguen ('fs'/'cwd' vs 'time'/'sleep')
# y deben coincidir; un hueco que es solo `_` no aporta evidencia, y una firma
# sin ningun hueco con contenido literal coincidente se considera generica.

_QUOTED = re.compile(r"'([^']*)'")
#: Huecos que SON el error aunque la plantilla sea unica: "use of undeclared
#: identifier 'builtin'" es la receta de @import("builtin"); 'foo' no lo es.
_IDENTITY_SLOTS = frozenset({"builtin"})


def _norm_text(s: str) -> str:
    return re.sub(r"\d+", "N", s)  # 'u32' -> 'uN', '[4]' -> '[N]'  (como la mineria)


def _split_signature(sig: str) -> tuple[str, list[str]]:
    sig = sig.strip()
    if sig.startswith("error: "):
        sig = sig[len("error: "):]
    slots = [_norm_text(m) for m in _QUOTED.findall(sig)]
    template = _norm_text(_QUOTED.sub("'*'", sig)).lower()
    return template, slots


def signature_key(sig: str) -> str:
    """Clave canonica de una firma: plantilla + huecos normalizados."""
    t, slots = _split_signature(sig)
    return t + "|" + "|".join(slots)


def _slot_matches(msg_slot: str, corpus_slot: str) -> bool | None:
    """True/False si el hueco del mensaje coincide con el del corpus; None si el
    hueco del mensaje es comodin puro (`_`) y no aporta evidencia."""
    if msg_slot.strip("_") == "":
        return None
    if "_" not in msg_slot:
        return msg_slot == corpus_slot
    # comodin parcial de la mineria: 'array_list._(uN,null)', 'Build._._'
    parts = re.split(r"(?<![A-Za-z0-9])_(?![A-Za-z0-9])", msg_slot)
    if len(parts) == 1:
        return msg_slot == corpus_slot
    rx = r"[A-Za-z0-9_]+".join(re.escape(x) for x in parts)
    return re.fullmatch(rx, corpus_slot) is not None


def _signature_index() -> dict[str, list[tuple[int, Any, list[str]]]]:
    """plantilla -> [(posicion de la firma en su receta, entrada, huecos)]."""
    if not hasattr(_signature_index, "_cache"):
        idx: dict[str, list[tuple[int, Any, list[str]]]] = {}
        for e in _load_corpus_entries():
            for pos, sig in enumerate(e.error_signatures or []):
                t, slots = _split_signature(sig)
                idx.setdefault(t, []).append((pos, e, slots))
        _signature_index._cache = idx
    return _signature_index._cache


def match_signature(message: str) -> list[dict] | None:
    """Recetas cuya `error_signatures` coincide con el mensaje (plantilla y
    huecos). Devuelve [] si la plantilla es conocida pero el mensaje es generico
    o no coincide con ninguna, y None si la plantilla no aparece en el corpus."""
    template, slots = _split_signature(message)
    cands = _signature_index().get(template)
    if not cands:
        return None
    distinct = {e.operation_id for _, e, _ in cands}
    scored: dict[str, tuple[int, Any]] = {}
    for pos, e, cslots in cands:
        if len(cslots) != len(slots):
            continue
        if any(c in _IDENTITY_SLOTS for c in cslots) and \
                any(m != c for m, c in zip(slots, cslots) if c in _IDENTITY_SLOTS):
            continue
        if len(distinct) > 1 and cslots:
            verdicts = [_slot_matches(m, c) for m, c in zip(slots, cslots)]
            if False in verdicts or True not in verdicts:
                continue
        prev = scored.get(e.operation_id)
        if prev is None or pos < prev[0]:
            scored[e.operation_id] = (pos, e)
    hits = sorted(scored.values(), key=lambda pe: (pe[0], pe[1].operation_id))
    return [{"operation_id": e.operation_id, "name": e.name,
             "status": e.status, "apis_used": list(e.apis_used or [])}
            for _, e in hits]


def _anchored_std_api(message: str, notes: list[str] | None, source_line: str) -> bool:
    """Hay una API de la std nombrada (`std.X.y`), o un 'struct X has no member
    named Y' con nombres concretos: la busqueda tiene algo a lo que agarrarse."""
    for block in (message, source_line, *(notes or ())):
        if block and _STD_CHAIN_RE.search(block):
            return True
    m = re.search(r"struct '([^']+)' has no member named '([^']+)'", message)
    return bool(m and m.group(1).strip("_") and m.group(2).strip("_"))


def suggest_for_message(message: str, notes: list[str] | None = None,
                        source_line: str = "", zig_version: str = "0.16.0",
                        limit: int = MAX_SUGGESTIONS) -> list[dict[str, Any]] | None:
    """Camino de sugerencia de `check_zig` para un error del compilador.

    1. Firma: si el mensaje coincide con `error_signatures` (plantilla + huecos),
       esas recetas, sin pasar por la busqueda.
    2. Abstencion: sin firma y sin API de la std anclada, el error es generico
       ("expected type '_', found '_'"): no se sugiere nada.
    3. Busqueda hibrida con la consulta de `build_error_query`.
    """
    sig_hits = match_signature(message)
    if sig_hits:
        return sig_hits[:limit]
    if not _anchored_std_api(message, notes, source_line):
        return None
    m = re.search(r"struct '([^']+)' has no member named '([^']+)'", message)
    if m:
        # el texto de la plantilla no discrimina: buscar por la API que falta
        q = f"std.{m.group(1)}.{m.group(2)} {m.group(2)}"
        if source_line:
            q += " " + " ".join(extract_api_identifiers("", source_line=source_line))
    else:
        q = build_error_query(message, notes=notes, source_line=source_line)
    return suggest_for_error(q, zig_version=zig_version, limit=limit)
