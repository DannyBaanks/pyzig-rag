"""Triage de divergencias: separa las divergencias conocidas de las nuevas.

Una divergencia *conocida* esta declarada en el contrato del corpus
(`fuzz.known_divergences`): dice que campos pueden diferir y con que valores.
Todo lo que no encaje en ninguna declaracion es una divergencia NUEVA, y por
eso es un hallazgo: o el corpus miente sobre la semántica, o la receta tiene
un bug.

Formato de una declaracion:

    {
      "id": "limite-captura",
      "fields": ["status", "error", "stdout_len"],   # campos que pueden diferir
      "expect": {"status": "err", "error": "StreamTooLong"},   # lado Zig
      "oracle": {"status": "ok", "error": ""},                  # lado Python
      "why": "la receta Zig limita la captura a 64 KiB; subprocess.run no limita"
    }

Los valores admiten patrones: exacto, "*" (cualquiera) y "digits" (entero
decimal).
"""

from __future__ import annotations

import re

_DIGITS = re.compile(r"^[0-9]+$")


def match_value(pattern: str, value: str) -> bool:
    """Compara un valor observado contra el patron declarado."""
    if pattern == "*":
        return True
    if pattern == "digits":
        return bool(_DIGITS.match(value))
    return pattern == value


def match_known(field_diffs: list[dict], known: list[dict]) -> str | None:
    """Devuelve el id de la divergencia conocida que explica los diffs.

    `None` si ninguna declaracion cubre esta diferencia (es una nueva).
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
        if ok:
            return decl.get("id", "desconocida")
    return None


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
