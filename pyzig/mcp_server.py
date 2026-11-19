#!/usr/bin/env python3
"""Servidor MCP de solo lectura para el corpus Python<->Zig 0.16.

Transporte: stdio (JSON-RPC MCP). No ejecuta codigo recuperado ni escribe
nada: las herramientas son consultas puras sobre el indice.
"""
from __future__ import annotations
import sys, json, pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from fastmcp import FastMCP  # type: ignore

from pyzig import search as s

INSTRUCTIONS = """pyzig-rag: recetas Python -> Zig 0.16.0 VERIFICADAS (cada una compilo y paso `zig test` con zig 0.16.0).
Consultalo ANTES de escribir Zig que toque std.Io, archivos/rutas, json, procesos, colecciones, texto/numeros, tiempo, argv o hashes:
la API de 0.16 (std.Io, Io.Dir, Io.Limit, writer/reader nuevos) difiere de lo que recuerdan los modelos.
Flujo: pyzig_search(intent="que quieres hacer", py_code="opcional") -> el primer resultado trae zig_impl completo;
pyzig_get(operation_id) para contrato, tests y procedencia de otro; pyzig_catalog() lista todas las operaciones.
Lee 'status': solo DEMONSTRATED es equivalencia verificada; NOT_DEMONSTRATED documenta un hueco real de la std.
'differences' lista las trampas Python vs Zig. NO_RESULTS = no hay receta: no inventes que la hay."""

mcp = FastMCP("pyzig-rag", instructions=INSTRUCTIONS)

@mcp.tool
def pyzig_search(intent: str, py_code: str = "", zig_version: str = "0.16.0",
                 platform: str = "linux", max_results: int = 5,
                 mode: str = "hybrid", code: str = "top") -> dict:
    """Busca equivalencias Python->Zig por intencion (y codigo Python opcional).

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

@mcp.tool
def pyzig_get(operation_id: str) -> dict:
    """Recupera una equivalencia por ID: contrato, codigo, tests, procedencia."""
    try:
        d = s.get(operation_id)
        return {"ok": True, "entry": d}
    except s.NoResults as e:
        return {"ok": False, "error": "NO_RESULTS", "message": str(e)}
    except s.IndexUnavailable as e:
        return {"ok": False, "error": "INDEX_UNAVAILABLE", "message": str(e)}

@mcp.tool
def pyzig_catalog() -> dict:
    """Operaciones disponibles, versiones soportadas y salud del indice."""
    try:
        return {"ok": True, "catalog": s.catalog()}
    except s.IndexUnavailable as e:
        return {"ok": False, "error": "INDEX_UNAVAILABLE", "message": str(e)}

if __name__ == "__main__":
    mcp.run(show_banner=False)
