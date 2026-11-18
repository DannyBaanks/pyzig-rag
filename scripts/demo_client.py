#!/usr/bin/env python3
"""Cliente MCP real: lanza el servidor por stdio y consulta las 3 herramientas."""
import asyncio, json, os, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SERVER = ROOT / "pyzig" / "mcp_server.py"

from mcp import ClientSession, StdioServerParameters  # type: ignore
from mcp.client.stdio import stdio_client  # type: ignore

async def main() -> None:
    env = dict(os.environ)
    params = StdioServerParameters(command=sys.executable, args=[str(SERVER)], env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("herramientas:", sorted(t.name for t in tools.tools))
            r = await session.call_tool("pyzig_search", {
                "intent": "Necesito implementar en Zig 0.16 un equivalente de subprocess.run "
                          "que capture ambas salidas, distinga errores de terminacion y limite "
                          "el tamano de los datos",
                "zig_version": "0.16.0", "platform": "linux", "max_results": 3})
            payload = json.loads(r.content[0].text)
            print("\npyzig_search ok=", payload.get("ok"), "count=", payload.get("count"))
            for it in payload.get("results", [])[:3]:
                print(" -", it["operation_id"], it["score"], it["status"], it["reason"])
            top = payload["results"][0]["operation_id"]
            g = await session.call_tool("pyzig_get", {"operation_id": top})
            entry = json.loads(g.content[0].text)["entry"]
            print("\npyzig_get:", entry["name"])
            print("  status:", entry["evidence"]["status"],
                  "| runs:", len(entry["evidence"]["runs"]))
            print("  zig:", entry["zig_version"], "| plataforma:", entry["platform"])
            c = await session.call_tool("pyzig_catalog", {})
            cat = json.loads(c.content[0].text)["catalog"]
            print("\npyzig_catalog: entradas", cat["entries"], "| embed", cat["embed_mode"],
                  "| zig", cat["zig_versions"])

if __name__ == "__main__":
    asyncio.run(main())
