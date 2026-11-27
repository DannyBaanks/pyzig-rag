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

import base64
import binascii
import hashlib
import math
import os
import re
import shutil
import struct
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


#: Error canonico de codificacion (binascii.Error / ValueError de hex): ambos
#: lados lo usan para cualquier entrada que no decodifica.
BAD_ENCODING = "BadEncoding"


def model_base64(fields: list[bytes]) -> tuple[str, list[str]]:
    """base64.b64encode / b64decode(validate=True): estricto como el Decoder Zig.

    Sin validate=True Python descartaria los caracteres fuera del alfabeto
    (saltos de linea incluidos); ese caso es una divergencia de semantica y se
    deja fuera del modelo a proposito: el contrato compara el decodificador
    estricto de ambos lados.
    """
    n = 3
    if len(fields) < 2:
        return _invalid(n)
    op = _text(fields[0])
    data = fields[1]
    if op == "enc":
        return "ok", ["ok", "", base64.b64encode(data)]
    if op == "dec":
        try:
            out = base64.b64decode(data, validate=True)
        except binascii.Error:
            return "err", ["err", BAD_ENCODING, ""]
        return "ok", ["ok", "", out]
    return _invalid(n)


def model_hex(fields: list[bytes]) -> tuple[str, list[str]]:
    """bytes.hex() / bytes.fromhex(str): ValueError -> BadEncoding."""
    n = 3
    if len(fields) < 2:
        return _invalid(n)
    op = _text(fields[0])
    data = fields[1]
    if op == "enc":
        return "ok", ["ok", "", data.hex()]
    if op == "dec":
        try:
            out = bytes.fromhex(data.decode("ascii"))
        except (UnicodeDecodeError, ValueError):
            return "err", ["err", BAD_ENCODING, ""]
        return "ok", ["ok", "", out]
    return _invalid(n)


_I32_MIN, _I32_MAX = -(2 ** 31), 2 ** 31 - 1


def model_parseint(fields: list[bytes]) -> tuple[str, list[str]]:
    """int(text, base) con el resultado restringido al tipo destino i32.

    Python no desborda; el contrato fija el tipo de Zig (i32) y reporta fuera
    de rango como Overflow. La base 0 y 2..36 son validas; otra base es invalid.
    """
    n = 3
    if len(fields) < 2:
        return _invalid(n)
    try:
        base = int(_text(fields[1]))
    except ValueError:
        return _invalid(n)
    if base != 0 and not 2 <= base <= 36:
        return _invalid(n)
    try:
        value = int(fields[0].decode("utf-8"), base)
    except (UnicodeDecodeError, ValueError):
        return "err", ["err", "InvalidLiteral", ""]
    if not _I32_MIN <= value <= _I32_MAX:
        return "err", ["err", "Overflow", ""]
    return "ok", ["ok", "", str(value)]


# --- mate_bytes -------------------------------------------------------------

#: Formato numerico estricto compartido con los drivers: `-?[0-9]+`, sin
#: '+', espacios ni separadores. Fuera de este formato el caso es invalid.
_STRICT_INT = re.compile(rb"-?[0-9]+")
_I64_MIN, _I64_MAX = -(2 ** 63), 2 ** 63 - 1
_U32_MAX = 2 ** 32 - 1


def _strict_int(raw: bytes, lo: int, hi: int) -> int | None:
    """Entero decimal estricto dentro de [lo, hi]; None si no cumple."""
    if not _STRICT_INT.fullmatch(raw):
        return None
    value = int(raw)
    return value if lo <= value <= hi else None


#: Error canonico de division por cero (ZeroDivisionError en Python).
DIVISION_BY_ZERO = "DivisionByZero"
#: Error canonico de rango fuera del tipo (struct.error "argument out of range").
OUT_OF_RANGE = "OutOfRange"
#: Error canonico de buffer demasiado corto (struct.error de unpack/pack_into).
SHORT_BUFFER = "ShortBuffer"


def model_divmod(fields: list[bytes]) -> tuple[str, list[str]]:
    """// y % de Python con negativos, enteros i32.

    Division por cero -> DivisionByZero. El cociente se restringe a i32 (el
    tipo de la receta): minInt // -1 == 2**31 no cabe y es Overflow.
    """
    n = 4
    if len(fields) < 2:
        return _invalid(n)
    a = _strict_int(fields[0], _I32_MIN, _I32_MAX)
    b = _strict_int(fields[1], _I32_MIN, _I32_MAX)
    if a is None or b is None:
        return _invalid(n)
    if b == 0:
        return "err", ["err", DIVISION_BY_ZERO, "", ""]
    quot, rem = a // b, a % b
    if not _I32_MIN <= quot <= _I32_MAX:
        return "err", ["err", "Overflow", "", ""]
    return "ok", ["ok", "", str(quot), str(rem)]


def model_bits(fields: list[bytes]) -> tuple[str, list[str]]:
    """int.bit_count() (con signo: cuenta bits de abs) e int.bit_length().

    El texto se restringe a i64 (el tipo de la receta). Fuera de i64 -> invalid.
    """
    n = 3
    if len(fields) < 2:
        return _invalid(n)
    x = _strict_int(fields[1], _I64_MIN, _I64_MAX)
    if x is None:
        return _invalid(n)
    if fields[0] == b"count":
        return "ok", ["ok", "", str(x.bit_count())]
    if fields[0] == b"length":
        return "ok", ["ok", "", str(x.bit_length())]
    return _invalid(n)


def model_packint(fields: list[bytes]) -> tuple[str, list[str]]:
    """struct.pack / struct.unpack_from / struct.pack_into con '>I', '<i', ...

    Orden de comprobacion (el de CPython: pack_into mira el tamano del buffer
    antes que el rango del valor): formato -> limites -> rango.
    """
    n = 4
    if len(fields) < 5:
        return _invalid(n)
    op, endian = fields[0], fields[1]
    if op not in (b"pack", b"read", b"readi", b"write"):
        return _invalid(n)
    if endian not in (b"big", b"little"):
        return _invalid(n)
    value = _strict_int(fields[2], _I64_MIN, _I64_MAX)
    offset = _strict_int(fields[3], 0, _I64_MAX)
    if value is None or offset is None:
        return _invalid(n)
    data = fields[4]
    prefix = ">" if endian == b"big" else "<"
    if op == b"pack":
        try:
            out = struct.pack(prefix + "I", value)
        except struct.error:
            return "err", ["err", OUT_OF_RANGE, "", ""]
        return "ok", ["ok", "", "", out.hex()]
    if op in (b"read", b"readi"):
        if offset + 4 > len(data):
            return "err", ["err", SHORT_BUFFER, "", ""]
        code = "I" if op == b"read" else "i"
        (v,) = struct.unpack_from(prefix + code, data, offset)
        return "ok", ["ok", "", str(v), ""]
    # write
    buf = bytearray(data)
    if offset + 4 > len(buf):
        return "err", ["err", SHORT_BUFFER, "", ""]
    try:
        struct.pack_into(prefix + "I", buf, offset, value)
    except struct.error:
        return "err", ["err", OUT_OF_RANGE, "", ""]
    return "ok", ["ok", "", "", bytes(buf).hex()]


# --- ola 6: straffix, parsefloat, sortkey, intbytes, roundfloat, utf8cp -----

_HEX16_LOWER = re.compile(rb"[0-9a-f]{16}")
_U32_STRICT = re.compile(rb"[0-9]+")
_I128_MIN, _I128_MAX = -(2 ** 127), 2 ** 127 - 1


def _decode_utf8_strict(raw: bytes) -> str | None:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _unpack_f64_hex(raw: bytes) -> float | None:
    if not _HEX16_LOWER.fullmatch(raw):
        return None
    return struct.unpack(">d", bytes.fromhex(raw.decode("ascii")))[0]


def _pack_fields_local(items: list[bytes]) -> bytes:
    parts = []
    for item in items:
        parts.append(struct.pack("<I", len(item)))
        parts.append(item)
    return b"".join(parts)


def model_straffix(fields: list[bytes]) -> tuple[str, list[str]]:
    """str.startswith, str.endswith, str.find, str.replace sobre UTF-8 valido."""
    n = 3
    if len(fields) < 4:
        return _invalid(n)
    op = fields[0]
    s = _decode_utf8_strict(fields[1])
    a = _decode_utf8_strict(fields[2])
    b = _decode_utf8_strict(fields[3])
    if s is None or a is None or b is None:
        return _invalid(n)
    if op == b"starts":
        return "ok", ["ok", "", "1" if s.startswith(a) else "0"]
    if op == b"ends":
        return "ok", ["ok", "", "1" if s.endswith(a) else "0"]
    if op == b"find":
        return "ok", ["ok", "", str(s.find(a))]
    if op == b"replace":
        return "ok", ["ok", "", s.replace(a, b)]
    return _invalid(n)


def model_parsefloat(fields: list[bytes]) -> tuple[str, list[str]]:
    """float(text) y f'{x:.2f}'."""
    n = 3
    if len(fields) < 2:
        return _invalid(n)
    op, text = fields[0], fields[1]
    if op == b"parse":
        try:
            x = float(text.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return "err", ["err", "InvalidLiteral", ""]
        if math.isnan(x):
            return "ok", ["ok", "", "nan"]
        return "ok", ["ok", "", struct.pack(">d", x).hex()]
    if op == b"fmt2":
        x = _unpack_f64_hex(text)
        if x is None:
            return _invalid(n)
        return "ok", ["ok", "", f"{x:.2f}"]
    return _invalid(n)


def model_sortkey(fields: list[bytes]) -> tuple[str, list[str]]:
    """sorted(people, key=lambda p: p[1], reverse=rev) estable y sorted(strings)."""
    n = 3
    if len(fields) < 2:
        return _invalid(n)
    op, rev_b = fields[0], fields[1]
    rest = fields[2:]
    if op == b"byage":
        if rev_b == b"0":
            rev = False
        elif rev_b == b"1":
            rev = True
        else:
            return _invalid(n)
        if len(rest) % 2 != 0:
            return _invalid(n)
        people: list[tuple[str, int]] = []
        for i in range(0, len(rest), 2):
            name = _decode_utf8_strict(rest[i])
            if name is None or ":" in name or "," in name:
                return _invalid(n)
            age_raw = rest[i + 1]
            if not _U32_STRICT.fullmatch(age_raw):
                return _invalid(n)
            age = int(age_raw)
            if age > _U32_MAX:
                return _invalid(n)
            people.append((name, age))
        ordered = sorted(people, key=lambda p: p[1], reverse=rev)
        out = ",".join(f"{name}:{age}" for name, age in ordered)
        return "ok", ["ok", "", out]
    if op == b"strings":
        if rev_b != b"0":
            return _invalid(n)
        decoded: list[str] = []
        for raw in rest:
            s = _decode_utf8_strict(raw)
            if s is None:
                return _invalid(n)
            decoded.append(s)
        decoded.sort()
        packed = _pack_fields_local([s.encode("utf-8") for s in decoded])
        return "ok", ["ok", "", packed.hex()]
    return _invalid(n)


def model_intbytes(fields: list[bytes]) -> tuple[str, list[str]]:
    """int.to_bytes / int.from_bytes con ancho 1/4/8, signed y endian."""
    n = 4
    if len(fields) < 6:
        return _invalid(n)
    op, width_b, signed_b, endian_b, val_b, data = fields[:6]
    if op not in (b"to", b"from"):
        return _invalid(n)
    if width_b not in (b"1", b"4", b"8"):
        return _invalid(n)
    if signed_b not in (b"0", b"1"):
        return _invalid(n)
    if endian_b not in (b"big", b"little"):
        return _invalid(n)
    width = int(width_b)
    signed = signed_b == b"1"
    byteorder = endian_b.decode("ascii")
    if op == b"to":
        value = _strict_int(val_b, _I128_MIN, _I128_MAX)
        if value is None:
            return _invalid(n)
        try:
            out = value.to_bytes(width, byteorder, signed=signed)
        except OverflowError:
            return "err", ["err", OUT_OF_RANGE, "", ""]
        return "ok", ["ok", "", "", out.hex()]
    if len(data) != width:
        return _invalid(n)
    v = int.from_bytes(data, byteorder, signed=signed)
    return "ok", ["ok", "", str(v), ""]


def model_roundfloat(fields: list[bytes]) -> tuple[str, list[str]]:
    """round(x), math.floor(x), math.ceil(x) sobre f64 IEEE-754."""
    n = 3
    if len(fields) < 2:
        return _invalid(n)
    op = fields[0]
    if op not in (b"round_even", b"floor", b"ceil", b"zig_round"):
        return _invalid(n)
    x = _unpack_f64_hex(fields[1])
    if x is None:
        return _invalid(n)
    try:
        if op in (b"round_even", b"zig_round"):
            res = round(x)
        elif op == b"floor":
            res = math.floor(x)
        else:
            res = math.ceil(x)
    except OverflowError:
        return "err", ["err", "Overflow", ""]
    except ValueError:
        return "err", ["err", "InvalidArgument", ""]
    return "ok", ["ok", "", str(res)]


def model_utf8cp(fields: list[bytes]) -> tuple[str, list[str]]:
    """bytes.decode('utf-8'), len(s), sum(ord(c) for c in s)."""
    n = 5
    if not fields:
        return _invalid(n)
    data = fields[0]
    try:
        s = data.decode("utf-8")
    except UnicodeDecodeError:
        return "err", ["err", BAD_ENCODING, "0", "", ""]
    return "ok", ["ok", "", "1", str(len(s)), str(sum(ord(c) for c in s))]


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
    "base64": model_base64,
    "hex": model_hex,
    "parseint": model_parseint,
    "divmod": model_divmod,
    "bits": model_bits,
    "packint": model_packint,
    "straffix": model_straffix,
    "parsefloat": model_parsefloat,
    "sortkey": model_sortkey,
    "intbytes": model_intbytes,
    "roundfloat": model_roundfloat,
    "utf8cp": model_utf8cp,
}
