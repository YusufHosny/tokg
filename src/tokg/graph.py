# ABOUTME: KnowledgeGraph: the manager that owns all mutation and queries. Runs the ingest pipeline
# ABOUTME: (extract -> materialize -> resolve -> apply), escalations, and context/time-aware views.
import re
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.utils import parseaddr
from itertools import groupby
from typing import Literal, assert_never

from tokg.answer import Answerer, LLMAnswerer
from tokg.extract import ClaimDraft, EntityMention, Extractor, LLMExtractor
from tokg.models import (
  AttributeStatement, Claim, Escalation, Fact, Node, NoteSource, OwnershipStatement,
  RelationStatement, Source, SourceRef, Statement, as_utc, slugify, utcnow,
)
from tokg.resolve import Decision, ResolutionInput, Resolver, RuleResolver
from tokg.schema import Schema
from tokg.seed import Seed
from tokg.store import GraphStore, MemoryStore
from tokg.views import AskResult, Contact, FactView, Gaps, NodeView, SourcedRef, Trust

Verdict = Literal["approve", "reject"]

_STOPWORDS = frozenset(
  "the and for with that this what how who when where which does need our are can from have "
  "has was were will just about into there their them they you your any all not but".split())


@dataclass
class ClaimOutcome:
  claim_id: str
  decision: Decision | None = None
  error: str | None = None


@dataclass
class IngestReport:
  source_ids: list[str] = field(default_factory=list)
  outcomes: list[ClaimOutcome] = field(default_factory=list)

  def merge(self, other: "IngestReport") -> None:
    self.source_ids += other.source_ids
    self.outcomes += other.outcomes

  @property
  def skipped(self) -> list[ClaimOutcome]:
    return [o for o in self.outcomes if o.error is not None]


_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _tokens(text: str) -> set[str]:
  # crude stemming by truncation is enough for keyword retrieval in a POC
  return {w[:6] for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2 and w not in _STOPWORDS}


class KnowledgeGraph:
  def __init__(self, schema: Schema, store: GraphStore | None = None,
               extractor: Extractor | None = None, resolver: Resolver | None = None,
               answerer: Answerer | None = None, seed: Seed | None = None,
               enforce_ownership: bool = True, clock: Callable[[], datetime] = utcnow) -> None:
    self.schema = schema
    self.store = store or MemoryStore()
    self.extractor = extractor or LLMExtractor()
    self.resolver = resolver or RuleResolver()
    self.answerer = answerer or LLMAnswerer()
    # when on, no resolver (LLM or scripted) can supersede an owned fact on a non-owner's word
    self.enforce_ownership = enforce_ownership
    self.clock = clock
    self.seed = seed or Seed()
    self._bootstrap()

  # -------------------------------------------------------------------------------------------
  # bootstrap: idempotent, so it can run on every start against a restored snapshot

  def _bootstrap(self) -> None:
    for t in self.seed.topics:
      if self.schema.entity(t.type) is None:
        raise ValueError(f"seed topic '{t.key}' has unknown type '{t.type}'")
      node_id = Node.make_id(t.type, t.key)
      if self.store.get_node(node_id) is None:
        self.store.put_node(Node(id=node_id, type=t.type, name=t.name, aliases=[t.key, *t.aliases],
                                 description=t.description, created_at=self.clock()))
    topics = {t.key: Node.make_id(t.type, t.key) for t in self.seed.topics}
    seed_source = NoteSource(id="note:seed", title="Bootstrap ownership", author="seed",
                             timestamp=_EPOCH, content="Initial owners assigned at bootstrap.")
    for p in self.seed.people:
      person = self._ensure_person(f"{p.name} <{p.id}>")
      props = {"role": p.role or "", "external": str(p.external).lower()}
      if person.properties != props or person.name != p.name:
        person.name, person.properties = p.name, props
        self.store.put_node(person)
      for key in p.owns:
        if key not in topics:
          raise ValueError(f"{p.id} owns unknown seed topic '{key}'")
        node_id = topics[key]
        if self.owner_of(node_id) is not None:
          continue  # ownership is managed by the graph once set
        self.store.put_source(seed_source)
        self.store.put_fact(Fact(
          id=f"seed:{node_id}", subject_id=node_id, statement=OwnershipStatement(owner_id=person.id),
          valid_from=_EPOCH, recorded_at=self.clock(), sources=[SourceRef(source_id=seed_source.id)],
          confirmed_by=person.id, rationale="Bootstrap owner."))

  # -------------------------------------------------------------------------------------------
  # ingestion

  # extraction is independent per source, so it runs in parallel (LLM calls dominate); resolution
  # stays sequential and chronological because each claim is judged against the graph so far
  def ingest(self, sources: Iterable[Source], workers: int = 8) -> IngestReport:
    ordered = [s for s in sorted(sources, key=lambda s: s.timestamp) if self.store.get_source(s.id) != s]
    known = self.store.nodes()
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
      drafts = list(pool.map(lambda s: self.extractor.extract(s, self.schema, known), ordered))
    report = IngestReport()
    for source, d in zip(ordered, drafts):
      report.merge(self.ingest_source(source, drafts=d))
    return report

  def ingest_source(self, source: Source, drafts: list[ClaimDraft] | None = None) -> IngestReport:
    report = IngestReport(source_ids=[source.id])
    # sources are immutable evidence: re-ingesting is fine, rewriting one is not
    if (existing := self.store.get_source(source.id)) is not None and existing != source:
      raise ValueError(f"source '{source.id}' already exists with different content")
    self.store.put_source(source)
    author_id = None if self.seed.is_non_person(source.author) else self._ensure_person(source.author).id
    if drafts is None:
      drafts = self.extractor.extract(source, self.schema, self.store.nodes())
    for i, draft in enumerate(drafts):
      claim_id = f"{source.id}:{i}"
      if self.store.get_fact(claim_id) is not None:
        report.outcomes.append(ClaimOutcome(claim_id, error="already ingested"))
        continue
      claim = self._materialize(claim_id, draft, source, author_id)
      if isinstance(claim, str):
        report.outcomes.append(ClaimOutcome(claim_id, error=claim))
        continue
      decision = self._resolve(claim)
      self._apply(claim, decision)
      report.outcomes.append(ClaimOutcome(claim_id, decision=decision))
    return report

  # validate everything before creating nodes, so a bad claim leaves no debris behind
  def _materialize(self, claim_id: str, d: ClaimDraft, source: Source, author_id: str | None) -> Claim | str:
    if self.schema.entity(d.subject.type) is None:
      return f"unknown entity type '{d.subject.type}'"
    if err := self.schema.check_context(d.context):
      return err
    match d.kind:
      case "attribute":
        if d.attribute is None or d.value is None:
          return "attribute claim needs attribute and value"
        if err := self.schema.check_attribute(d.subject.type, d.attribute):
          return err
      case "relation":
        if d.relation is None or d.target is None:
          return "relation claim needs relation and target"
        if err := self.schema.check_relation(d.relation, d.subject.type, d.target.type):
          return err
      case "ownership":
        if not d.owner:
          return "ownership claim needs an owner"
        if self.seed.is_non_person(d.owner):
          return f"'{d.owner}' is a system, not a person, and cannot own knowledge"
      case _:
        assert_never(d.kind)

    subject = self._ensure_node(d.subject)
    statement: Statement
    match d.kind:
      case "attribute":
        assert d.attribute is not None and d.value is not None
        statement = AttributeStatement(attribute=d.attribute, value=d.value)
      case "relation":
        assert d.relation is not None and d.target is not None
        statement = RelationStatement(relation=d.relation, target_id=self._ensure_node(d.target).id)
      case "ownership":
        assert d.owner is not None
        statement = OwnershipStatement(owner_id=self._ensure_person(d.owner).id)
      case _:
        assert_never(d.kind)
    return Claim(id=claim_id, subject_id=subject.id, statement=statement,
                 context=self._normalize_context(d.context, create=True),
                 valid_from=as_utc(d.valid_from) if d.valid_from else source.timestamp,
                 source=SourceRef(source_id=source.id, quote=d.quote),
                 asserted_by=self._speaker(d, source) or author_id)

  # the extractor may credit a statement to someone other than the author (a decision in a bot's
  # meeting summary), but only to a known person who took part in that source
  def _speaker(self, d: ClaimDraft, source: Source) -> str | None:
    if not d.asserted_by or self.seed.is_non_person(d.asserted_by):
      return None
    speaker = self._find_person(d.asserted_by)
    participants = {p.id for ref in source.participants() if (p := self._find_person(ref))}
    return speaker.id if speaker and speaker.id in participants else None

  def _authoritative(self, asserted_by: str | None, owner_id: str | None) -> bool:
    if owner_id is None:
      return True
    authorities = {p.id for a in self.seed.authorities if (p := self._find_person(a))}
    return asserted_by is not None and (asserted_by == owner_id or asserted_by in authorities)

  def _resolve(self, claim: Claim) -> Decision:
    slot = (claim.subject_id, *claim.statement.slot())
    candidates = [f for f in self.store.facts(subject_id=claim.subject_id)
                  if f.slot == slot and (f.status == "pending" or (f.status == "active" and f.valid_to is None))]
    subject = self.store.get_node(claim.subject_id)
    assert subject is not None
    owner_id = self.owner_of(claim.subject_id)
    authoritative = self._authoritative(claim.asserted_by, owner_id)
    decision = self.resolver.resolve(ResolutionInput(
      claim=claim, subject=subject, candidates=candidates, owner_id=owner_id,
      authoritative=authoritative, schema=self.schema))
    if self.enforce_ownership and decision.action == "supersede" and not authoritative:
      return Decision(action="escalate", target_fact_ids=decision.target_fact_ids,
                      rationale=f"{decision.rationale} Not asserted by the owner or an authority, "
                                "so it needs approval.",
                      question=f"Approve '{claim.statement.describe()}' for {subject.name}?")
    return decision

  def _apply(self, claim: Claim, decision: Decision) -> None:
    owner_id = self.owner_of(claim.subject_id)
    confirmed_by = (claim.asserted_by if owner_id is not None
                    and self._authoritative(claim.asserted_by, owner_id) else None)
    targets = decision.target_fact_ids
    match decision.action:
      case "create":
        self.store.put_fact(Fact.from_claim(claim, "active", decision.rationale).model_copy(
          update={"confirmed_by": confirmed_by}))
      case "supersede":
        fact = Fact.from_claim(claim, "active", decision.rationale, supersedes=targets).model_copy(
          update={"confirmed_by": confirmed_by})
        self.store.put_fact(fact)
        self._close(targets, fact)
      case "confirm":
        for fact in self._facts(targets):
          fact.sources.append(claim.source)
          fact.confirmed_by = fact.confirmed_by or confirmed_by
          self.store.put_fact(fact)
      case "conflict" | "escalate":
        fact = Fact.from_claim(claim, "pending", decision.rationale, supersedes=targets)
        self.store.put_fact(fact)
        self.store.put_escalation(Escalation(
          id=f"esc:{fact.id}", reason="conflict" if decision.action == "conflict" else "approval",
          subject_id=claim.subject_id, question=decision.question or decision.rationale,
          assignee_id=owner_id, fact_id=fact.id, related_fact_ids=targets,
          raised_by=claim.asserted_by, created_at=self.clock()))
      case "ignore":
        pass
      case _:
        assert_never(decision.action)

  def _close(self, fact_ids: list[str], by: Fact) -> None:
    for fact in self._facts(fact_ids):
      if fact.status == "active" and fact.valid_to is None:
        fact.valid_to = max(by.valid_from, fact.valid_from)
        fact.superseded_by = by.id
        self.store.put_fact(fact)

  def _facts(self, fact_ids: list[str]) -> list[Fact]:
    return [f for i in fact_ids if (f := self.store.get_fact(i)) is not None]

  # -------------------------------------------------------------------------------------------
  # entities

  def _ensure_node(self, mention: EntityMention) -> Node:
    if mention.type == self.schema.owner_type:
      return self._ensure_person(mention.name)
    if (node := self.store.get_node(mention.name)) is not None and node.type == mention.type:
      return node
    if node := next((n for n in self.store.nodes(mention.type) if n.matches(mention.name)), None):
      return node
    node = Node(id=Node.make_id(mention.type, mention.name), type=mention.type, name=mention.name,
                created_at=self.clock())
    self.store.put_node(node)
    return node

  # lookup only: never creates people from recipients like distribution lists
  def _find_person(self, ref: str) -> Node | None:
    ptype = self.schema.owner_type
    if (node := self.store.get_node(ref)) is not None and node.type == ptype:
      return node
    name, addr = parseaddr(ref) if "@" in ref else (ref, "")
    name, addr = name.strip(), addr.strip().lower()
    people = self.store.nodes(ptype)
    return next((p for p in people if addr and addr in p.aliases), None) or \
           next((p for p in people if name and p.matches(name)), None)

  # people are matched by node id, then email alias, then name
  def _ensure_person(self, ref: str) -> Node:
    ptype = self.schema.owner_type
    if (node := self.store.get_node(ref)) is not None and node.type == ptype:
      return node
    # an id of a person we have not seen yet (e.g. an authenticated API user): keep the id verbatim
    if ref.startswith(prefix := f"{ptype.lower()}:"):
      node = Node(id=ref, type=ptype, name=ref.removeprefix(prefix), created_at=self.clock())
      self.store.put_node(node)
      return node
    name, addr = parseaddr(ref) if "@" in ref else (ref, "")
    name, addr = name.strip(), addr.strip().lower()
    people = self.store.nodes(ptype)
    node = next((p for p in people if addr and addr in p.aliases), None) or \
           next((p for p in people if name and p.matches(name)), None)
    if node is None:
      node = Node(id=Node.make_id(ptype, addr or name), type=ptype, name=name or addr,
                  aliases=[addr] if addr else [], created_at=self.clock())
      self.store.put_node(node)
    elif addr and addr not in node.aliases:
      node.aliases.append(addr)
      self.store.put_node(node)
    return node

  # context values of entity-backed dimensions become node ids (e.g. client=Acme -> client:acme)
  def _normalize_context(self, context: dict[str, str], create: bool) -> dict[str, str]:
    out = {}
    for key, value in context.items():
      dim = self.schema.dimension(key)
      if dim is None or dim.entity is None:
        out[key] = value
        continue
      mention = EntityMention(type=dim.entity, name=value)
      if create:
        out[key] = self._ensure_node(mention).id
      else:
        found = self.store.get_node(value) or next(
          (n for n in self.store.nodes(dim.entity) if n.matches(value)), None)
        out[key] = found.id if found else value
    return out

  def owner_of(self, node_id: str, as_of: datetime | None = None) -> str | None:
    as_of = as_of or self.clock()
    owned = [f for f in self.store.facts(subject_id=node_id)
             if isinstance(f.statement, OwnershipStatement) and f.is_current(as_of)]
    if not owned:
      return None
    latest = max(owned, key=lambda f: f.valid_from).statement
    assert isinstance(latest, OwnershipStatement)
    return latest.owner_id

  # -------------------------------------------------------------------------------------------
  # human oversight

  def _open_escalation(self, escalation_id: str) -> Escalation:
    esc = self.store.get_escalation(escalation_id)
    if esc is None:
      raise KeyError(f"no escalation '{escalation_id}'")
    if esc.status != "open":
      raise ValueError(f"escalation '{escalation_id}' is already {esc.status}")
    return esc

  @staticmethod
  def _authorize(esc: Escalation, actor_id: str) -> None:
    if esc.assignee_id is None:
      raise PermissionError(f"escalation '{esc.id}' has no assignee; assign an owner first")
    if actor_id != esc.assignee_id:
      raise PermissionError(f"only {esc.assignee_id} can act on escalation '{esc.id}'")

  def resolve_escalation(self, escalation_id: str, actor_id: str, verdict: Verdict,
                         note: str | None = None) -> Escalation:
    esc = self._open_escalation(escalation_id)
    self._authorize(esc, actor_id)
    if esc.fact_id is None or (fact := self.store.get_fact(esc.fact_id)) is None:
      raise ValueError(f"escalation '{esc.id}' has no pending fact; answer it instead")
    match verdict:
      case "approve":
        fact.status, fact.confirmed_by = "active", actor_id
        self.store.put_fact(fact)
        self._close(esc.related_fact_ids, fact)
        esc.status = "approved"
      case "reject":
        fact.status = "rejected"
        self.store.put_fact(fact)
        esc.status = "rejected"
      case _:
        assert_never(verdict)
    esc.resolved_at, esc.resolved_by, esc.resolution = self.clock(), actor_id, note
    self.store.put_escalation(esc)
    return esc

  def ask_owner(self, node_id: str, question: str, asked_by: str) -> Escalation:
    if self.store.get_node(node_id) is None:
      raise KeyError(f"no node '{node_id}'")
    prefix = f"esc:q:{slugify(node_id)}:"
    n = sum(e.id.startswith(prefix) for e in self.store.escalations())
    esc = Escalation(id=f"{prefix}{n}", reason="question", subject_id=node_id, question=question,
                     assignee_id=self.owner_of(node_id), raised_by=asked_by, created_at=self.clock())
    self.store.put_escalation(esc)
    return esc

  # the answer becomes a source and flows through the normal pipeline, so the next person
  # asking gets it from the graph instead of from the owner
  def answer_escalation(self, escalation_id: str, actor_id: str, answer: str) -> IngestReport:
    esc = self._open_escalation(escalation_id)
    self._authorize(esc, actor_id)
    esc.status, esc.resolution = "answered", answer
    esc.resolved_at, esc.resolved_by = self.clock(), actor_id
    self.store.put_escalation(esc)
    subject = self.store.get_node(esc.subject_id)
    source = NoteSource(id=f"note:{esc.id}", title=f"Answer: {esc.question}", author=actor_id,
                        timestamp=self.clock(), escalation_id=esc.id,
                        content=f"About {subject.name if subject else esc.subject_id}.\n"
                                f"Q: {esc.question}\nA: {answer}")
    return self.ingest_source(source)

  # admin action: makes a node owned, and hands its unassigned escalations to the new owner
  def assign_owner(self, node_id: str, owner_id: str, assigned_by: str) -> Fact:
    if self.store.get_node(node_id) is None:
      raise KeyError(f"no node '{node_id}'")
    owner = self._ensure_person(owner_id)
    now = self.clock()
    prefix = f"note:assign:{slugify(node_id)}:"
    n = sum(s.id.startswith(prefix) for s in self.store.sources())
    source = NoteSource(id=f"{prefix}{n}", title=f"Owner assignment for {node_id}", author=assigned_by,
                        timestamp=now, content=f"{assigned_by} assigned {owner.id} as owner of {node_id}.")
    self.store.put_source(source)
    claim = Claim(id=f"{source.id}:0", subject_id=node_id, statement=OwnershipStatement(owner_id=owner.id),
                  valid_from=now, source=SourceRef(source_id=source.id), asserted_by=assigned_by)
    previous = [f.id for f in self.store.facts(subject_id=node_id)
                if isinstance(f.statement, OwnershipStatement) and f.status == "active" and f.valid_to is None]
    fact = Fact.from_claim(claim, "active", "Assigned by an administrator.", supersedes=previous)
    fact.confirmed_by = owner.id
    self.store.put_fact(fact)
    self._close(previous, fact)
    for esc in self.store.escalations():
      if esc.subject_id == node_id and esc.status == "open" and esc.assignee_id is None:
        esc.assignee_id = owner.id
        self.store.put_escalation(esc)
    return fact

  # -------------------------------------------------------------------------------------------
  # queries

  def _fact_view(self, fact: Fact) -> FactView:
    trust: Trust = "pending" if fact.status == "pending" else (
      "confirmed" if fact.confirmed_by else "unconfirmed")
    history, frontier = [], list(fact.supersedes)
    while frontier:
      if (old := self.store.get_fact(frontier.pop(0))) is not None and old not in history:
        history.append(old)
        frontier += old.supersedes
    return FactView(fact=fact, trust=trust,
                    sources=[SourcedRef(ref=r, source=self.store.get_source(r.source_id)) for r in fact.sources],
                    history=sorted(history, key=lambda f: f.valid_from, reverse=True))

  def view(self, node_id: str, context: dict[str, str] | None = None,
           as_of: datetime | None = None) -> NodeView:
    node = self.store.get_node(node_id)
    if node is None:
      raise KeyError(f"no node '{node_id}'")
    as_of = as_of or self.clock()
    ctx = self._normalize_context(context or {}, create=False)
    facts = self.store.facts(subject_id=node_id)
    live = [f for f in facts if f.is_current(as_of)]
    applicable = [f for f in live if f.applies_to(ctx)]

    # per slot: the most recent applicable fact wins, the most specific breaks ties
    current, alternatives = [], []
    ranked = sorted(applicable, key=lambda f: (f.slot, f.valid_from, len(f.context)), reverse=True)
    for _, group in groupby(ranked, key=lambda f: f.slot):
      winner, *rest = list(group)
      current.append(winner)
      alternatives += rest

    owner_id = self.owner_of(node_id, as_of)
    owner = self.store.get_node(owner_id) if owner_id else None
    incoming = [f for f in self.store.facts(target_id=node_id) if f.is_current(as_of)]
    return NodeView(
      node=node, owner=owner, context=ctx,
      current=[self._fact_view(f) for f in sorted(current, key=lambda f: f.slot)],
      alternatives=[self._fact_view(f) for f in alternatives],
      pending=[self._fact_view(f) for f in facts if f.status == "pending"],
      other_contexts=[self._fact_view(f) for f in live if not f.applies_to(ctx)],
      incoming=[self._fact_view(f) for f in incoming],
      contacts=self._contacts(node, owner, ctx, incoming, as_of),
      escalations=[e for e in self.store.escalations() if e.subject_id == node_id and e.status == "open"],
    )

  def _contacts(self, node: Node, owner: Node | None, ctx: dict[str, str], incoming: list[Fact],
                as_of: datetime) -> list[Contact]:
    contacts: dict[str, Contact] = {}

    def add(person_id: str | None, role: str) -> None:
      if person_id and person_id not in contacts and (p := self.store.get_node(person_id)):
        contacts[person_id] = Contact(person=p, role=role)

    if owner:
      add(owner.id, f"owner of {node.type} '{node.name}'")
    for key, value in ctx.items():
      if (dim := self.schema.dimension(key)) and dim.entity and (ctx_node := self.store.get_node(value)):
        add(self.owner_of(ctx_node.id, as_of), f"owner of {dim.entity} '{ctx_node.name}' ({key})")
    for fact in incoming:
      if related := self.store.get_node(fact.subject_id):
        add(self.owner_of(related.id, as_of), f"owner of related {related.type} '{related.name}'")
    return list(contacts.values())

  def search(self, text: str, type_: str | None = None, limit: int = 5,
             as_of: datetime | None = None) -> list[Node]:
    as_of = as_of or self.clock()
    query = _tokens(text)
    scored = []
    for node in self.store.nodes(type_):
      if node.type == self.schema.owner_type and type_ is None:
        continue
      names = _tokens(" ".join([node.name, *node.aliases]))
      values = _tokens(" ".join(f.statement.value for f in self.store.facts(subject_id=node.id)
                                if isinstance(f.statement, AttributeStatement) and f.is_current(as_of)))
      if score := 3 * len(query & names) + len(query & values):
        scored.append((score, node.name, node))
    return [n for *_, n in sorted(scored, key=lambda t: (-t[0], t[1]))[:limit]]

  def ask(self, question: str, context: dict[str, str] | None = None, limit: int = 3) -> AskResult:
    views = [self.view(n.id, context) for n in self.search(question, limit=limit)]
    return AskResult(question=question, answer=self.answerer.answer(question, views), views=views)

  def gaps(self, stale_after: timedelta = timedelta(days=365), as_of: datetime | None = None) -> Gaps:
    as_of = as_of or self.clock()
    facts = self.store.facts()
    return Gaps(
      unowned=[n for n in self.store.nodes()
               if n.type != self.schema.owner_type and self.owner_of(n.id, as_of) is None],
      pending=[f for f in facts if f.status == "pending"],
      stale=[f for f in facts if f.is_current(as_of) and f.valid_to is None
             and isinstance(f.statement, AttributeStatement) and f.valid_from < as_of - stale_after],
      open_escalations=[e for e in self.store.escalations() if e.status == "open"],
    )
