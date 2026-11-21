"""Anotaciones MCP completas y una llamada real por cada tool declarada.

Los directorios (p. ej. OpenAI) rechazan tools a las que les falte cualquiera de
las cuatro hints (readOnlyHint, destructiveHint, idempotentHint, openWorldHint)
o que las declaren como no-boolean. Este test fija el contrato y comprueba que
cada tool anunciada se puede invocar.
"""
from __future__ import annotations

import asyncio
import pathlib
import shutil
import tempfile
import unittest
from unittest import mock

from pyzig import check as check_mod
from pyzig import index as idx
from pyzig import mcp_server

HAS_ZIG = shutil.which("zig") is not None
HAS_BWRAP = check_mod.probe_bwrap() is not None

HINTS = ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")

#: name -> (readOnly, destructive, idempotent, openWorld)
EXPECTED = {
    "pyzig_search": (True, False, True, False),
    "pyzig_get": (True, False, True, False),
    "pyzig_catalog": (True, False, True, False),
    "pyzig_check": (False, False, True, False),
}


def _listed_tools() -> dict[str, dict]:
    tools = asyncio.run(mcp_server.mcp.list_tools())
    return {t.name: t.model_dump(by_alias=True) for t in tools}


class McpAnnotationsTest(unittest.TestCase):
    def test_every_declared_tool_has_all_four_boolean_hints(self) -> None:
        tools = _listed_tools()
        self.assertEqual(set(tools), set(EXPECTED))
        for name, (ro, de, idem, ow) in EXPECTED.items():
            ann = tools[name].get("annotations") or {}
            got = {k: ann.get(k) for k in HINTS}
            self.assertEqual(
                got,
                {"readOnlyHint": ro, "destructiveHint": de,
                 "idempotentHint": idem, "openWorldHint": ow},
                f"{name} declara hints incompletas o no-boolean: {ann}",
            )
            for hint, value in got.items():
                self.assertIsInstance(value, bool, f"{name}.{hint} no es bool")


class McpToolsCallableTest(unittest.TestCase):
    """Cada tool anunciada responde con un dict sobre un indice hermetico."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="pyzig-mcp-tools-test-")
        cls.var = pathlib.Path(cls._tmp.name)
        cls._patchers = [
            mock.patch.object(idx, "DB", cls.var / "pyzig.db"),
            mock.patch.object(idx, "VAR", cls.var),
            mock.patch.object(check_mod, "CACHE_DIR", cls.var / "check-cache"),
            mock.patch.object(mcp_server, "NORES_FILE", cls.var / "nores.jsonl"),
        ]
        for p in cls._patchers:
            p.start()
        idx.build(embed=None)

    @classmethod
    def tearDownClass(cls) -> None:
        for p in reversed(cls._patchers):
            p.stop()
        cls._tmp.cleanup()

    def test_catalog_returns_operations(self) -> None:
        res = mcp_server.pyzig_catalog()
        self.assertTrue(res["ok"])
        self.assertGreater(len(res["catalog"]["operations"]), 0)

    def test_search_then_get(self) -> None:
        res = mcp_server.pyzig_search(
            intent="ejecutar un proceso externo y capturar su salida",
            zig_version="0.16.0", mode="lexical",
        )
        self.assertTrue(res["ok"], res)
        self.assertGreater(res["count"], 0)
        oid = res["results"][0]["operation_id"]
        got = mcp_server.pyzig_get(operation_id=oid)
        self.assertTrue(got["ok"], got)
        self.assertEqual(got["entry"]["operation_id"], oid)

    def test_get_unknown_id_is_no_results(self) -> None:
        res = mcp_server.pyzig_get(operation_id="zig0.16/no-existe-esta-operacion")
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"], "NO_RESULTS")

    @unittest.skipUnless(HAS_ZIG and HAS_BWRAP, "zig o bwrap no disponibles")
    def test_check_compiles_valid_zig(self) -> None:
        res = mcp_server.pyzig_check(zig_code="const x: u8 = 1;\n", mode="ast")
        self.assertTrue(res["ok"], res)
        self.assertTrue(res["compiled"], res)


if __name__ == "__main__":
    unittest.main()
