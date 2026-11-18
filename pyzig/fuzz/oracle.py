#!/usr/bin/env python3
"""Oracle de pyzig-fuzz: lado Python del fuzzer diferencial.

Un proceso por CHUNK (no por caso): lee un fichero de casos (un caso por
linea, en hex), ejecuta el modelo de referencia Python de cada caso y escribe
un fichero de observaciones (una por linea):

    <status>\t<hex(campos empaquetados)>

Los campos van en el orden que fija el contrato del corpus
(`fuzz.compared_fields`): el mismo orden que usa el driver Zig, para que la
comparacion sea por nombre de campo y no por blob.

Uso (lo invoca el motor Zig):

    python3 -m pyzig.fuzz.oracle --schema read --cases cases.hexl --obs oracle.zigl
"""

from __future__ import annotations

import argparse
import sys

from . import contracts
from .models import MODELS


def decode_fields(data: bytes) -> list[bytes]:
    """Decodifica campos empaquetados: [u32 len][bytes]..."""
    fields: list[bytes] = []
    pos = 0
    while pos + 4 <= len(data):
        length = int.from_bytes(data[pos:pos + 4], "little")
        pos += 4
        if pos + length > len(data):
            break
        fields.append(data[pos:pos + length])
        pos += length
    return fields


def pack_fields(fields: list[bytes]) -> bytes:
    """Empaqueta campos: [u32 len][bytes]..."""
    out = bytearray()
    for f in fields:
        out += len(f).to_bytes(4, "little")
        out += f
    return bytes(out)


def read_cases(path: str) -> list[bytes]:
    cases: list[bytes] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            t = line.strip()
            if not t:
                continue
            cases.append(bytes.fromhex(t))
    return cases


def observe(schema: str, payload: bytes) -> tuple[str, bytes]:
    """Ejecuta el modelo del esquema sobre un caso y devuelve (status, payload)."""
    contract = contracts.contract_for_schema(schema)
    model_name = contract["model"]
    fn = MODELS.get(model_name)
    if fn is None:
        return "unsupported", pack_fields([b"unsupported", b"modelo desconocido"] + [b""] * 8)
    fields = decode_fields(payload)
    status, values = fn(fields)
    expected = len(contract["compared_fields"])
    if len(values) != expected:
        # el modelo no cumple el contrato: se marca como no soportado, no se
        # inventa una respuesta parcheada.
        values = (values + [""] * expected)[:expected]
    # values puede ser list[str] o list[bytes] (kv usa bytes para mantener
    # paridad con el driver Zig). Normalizamos a bytes.
    encoded = []
    for v in values:
        if isinstance(v, bytes):
            encoded.append(v)
        else:
            encoded.append(v.encode("utf-8", errors="surrogateescape"))
    return status, pack_fields(encoded)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pyzig.fuzz.oracle")
    ap.add_argument("--schema", required=True)
    ap.add_argument("--cases", required=True)
    ap.add_argument("--obs", required=True)
    args = ap.parse_args(argv)

    try:
        contracts.contract_for_schema(args.schema)
    except KeyError as exc:
        print(f"oracle: {exc}", file=sys.stderr)
        return 2

    out: list[str] = []
    for payload in read_cases(args.cases):
        status, obs = observe(args.schema, payload)
        out.append(f"{status}\t{obs.hex()}")

    with open(args.obs, "w", encoding="utf-8") as f:
        for line in out:
            f.write(line + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
