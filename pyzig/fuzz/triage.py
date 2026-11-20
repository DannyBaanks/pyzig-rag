"""Triage de divergencias: separa las divergencias conocidas de las nuevas.

Una divergencia *conocida* esta declarada en el contrato del corpus
(`fuzz.known_divergences`): dice que campos pueden diferir, con que valores y,
opcionalmente, sobre que ENTRADA del caso aplica. Todo lo que no encaje en
ninguna declaracion es una divergencia NUEVA, y por eso es un hallazgo: o el
corpus miente sobre la semantica, o la receta tiene un bug.

Formato de una declaracion:

    {
      "id": "limite-captura",
      "fields": ["status", "error", "stdout_len"],   # campos que pueden diferir
      "expect": {"status": "err", "error": "StreamTooLong"},   # lado Zig
      "oracle": {"status": "ok", "error": ""},                  # lado Python
      "input": {"text": {"regex": "[0-9]+"}},          # OPCIONAL: sobre la entrada
      "why": "la receta Zig limita la captura a 64 KiB; subprocess.run no limita"
    }

Los valores de `expect`/`oracle` admiten patrones: exacto, "*" (cualquiera) y
"digits" (entero decimal).

`input` acota la declaracion por la ENTRADA decodificada del caso (el campo
`case` de results.jsonl). Dos formas, combinables con el resto de la
declaracion:

- `{"<campo>": {"regex": "..."}}`: el valor de ese campo de entrada (nombres en
  `INPUT_FIELDS`, p. ej. `text`/`base`/`data`) debe cumplir la expresion
  completa (`re.fullmatch`).
- `"<nombre>"`: un predicado registrado en `PREDICATES` que recibe el contexto
  completo del caso (entrada, valor Zig y valor Python) y devuelve bool.

Sin `input` la declaracion se comporta como antes (solo campos del resultado).
Si `input` esta declarado pero el caso no puede decodificarse, la declaracion
NO encaja: el caso queda como NUEVO (fallo cerrado).
"""

from __future__ import annotations

import re
from typing import Callable

from pyzig.fuzz.oracle import decode_fields

_DIGITS = re.compile(r"^[0-9]+$")

#: Espacios que Python acepta en int() y bytes.fromhex() (solo ASCII).
ASCII_WS = " \t\n\r\x0b\x0c"

I32_MIN, I32_MAX = -(2 ** 31), 2 ** 31 - 1

#: Nombres de los campos de ENTRADA de cada esquema, en orden de `case`
#: (ver la cabecera de fuzz/src/gen.zig). Solo los esquemas con predicados.
INPUT_FIELDS: dict[str, tuple[str, ...]] = {
    "parseint": ("text", "base"),
    "hex": ("op", "data"),
    "base64": ("op", "data"),
}


def match_value(pattern: str, value: str) -> bool:
    """Compara un valor observado contra el patron declarado."""
    if pattern == "*":
        return True
    if pattern == "digits":
        return bool(_DIGITS.match(value))
    return pattern == value


# --------------------------------------------------------------------------
# Contexto del caso
# --------------------------------------------------------------------------

def _named(payload_hex: str, names: list[str]) -> dict[str, str] | None:
    """Campos empaquetados de una observacion -> {nombre: valor}."""
    try:
        values = decode_fields(bytes.fromhex(payload_hex))
    except (TypeError, ValueError):
        return None
    if len(values) < len(names):
        return None
    return {n: v.decode("utf-8", errors="surrogateescape")
            for n, v in zip(names, values)}


def case_context(row: dict, schema: str, compared_fields: list[str]) -> dict:
    """Contexto de una fila de results.jsonl: entrada, valor Zig y valor Python.

    Cada seccion queda vacia ({}) si no puede decodificarse; un predicado que la
    necesita no encaja.
    """
    ctx: dict[str, dict[str, str]] = {"input": {}, "subject": {}, "oracle": {}}
    names = INPUT_FIELDS.get(schema)
    if names and row.get("case"):
        parsed = _named(row["case"], list(names))
        if parsed is not None:
            ctx["input"] = parsed
    for side in ("subject", "oracle"):
        payload = (row.get(side) or {}).get("payload")
        if payload and compared_fields:
            parsed = _named(payload, list(compared_fields))
            if parsed is not None:
                ctx[side] = parsed
    return ctx


# --------------------------------------------------------------------------
# Predicados sobre la entrada (registrados por nombre)
# --------------------------------------------------------------------------

_PREFIX_BASE = {"0x": 16, "0o": 8, "0b": 2}


def _sign_split(s: str) -> tuple[str, str]:
    return (s[:1], s[1:]) if s[:1] in ("+", "-") else ("", s)


def _prefix_base(body: str) -> int | None:
    """Base que implica un prefijo 0x/0o/0b al inicio (sin signo)."""
    return _PREFIX_BASE.get(body[:2].lower())


def _base(ctx: dict) -> int | None:
    """Base de la entrada si es valida para int() (0 o 2..36)."""
    try:
        b = int(ctx["input"]["base"])
    except (KeyError, TypeError, ValueError):
        return None
    return b if b == 0 or 2 <= b <= 36 else None


def _text(ctx: dict) -> str | None:
    t = ctx["input"].get("text")
    return t if t is not None and t.isascii() else None


def _oracle_is(ctx: dict, status: str, **fields: str) -> bool:
    o = ctx["oracle"]
    return o.get("status") == status and all(o.get(k) == v for k, v in fields.items())


def _subject_is(ctx: dict, status: str, **fields: str) -> bool:
    s = ctx["subject"]
    return s.get("status") == status and all(s.get(k) == v for k, v in fields.items())


def pred_parseint_recorta_ascii(ctx: dict) -> bool:
    """int() recorta espacios ASCII en los bordes o acepta el prefijo de la base.

    Solo ASCII: un digito Unicode ('٣') o un espacio Unicode no encaja aqui
    aunque el resto del patron sea el mismo. El valor de Python tiene que ser
    exactamente int(texto_recortado, base).
    """
    base, text = _base(ctx), _text(ctx)
    if base is None or text is None:
        return False
    core = text.strip(ASCII_WS)
    sign, body = _sign_split(core)
    if not core or not body:
        return False
    edges = core != text
    pb = _prefix_base(body)
    prefix_ok = pb is not None and base in (0, pb)
    if not (edges or prefix_ok):
        return False
    try:
        expected = int(core, base)
    except ValueError:
        return False
    return _oracle_is(ctx, "ok", value=str(expected))


def pred_parseint_precedencia_overflow(ctx: dict) -> bool:
    """Zig informa Overflow porque el prefijo valido ya desborda i32 antes del
    primer caracter invalido; Python ve el caracter invalido (InvalidLiteral).

    Zig solo consume el prefijo 0x/0o/0b con base 0 (igual que el driver).
    """
    base, text = _base(ctx), ctx["input"].get("text")
    if base is None or text is None or not text.isascii():
        return False
    sign, rest = _sign_split(text)
    eff = base
    if base == 0:
        pb = _prefix_base(rest)
        if pb is not None:
            rest, eff = rest[2:], pb
        else:
            eff = 10
    first_bad = None
    for i, c in enumerate(rest):
        if c == "_":
            continue
        if not (c.isalnum() and int(c, 36) < eff):
            first_bad = i
            break
    if first_bad is None:
        return False
    prefix = rest[:first_bad].replace("_", "")
    if not prefix:
        return False
    value = int(prefix, eff)
    if sign == "-":
        value = -value
    overflow = not (I32_MIN <= value <= I32_MAX)
    return overflow and _oracle_is(ctx, "err", error="InvalidLiteral")


def pred_parseint_guion_bajo_valor(ctx: dict) -> bool:
    """Zig acepta guiones bajos que Python rechaza: '__' entre digitos, o base 0
    con cero a la izquierda sin prefijo ('010', '0_1'). El valor Zig tiene que
    ser el de quitar los '_' y leer el resto con la base efectiva.
    """
    base, text = _base(ctx), _text(ctx)
    if base is None or text is None:
        return False
    sign, rest = _sign_split(text)
    if not rest:
        return False
    double = re.search(r"[0-9A-Za-z]__+[0-9A-Za-z]", rest) is not None
    leading_zero = (base == 0 and _prefix_base(rest) is None
                    and re.match(r"0[0-9_]", rest) is not None)
    if not (double or leading_zero):
        return False
    clean = rest.replace("_", "")
    eff = base if base else (_prefix_base(clean) or 10)
    try:
        expected = int(sign + clean, eff)
    except ValueError:
        return False
    if not I32_MIN <= expected <= I32_MAX:
        return False
    return _subject_is(ctx, "ok", value=str(expected))


#: nombre -> predicado sobre el contexto completo del caso
PREDICATES: dict[str, Callable[[dict], bool]] = {
    "parseint-recorta-ascii": pred_parseint_recorta_ascii,
    "parseint-precedencia-overflow": pred_parseint_precedencia_overflow,
    "parseint-guion-bajo-valor": pred_parseint_guion_bajo_valor,
}


# --------------------------------------------------------------------------
# Matching
# --------------------------------------------------------------------------

def _input_ok(spec, ctx: dict | None) -> bool:
    """Evalua el campo `input` de una declaracion contra el contexto del caso."""
    if ctx is None:
        return False
    if isinstance(spec, str):
        pred = PREDICATES.get(spec)
        if pred is None:
            raise ValueError(f"predicado de entrada no registrado: {spec}")
        return pred(ctx)
    values = ctx.get("input") or {}
    for name, rule in spec.items():
        if name not in values:
            return False
        if "regex" in rule and re.fullmatch(rule["regex"], values[name]) is None:
            return False
    return True


def match_known(field_diffs: list[dict], known: list[dict], ctx: dict | None = None) -> str | None:
    """Devuelve el id de la divergencia conocida que explica los diffs.

    `ctx` es el contexto del caso (ver `case_context`); hace falta solo si
    alguna declaracion trae `input`. `None` si ninguna declaracion cubre esta
    diferencia (es una nueva).
    """
    if not field_diffs:
        return None
    names = {d.get("name", "") for d in field_diffs}
    for decl in known or []:
        allowed = set(decl.get("fields", []))
        if not allowed or not names.issubset(allowed):
            continue
        expect = decl.get("expect", {})
        oracle = decl.get("oracle", {})
        ok = True
        for d in field_diffs:
            name = d.get("name", "")
            if name in expect and not match_value(expect[name], d.get("subject", "")):
                ok = False
                break
            if name in oracle and not match_value(oracle[name], d.get("oracle", "")):
                ok = False
                break
        if ok and "input" in decl:
            ok = _input_ok(decl["input"], ctx)
        if ok:
            return decl.get("id", "desconocida")
    return None


def classify(row: dict, known: list[dict], schema: str, compared_fields: list[str]) -> str | None:
    """Id de la declaracion conocida de una fila de results.jsonl, o None (nueva)."""
    ctx = case_context(row, schema, compared_fields)
    return match_known(row.get("fields", []), known, ctx)


def signature(field_diffs: list[dict]) -> str:
    """Firma estable de una divergencia (para agrupar hallazgos)."""
    parts = []
    for d in sorted(field_diffs, key=lambda x: x.get("name", "")):
        parts.append(f"{d.get('name','')}={d.get('subject','')}!={d.get('oracle','')}")
    return "|".join(parts)


def group(field_diffs: list[dict]) -> dict[str, list[dict]]:
    """Agrupa diffs por firma."""
    out: dict[str, list[dict]] = {}
    for d in field_diffs:
        out.setdefault(signature(d), []).append(d)
    return out
