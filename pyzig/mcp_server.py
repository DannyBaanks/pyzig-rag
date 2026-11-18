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

mcp = FastMCP("pyzig-rag")

@mcp.tool
def pyzig_search(intent: str, py_code: str = "", zig_version: str = "0.16.0",
                 platform: str = "linux", max_results: int = 5,
                 mode: str = "hybrid") -> dict:
    """Busca equivalencias Python->Zig por intencion (y codigo Python opcional).

    Devuelve candidatos ordenados con motivo de coincidencia, restricciones,
    estado de evidencia y referencia recuperable con pyzig_get.
    Errores distinguibles: NO_RESULTS, VERSION_MISMATCH, INDEX_UNAVAILABLE.
    """
    q = intent if not py_code else f"{intent}\n{py_code}"
    try:
        rs = s.search(q, zig_version=zig_version or None, platform=platform or None,
                      limit=max(1, min(int(max_results), 20)), mode=mode)
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
    mcp.run()
