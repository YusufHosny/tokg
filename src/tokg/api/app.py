# ABOUTME: FastAPI app over a KnowledgeGraph. Every route except /health needs a bearer token;
# ABOUTME: owner-only actions are enforced by the graph itself, admin-only ones here.
import threading
from collections.abc import Callable
from datetime import datetime
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from tokg.api.auth import Principal, TokenRegistry
from tokg.graph import IngestReport, KnowledgeGraph, Verdict
from tokg.models import Escalation, EscalationStatus, Fact, Node, Source
from tokg.schema import Schema
from tokg.views import AskResult, Gaps, NodeView


class AskRequest(BaseModel):
  question: str = Field(..., min_length=1, max_length=2000)
  context: dict[str, str] = Field(default_factory=dict)


class QuestionRequest(BaseModel):
  question: str = Field(..., min_length=1, max_length=2000)


class VerdictRequest(BaseModel):
  verdict: Verdict
  note: str | None = Field(default=None, max_length=2000)


class AnswerRequest(BaseModel):
  answer: str = Field(..., min_length=1, max_length=10000)


class OwnerRequest(BaseModel):
  owner_id: str


def _parse_context(pairs: list[str]) -> dict[str, str]:
  bad = [p for p in pairs if "=" not in p]
  if bad:
    raise HTTPException(422, f"context entries must be key=value, got {bad}")
  return dict(p.split("=", 1) for p in pairs)


_bearer = HTTPBearer(auto_error=False)


def _principal(request: Request,
               creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]) -> Principal:
  registry: TokenRegistry = request.app.state.registry
  if creds is None or (p := registry.authenticate(creds.credentials)) is None:
    raise HTTPException(401, "invalid or missing bearer token", headers={"WWW-Authenticate": "Bearer"})
  return p


def _admin(p: Annotated[Principal, Depends(_principal)]) -> Principal:
  if p.role != "admin":
    raise HTTPException(403, "admin only")
  return p


User = Annotated[Principal, Depends(_principal)]
Admin = Annotated[Principal, Depends(_admin)]


def create_app(graph: KnowledgeGraph, registry: TokenRegistry,
               on_change: Callable[[], None] | None = None,
               cors_origins: list[str] | None = None) -> FastAPI:
  app = FastAPI(title="tokg", description="Temporal ownership knowledge graph")
  if cors_origins:
    app.add_middleware(CORSMiddleware, allow_origins=cors_origins, allow_methods=["*"],
                       allow_headers=["Authorization", "Content-Type"])
  app.state.registry = registry
  # the in-memory store is not thread-safe and FastAPI runs sync routes in a threadpool
  lock = threading.RLock()

  def changed() -> None:
    if on_change:
      on_change()

  @app.exception_handler(KeyError)
  def _not_found(_: Request, e: KeyError) -> JSONResponse:
    return JSONResponse({"detail": str(e.args[0]) if e.args else "not found"}, status_code=404)

  @app.exception_handler(PermissionError)
  def _forbidden(_: Request, e: PermissionError) -> JSONResponse:
    return JSONResponse({"detail": str(e)}, status_code=403)

  @app.exception_handler(ValueError)
  def _conflict(_: Request, e: ValueError) -> JSONResponse:
    return JSONResponse({"detail": str(e)}, status_code=409)

  @app.get("/health")
  def health() -> dict[str, str]:
    return {"status": "ok"}

  @app.get("/me")
  def me(p: User) -> Node | None:
    return graph.store.get_node(p.person_id)

  @app.get("/schema")
  def schema(_: User) -> Schema:
    return graph.schema

  @app.get("/nodes")
  def nodes(_: User, type: str | None = None, q: str | None = None, limit: int = Query(20, le=100)) -> list[Node]:
    with lock:
      return graph.search(q, type_=type, limit=limit) if q else graph.store.nodes(type)[:limit]

  @app.get("/nodes/{node_id}")
  def view(_: User, node_id: str, context: Annotated[list[str], Query()] = [],
           as_of: datetime | None = None) -> NodeView:
    with lock:
      return graph.view(node_id, _parse_context(context), as_of)

  @app.post("/nodes/{node_id}/questions")
  def ask_owner(p: User, node_id: str, body: QuestionRequest) -> Escalation:
    with lock:
      esc = graph.ask_owner(node_id, body.question, asked_by=p.person_id)
      changed()
      return esc

  @app.put("/nodes/{node_id}/owner")
  def assign_owner(p: Admin, node_id: str, body: OwnerRequest) -> Fact:
    with lock:
      fact = graph.assign_owner(node_id, body.owner_id, assigned_by=p.person_id)
      changed()
      return fact

  @app.get("/facts/{fact_id}")
  def fact(_: User, fact_id: str) -> Fact:
    if (f := graph.store.get_fact(fact_id)) is None:
      raise KeyError(f"no fact '{fact_id}'")
    return f

  @app.get("/sources/{source_id}")
  def source(_: User, source_id: str) -> Source:
    if (s := graph.store.get_source(source_id)) is None:
      raise KeyError(f"no source '{source_id}'")
    return s

  # members can only ingest as themselves: authorship decides whether a change needs owner
  # approval, so a forged author would bypass the ownership check
  @app.post("/ingest")
  def ingest(p: User, sources: list[Source]) -> IngestReport:
    if p.role != "admin":
      sources = [s.model_copy(update={"author": p.person_id}) for s in sources]
    with lock:
      report = graph.ingest(sources)
      changed()
      return report

  @app.post("/ask")
  def ask(_: User, body: AskRequest) -> AskResult:
    with lock:
      return graph.ask(body.question, body.context)

  @app.get("/escalations")
  def escalations(p: User, mine: bool = False, status: EscalationStatus | None = None) -> list[Escalation]:
    return [e for e in graph.store.escalations()
            if (not mine or e.assignee_id == p.person_id) and (status is None or e.status == status)]

  @app.post("/escalations/{escalation_id}/resolve")
  def resolve(p: User, escalation_id: str, body: VerdictRequest) -> Escalation:
    with lock:
      esc = graph.resolve_escalation(escalation_id, p.person_id, body.verdict, body.note)
      changed()
      return esc

  @app.post("/escalations/{escalation_id}/answer")
  def answer(p: User, escalation_id: str, body: AnswerRequest) -> IngestReport:
    with lock:
      report = graph.answer_escalation(escalation_id, p.person_id, body.answer)
      changed()
      return report

  @app.get("/gaps")
  def gaps(_: User) -> Gaps:
    with lock:
      return graph.gaps()

  return app
