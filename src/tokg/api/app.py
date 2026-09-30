# ABOUTME: FastAPI app over a KnowledgeGraph. Every route except /health needs a bearer token;
# ABOUTME: owner-only actions are enforced by the graph itself, admin-only ones here.
import math
import re
import threading
import time
from collections import deque
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated

from fastapi import Body, Depends, FastAPI, HTTPException
from fastapi import Path as PathParam
from fastapi import Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, StringConstraints, ValidationError

from tokg.answer import TemplateAnswerer
from tokg.api.auth import Principal, TokenRegistry
from tokg.extract import MAX_KNOWN_ENTITIES, ClaimDraft
from tokg.graph import RESERVED_SOURCE_PREFIXES, SOURCE_ID, ClaimOutcome, IngestReport, KnowledgeGraph, Verdict
from tokg.models import Escalation, EscalationStatus, Fact, Node, NoteSource, Source, SourceRef, as_utc
from tokg.schema import Schema
from tokg.store import GraphStore
from tokg.views import AskResult, FactView, Gaps, NodeView

WEB = Path(__file__).parent.parent / "web"

MAX_BODY_BYTES = 2_000_000
MAX_SOURCES = 50
MAX_CONTENT = 200_000
MAX_MEMBER_CONTENT = 50_000
BYTE_UNIT = 1000
MAX_TITLE = 500
MAX_PEOPLE_REF = 320
MAX_RECIPIENTS = 200
MAX_CONTEXT = 16
MAX_ID = 256
MAX_ESCALATION_ID = 300
EXTRACT_WORKERS = 8
ASK_LIMIT = 3
MEMBER_SOURCE_SEPARATOR = "+"
MEMBER_FORBIDDEN_KINDS = frozenset({"note"})
MEMBER_CLOCK_SKEW = timedelta(days=1)
MAX_MEMBER_SOURCES = 1000
MAX_MEMBER_STORAGE_BYTES = 200_000_000
_CHARGE_LOCK = threading.Lock()

APP_CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
           "img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; "
           "form-action 'self'; frame-ancestors 'none'")
API_CSP = "default-src 'none'; frame-ancestors 'none'"
EXTRACTION_FAILED = "extraction failed"
NOT_ALLOWED = "not allowed"
NOT_FOUND = "not found"
CONFLICT = "conflict"
REDACTED_NOTE_TITLE = "Answer"
PUBLIC_URI_SCHEMES = ("http", "https")
PUBLIC_URI_ROOT = "examples"

ContextKey = Annotated[str, StringConstraints(min_length=1, max_length=64)]
ContextValue = Annotated[str, StringConstraints(max_length=256)]
Id = Annotated[str, PathParam(min_length=1, max_length=MAX_ID)]
EscalationId = Annotated[str, PathParam(min_length=1, max_length=MAX_ESCALATION_ID)]


class SlidingWindow:
  def __init__(self, limit: int, seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
    self.limit, self.seconds, self.clock = limit, seconds, clock
    self._hits: dict[str, deque[float]] = {}
    self._lock = threading.Lock()

  def _wait(self, hits: deque[float], now: float, cost: int) -> float | None:
    while hits and hits[0] <= now - self.seconds:
      hits.popleft()
    if cost > self.limit:
      return self.seconds
    if (excess := len(hits) + cost - self.limit) > 0:
      return hits[excess - 1] + self.seconds - now
    return None

  def peek(self, key: str, cost: int = 1) -> float | None:
    now = self.clock()
    with self._lock:
      return self._wait(self._hits.setdefault(key, deque()), now, cost)

  def hit(self, key: str, cost: int = 1) -> float | None:
    now = self.clock()
    with self._lock:
      hits = self._hits.setdefault(key, deque())
      if (wait := self._wait(hits, now, cost)) is not None:
        return wait
      hits.extend([now] * cost)
      return None


@dataclass
class RateLimits:
  requests: SlidingWindow = field(default_factory=lambda: SlidingWindow(120, 60))
  questions: SlidingWindow = field(default_factory=lambda: SlidingWindow(20, 3600))
  asks: SlidingWindow = field(default_factory=lambda: SlidingWindow(300, 3600))
  ingested: SlidingWindow = field(default_factory=lambda: SlidingWindow(200, 3600))
  ingested_bytes: SlidingWindow = field(default_factory=lambda: SlidingWindow(5_000, 3600))
  reads: SlidingWindow = field(default_factory=lambda: SlidingWindow(600, 60))
  answers: SlidingWindow = field(default_factory=lambda: SlidingWindow(60, 3600))
  searches: SlidingWindow = field(default_factory=lambda: SlidingWindow(60, 60))


class AskRequest(BaseModel):
  question: str = Field(..., min_length=1, max_length=2000)
  context: dict[ContextKey, ContextValue] = Field(default_factory=dict, max_length=MAX_CONTEXT)


class QuestionRequest(BaseModel):
  question: str = Field(..., min_length=1, max_length=2000)


class VerdictRequest(BaseModel):
  verdict: Verdict
  note: str | None = Field(default=None, max_length=2000)


class AnswerRequest(BaseModel):
  answer: str = Field(..., min_length=1, max_length=10000)


class OwnerRequest(BaseModel):
  owner_id: str = Field(..., min_length=1, max_length=MAX_PEOPLE_REF)


def _parse_context(pairs: list[str]) -> dict[str, str]:
  if len(pairs) > MAX_CONTEXT or any(len(p) > 321 for p in pairs):
    raise HTTPException(422, f"at most {MAX_CONTEXT} context entries of up to 321 characters")
  bad = [p for p in pairs if "=" not in p]
  if bad:
    raise HTTPException(422, f"context entries must be key=value, got {bad}")
  return dict(p.split("=", 1) for p in pairs)


def _member_source_id(p: Principal, source_id: str) -> str:
  namespace = f"{p.person_id}{MEMBER_SOURCE_SEPARATOR}"
  return source_id if source_id.startswith(namespace) else f"{namespace}{source_id}"


def _check_source(p: Principal, s: Source, now: datetime) -> Source:
  if not SOURCE_ID.fullmatch(s.id) or s.id.startswith(RESERVED_SOURCE_PREFIXES):
    raise HTTPException(422, f"invalid or reserved source id '{s.id[:MAX_ID]}'")
  member = p.role != "admin"
  if member and s.kind in MEMBER_FORBIDDEN_KINDS:
    raise HTTPException(403, f"members cannot ingest '{s.kind}' sources")
  if (len(s.content) > (MAX_MEMBER_CONTENT if member else MAX_CONTENT) or len(s.title) > MAX_TITLE
      or len(s.author) > MAX_PEOPLE_REF or len(s.recipients) > MAX_RECIPIENTS
      or any(len(r) > MAX_PEOPLE_REF for r in s.recipients) or len(s.uri or "") > 2048):
    raise HTTPException(413, f"source '{s.id}' exceeds size limits")
  if not member:
    return s
  if s.timestamp > now + MEMBER_CLOCK_SKEW:
    raise HTTPException(422, f"source '{s.id}' is dated in the future")
  if not SOURCE_ID.fullmatch(source_id := _member_source_id(p, s.id)):
    raise HTTPException(422, f"source id '{s.id}' does not fit the member namespace")
  return s.model_copy(update={"id": source_id, "author": p.person_id, "timestamp": min(s.timestamp, now)})


def _already_stored(store: GraphStore, sent: Source, checked: Source) -> Source:
  if (existing := store.get_source(checked.id)) is None \
      or not sent.timestamp - MEMBER_CLOCK_SKEW <= existing.timestamp <= sent.timestamp:
    return checked
  return existing if checked.model_copy(update={"timestamp": existing.timestamp}) == existing else checked


def _source_bytes(s: Source) -> int:
  return len(s.model_dump_json().encode())


def _is_member_source(s: Source, person_prefix: str) -> bool:
  return s.id.startswith(person_prefix) and MEMBER_SOURCE_SEPARATOR in s.id


def _check_quota(p: Principal, store: GraphStore, sources: list[Source], member_bytes: int) -> None:
  if not (new := [s for s in sources if store.get_source(s.id) is None]):
    return
  namespace = f"{p.person_id}{MEMBER_SOURCE_SEPARATOR}"
  if sum(s.id.startswith(namespace) for s in store.sources()) + len(new) > MAX_MEMBER_SOURCES:
    raise HTTPException(429, "storage quota exceeded")
  if member_bytes + sum(_source_bytes(s) for s in new) > MAX_MEMBER_STORAGE_BYTES:
    raise HTTPException(429, "storage quota exceeded")


def _visible(p: Principal, esc: Escalation) -> bool:
  return p.role == "admin" or p.person_id in (esc.assignee_id, esc.raised_by)


def _public_uri(uri: str | None) -> str | None:
  if uri is None or uri.split(":", 1)[0].lower() in PUBLIC_URI_SCHEMES:
    return uri
  parts = [part for part in re.split(r"[\\/]+", uri.removeprefix("file:")) if part]
  if PUBLIC_URI_ROOT in parts:
    return "/".join(parts[parts.index(PUBLIC_URI_ROOT):])
  return parts[-1] if parts else ""


def _note_escalation(store: GraphStore, s: Source) -> Escalation | None:
  return store.get_escalation(s.escalation_id) if isinstance(s, NoteSource) and s.escalation_id else None


def _can_read(p: Principal, store: GraphStore, s: Source) -> bool:
  if p.role == "admin" or not isinstance(s, NoteSource) or s.escalation_id is None:
    return True
  return (esc := _note_escalation(store, s)) is not None and _visible(p, esc)


def _without_question(s: Source, esc: Escalation) -> Source:
  return s.model_copy(update={"title": REDACTED_NOTE_TITLE if esc.question in s.title else s.title,
                              "content": esc.resolution if esc.resolution and esc.resolution in s.content else ""})


def _public_source(p: Principal, store: GraphStore, s: Source) -> Source | None:
  if not _can_read(p, store, s):
    if (esc := _note_escalation(store, s)) is None:
      return None
    s = _without_question(s, esc)
  return s.model_copy(update={"uri": _public_uri(s.uri)})


def _public_ref(p: Principal, store: GraphStore, ref: SourceRef) -> SourceRef:
  if ref.quote is None or (s := store.get_source(ref.source_id)) is None or _can_read(p, store, s):
    return ref
  return ref.model_copy(update={"quote": None})


def _public_fact(p: Principal, store: GraphStore, f: Fact) -> Fact:
  return f.model_copy(update={"sources": [_public_ref(p, store, r) for r in f.sources]})


def _public_facts(p: Principal, store: GraphStore, views: list[FactView]) -> list[FactView]:
  return [v.model_copy(update={
    "fact": _public_fact(p, store, v.fact),
    "history": [_public_fact(p, store, f) for f in v.history],
    "sources": [r.model_copy(update={"ref": _public_ref(p, store, r.ref),
                                     "source": _public_source(p, store, r.source) if r.source else None})
                for r in v.sources]})
    for v in views]


def _public_report(report: IngestReport) -> IngestReport:
  return IngestReport(source_ids=list(report.source_ids), outcomes=[
    replace(o, error=EXTRACTION_FAILED) if o.error and o.error.startswith(EXTRACTION_FAILED) else o
    for o in report.outcomes])


def _public_gaps(p: Principal, store: GraphStore, gaps: Gaps) -> Gaps:
  return gaps.model_copy(update={
    "pending": [_public_fact(p, store, f) for f in gaps.pending],
    "stale": [_public_fact(p, store, f) for f in gaps.stale],
    "open_escalations": [e for e in gaps.open_escalations if _visible(p, e)]})


def _known_nodes(graph: KnowledgeGraph) -> list[Node]:
  known = graph._known_nodes() if hasattr(graph, "_known_nodes") else graph.store.nodes()
  return [n.model_copy(deep=True) for n in known[:MAX_KNOWN_ENTITIES]]


def _redact(p: Principal, store: GraphStore, view: NodeView) -> NodeView:
  return view.model_copy(update={
    "escalations": [e for e in view.escalations if _visible(p, e)],
    **{k: _public_facts(p, store, getattr(view, k))
       for k in ("current", "alternatives", "pending", "other_contexts", "incoming")}})


_bearer = HTTPBearer(auto_error=False)


def _principal(request: Request,
               creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]) -> Principal:
  registry: TokenRegistry = request.app.state.registry
  if creds is None or (p := registry.authenticate(creds.credentials)) is None:
    raise HTTPException(401, "invalid or missing bearer token", headers={"WWW-Authenticate": "Bearer"})
  prefix: str = request.app.state.person_prefix
  if not p.person_id.startswith(prefix) or len(p.person_id) == len(prefix) \
      or MEMBER_SOURCE_SEPARATOR in p.person_id:
    raise HTTPException(403, "token is not bound to a person id")
  return p


def _admin(p: Annotated[Principal, Depends(_principal)]) -> Principal:
  if p.role != "admin":
    raise HTTPException(403, "admin only")
  return p


def _rate_limited(wait: float) -> HTTPException:
  return HTTPException(429, "rate limit exceeded", headers={"Retry-After": str(max(1, math.ceil(wait)))})


def _throttle(window: SlidingWindow, p: Principal, cost: int = 1) -> None:
  if (wait := window.hit(p.person_id, cost)) is not None:
    raise _rate_limited(wait)


def _peek_all(p: Principal, charges: list[tuple[SlidingWindow, int]]) -> None:
  if waits := [w for window, cost in charges if (w := window.peek(p.person_id, cost)) is not None]:
    raise _rate_limited(max(waits))


def _check_all(p: Principal, charges: list[tuple[SlidingWindow, int]]) -> None:
  with _CHARGE_LOCK:
    _peek_all(p, charges)


def _throttle_all(p: Principal, charges: list[tuple[SlidingWindow, int]]) -> None:
  with _CHARGE_LOCK:
    _peek_all(p, charges)
    for window, cost in charges:
      _throttle(window, p, cost)


def _request_rate(request: Request, p: Annotated[Principal, Depends(_principal)]) -> None:
  _throttle(request.app.state.rate_limits.requests, p)


def _ask_rate(request: Request, p: Annotated[Principal, Depends(_principal)]) -> None:
  limits: RateLimits = request.app.state.rate_limits
  _throttle_all(p, [(limits.asks, 1), *([] if p.role == "admin" else [(limits.searches, 1)])])


def _search_rate(request: Request, p: Annotated[Principal, Depends(_principal)]) -> None:
  if p.role != "admin":
    _throttle(request.app.state.rate_limits.searches, p)


def _read_rate(request: Request, p: Annotated[Principal, Depends(_principal)]) -> None:
  _throttle(request.app.state.rate_limits.reads, p)


def _answer_rate(request: Request, p: Annotated[Principal, Depends(_principal)]) -> None:
  _throttle(request.app.state.rate_limits.answers, p)


User = Annotated[Principal, Depends(_principal)]
Admin = Annotated[Principal, Depends(_admin)]
Throttled = Depends(_request_rate)
AskThrottled = Depends(_ask_rate)
ReadThrottled = Depends(_read_rate)
AnswerThrottled = Depends(_answer_rate)


def create_app(graph: KnowledgeGraph, registry: TokenRegistry,
               on_change: Callable[[], None] | None = None,
               cors_origins: list[str] | None = None, rate_limits: RateLimits | None = None) -> FastAPI:
  app = FastAPI(title="tokg", description="TOKG: Temporal Ownership-Grounded Knowledge Graph",
                docs_url=None, redoc_url=None, openapi_url=None)
  if cors_origins:
    app.add_middleware(CORSMiddleware, allow_origins=cors_origins, allow_methods=["GET", "POST", "PUT"],
                       allow_headers=["Authorization", "Content-Type"])

  @app.middleware("http")
  async def _harden(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    if request.method in ("POST", "PUT", "PATCH"):
      length = request.headers.get("content-length")
      if length is None or not (length.isascii() and length.isdigit()):
        return JSONResponse({"detail": "content-length required"}, status_code=411)
      if int(length) > MAX_BODY_BYTES:
        return JSONResponse({"detail": "request body too large"}, status_code=413)
    response = await call_next(request)
    path = request.url.path
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    if path == "/app" or path.startswith("/app/"):
      response.headers["Content-Security-Policy"] = APP_CSP
    else:
      response.headers["Content-Security-Policy"] = API_CSP
      response.headers["Cache-Control"] = "no-store"
    return response
  app.state.registry = registry
  app.state.person_prefix = f"{graph.schema.owner_type.lower()}:"
  app.state.rate_limits = rate_limits or RateLimits()
  app.state.member_bytes = sum(_source_bytes(s) for s in graph.store.sources()
                               if _is_member_source(s, app.state.person_prefix))
  # the in-memory store is not thread-safe and FastAPI runs sync routes in a threadpool
  lock = threading.RLock()

  def changed() -> None:
    if on_change:
      on_change()

  @app.exception_handler(KeyError)
  def _not_found(_: Request, e: KeyError) -> JSONResponse:
    return JSONResponse({"detail": NOT_FOUND}, status_code=404)

  @app.exception_handler(PermissionError)
  def _forbidden(_: Request, e: PermissionError) -> JSONResponse:
    return JSONResponse({"detail": NOT_ALLOWED}, status_code=403)

  @app.exception_handler(ValueError)
  def _conflict(_: Request, e: ValueError) -> JSONResponse:
    if isinstance(e, ValidationError):
      return JSONResponse({"detail": "invalid data"}, status_code=422)
    return JSONResponse({"detail": CONFLICT}, status_code=409)

  @app.get("/health")
  def health() -> dict[str, str]:
    return {"status": "ok"}

  # the Recall web app is static; every data call it makes goes through the bearer-token API
  app.mount("/app", StaticFiles(directory=WEB, html=True), name="app")

  @app.get("/", include_in_schema=False)
  def root() -> RedirectResponse:
    return RedirectResponse("/app/")

  @app.get("/me", dependencies=[ReadThrottled])
  def me(p: User) -> Node | None:
    return graph.store.get_node(p.person_id)

  @app.get("/schema", dependencies=[ReadThrottled])
  def schema(_: User) -> Schema:
    return graph.schema

  @app.get("/nodes", dependencies=[ReadThrottled])
  def nodes(request: Request, p: User, type: Annotated[str | None, Query(max_length=64)] = None,
            q: Annotated[str | None, Query(max_length=500)] = None,
            limit: int = Query(20, ge=1, le=100)) -> list[Node]:
    if q:
      _search_rate(request, p)
    with lock:
      return graph.search(q, type_=type, limit=limit) if q else graph.store.nodes(type)[:limit]

  @app.get("/nodes/{node_id}", dependencies=[ReadThrottled])
  def view(p: User, node_id: Id, context: Annotated[list[str], Query()] = [],
           as_of: datetime | None = None) -> NodeView:
    with lock:
      return _redact(p, graph.store, graph.view(node_id, _parse_context(context), as_utc(as_of) if as_of else None))

  @app.post("/nodes/{node_id}/questions", dependencies=[Throttled])
  def ask_owner(request: Request, p: User, node_id: Id, body: QuestionRequest) -> Escalation:
    questions: SlidingWindow = request.app.state.rate_limits.questions
    with lock:
      _check_all(p, [(questions, 1)])
      esc = graph.ask_owner(node_id, body.question, asked_by=p.person_id)
      _throttle(questions, p)
      changed()
      return esc

  @app.put("/nodes/{node_id}/owner", dependencies=[Throttled])
  def assign_owner(p: Admin, node_id: Id, body: OwnerRequest) -> Fact:
    with lock:
      fact = graph.assign_owner(node_id, body.owner_id, assigned_by=p.person_id)
      changed()
      return fact

  @app.get("/facts/{fact_id}", dependencies=[ReadThrottled])
  def fact(p: User, fact_id: Id) -> Fact:
    with lock:
      if (f := graph.store.get_fact(fact_id)) is None:
        raise KeyError(f"no fact '{fact_id}'")
      return _public_fact(p, graph.store, f)

  @app.get("/sources/{source_id}", dependencies=[ReadThrottled])
  def source(p: User, source_id: Id) -> Source:
    with lock:
      if (s := graph.store.get_source(source_id)) is None or not _can_read(p, graph.store, s):
        raise KeyError(f"no source '{source_id}'")
      return _public_source(p, graph.store, s)

  def refuse_rewrites(sources: list[Source]) -> None:
    for s in sources:
      if (existing := graph.store.get_source(s.id)) is not None and existing != s:
        raise ValueError(f"source '{s.id}' already exists with different content")

  def extract(source: Source, known: list[Node]) -> list[ClaimDraft] | None:
    try:
      return graph.extractor.extract(source, graph.schema, known)
    except Exception:
      return None

  # members can only ingest as themselves: authorship decides whether a change needs owner
  # approval, so a forged author would bypass the ownership check
  @app.post("/ingest", dependencies=[Throttled])
  def ingest(request: Request, p: User, sources: Annotated[list[Source], Body(max_length=MAX_SOURCES)]) -> IngestReport:
    member = p.role != "admin"
    now = graph.clock()
    sent, sources = sources, [_check_source(p, s, now) for s in sources]
    if len({s.id for s in sources}) != len(sources):
      raise HTTPException(422, "duplicate source ids in one request")
    with lock:
      if member:
        sources = [_already_stored(graph.store, s, c) for s, c in zip(sent, sources)]
      refuse_rewrites(sources)
      if member:
        _check_quota(p, graph.store, sources, request.app.state.member_bytes)
      ordered = [s for s in sorted(sources, key=lambda s: s.timestamp) if graph.store.get_source(s.id) != s]
      if member and ordered:
        limits: RateLimits = request.app.state.rate_limits
        size = sum(len(s.model_dump_json().encode()) for s in ordered)
        _throttle_all(p, [(limits.ingested, len(ordered)),
                          (limits.ingested_bytes, max(1, math.ceil(size / BYTE_UNIT)))])
      known = _known_nodes(graph)
    with ThreadPoolExecutor(max_workers=EXTRACT_WORKERS) as pool:
      results = list(pool.map(lambda s: extract(s, known), ordered))
    with lock:
      refuse_rewrites(sources)
      if member:
        _check_quota(p, graph.store, sources, request.app.state.member_bytes)
      report = IngestReport()
      for s, drafts in zip(ordered, results):
        if graph.store.get_source(s.id) == s:
          report.outcomes.append(ClaimOutcome(s.id, error="already ingested"))
        elif drafts is None:
          report.outcomes.append(ClaimOutcome(s.id, error=EXTRACTION_FAILED))
        else:
          report.merge(graph.ingest_source(s, drafts=drafts, trust_speakers=not member))
          if _is_member_source(s, request.app.state.person_prefix):
            request.app.state.member_bytes += _source_bytes(s)
      if report.source_ids:
        changed()
      return _public_report(report)

  @app.post("/ask", dependencies=[Throttled, AskThrottled])
  def ask(p: User, body: AskRequest) -> AskResult:
    with lock:
      views = [graph.view(n.id, body.context).model_copy(deep=True)
               for n in graph.ask_hits(body.question, limit=ASK_LIMIT)]
      public = [_redact(p, graph.store, v) for v in views]
    try:
      answer = graph.answerer.answer(body.question, public)
    except Exception:
      answer = TemplateAnswerer().answer(body.question, public)
    return AskResult(question=body.question, answer=answer, views=public)

  @app.get("/escalations", dependencies=[ReadThrottled])
  def escalations(p: User, mine: bool = False, status: EscalationStatus | None = None) -> list[Escalation]:
    with lock:
      return [e for e in graph.store.escalations() if _visible(p, e)
              and (not mine or e.assignee_id == p.person_id) and (status is None or e.status == status)]

  def visible_escalation(p: Principal, escalation_id: str) -> Escalation:
    if (esc := graph.store.get_escalation(escalation_id)) is None or not _visible(p, esc):
      raise KeyError(f"no escalation '{escalation_id}'")
    return esc

  @app.post("/escalations/{escalation_id}/resolve", dependencies=[Throttled])
  def resolve(p: User, escalation_id: EscalationId, body: VerdictRequest) -> Escalation:
    with lock:
      visible_escalation(p, escalation_id)
      esc = graph.resolve_escalation(escalation_id, p.person_id, body.verdict, body.note)
      changed()
      return esc

  @app.post("/escalations/{escalation_id}/answer", dependencies=[Throttled, AnswerThrottled])
  def answer(p: User, escalation_id: EscalationId, body: AnswerRequest) -> IngestReport:
    with lock:
      visible_escalation(p, escalation_id)
      plan = graph.prepare_answer(escalation_id, p.person_id, body.answer)
    try:
      drafts = graph.extract_answer(plan)
    except Exception:
      with lock:
        changed()
      return IngestReport(outcomes=[ClaimOutcome(plan.source.id, error=EXTRACTION_FAILED)])
    with lock:
      visible_escalation(p, escalation_id)
      report = graph.commit_answer(plan, drafts)
      changed()
      return _public_report(report)

  @app.get("/gaps", dependencies=[ReadThrottled])
  def gaps(p: User) -> Gaps:
    with lock:
      return _public_gaps(p, graph.store, graph.gaps())

  return app
