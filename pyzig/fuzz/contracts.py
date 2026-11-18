"""Contratos de fuzzing: liga cada receta del corpus con su esquema, driver
Zig, modelo de referencia Python, campos comparados y firma de tipo.

Este modulo es la fuente de verdad del contrato; `scripts/make_corpus.py` lo
pega dentro de cada entrada del corpus (bloque `fuzz`) y el corpus es lo que
leen tanto el oracle como el warden. Nada se duplica a mano.

Convenciones de observacion (protocolo `fuzz/src/proto.zig`):

    <status>\t<hex(packed fields)>

Los campos del packed payload van en el orden de `compared_fields` y todos
los lados (driver Zig y modelo Python) emiten exactamente los mismos nombres.
Los valores son canonicos: texto plano, enteros decimales o hex sin prefijo.

    status  ok | err | unsupported | invalid
    error   "" o nombre canonico del error (FileNotFound, StreamTooLong, ...)
"""

from __future__ import annotations

import copy

#: Nombres de error canonicos compartidos por ambos lados.
ERROR_NAMES = (
    "FileNotFound", "IsDir", "NotDir", "StreamTooLong", "PermissionDenied",
    "Timeout", "InvalidArgument", "OutOfMemory", "NoSpaceLeft", "Unknown",
)

#: Estados de observacion del protocolo.
STATUSES = ("ok", "err", "unsupported", "invalid", "crash", "timeout", "missing")


def _c(schema, driver, model, fields, *, type_sig=None, pipeline=None,
       known=(), skip_reason=None):
    """Constructor de un contrato de fuzzing."""
    return {
        "schema": schema,
        "schema_version": "v1",
        "driver": driver,
        "model": model,
        "fuzzable": skip_reason is None,
        "skip_reason": skip_reason,
        "compared_fields": list(fields),
        "known_divergences": [dict(d) for d in known],
        "type_signature": dict(type_sig or {"input": "any", "output": "any"}),
        "pipeline": dict(pipeline) if pipeline else None,
    }


#: Contrato por operation_id del corpus.
CONTRACTS: dict[str, dict] = {
    "zig0.16/subprocess-run-capture": _c(
        "argv", "drivers/argv.zig", "argv",
        ["status", "error", "term", "exit_code", "stdout_len", "stderr_len"],
        type_sig={"input": "argv", "output": "process_result"},
        known=[{
            "id": "capture-64kib",
            "fields": ["status", "error", "term", "exit_code", "stdout_len"],
            "expect": {"status": "err", "error": "StreamTooLong", "term": "spawn_error", "exit_code": "", "stdout_len": "0"},
            "oracle": {"status": "ok", "error": "", "term": "exited", "exit_code": "0", "stdout_len": "70000"},
            "why": "la receta Zig limita la captura del hijo a 64 KiB; subprocess.run captura sin limite",
        }],
    ),
    "zig0.16/read-file-text-limited": _c(
        "read", "drivers/read.zig", "read",
        ["status", "error", "size"],
        type_sig={"input": "path", "output": "bytes"},
        pipeline={"input": "path", "output": "bytes", "adapter": "step_read_path_to_bytes"},
        known=[
            {
                "id": "read-sin-limite",
                "fields": ["status", "error", "size"],
                "expect": {"status": "err", "error": "StreamTooLong"},
                "oracle": {"status": "ok", "error": ""},
                "why": "read_file_text_limit falla con StreamTooLong pasado el limite; Path.read_text no tiene limite",
            },
            {
                "id": "read-directorio-precedencia",
                "fields": ["error"],
                "expect": {"error": "StreamTooLong"},
                "oracle": {"error": "IsDir"},
                "why": "en directorios la receta Zig comprueba el limite antes de abrir; Python falla con IsADirectoryError al abrir",
            },
        ],
    ),
    "zig0.16/write-file-bytes-atomic": _c(
        "write", "drivers/write.zig", "write",
        ["status", "error", "size"],
        type_sig={"input": "bytes", "output": "bytes"},
        pipeline={"input": "bytes", "output": "bytes", "adapter": "step_write_bytes_to_bytes"},
    ),
    "zig0.16/file-exists-vs-error": _c(
        "exists", "drivers/exists.zig", "exists",
        ["status", "error", "kind"],
        type_sig={"input": "path", "output": "exists"},
    ),
    "zig0.16/stdout-print-flush": _c(
        "stdout", "drivers/stdout.zig", "stdout",
        ["status", "error", "stream", "written"],
        type_sig={"input": "bytes", "output": "void"},
    ),
    "zig0.16/parse-kv-config": _c(
        "kv", "drivers/kv.zig", "kv",
        ["status", "error", "pairs", "digest", "first_key", "first_value"],
        type_sig={"input": "kv_text", "output": "bytes"},
        pipeline={"input": "kv_text", "output": "bytes", "adapter": "step_kv_text_to_bytes"},
    ),
    "zig0.16/sleep-ms": _c(
        "sleep", "drivers/sleep.zig", "sleep",
        ["status", "error", "slept_ms"],
        type_sig={"input": "ms", "output": "void"},
    ),
    "zig0.16/string-split-strip-format": _c(
        "splitfmt", "drivers/splitfmt.zig", "splitfmt",
        ["status", "error", "tokens", "formatted"],
        type_sig={"input": "split_input", "output": "bytes"},
        pipeline={"input": "split_input", "output": "bytes", "adapter": "step_split_to_bytes"},
        known=[{
            "id": "padding-bytes-vs-codepoints",
            "fields": ["formatted"],
            "expect": {"formatted": "*"},
            "oracle": {"formatted": "*"},
            "why": "bufPrint con {s:<N} rellena bytes UTF-8; la f-string de Python rellena codepoints, asi que '\\xc3\\xb1' ocupa dos columnas menos en Zig",
        }],
    ),
    "zig0.16/spawn-redirect-child": _c(
        "spawn", "drivers/spawn.zig", "spawn",
        ["status", "error", "term", "exit_code", "log_len", "log_digest"],
        type_sig={"input": "argv", "output": "process_result"},
    ),
    "zig0.16/env-var-read": _c(
        "env", "drivers/env.zig", "env",
        ["status", "error", "value_kind", "value"],
        type_sig={"input": "env_key", "output": "bytes"},
        pipeline={"input": "env_key", "output": "bytes", "adapter": "step_env_key_to_bytes"},
    ),
    "zig0.16/sha256-bytes": _c(
        "sha256", "drivers/sha256.zig", "sha256",
        ["status", "error", "digest"],
        type_sig={"input": "bytes", "output": "digest"},
        pipeline={"input": "bytes", "output": "digest", "adapter": "step_bytes_to_digest"},
    ),
    "zig0.16/detached-daemon-no-shell": _c(
        None, None, None, [],
        skip_reason=("gap NOT_DEMONSTRATED: std 0.16 no expone setsid ni doble-fork, "
                     "no hay implementacion contra la que comparar"),
    ),
}


def contract_for(operation_id: str) -> dict:
    """Contrato de una entrada (copia profunda: el corpus no se comparte)."""
    if operation_id not in CONTRACTS:
        raise KeyError(f"sin contrato de fuzzing: {operation_id}")
    return copy.deepcopy(CONTRACTS[operation_id])


def by_schema(schema: str) -> list[tuple[str, dict]]:
    """(operation_id, contrato) de las entradas fuzzables de un esquema."""
    out = []
    for oid, c in CONTRACTS.items():
        if c["fuzzable"] and c["schema"] == schema:
            out.append((oid, copy.deepcopy(c)))
    return out


def contract_for_schema(schema: str) -> dict:
    """Contrato de un esquema (el unico caso: un esquema, una entrada).

    El esquema `pipe` esta reservado para los pipelines (F2): todavia no
    tiene receta, asi que no se puede diferencializar.
    """
    matches = by_schema(schema)
    if not matches:
        raise KeyError(f"sin contrato de fuzzing para el esquema: {schema}")
    return matches[0][1]


def fuzzable_ids() -> list[str]:
    return [oid for oid, c in CONTRACTS.items() if c["fuzzable"]]
