# ABOUTME: MCP server smoke test through FastMCP's in-memory client.
import asyncio

from conftest import OTHER_ID, OWNER, doc, make_graph, owns, rule
from fastmcp import Client

from tokg.mcp import create_mcp
from tokg.rig import Rig


def test_mcp_tools(schema):
  g = make_graph(schema, Rig(extractions={"doc:a": [owns(OWNER), rule("no note day 1", country="BE")]}))
  g.ingest([doc("doc:a", OWNER, "2021-01-01")])
  mcp = create_mcp(g, OTHER_ID)

  async def run():
    async with Client(mcp) as c:
      names = {t.name for t in await c.list_tools()}
      found = await c.call_tool("search", {"query": "sick note"})
      view = await c.call_tool("view_node", {"node_id": "policy:sick-note", "context": {"country": "BE"}})
      missing = await c.call_tool("view_node", {"node_id": "policy:nope"})
      esc = await c.call_tool("ask_owner", {"node_id": "policy:sick-note", "question": "why?"})
      return names, found, view, missing, esc

  names, found, view, missing, esc = asyncio.run(run())
  assert names == {"search", "view_node", "ask", "ask_owner", "gaps"}
  assert found.structured_content["result"][0]["id"] == "policy:sick-note"
  assert view.structured_content["owner"]["name"] == "Olga Owner"
  assert "error" in missing.structured_content
  assert esc.structured_content["raised_by"] == OTHER_ID
