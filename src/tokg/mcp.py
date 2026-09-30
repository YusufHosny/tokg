# ABOUTME: MCP server (FastMCP) so users can query the graph from their own agents. Runs over stdio
# ABOUTME: as one fixed person; tools are read-only except ask_owner, which raises a question.
from typing import Any

from fastmcp import FastMCP

from tokg.graph import KnowledgeGraph


def create_mcp(graph: KnowledgeGraph, person_id: str) -> FastMCP:
  mcp = FastMCP("tokg", instructions=(
    "Organisational knowledge graph with temporal facts, owners and sources. Use `ask` for questions, "
    "`view_node` to drill into current facts, history and sources, and `ask_owner` when the graph "
    "has no answer. Always mention who owns the knowledge and whether facts are confirmed."))

  @mcp.tool(description='Find knowledge graph nodes by keywords.')
  def search(query: str, type: str | None = None) -> list[dict[str, Any]]:
    return [n.model_dump(mode="json") for n in graph.search(query, type_=type)]

  @mcp.tool(description='Current facts, history, sources, owner and contacts of a node in a context (e.g. {"country": "BE"}).')
  def view_node(node_id: str, context: dict[str, str] | None = None) -> dict[str, Any]:
    try:
      return graph.view(node_id, context).model_dump(mode="json")
    except KeyError as e:
      return {"error": str(e)}

  @mcp.tool(description='Answer a question from the graph, with cited facts, contacts and caveats.')
  def ask(question: str, context: dict[str, str] | None = None) -> dict[str, Any]:
    return graph.ask(question, context).model_dump(mode="json")

  @mcp.tool(description='Escalate a question to the owner of a node when the graph cannot answer it.')
  def ask_owner(node_id: str, question: str) -> dict[str, Any]:
    try:
      return graph.ask_owner(node_id, question, asked_by=person_id).model_dump(mode="json")
    except KeyError as e:
      return {"error": str(e)}

  @mcp.tool(description='Unowned nodes, pending changes, stale facts and open escalations.')
  def gaps() -> dict[str, Any]:
    return graph.gaps().model_dump(mode="json")

  return mcp
