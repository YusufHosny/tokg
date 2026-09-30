# ABOUTME: MCP server (FastMCP) so users can query the graph from their own agents. Runs over stdio
# ABOUTME: as one fixed person; tools are read-only except ask_owner, which raises a question.
import threading
from collections.abc import Callable
from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field, StringConstraints

from tokg.api.app import ASK_LIMIT, SlidingWindow, _public_gaps, _redact
from tokg.api.auth import Principal
from tokg.graph import KnowledgeGraph
from tokg.views import AskResult

MAX_CONTEXT = 16
ContextKey = Annotated[str, StringConstraints(min_length=1, max_length=64)]
ContextValue = Annotated[str, StringConstraints(max_length=256)]
Context = Annotated[dict[ContextKey, ContextValue], Field(max_length=MAX_CONTEXT)]
NodeId = Annotated[str, Field(min_length=1, max_length=256)]
Query = Annotated[str, Field(min_length=1, max_length=500)]
TypeName = Annotated[str, Field(min_length=1, max_length=64)]
Question = Annotated[str, Field(min_length=1, max_length=2000)]
RATE_LIMITED = "rate limit exceeded"
READ_ONLY = "store is in use by the server; ask through the web app"


def create_mcp(graph: KnowledgeGraph, person_id: str, on_change: Callable[[], None] | None = None,
               questions: SlidingWindow | None = None, read_only: bool = False) -> FastMCP:
  mcp = FastMCP("tokg", mask_error_details=True, instructions=(
    "TOKG (Temporal Ownership-Grounded Knowledge Graph): organisational knowledge with temporal facts, "
    "owners and sources. Use `ask` for questions, "
    "`view_node` to drill into current facts, history and sources, and `ask_owner` when the graph "
    "has no answer. Always mention who owns the knowledge and whether facts are confirmed."))

  principal = Principal(person_id=person_id, role="member")
  questions = questions or SlidingWindow(20, 3600)
  lock = threading.Lock()

  @mcp.tool(description='Find knowledge graph nodes by keywords.')
  def search(query: Query, type: TypeName | None = None) -> list[dict[str, Any]]:
    with lock:
      return [n.model_dump(mode="json") for n in graph.search(query, type_=type)]

  @mcp.tool(description='Current facts, history, sources, owner and contacts of a node in a context (e.g. {"country": "BE"}).')
  def view_node(node_id: NodeId, context: Context | None = None) -> dict[str, Any]:
    with lock:
      try:
        return _redact(principal, graph.store, graph.view(node_id, context)).model_dump(mode="json")
      except KeyError:
        return {"error": f"no node '{node_id}'"}

  @mcp.tool(description='Answer a question from the graph, with cited facts, contacts and caveats.')
  def ask(question: Question, context: Context | None = None) -> dict[str, Any]:
    with lock:
      views = [_redact(principal, graph.store, graph.view(n.id, context))
               for n in graph.ask_hits(question, limit=ASK_LIMIT)]
      answer = graph.answerer.answer(question, views)
      return AskResult(question=question, answer=answer, views=views).model_dump(mode="json")

  @mcp.tool(description='Escalate a question to the owner of a node when the graph cannot answer it.')
  def ask_owner(node_id: NodeId, question: Question) -> dict[str, Any]:
    with lock:
      if read_only:
        return {"error": READ_ONLY}
      if questions.peek(person_id) is not None:
        return {"error": RATE_LIMITED}
      try:
        esc = graph.ask_owner(node_id, question, asked_by=person_id)
      except KeyError:
        return {"error": f"no node '{node_id}'"}
      except ValueError as e:
        return {"error": str(e)}
      questions.hit(person_id)
      if on_change:
        on_change()
      return esc.model_dump(mode="json")

  @mcp.tool(description='Unowned nodes, pending changes, stale facts and open escalations.')
  def gaps() -> dict[str, Any]:
    with lock:
      return _public_gaps(principal, graph.store, graph.gaps()).model_dump(mode="json")

  return mcp
