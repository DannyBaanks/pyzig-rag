#!/usr/bin/env python3
"""Servidor MCP para el corpus Python<->Zig 0.16.

Transporte: stdio (JSON-RPC MCP). Consulta recetas verificadas del indice y
permite verificar codigo Zig 0.16 (`pyzig_check` compila y ejecuta en bwrap sin red;
sin bwrap se niega).
"""
from __future__ import annotations
from datetime import datetime, timezone
import sys, json, pathlib
from typing import Annotated

from pydantic import Field

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from fastmcp import FastMCP  # type: ignore
from mcp.types import ToolAnnotations

from pyzig import check as check_mod
from pyzig import search as s
from pyzig.paths import VAR

NORES_FILE = VAR / "nores.jsonl"
_NORES_INTENT_LIMIT = 300

# Anotaciones MCP completas: los directorios (p. ej. OpenAI) rechazan tools a las
# que les falte cualquiera de las cuatro hints, o que las declaren como no-boolean.
# `pyzig_search` solo escribe su log diagnostico local (var/nores.jsonl), no estado
# del usuario; `pyzig_check` compila y ejecuta codigo, asi que no es read-only.
_READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False,
                             idempotent_hint=True, open_world_hint=False)
_EXECUTES = ToolAnnotations(read_only_hint=False, destructive_hint=False,
                            idempotent_hint=True, open_world_hint=False)

INSTRUCTIONS = """pyzig-rag: recetas Python -> Zig 0.16.0 verificadas con `zig test`.
Usalo ANTES de escribir Zig que porte codigo Python y antes de usar APIs que cambiaron en 0.16, como `std.Io`, `ArrayList` o `build.zig`.
Cubre archivos/rutas, json, procesos, hilos, red, colecciones, texto/numeros, tiempo, argv y hashes: la API 0.16 difiere de lo que recuerdan los modelos.
Si aparece un error de compilacion 0.16, pega el mensaje exacto en `pyzig_search(intent=...)`; para compilar el fragmento y obtener sugerencias, usa `pyzig_check(zig_code=...)`.
`pyzig_search(intent, py_code)` busca equivalencias; el primer resultado incluye `zig_impl`. Usa `pyzig_get(operation_id)` para contrato, tests y procedencia; `pyzig_catalog()` lista operaciones.
`pyzig_check(zig_code, mode="test"|"ast")` compila y, en modo test, ejecuta en bwrap sin red; sin bwrap se niega. Devuelve hasta 2 recetas sugeridas por error.
Solo `status=DEMONSTRATED` indica equivalencia verificada; `NOT_DEMONSTRATED` documenta un hueco. `NO_RESULTS` significa que no hay receta admitida."""

mcp = FastMCP("pyzig-rag", instructions=INSTRUCTIONS)


def _log_nores(intent: str, zig_version: str) -> None:
    """Registra localmente consultas sin resultado en var/nores.jsonl; fallo silencioso."""
    try:
        NORES_FILE.parent.mkdir(parents=True, exist_ok=True)
        rec = {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "intent": str(intent)[:_NORES_INTENT_LIMIT],
            "zig_version": zig_version,
        }
        with NORES_FILE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        pass


def _count_nores() -> int:
    try:
        if not NORES_FILE.exists():
            return 0
        with NORES_FILE.open("r", encoding="utf-8") as fh:
            return sum(1 for line in fh if line.strip())
    except Exception:  # noqa: BLE001
        return 0

@mcp.tool(annotations=_READ_ONLY)
def pyzig_search(
    intent: Annotated[str, Field(description="Operacion que quieres portar o investigar. Ante un error Zig 0.16, pega aqui el mensaje exacto para buscar una receta de migracion.")],
    py_code: Annotated[str, Field(description="Codigo Python de origen; incluyelo antes de portarlo para recuperar una equivalencia con su comportamiento.")] = "",
    zig_version: Annotated[str, Field(description="Version Zig destino para filtrar recetas; usa 0.16.0 para la API actual.")] = "0.16.0",
    platform: Annotated[str, Field(description="Plataforma destino para filtrar recetas.")] = "linux",
    max_results: Annotated[int, Field(description="Maximo de recetas candidatas que devuelve la busqueda.")] = 5,
    mode: Annotated[str, Field(description="Modo de recuperacion: hybrid o lexical.")] = "hybrid",
    code: Annotated[str, Field(description="Codigo incluido en resultados: top, all o none.")] = "top",
) -> dict:
    """Busca equivalencias Python->Zig por intencion y codigo Python.

    Usala antes de portar codigo Python a Zig 0.16, al revisar cambios en
    std.Io, ArrayList o build.zig, y para buscar pegando un error de compilacion
    0.16 exacto en intent.

    Devuelve candidatos ordenados con motivo de coincidencia, restricciones,
    estado de evidencia y referencia recuperable con pyzig_get.
    code: "top" (defecto) adjunta zig_impl completo al primer resultado,
    "all" a todos, "none" a ninguno (solo la primera linea en summary).
    Errores distinguibles: NO_RESULTS, VERSION_MISMATCH, INDEX_UNAVAILABLE.
    """
    q = intent if not py_code else f"{intent}\n{py_code}"
    try:
        rs = s.search(q, zig_version=zig_version or None, platform=platform or None,
                      limit=max(1, min(int(max_results), 20)), mode=mode)
        n_code = {"top": 1, "all": len(rs), "none": 0}.get(code, 1)
        for r in rs[:n_code]:
            r["zig_impl"] = s.get(r["operation_id"])["zig_impl"]
        return {"ok": True, "query": q, "count": len(rs), "results": rs}
    except s.NoResults as e:
        _log_nores(intent, zig_version)
        return {"ok": False, "error": "NO_RESULTS", "message": str(e),
                "hint": "no hay equivalencia admitida; reformula o pyzig_catalog para ver operaciones"}
    except s.VersionMismatch as e:
        return {"ok": False, "error": "VERSION_MISMATCH", "message": str(e),
                "supported": s.catalog().get("zig_versions", [])}
    except s.IndexUnavailable as e:
        return {"ok": False, "error": "INDEX_UNAVAILABLE", "message": str(e),
                "hint": "ejecuta scripts/build_index.py"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "INTERNAL", "message": f"{type(e).__name__}: {e}"}

@mcp.tool(annotations=_READ_ONLY)
def pyzig_get(operation_id: Annotated[str, Field(description="operation_id de un resultado de pyzig_search para recuperar su receta completa.")]) -> dict:
    """Usala tras pyzig_search para leer contrato, codigo, tests y procedencia."""
    try:
        d = s.get(operation_id)
        return {"ok": True, "entry": d}
    except s.NoResults as e:
        return {"ok": False, "error": "NO_RESULTS", "message": str(e)}
    except s.IndexUnavailable as e:
        return {"ok": False, "error": "INDEX_UNAVAILABLE", "message": str(e)}

@mcp.tool(annotations=_READ_ONLY)
def pyzig_catalog() -> dict:
    """Usala para descubrir operaciones disponibles o revisar versiones y salud del indice."""
    try:
        cat = s.catalog()
        cat["nores_count"] = _count_nores()
        return {"ok": True, "catalog": cat}
    except s.IndexUnavailable as e:
        return {"ok": False, "error": "INDEX_UNAVAILABLE", "message": str(e)}


@mcp.tool(annotations=_EXECUTES)
def pyzig_check(
    zig_code: Annotated[str, Field(description="Fragmento Zig 0.16 que quieres compilar; al fallar devuelve errores y hasta 2 recetas sugeridas por error.")],
    mode: Annotated[str, Field(description="test compila y ejecuta tests; ast solo valida sintaxis y tipos.")] = "test",
) -> dict:
    """Compila codigo Zig 0.16 y ofrece recetas para resolver errores.

    Usala para comprobar el fragmento tras consultar una receta o cuando falle
    la compilacion. Para buscar por el texto exacto del error, pegalo en el
    parametro intent de pyzig_search.

    mode='test' compila y ejecuta en bwrap sin red; mode='ast' usa zig ast-check.
    Sin bwrap se niega (SANDBOX_UNAVAILABLE). Devuelve hasta 2 recetas por error.
    """
    try:
        return check_mod.check_zig(zig_code, mode=mode)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "INTERNAL", "message": f"{type(e).__name__}: {e}",
                "sandbox": None, "compiled": False, "tests_passed": None,
                "errors": [], "stderr_tail": ""}

if __name__ == "__main__":
    mcp.run(show_banner=False)
