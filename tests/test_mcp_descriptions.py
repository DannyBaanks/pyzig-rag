"""El texto anunciado por MCP debe activar consultas en los momentos clave."""
from __future__ import annotations

import asyncio
import unittest

from pyzig import mcp_server


def _listed_tools() -> dict[str, object]:
    return {tool.name: tool for tool in asyncio.run(mcp_server.mcp.list_tools())}


class McpDescriptionsTest(unittest.TestCase):
    def test_tool_names_and_parameter_shapes_are_stable(self) -> None:
        tools = _listed_tools()
        expected = {
            "pyzig_search": {
                "intent": ("string", None),
                "py_code": ("string", ""),
                "zig_version": ("string", "0.16.0"),
                "platform": ("string", "linux"),
                "max_results": ("integer", 5),
                "mode": ("string", "hybrid"),
                "code": ("string", "top"),
            },
            "pyzig_get": {"operation_id": ("string", None)},
            "pyzig_catalog": {},
            "pyzig_check": {
                "zig_code": ("string", None),
                "mode": ("string", "test"),
            },
        }
        self.assertEqual(set(tools), set(expected))
        for name, parameters in expected.items():
            schema = tools[name].parameters
            self.assertEqual(set(schema["properties"]), set(parameters), name)
            self.assertEqual(set(schema.get("required", [])), {
                key for key, (_, default) in parameters.items() if default is None
            }, name)
            for key, (kind, default) in parameters.items():
                prop = schema["properties"][key]
                self.assertEqual(prop["type"], kind, f"{name}.{key}")
                if default is not None:
                    self.assertEqual(prop["default"], default, f"{name}.{key}")

    def test_every_parameter_has_a_short_description(self) -> None:
        for name, tool in _listed_tools().items():
            for parameter, schema in tool.parameters["properties"].items():
                self.assertTrue(
                    schema.get("description", "").strip(),
                    f"Falta descripcion para {name}.{parameter}",
                )

    def test_instructions_and_tool_text_name_the_use_triggers(self) -> None:
        tools = _listed_tools()
        instructions = mcp_server.INSTRUCTIONS
        for phrase in ("ANTES", "porte codigo Python", "std.Io", "ArrayList",
                       "build.zig", "mensaje exacto", "pyzig_search(intent",
                       "pyzig_check(zig_code"):
            self.assertIn(phrase, instructions)

        search = tools["pyzig_search"]
        for phrase in ("portar codigo Python", "std.Io", "ArrayList",
                       "build.zig", "error de compilacion"):
            self.assertIn(phrase, search.description)
        self.assertIn("mensaje exacto", search.parameters["properties"]["intent"]["description"])
        self.assertIn("antes de portarlo", search.parameters["properties"]["py_code"]["description"])

        check = tools["pyzig_check"]
        self.assertIn("errores", check.description)
        self.assertIn("recetas", check.description)
        self.assertIn("compilar", check.parameters["properties"]["zig_code"]["description"])


if __name__ == "__main__":
    unittest.main()
