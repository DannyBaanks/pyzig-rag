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
    "BadEncoding", "InvalidLiteral", "Overflow", "DivisionByZero", "OutOfRange",
    "ShortBuffer", "EmptyNeedle",
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
    "zig0.16/base64-encode-decode": _c(
        "base64", "drivers/base64.zig", "base64",
        ["status", "error", "out"],
        type_sig={"input": "op/bytes", "output": "bytes"},
    ),
    "zig0.16/hex-encode-decode": _c(
        "hex", "drivers/hex.zig", "hex",
        ["status", "error", "out"],
        type_sig={"input": "op/bytes", "output": "bytes"},
        known=[{
            "id": "hex-espacios-entre-pares",
            "fields": ["status", "error", "out"],
            "expect": {"status": "err", "error": "BadEncoding"},
            "oracle": {"status": "ok"},
            # solo decodificacion ('dec') con espacios ASCII entre o alrededor de
            # pares de hex; un byte no hex o un espacio dentro de un par NO encaja
            "input": {
                "op": {"regex": "dec"},
                "data": {"regex": r"(?s)(?=.*[ \t\n\r\x0b\x0c])(?:[ \t\n\r\x0b\x0c]*[0-9A-Fa-f]{2})*[ \t\n\r\x0b\x0c]*"},
            },
            "why": "bytes.fromhex ignora cualquier espacio ASCII (espacio, tab, salto) entre pares de digitos y al borde; hexToBytes lo rechaza (InvalidCharacter).",
        }],
    ),
    "zig0.16/parse-int-base-overflow": _c(
        "parseint", "drivers/parseint.zig", "parseint",
        ["status", "error", "value"],
        type_sig={"input": "texto/base", "output": "i32"},
        # el orden importa: triage toma la primera declaracion que encaja
        known=[
            {
                "id": "int-recorta-espacios-y-prefijo-de-base",
                "fields": ["status", "error", "value"],
                "expect": {"status": "err", "error": "InvalidLiteral"},
                "oracle": {"status": "ok"},
                # solo ASCII: espacios ASCII en los bordes o prefijo 0x/0o/0b que
                # coincide con la base; el valor de Python es int(texto recortado)
                "input": "parseint-recorta-ascii",
                "why": "int() recorta espacios y saltos de linea (' 7 ', '7\\n') y acepta el prefijo 0x/0o/0b que coincide con la base ('0x10' base 16, '0o17' base 8); parseInt los rechaza (InvalidCharacter)",
            },
            {
                "id": "precedencia-overflow-sobre-caracter-invalido",
                "fields": ["error"],
                "expect": {"error": "Overflow"},
                "oracle": {"error": "InvalidLiteral"},
                # el prefijo valido antes del primer caracter invalido ya desborda i32
                "input": "parseint-precedencia-overflow",
                "why": "con una cadena a la vez desbordada y con caracter invalido, parseInt informa Overflow antes de ver el caracter; int() informa ValueError. Mismo estado (err), distinto nombre de error",
            },
            {
                "id": "zig-acepta-lo-que-int-rechaza",
                "fields": ["status", "error", "value"],
                "expect": {"status": "ok"},
                "oracle": {"status": "err", "error": "InvalidLiteral"},
                # '__' entre digitos, o base 0 con cero a la izquierda; el valor Zig
                # tiene que ser el del texto sin '_' (1__0 -> 10, 010 base 0 -> 10)
                "input": "parseint-guion-bajo-valor",
                "why": "parseInt acepta guiones bajos consecutivos ('1__0', '1___0') y, con base 0, ceros a la izquierda sin prefijo ('010' -> 10, '0_1' -> 1); int() rechaza ambos. La receta dice que parseInt acepta '_' como Python: no es cierto para '__'. Hallazgo, no corregido en la receta",
            },
        ],
    ),
    "zig0.16/detached-daemon-no-shell": _c(
        None, None, None, [],
        skip_reason=("gap NOT_DEMONSTRATED: std 0.16 no expone setsid ni doble-fork, "
                     "no hay implementacion contra la que comparar"),
    ),
    # --- mate_bytes (ola 5): contratos nuevos al final del dict ---
    # Guardas del driver (no son divergencias): division por cero, minInt // -1
    # y -minInt son panic en Zig; el driver las responde antes de llamar y el
    # modelo Python responde lo mismo (DivisionByZero / Overflow).
    "zig0.16/div-floor-mod-negative": _c(
        "divmod", "drivers/divmod.zig", "divmod",
        ["status", "error", "quot", "rem"],
        type_sig={"input": "i32/i32", "output": "i32/i32"},
    ),
    "zig0.16/int-bit-count-bit-length": _c(
        "bits", "drivers/bits.zig", "bits",
        ["status", "error", "value"],
        type_sig={"input": "op/i64", "output": "u7"},
    ),
    "zig0.16/struct-pack-endian-readint": _c(
        "packint", "drivers/packint.zig", "packint",
        ["status", "error", "value", "out"],
        type_sig={"input": "op/endian/i64/offset/bytes", "output": "u32/i32/bytes"},
    ),
    # --- ola 6: 6 recetas nuevas (texto_num, colecciones, mate_bytes) ---
    "zig0.16/str-find-replace-affix": _c(
        "straffix", "drivers/straffix.zig", "straffix",
        ["status", "error", "out"],
        type_sig={"input": "op/utf8/utf8/utf8", "output": "bool/int/utf8"},
        known=[
            {
                "id": "straffix-find-bytes-vs-codepoints",
                "fields": ["out"],
                "expect": {"out": "digits"},
                "oracle": {"out": "digits"},
                "input": "straffix-find-bytes-vs-codepoints",
                "why": "std.mem.find devuelve indice en bytes UTF-8; str.find de Python devuelve indice en codepoints",
            },
            {
                "id": "straffix-replace-empty-needle",
                "fields": ["status", "error", "out"],
                "expect": {"status": "err", "error": "EmptyNeedle", "out": ""},
                "oracle": {"status": "ok", "error": ""},
                "input": "straffix-replace-empty-needle",
                "why": "replaceAll rechaza old=='' con error.EmptyNeedle (std.mem.replaceOwned asserta needle.len>0); str.replace('', new) intercala new entre cada codepoint",
            },
        ],
    ),
    "zig0.16/parse-float-format-decimals": _c(
        "parsefloat", "drivers/parsefloat.zig", "parsefloat",
        ["status", "error", "value"],
        type_sig={"input": "op/text_or_f64hex", "output": "f64hex/text"},
        known=[
            {
                "id": "parsefloat-recorta-espacios-ascii",
                "fields": ["status", "error", "value"],
                "expect": {"status": "err", "error": "InvalidLiteral", "value": ""},
                "oracle": {"status": "ok", "error": ""},
                "input": "parsefloat-recorta-ascii",
                "why": "float() recorta espacios ASCII en los bordes (' 1.5 ', '1.5\\n'); std.fmt.parseFloat los rechaza (InvalidCharacter)",
            },
            {
                "id": "parsefloat-hexfloat-zig",
                "fields": ["status", "error", "value"],
                "expect": {"status": "ok", "error": ""},
                "oracle": {"status": "err", "error": "InvalidLiteral", "value": ""},
                "input": "parsefloat-hexfloat-zig",
                "why": "std.fmt.parseFloat acepta literales hexfloat ('0x1p3', '0x1.8p+1'); float() de Python los rechaza (usa float.fromhex)",
            },
            {
                "id": "parsefloat-fmt2-shortest-decimal",
                "fields": ["value"],
                "expect": {"value": "*"},
                "oracle": {"value": "*"},
                "input": "parsefloat-fmt2-shortest-decimal",
                "why": "Zig {d:.2} redondea mitad-lejos-de-cero sobre la representacion decimal mas corta (2.675->2.68, 0.125->0.13, 1849355331531703.75->.80); Python f'{x:.2f}' redondea al par sobre el binario exacto",
            },
        ],
    ),
    "zig0.16/sorted-key-stable": _c(
        "sortkey", "drivers/sortkey.zig", "sortkey",
        ["status", "error", "out"],
        type_sig={"input": "op/rev/items", "output": "sorted_items"},
    ),
    "zig0.16/int-from-bytes-to-bytes-endian": _c(
        "intbytes", "drivers/intbytes.zig", "intbytes",
        ["status", "error", "value", "out"],
        type_sig={"input": "op/width/signed/endian/int/bytes", "output": "int/hex"},
    ),
    "zig0.16/round-floor-ceil-bankers": _c(
        "roundfloat", "drivers/roundfloat.zig", "roundfloat",
        ["status", "error", "value"],
        type_sig={"input": "op/f64hex", "output": "int_or_special"},
        known=[
            {
                "id": "roundfloat-no-finito",
                "fields": ["status", "error", "value"],
                "expect": {"status": "ok", "error": ""},
                "oracle": {"status": "err"},
                "input": "roundfloat-no-finito",
                "why": "@round/@floor/@ceil/roundHalfEven devuelven f64 y propagan inf/-inf/nan; Python round/math.floor/math.ceil devuelven int y lanzan OverflowError/ValueError",
            },
            {
                "id": "roundfloat-menos-cero",
                "fields": ["value"],
                "expect": {"value": "-0"},
                "oracle": {"value": "0"},
                "input": "roundfloat-menos-cero",
                "why": "las operaciones IEEE-754 sobre f64 preservan -0.0 (formateado '-0'); int de Python no distingue cero negativo (0)",
            },
            {
                "id": "roundfloat-zig-round-empate",
                "fields": ["value"],
                "expect": {"value": "*"},
                "oracle": {"value": "*"},
                "input": "roundfloat-zig-round-empate",
                "why": "zigRound (@round) redondea empates .5 alejando de cero (2.5->3, -2.5->-3); round() de Python redondea al par (2.5->2, -2.5->-2). roundHalfEven si coincide",
            },
        ],
    ),
    "zig0.16/utf8-codepoints-validate": _c(
        "utf8cp", "drivers/utf8cp.zig", "utf8cp",
        ["status", "error", "valid", "count", "sum"],
        type_sig={"input": "bytes", "output": "bool/usize/u64"},
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
