"""Modelos de referencia Python para el fuzzer diferencial.

Cada modelo implementa la semántica *Python* de una receta del corpus y
devuelve la misma lista de campos que el driver Zig (el orden lo fija el
contrato `fuzz.compared_fields`). Cuando Python y Zig divergen de verdad, el
modelo NO maquilla la diferencia: la reporta. Las divergencias que ya se
conocen viven en el contrato (`known_divergences`).

Reglas comunes:
- un caso malformado se responde `invalid` (status) con los campos vacios;
- los nombres de error son canonicos (los mismos en ambos lados);
- el estado del sistema se limpia antes de cada caso (los dos lados ven el
  mismo entorno).
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import time
from typing import Callable

#: Nombre canonico de error para "el caso no es valido".
INVALID = "invalid"
#: Error canonico de un caso invalido.
INVALID_ERROR = "InvalidArgument"

#: Limite de captura de la receta Zig (64 KiB por stream).
CAPTURE_LIMIT = 64 * 1024
#: Timeout de los subprocesos del modelo (s).
SUBPROCESS_TIMEOUT = 5.0


def _invalid(n_fields: int) -> tuple[str, list[str]]:
    values = ["invalid", INVALID_ERROR] + [""] * (n_fields - 2)
    return INVALID, values


def _valid_path(path: str) -> bool:
    if not path or len(path) > 255:
        return False
    if "\x00" in path:
        return False
    if path.startswith("/"):
        return False
    if ".." in path:
        return False
    return True


def _valid_program(prog: str) -> bool:
    if not prog or len(prog) > 64:
        return False
    if "\x00" in prog or "/" in prog:
        return False
    return True


def _clean(path: str) -> None:
    """Deja el path como no existe (los dos lados empiezan igual)."""
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path, ignore_errors=True)
    elif os.path.exists(path) or os.path.islink(path):
        try:
            os.unlink(path)
        except OSError:
            pass


def _text(raw: bytes) -> str:
    return raw.decode("utf-8", errors="replace")


# --------------------------------------------------------------------------
# Modelos
# --------------------------------------------------------------------------

def model_argv(fields: list[bytes]) -> tuple[str, list[str]]:
    """subprocess.run: captura stdout/stderr, codigo de salida y senales."""
    n = 6
    if not fields:
        return _invalid(n)
    args = [_text(f) for f in fields]
    if not _valid_program(args[0]):
        return _invalid(n)
    # un argumento con NUL no es ejecutable (ValueError en subprocess)
    if any("\x00" in a for a in args):
        return _invalid(n)
    try:
        r = subprocess.run(args, capture_output=True, timeout=SUBPROCESS_TIMEOUT,
                           stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        return "err", ["err", "FileNotFound", "spawn_error", "", "0", "0"]
    except PermissionError:
        return "err", ["err", "PermissionDenied", "spawn_error", "", "0", "0"]
    except subprocess.TimeoutExpired:
        return "err", ["err", "Timeout", "timeout", "", "0", "0"]
    except OSError:
        return "err", ["err", "Unknown", "spawn_error", "", "0", "0"]
    term, code = "exited", str(r.returncode)
    if r.returncode < 0:
        term, code = "signal", str(-r.returncode)
    return "ok", ["ok", "", term, code, str(len(r.stdout)), str(len(r.stderr))]


def model_kv(fields: list[bytes]) -> tuple[str, list[str]]:
    """Parser plano KEY=VALOR: comentarios, comillas y espacios.

    Operamos sobre bytes Puros para mantener la paridad con el driver Zig:
    ambos devuelven lo que hay en los campos tal cual, sin decodificacion
    (y por tanto sin sustitucion por U+FFLD cuando hay UTF-8 invalido).
    """
    n = 6
    if not fields:
        return _invalid(n)
    pairs: list[tuple[bytes, bytes]] = []
    canonical_parts = []
    text = fields[0]
    for line in text.split(b"\n"):
        t = line.strip(b" \t")
        if not t or t.startswith(b"#"):
            continue
        if b"=" not in t:
            continue
        key, _, value = t.partition(b"=")
        key = key.strip(b" \t")
        value = value.strip(b" \t")
        if len(value) >= 2 and value[0:1] == b"'" and value[-1:] == b"'":
            value = value[1:-1]
        pairs.append((key, value))
        canonical_parts.append(key + b"=" + value + b"\n")
    canonical = b"".join(canonical_parts)
    digest = hashlib.sha256(canonical).hexdigest()
    fk = pairs[0][0] if pairs else b""
    fv = pairs[0][1] if pairs else b""
    # Para mantener paridad byte-a-byte con el driver Zig (que devuelve
    # bytes crudos), emitimos first_key/first_value como hex: asi ambos
    # lados ven la misma representacion y el arnes puede comparar sin
    # preocuparse por UTF-8 invalido.
    return "ok", ["ok", "", str(len(pairs)), digest, fk.hex().encode("ascii"), fv.hex().encode("ascii")]


def model_read(fields: list[bytes]) -> tuple[str, list[str]]:
    """Path.read_text(): sin limite de tamano (la receta Zig si lo tiene)."""
    n = 3
    if len(fields) < 4:
        return _invalid(n)
    path = _text(fields[0])
    present = _text(fields[1])
    content = fields[2]
    limit_raw = _text(fields[3])
    if not _valid_path(path):
        return _invalid(n)
    try:
        limit = int(limit_raw)
    except ValueError:
        return _invalid(n)
    if limit < 0:
        return _invalid(n)

    _clean(path)
    if present == "1":
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "wb") as f:
            f.write(content)
    elif present == "2":
        os.makedirs(path, exist_ok=True)

    try:
        with open(path, "rb") as f:
            data = f.read()
    except FileNotFoundError:
        return "err", ["err", "FileNotFound", "0"]
    except IsADirectoryError:
        return "err", ["err", "IsDir", "0"]
    except PermissionError:
        return "err", ["err", "PermissionDenied", "0"]
    except OSError:
        return "err", ["err", "Unknown", "0"]
    return "ok", ["ok", "", str(len(data))]


def model_write(fields: list[bytes]) -> tuple[str, list[str]]:
    """write_bytes / append: el archivo acaba con pre+data o solo data."""
    n = 3
    if len(fields) < 3:
        return _invalid(n)
    mode = _text(fields[0])
    pre = fields[1]
    data = fields[2]
    if mode not in ("truncate", "append"):
        return _invalid(n)
    target = "out.bin"
    _clean(target)
    try:
        with open(target, "wb") as f:
            f.write(pre)
        if mode == "truncate":
            with open(target, "wb") as f:
                f.write(data)
        else:
            with open(target, "ab") as f:
                f.write(data)
        size = os.path.getsize(target)
    except OSError:
        return "err", ["err", "Unknown", "0"]
    return "ok", ["ok", "", str(size)]


def model_exists(fields: list[bytes]) -> tuple[str, list[str]]:
    """Path.exists(): True tambien para directorios; oculta AccessDenied."""
    n = 3
    if len(fields) < 2:
        return _invalid(n)
    kind = _text(fields[0])
    path = _text(fields[1])
    if kind not in ("file", "missing", "dir"):
        return _invalid(n)
    if not _valid_path(path):
        return _invalid(n)

    _clean(path)
    try:
        if kind == "file":
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(path, "wb"):
                pass
        elif kind == "dir":
            os.makedirs(path, exist_ok=True)
    except OSError:
        return "err", ["err", "Unknown", ""]

    exists = os.path.exists(path)
    return "ok", ["ok", "", "yes" if exists else "missing"]


def model_splitfmt(fields: list[bytes]) -> tuple[str, list[str]]:
    """split + strip + f-string con relleno."""
    n = 4
    if len(fields) < 5:
        return _invalid(n)
    sep = _text(fields[0])
    text = _text(fields[1])
    mac = _text(fields[2])
    ip = _text(fields[3])
    width_raw = _text(fields[4])
    if len(sep.encode("utf-8", errors="replace")) != 1:
        return _invalid(n)
    try:
        width = int(width_raw)
    except ValueError:
        return _invalid(n)
    if width < 0:
        return _invalid(n)
    try:
        tokens = [t.strip() for t in text.split(sep) if t.strip()]
    except ValueError:
        # separador vacio: ValueError en Python (el caso no es valido)
        return _invalid(n)
    formatted = f"{mac:<{width}}|{ip}"
    return "ok", ["ok", "", str(len(tokens)), formatted]


def model_sleep(fields: list[bytes]) -> tuple[str, list[str]]:
    """time.sleep(): milisegundos enteros."""
    n = 3
    if not fields:
        return _invalid(n)
    try:
        ms = int(_text(fields[0]))
    except ValueError:
        return _invalid(n)
    if ms < 0:
        return _invalid(n)
    time.sleep(ms / 1000.0)
    return "ok", ["ok", "", str(ms)]


def model_env(fields: list[bytes]) -> tuple[str, list[str]]:
    """os.environ.get(): None si no existe."""
    n = 4
    if not fields:
        return _invalid(n)
    key = _text(fields[0])
    if not key or "=" in key or "\x00" in key:
        return _invalid(n)
    value = os.environ.get(key)
    if value is None:
        return "ok", ["ok", "", "absent", ""]
    return "ok", ["ok", "", "present", value]


def model_spawn(fields: list[bytes]) -> tuple[str, list[str]]:
    """Popen con stdout/stderr al log en modo append."""
    n = 6
    if len(fields) < 2:
        return _invalid(n)
    pre = fields[0]
    args = [_text(f) for f in fields[1:]]
    if not _valid_program(args[0]):
        return _invalid(n)
    if any("\x00" in a for a in args):
        return _invalid(n)
    log = "child.log"
    _clean(log)
    try:
        with open(log, "wb") as f:
            f.write(pre)
        with open(log, "ab") as f:
            r = subprocess.run(args, stdout=f, stderr=f, stdin=subprocess.DEVNULL,
                               timeout=SUBPROCESS_TIMEOUT)
    except FileNotFoundError:
        return "err", ["err", "FileNotFound", "spawn_error", "", "0", ""]
    except PermissionError:
        return "err", ["err", "PermissionDenied", "spawn_error", "", "0", ""]
    except subprocess.TimeoutExpired:
        return "err", ["err", "Timeout", "timeout", "", "0", ""]
    except OSError:
        return "err", ["err", "Unknown", "spawn_error", "", "0", ""]
    term, code = "exited", str(r.returncode)
    if r.returncode < 0:
        term, code = "signal", str(-r.returncode)
    try:
        with open(log, "rb") as f:
            log_bytes = f.read()
    except OSError:
        return "err", ["err", "Unknown", "", "", "0", ""]
    digest = hashlib.sha256(log_bytes).hexdigest()
    return "ok", ["ok", "", term, code, str(len(log_bytes)), digest]


def model_stdout(fields: list[bytes]) -> tuple[str, list[str]]:
    """print(..., flush=True) a stdout o stderr."""
    n = 4
    if len(fields) < 2:
        return _invalid(n)
    stream = _text(fields[0])
    msg = fields[1]
    if stream not in ("out", "err"):
        return _invalid(n)
    try:
        target = sys.stdout.buffer if stream == "out" else sys.stderr.buffer
        target.write(msg)
        target.flush()
    except OSError:
        return "err", ["err", "Unknown", stream, "0"]
    return "ok", ["ok", "", stream, str(len(msg))]


def model_sha256(fields: list[bytes]) -> tuple[str, list[str]]:
    """hashlib.sha256(data).hexdigest()"""
    n = 3
    if not fields:
        return _invalid(n)
    return "ok", ["ok", "", hashlib.sha256(fields[0]).hexdigest()]


#: nombre de modelo -> funcion
MODELS: dict[str, Callable[[list[bytes]], tuple[str, list[str]]]] = {
    "argv": model_argv,
    "kv": model_kv,
    "read": model_read,
    "write": model_write,
    "exists": model_exists,
    "splitfmt": model_splitfmt,
    "sleep": model_sleep,
    "env": model_env,
    "spawn": model_spawn,
    "stdout": model_stdout,
    "sha256": model_sha256,
}
