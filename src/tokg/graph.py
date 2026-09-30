# ABOUTME: KnowledgeGraph: the manager that owns all mutation and queries. Runs the ingest pipeline
# ABOUTME: (extract -> materialize -> resolve -> apply), escalations, and context/time-aware views.
import hashlib
import re
from collections.abc import Callable, Collection, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.utils import parseaddr
from itertools import groupby, islice
from typing import Literal, assert_never

from pydantic import ValidationError

from tokg.answer import Answerer, LLMAnswerer
from tokg.extract import MAX_KNOWN_ENTITIES, ClaimDraft, EntityMention, Extractor, LLMExtractor
from tokg.llm import fence
from tokg.models import (
  MAX_NAME, AttributeStatement, Claim, Escalation, Fact, Node, NoteSource, OwnershipStatement,
  RelationStatement, Source, SourceRef, Statement, as_utc, slugify, utcnow,
)
from tokg.resolve import Decision, DecisionAction, ResolutionInput, Resolver, RuleResolver
from tokg.schema import Schema
from tokg.seed import Seed
from tokg.store import GraphStore, MemoryStore
from tokg.views import AskResult, Contact, FactView, Gaps, NodeView, SourcedRef, Trust

Verdict = Literal["approve", "reject"]

_STOPWORDS = frozenset(
  "the and for with that this what how who when where which does need our are can from have "
  "has was were will just about into there their them they you your any all not but".split())
_NEGATIONS = frozenset("no not never dont don't without cannot cant".split())
_CONFUSABLES = str.maketrans("01|i53478", "olllseatb")


@dataclass
class ClaimOutcome:
  claim_id: str
  decision: Decision | None = None
  error: str | None = None


@dataclass
class AnswerPlan:
  escalation_id: str
  actor_id: str
  answer: str
  source: NoteSource
  known: list[Node]


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
MAX_OPEN_ESCALATIONS_PER_AUTHOR = 20
MAX_UNTRUSTED_CLAIMS_PER_SOURCE = 20
MAX_UNTRUSTED_NEW_NODES_PER_SOURCE = 3
MAX_UNTRUSTED_ID = 256
MAX_UNTRUSTED_BACKDATE = timedelta(days=3652)
MAX_GAPS_UNOWNED = 200
MAX_ID_SLUG = 200
MIN_ANSWER_QUOTE = 12
MEMBER_NAME = re.compile(r"[A-Za-z0-9 _.,'&()/:-]+")
SOURCE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@+-]{0,199}")
RESERVED_SOURCE_PREFIXES = ("note:", "seed:", "esc:", "q:")

LookalikeIndex = dict[tuple[str, str], str]


@dataclass
class MemberBudget:
  lookalikes: LookalikeIndex
  new_nodes: int = 0


def _id_slug(node_id: str) -> str:
  slug = slugify(node_id)
  return slug if len(slug) <= MAX_ID_SLUG else \
    f"{slug[:MAX_ID_SLUG]}-{hashlib.sha256(node_id.encode()).hexdigest()[:12]}"


def _normalized(text: str) -> str:
  return " ".join(text.split()).casefold()


def _tokens(text: str) -> set[str]:
  # crude stemming by truncation is enough for keyword retrieval in a POC
  return {w[:6] for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2 and w not in _STOPWORDS}


def _words(text: str) -> set[str]:
  return set(re.findall(r"[^\W_]+", text.casefold()))


def _negations(text: str) -> set[str]:
  return _NEGATIONS & set(re.findall(r"[^\W_]+(?:'[^\W_]+)*", text.casefold().replace("’", "'")))


def _lookalike_key(name: str) -> str:
  folded = name.casefold().translate(_CONFUSABLES).replace("rn", "m").replace("vv", "w")
  return re.sub(r"[^a-z0-9]+", "", folded)


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
      person = self._ensure_person(f"{p.name} <{p.id}>", adopt=True)
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
  def ingest(self, sources: Iterable[Source], workers: int = 8, trust_speakers: bool = True) -> IngestReport:
    report, ordered = IngestReport(), []
    for source in sorted(sources, key=lambda s: s.timestamp):
      if err := self._batch_error(source, trust_speakers):
        report.outcomes.append(ClaimOutcome(source.id, error=err))
      elif self._conflicts(source):
        report.outcomes.append(ClaimOutcome(source.id, error="source id conflict"))
      elif self.store.get_source(source.id) != source:
        ordered.append(source)
    known = self._known_nodes()
    # a failed extraction (LLM timeout, outage) must not sink the batch: the source is left
    # unstored, so the next run retries exactly the sources that failed
    def extract(source: Source) -> list[ClaimDraft] | str:
      try:
        return self.extractor.extract(source, self.schema, known)
      except Exception as e:
        return f"extraction failed: {type(e).__name__}: {e}"

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
      results = list(pool.map(extract, ordered))
    for source, result in zip(ordered, results):
      if isinstance(result, str):
        report.outcomes.append(ClaimOutcome(source.id, error=result))
        continue
      if self._conflicts(source):
        report.outcomes.append(ClaimOutcome(source.id, error="source id conflict"))
        continue
      report.merge(self.ingest_source(source, drafts=result, trust_speakers=trust_speakers))
    return report

  def ingest_source(self, source: Source, drafts: list[ClaimDraft] | None = None,
                    trust_speakers: bool = True,
                    screen: Callable[[ClaimDraft], str | None] | None = None) -> IngestReport:
    report = IngestReport(source_ids=[source.id])
    # sources are immutable evidence: re-ingesting is fine, rewriting one is not
    if self._conflicts(source):
      raise ValueError(f"source '{source.id}' already exists with different content")
    self.store.put_source(source)
    author_id = None if self.seed.is_non_person(source.author) else self._ensure_person(source.author).id
    if drafts is None:
      drafts = self.extractor.extract(source, self.schema, self._known_nodes())
    budget = None if trust_speakers else MemberBudget(self._lookalike_index())
    for i, draft in enumerate(drafts):
      claim_id = f"{source.id}:{i}"
      if self.store.get_fact(claim_id) is not None:
        report.outcomes.append(ClaimOutcome(claim_id, error="already ingested"))
        continue
      if screen is not None and (err := screen(draft)):
        report.outcomes.append(ClaimOutcome(claim_id, error=err))
        continue
      if not trust_speakers and (err := self._flood_error(i, author_id)):
        report.outcomes.append(ClaimOutcome(claim_id, error=err))
        continue
      try:
        claim = self._materialize(claim_id, draft, source, author_id, trust_speakers, budget)
      except ValidationError as e:
        claim = f"invalid claim: {e.error_count()} validation error(s)"
      except ValueError:
        claim = "invalid claim"
      if isinstance(claim, str):
        report.outcomes.append(ClaimOutcome(claim_id, error=claim))
        continue
      try:
        decision = self._resolve(claim, author_id, trust_speakers)
        self._apply(claim, decision, author_id, trust_speakers)
      except Exception:
        report.outcomes.append(ClaimOutcome(claim_id, error="resolution failed"))
        continue
      report.outcomes.append(ClaimOutcome(claim_id, decision=decision))
    if trust_speakers and not self._squat_source(source.id):
      self._hold_squats(report)
    return report

  def _hold_squats(self, report: IngestReport) -> None:
    since: dict[str, datetime] = {}
    for o in report.outcomes:
      if o.decision and o.decision.action in ("create", "supersede") and (f := self.store.get_fact(o.claim_id)):
        written = self._written(f)
        since[f.subject_id] = min(since.get(f.subject_id, written), written)
    topics = {t.type for t in self.seed.topics}
    for subject_id, valid_from in since.items():
      node = self.store.get_node(subject_id)
      topic = node is not None and node.type in topics
      if (owner_id := self.owner_of(subject_id)) is None and not topic:
        continue
      for f in self.store.facts(subject_id=subject_id):
        if self._squat_fact(f) and f.confirmed_by is None and (topic or self._written(f) > valid_from) \
            and not isinstance(f.statement, OwnershipStatement):
          f.status = "pending"
          self.store.put_fact(f)
          self.store.put_escalation(Escalation(
            id=self._next_id(f"esc:{f.id}:", lambda i: self.store.get_escalation(i) is not None),
            reason="approval", subject_id=subject_id,
            question=f"Approve '{f.statement.describe()}'? It was added after the owner's source without "
                     "their confirmation.",
            assignee_id=owner_id, fact_id=f.id, raised_by=None, created_at=self.clock()))

  def _batch_error(self, source: Source, trust_speakers: bool) -> str | None:
    if not SOURCE_ID.fullmatch(source.id) or source.id.startswith(RESERVED_SOURCE_PREFIXES):
      return "invalid or reserved source id"
    if source.kind == "note":
      return "note sources are written by the graph itself"
    return "member source id" if trust_speakers and self._member_source(source.id) else None

  def _conflicts(self, source: Source) -> bool:
    return (existing := self.store.get_source(source.id)) is not None and existing != source

  def _seeded_ids(self) -> set[str]:
    return {Node.make_id(t.type, t.key) for t in self.seed.topics}

  def _known_nodes(self) -> list[Node]:
    seeded = self._seeded_ids()
    return sorted(self.store.nodes(), key=lambda n: (n.id not in seeded, self._member_tainted(n.id),
                                                     -n.created_at.timestamp()))

  def _lookalike_index(self) -> LookalikeIndex:
    index: LookalikeIndex = {}
    for n in self.store.nodes():
      for name in (n.name, *n.aliases):
        if key := _lookalike_key(name):
          index.setdefault((n.type, key), n.id)
    return index

  def _flood_error(self, index: int, author_id: str | None) -> str | None:
    if index >= MAX_UNTRUSTED_CLAIMS_PER_SOURCE:
      return "too many claims in one source"
    open_count = sum(1 for e in self.store.escalations() if e.status == "open" and e.raised_by == author_id)
    return "too many open escalations" if author_id and open_count >= MAX_OPEN_ESCALATIONS_PER_AUTHOR else None

  # validate everything before creating nodes, so a bad claim leaves no debris behind
  def _materialize(self, claim_id: str, d: ClaimDraft, source: Source, author_id: str | None,
                   trust_speakers: bool = True, budget: MemberBudget | None = None) -> Claim | str:
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
    if err := self._oversized(d):
      return err
    if not trust_speakers and (err := self._unresolved(d) or self._untrusted_error(d, budget)):
      return err

    fresh = budget is not None and self._is_new_subject(d)
    subject = self._ensure_node(d.subject)
    if budget is not None:
      budget.new_nodes += int(fresh)
      if key := _lookalike_key(subject.name):
        budget.lookalikes.setdefault((subject.type, key), subject.id)
    statement: Statement
    match d.kind:
      case "attribute":
        if d.attribute is None or d.value is None:
          raise ValueError("attribute claim needs attribute and value")
        statement = AttributeStatement(attribute=d.attribute, value=d.value)
      case "relation":
        if d.relation is None or d.target is None:
          raise ValueError("relation claim needs relation and target")
        statement = RelationStatement(relation=d.relation, target_id=self._ensure_node(d.target).id)
      case "ownership":
        if d.owner is None:
          raise ValueError("ownership claim needs an owner")
        statement = OwnershipStatement(owner_id=self._ensure_person(d.owner).id)
      case _:
        assert_never(d.kind)
    valid_from = as_utc(d.valid_from) if d.valid_from else source.timestamp
    if not trust_speakers:
      valid_from = max(min(valid_from, self.clock()), self._backdate_floor(subject.id, statement))
    return Claim(id=claim_id, subject_id=subject.id, statement=statement,
                 context=self._normalize_context(d.context, create=True),
                 valid_from=valid_from,
                 source=SourceRef(source_id=source.id, quote=d.quote),
                 asserted_by=(self._speaker(d, source) if trust_speakers else None) or author_id)

  def _backdate_floor(self, subject_id: str, statement: Statement) -> datetime:
    slot = (subject_id, *statement.slot())
    existing = [f.valid_from for f in self.store.facts(subject_id=subject_id)
                if f.slot == slot and f.status == "active"]
    return max(existing) if existing else self.clock() - MAX_UNTRUSTED_BACKDATE

  def _context_mentions(self, context: dict[str, str]) -> list[EntityMention]:
    return [EntityMention(type=dim.entity, name=value) for key, value in context.items()
            if (dim := self.schema.dimension(key)) is not None and dim.entity is not None]

  def _oversized(self, d: ClaimDraft) -> str | None:
    owner = [EntityMention(type=self.schema.owner_type, name=d.owner)] if d.kind == "ownership" and d.owner else []
    mentions = [d.subject, *([d.target] if d.kind == "relation" and d.target else []), *owner,
                *self._context_mentions(d.context)]
    return next((f"{m.type} name is longer than {MAX_NAME} characters"
                 for m in mentions if len(m.name) > MAX_NAME), None)

  def _lookup(self, mention: EntityMention) -> Node | None:
    if mention.type == self.schema.owner_type:
      return self._find_person(mention.name, by_name=False)
    return self._find_node(mention)

  def _unresolved(self, d: ClaimDraft) -> str | None:
    refs = [*([d.subject] if d.subject.type == self.schema.owner_type else []),
            *([d.target] if d.kind == "relation" and d.target else []), *self._context_mentions(d.context)]
    if missing := next((m for m in refs if self._lookup(m) is None), None):
      return f"unknown {missing.type} '{missing.name}'"
    if d.kind == "ownership" and d.owner and self._find_person(d.owner, by_name=False) is None:
      return f"unknown person '{d.owner}'"
    return None

  def _is_new_subject(self, d: ClaimDraft) -> bool:
    return d.subject.type != self.schema.owner_type and self._find_node(d.subject) is None

  def _untrusted_error(self, d: ClaimDraft, budget: MemberBudget | None = None) -> str | None:
    if d.valid_from is not None and d.valid_from > self.clock().date():
      return "valid_from is in the future"
    if not self._is_new_subject(d):
      return None
    budget = MemberBudget(self._lookalike_index()) if budget is None else budget
    if budget.new_nodes >= MAX_UNTRUSTED_NEW_NODES_PER_SOURCE:
      return "too many new topics in one source"
    if not MEMBER_NAME.fullmatch(d.subject.name):
      return "names must be plain ASCII"
    if len(Node.make_id(d.subject.type, d.subject.name)) > MAX_UNTRUSTED_ID:
      return "name is too long"
    return "name looks like an existing node" \
      if (d.subject.type, _lookalike_key(d.subject.name)) in budget.lookalikes else None

  # the extractor may credit a statement to someone other than the author (a decision in a bot's
  # meeting summary), but only to a known person who took part in that source
  def _speaker(self, d: ClaimDraft, source: Source) -> str | None:
    if not d.asserted_by or self.seed.is_non_person(d.asserted_by):
      return None
    speaker = self._find_person(d.asserted_by, by_name=False)
    participants = {p.id for ref in source.participants() if (p := self._find_person(ref, by_name=False))}
    return speaker.id if speaker and speaker.id in participants else None

  def _is_authority(self, person_id: str | None) -> bool:
    return person_id is not None and person_id in {
      p.id for a in self.seed.authorities if (p := self._find_person(a, by_name=False))}

  def _authoritative(self, claim: Claim, author_id: str | None, owner_id: str | None) -> bool:
    if owner_id is None:
      return True
    judged = {claim.asserted_by} if author_id is None else {claim.asserted_by, author_id}
    return all(p is not None and (p == owner_id or self._is_authority(p)) for p in judged)

  def _from_portal(self, claim: Claim) -> bool:
    return (source := self.store.get_source(claim.source.source_id)) is not None and source.kind == "portal"

  def _gate_node(self, claim: Claim, author_id: str | None, trusted: bool) -> str:
    if trusted or not self.enforce_ownership or not isinstance(claim.statement, RelationStatement) \
        or not self._authoritative(claim, author_id, self.owner_of(claim.subject_id)):
      return claim.subject_id
    target_id = claim.statement.target_id
    if self._unowned_established_target(claim) is not None and not self._is_authority(claim.asserted_by):
      return target_id
    return claim.subject_id if self._authoritative(claim, author_id, self.owner_of(target_id)) else target_id

  def _unowned_established_target(self, claim: Claim) -> str | None:
    if not isinstance(claim.statement, RelationStatement):
      return None
    target_id = claim.statement.target_id
    return target_id if self.owner_of(target_id) is None \
      and self._established(target_id, claim.source.source_id) else None

  def _has_other_facts(self, node_id: str, source_id: str) -> bool:
    return any(f.status != "rejected" and f.sources[0].source_id != source_id
               for f in self.store.facts(subject_id=node_id))

  def _references(self, fact: Fact, node_id: str) -> bool:
    target = fact.statement.target_id if isinstance(fact.statement, RelationStatement) else None
    return node_id in (fact.subject_id, target, *fact.context.values())

  def _established(self, node_id: str, source_id: str) -> bool:
    return node_id in self._seeded_ids() or self._has_other_facts(node_id, source_id) or any(
      f.status != "rejected" and not self._member_fact(f) and self._references(f, node_id)
      for f in self.store.facts())

  def _approval_reason(self, claim: Claim, action: DecisionAction, owner_id: str | None,
                       authoritative: bool, trusted: bool, contested: bool) -> str | None:
    if not self.enforce_ownership or action not in ("create", "supersede"):
      return None
    if owner_id is None and self._from_portal(claim) and (
        self._has_other_facts(claim.subject_id, claim.source.source_id)
        or claim.subject_id in self._seeded_ids() or any(
          f.status != "rejected" and f.sources[0].source_id != claim.source.source_id
          and not self._member_fact(f) and self._references(f, claim.subject_id) for f in self.store.facts())):
      return "Changes an unowned topic that already has facts, so it waits for an owner."
    if authoritative and trusted:
      return None
    if trusted:
      if isinstance(claim.statement, OwnershipStatement) and owner_id is not None and (
          action == "supersede" or self._from_portal(claim)
          or (current := self._owner_fact(claim.subject_id)) is None or current.context != claim.context):
        return "Ownership changes need approval by the current owner or an administrator."
      if action == "supersede" or (owner_id is not None and (
          self._from_portal(claim) or (contested and (
            claim.subject_id in self._seeded_ids() or not self._related_owner(claim))))):
        return "Not asserted by the owner or an authority, so it needs approval."
      return None
    if self._is_authority(claim.asserted_by):
      return None
    if isinstance(claim.statement, OwnershipStatement):
      return None if owner_id is not None and authoritative else \
        "Ownership changes need approval by the current owner or an administrator."
    if self._unowned_established_target(claim) is not None:
      return "Links to an unowned topic that already has facts, so it waits for an owner."
    if owner_id is not None:
      return None if authoritative else "Not asserted by the owner or an authority, so it needs approval."
    return "Changes an unowned topic that already has facts, so it waits for an owner." \
      if self._established(claim.subject_id, claim.source.source_id) else None

  def _squat_source(self, source_id: str) -> bool:
    return self._member_source(source_id) or (
      (source := self.store.get_source(source_id)) is not None and source.kind == "portal")

  def _squat_fact(self, fact: Fact) -> bool:
    return fact.status == "active" and fact.valid_to is None \
      and all(self._squat_source(r.source_id) for r in fact.sources) \
      and not self._is_authority(fact.asserted_by) and not self._owner_asserted(fact)

  def _owner_asserted(self, fact: Fact) -> bool:
    if isinstance(fact.statement, OwnershipStatement) or fact.asserted_by is None:
      return False
    owner = self._owner_fact(fact.subject_id)
    return owner is not None and owner.statement.owner_id == fact.asserted_by \
      and not all(self._squat_source(r.source_id) for r in owner.sources)

  def _written(self, item: Claim | Fact) -> datetime:
    ref = item.source if isinstance(item, Claim) else item.sources[0]
    source = self.store.get_source(ref.source_id)
    written = item.valid_from if source is None else max(item.valid_from, source.timestamp)
    if not isinstance(item, Claim) and self._member_source(ref.source_id):
      return max(written, item.recorded_at)
    return written

  def _source_author(self, source_id: str) -> str | None:
    source = self.store.get_source(source_id)
    if source is None or self.seed.is_non_person(source.author):
      return None
    return author.id if (author := self._find_person(source.author, by_name=False)) else None

  def _related_owner(self, claim: Claim) -> bool:
    now = self.clock()
    owner_id = self.owner_of(claim.subject_id)
    return claim.asserted_by is not None and owner_id is not None \
      and self._source_author(claim.source.source_id) == claim.asserted_by and any(
      isinstance(f.statement, RelationStatement) and f.is_current(now) and f.asserted_by != claim.asserted_by
      and not all(self._squat_source(r.source_id) for r in f.sources)
      and f.asserted_by == owner_id and self._source_author(f.sources[0].source_id) == owner_id
      and self.owner_of(f.statement.target_id) == claim.asserted_by
      for f in self.store.facts(subject_id=claim.subject_id))

  def _squatted_owner(self, claim: Claim, trusted: bool) -> Fact | None:
    if not trusted or self._from_portal(claim):
      return None
    fact = self._owner_fact(claim.subject_id)
    return fact if fact is not None and fact.confirmed_by is None and self._squat_fact(fact) \
      and self._written(fact) > self._written(claim) else None

  def _squats(self, claim: Claim, trusted: bool) -> list[Fact]:
    if not trusted or self._from_portal(claim):
      return []
    squatter = self._squatted_owner(claim, trusted)
    facts = self.store.facts(subject_id=claim.subject_id)
    voided = {f.statement.owner_id for f in facts if isinstance(f.statement, OwnershipStatement)
              and f.valid_to is not None and f.valid_to == f.valid_from
              and all(self._squat_source(r.source_id) for r in f.sources)}
    by = {None, *voided, *([self.owner_of(claim.subject_id)] if squatter else [])}
    slot = (claim.subject_id, *claim.statement.slot())
    found = [f for f in facts if f.slot == slot and self._squat_fact(f) and f.confirmed_by in by]
    return [*found, squatter] if squatter and squatter not in found else found

  def _resolve(self, claim: Claim, author_id: str | None, trusted: bool = True) -> Decision:
    slot = (claim.subject_id, *claim.statement.slot())
    now = self.clock()
    squats = [f.id for f in self._squats(claim, trusted)]
    squatter = self._squatted_owner(claim, trusted)
    candidates = [f for f in self.store.facts(subject_id=claim.subject_id)
                  if f.slot == slot and f.id not in squats
                  and (f.status == "pending" or (f.status == "active" and f.valid_to is None
                                                 and (f.valid_from <= now or claim.valid_from > now)))]
    subject = self.store.get_node(claim.subject_id)
    if subject is None:
      raise KeyError(f"no node '{claim.subject_id}'")
    owner_id = None if squatter else self.owner_of(claim.subject_id)
    authoritative = self._authoritative(claim, author_id, owner_id)
    decision = self.resolver.resolve(ResolutionInput(
      claim=claim, subject=subject, candidates=candidates, owner_id=owner_id,
      authoritative=authoritative, schema=self.schema))
    known = {f.id for f in candidates}
    decision.target_fact_ids = [t for t in decision.target_fact_ids if t in known]
    contested = any(f.status == "active" for f in candidates)
    if reason := self._approval_reason(claim, decision.action, owner_id, authoritative, trusted, contested):
      return Decision(action="escalate", target_fact_ids=decision.target_fact_ids,
                      rationale=f"{decision.rationale} {reason}",
                      question=f"Approve '{claim.statement.describe()}' for {subject.name}?")
    if decision.action in ("create", "supersede") and \
        (gate := self._gate_node(claim, author_id, trusted)) != claim.subject_id:
      return Decision(action="escalate", target_fact_ids=decision.target_fact_ids,
                      rationale=f"{decision.rationale} Links to {gate}, which someone else owns, so its owner "
                                "must approve.",
                      question=f"Approve '{claim.statement.describe()}' for {subject.name}?")
    if decision.action == "confirm" and not trusted and not authoritative:
      return Decision(action="ignore", target_fact_ids=decision.target_fact_ids,
                      rationale=f"{decision.rationale} Not asserted by the owner or an authority, so it "
                                "adds no support.")
    if squats and decision.action in ("create", "supersede") and not authoritative:
      return Decision(action="escalate", target_fact_ids=[*decision.target_fact_ids, *squats],
                      rationale=f"{decision.rationale} Replaces unconfirmed portal or member facts on an owned "
                                "topic, so the owner must approve.",
                      question=f"Approve '{claim.statement.describe()}' for {subject.name}?")
    if squats and decision.action in ("create", "supersede"):
      return Decision(action="supersede", target_fact_ids=[*decision.target_fact_ids, *squats],
                      rationale=decision.rationale, question=decision.question)
    return decision

  def _apply(self, claim: Claim, decision: Decision, author_id: str | None, trusted: bool = True) -> None:
    owner_id = self.owner_of(claim.subject_id)
    confirmed_by = (claim.asserted_by if owner_id is not None
                    and self._authoritative(claim, author_id, owner_id) else None)
    targets = decision.target_fact_ids
    match decision.action:
      case "create":
        self.store.put_fact(Fact.from_claim(claim, "active", decision.rationale).model_copy(
          update={"confirmed_by": confirmed_by}))
        self._reassign_if_ownership(claim)
      case "supersede":
        squats = {f.id for f in self._squats(claim, trusted)}
        fact = Fact.from_claim(claim, "active", decision.rationale, supersedes=targets).model_copy(
          update={"confirmed_by": confirmed_by})
        self.store.put_fact(fact)
        self._close(targets, fact, squats)
        self._reassign_if_ownership(claim)
      case "confirm":
        for fact in self._facts(targets):
          fact.sources.append(claim.source)
          fact.confirmed_by = fact.confirmed_by or confirmed_by
          self.store.put_fact(fact)
      case "conflict" | "escalate":
        fact = Fact.from_claim(claim, "pending", decision.rationale, supersedes=targets)
        self.store.put_fact(fact)
        esc_id, gate = f"esc:{fact.id}", self._gate_node(claim, author_id, trusted)
        if self.store.get_escalation(esc_id) is not None:
          esc_id = self._next_id(f"{esc_id}:", lambda i: self.store.get_escalation(i) is not None)
        self.store.put_escalation(Escalation(
          id=esc_id, reason="conflict" if decision.action == "conflict" else "approval",
          subject_id=gate, question=decision.question or decision.rationale,
          assignee_id=self.owner_of(gate), fact_id=fact.id, related_fact_ids=targets,
          raised_by=claim.asserted_by, created_at=self.clock()))
      case "ignore":
        pass
      case _:
        assert_never(decision.action)

  def _reassign_if_ownership(self, fact: Claim | Fact) -> None:
    if isinstance(fact.statement, OwnershipStatement):
      self._reassign(fact.subject_id)

  def _reassign(self, node_id: str) -> None:
    if (owner_id := self.owner_of(node_id)) is None:
      return
    for esc in self.store.escalations():
      if esc.subject_id == node_id and esc.status == "open" and esc.assignee_id != owner_id:
        esc.assignee_id = owner_id
        self.store.put_escalation(esc)

  def _close(self, fact_ids: list[str], by: Fact, void: Collection[str] = ()) -> None:
    for fact in self._facts(fact_ids):
      if fact.status == "active" and fact.valid_to is None:
        fact.valid_to = fact.valid_from if fact.id in void else max(by.valid_from, fact.valid_from)
        fact.superseded_by = by.id
        self.store.put_fact(fact)

  def _facts(self, fact_ids: list[str]) -> list[Fact]:
    return [f for i in fact_ids if (f := self.store.get_fact(i)) is not None]

  @staticmethod
  def _next_id(prefix: str, taken: Callable[[str], bool]) -> str:
    n = 0
    while taken(f"{prefix}{n}"):
      n += 1
    return f"{prefix}{n}"

  # -------------------------------------------------------------------------------------------
  # entities

  def _find_node(self, mention: EntityMention) -> Node | None:
    if mention.type == self.schema.owner_type:
      return self._find_person(mention.name)
    if (node := self.store.get_node(mention.name)) is not None and node.type == mention.type:
      return node
    return next((n for n in self.store.nodes(mention.type) if n.matches(mention.name)), None)

  def _ensure_node(self, mention: EntityMention) -> Node:
    if mention.type == self.schema.owner_type:
      return self._ensure_person(mention.name)
    if (node := self._find_node(mention)) is not None:
      return node
    node_id = Node.make_id(mention.type, mention.name)
    if (node := self.store.get_node(node_id)) is not None:
      if node.type == mention.type and node.name.casefold() == mention.name.casefold():
        return node
      node_id = self._next_id(f"{node_id}-", lambda i: self.store.get_node(i) is not None)
    node = Node(id=node_id, type=mention.type, name=mention.name, created_at=self.clock())
    self.store.put_node(node)
    return node

  @staticmethod
  def _parse_person(ref: str) -> tuple[str, str]:
    name, addr = parseaddr(ref) if "@" in ref else (ref, "")
    return name.strip(), addr.strip().lower()

  # lookup only: never creates people from recipients like distribution lists
  def _find_person(self, ref: str, by_name: bool = True) -> Node | None:
    ptype = self.schema.owner_type
    if (node := self.store.get_node(ref)) is not None and node.type == ptype:
      return node
    name, addr = self._parse_person(ref)
    people = self.store.nodes(ptype)
    if addr:
      return next((p for p in people if addr in p.aliases), None)
    return next((p for p in people if name and p.matches(name)), None) if by_name else None

  # people are matched by node id or email alias, never by display name
  def _ensure_person(self, ref: str, adopt: bool = False) -> Node:
    ptype = self.schema.owner_type
    if (node := self.store.get_node(ref)) is not None and node.type == ptype:
      return node
    # an id of a person we have not seen yet (e.g. an authenticated API user): keep the id verbatim
    if ref.startswith(prefix := f"{ptype.lower()}:"):
      node = Node(id=ref, type=ptype, name=ref.removeprefix(prefix), created_at=self.clock())
      self.store.put_node(node)
      return node
    name, addr = self._parse_person(ref)
    if addr and (node := self._find_person(ref, by_name=False)) is not None:
      return node
    node_id = Node.make_id(ptype, addr or name)
    if (node := self.store.get_node(node_id)) is not None:
      if node.type == ptype and not node.aliases and (not addr or adopt):
        if addr:
          node.name, node.aliases = name or addr, [addr]
          self.store.put_node(node)
        return node
      node_id = self._next_id(f"{node_id}-", lambda i: self.store.get_node(i) is not None)
    node = Node(id=node_id, type=ptype, name=name or addr, aliases=[addr] if addr else [],
                created_at=self.clock())
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

  def _owner_fact(self, node_id: str, as_of: datetime | None = None) -> Fact | None:
    as_of = as_of or self.clock()
    owned = [f for f in self.store.facts(subject_id=node_id)
             if isinstance(f.statement, OwnershipStatement) and f.is_current(as_of)]
    return max(owned, key=lambda f: f.valid_from) if owned else None

  def owner_of(self, node_id: str, as_of: datetime | None = None) -> str | None:
    if (fact := self._owner_fact(node_id, as_of)) is None:
      return None
    if not isinstance(fact.statement, OwnershipStatement):
      return None
    return fact.statement.owner_id

  # -------------------------------------------------------------------------------------------
  # human oversight

  def _open_escalation(self, escalation_id: str) -> Escalation:
    esc = self.store.get_escalation(escalation_id)
    if esc is None:
      raise KeyError(f"no escalation '{escalation_id}'")
    if esc.status != "open":
      raise ValueError(f"escalation '{escalation_id}' is already {esc.status}")
    if self.store.get_node(esc.subject_id) is None:
      raise ValueError(f"escalation '{escalation_id}' is about a node that no longer exists")
    return esc

  def _authorize(self, esc: Escalation, actor_id: str) -> None:
    if (owner_id := self.owner_of(esc.subject_id)) is not None and owner_id != esc.assignee_id:
      esc.assignee_id = owner_id
      self.store.put_escalation(esc)
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
    if fact.status != "pending":
      raise ValueError(f"fact '{fact.id}' is already {fact.status}")
    if verdict == "approve" and isinstance(fact.statement, RelationStatement) and \
        (target_owner := self.owner_of(target_id := fact.statement.target_id)) is not None and \
        target_owner != actor_id and not self._is_authority(actor_id):
      esc.subject_id, esc.assignee_id = target_id, target_owner
      self.store.put_escalation(esc)
      return esc
    match verdict:
      case "approve":
        void = self._approved_squats(fact)
        fact.status, fact.confirmed_by = "active", actor_id
        self.store.put_fact(fact)
        self._close(esc.related_fact_ids, fact, void)
        esc.status = "approved"
      case "reject":
        fact.status = "rejected"
        self.store.put_fact(fact)
        esc.status = "rejected"
      case _:
        assert_never(verdict)
    esc.resolved_at, esc.resolved_by, esc.resolution = self.clock(), actor_id, note
    self.store.put_escalation(esc)
    if verdict == "approve":
      self._reassign_if_ownership(fact)
    return esc

  def _approved_squats(self, fact: Fact) -> set[str]:
    if not fact.sources or self._squat_source(fact.sources[0].source_id):
      return set()
    claim = Claim(id=fact.id, subject_id=fact.subject_id, statement=fact.statement, context=fact.context,
                  valid_from=fact.valid_from, source=fact.sources[0], asserted_by=fact.asserted_by)
    return {f.id for f in self._squats(claim, True)}

  def ask_owner(self, node_id: str, question: str, asked_by: str) -> Escalation:
    if self.store.get_node(node_id) is None:
      raise KeyError(f"no node '{node_id}'")
    if sum(e.status == "open" and e.raised_by == asked_by
           for e in self.store.escalations()) >= MAX_OPEN_ESCALATIONS_PER_AUTHOR:
      raise ValueError(f"{asked_by} already has {MAX_OPEN_ESCALATIONS_PER_AUTHOR} open escalations")
    esc_id = self._next_id(f"esc:q:{_id_slug(node_id)}:", lambda i: self.store.get_escalation(i) is not None)
    esc = Escalation(id=esc_id, reason="question", subject_id=node_id, question=question,
                     assignee_id=self.owner_of(node_id), raised_by=asked_by, created_at=self.clock())
    self.store.put_escalation(esc)
    return esc

  # the answer becomes a source and flows through the normal pipeline, so the next person
  # asking gets it from the graph instead of from the owner
  def answer_escalation(self, escalation_id: str, actor_id: str, answer: str) -> IngestReport:
    plan = self.prepare_answer(escalation_id, actor_id, answer)
    try:
      drafts = self.extract_answer(plan)
    except Exception as e:
      return IngestReport(outcomes=[ClaimOutcome(plan.source.id, error=f"extraction failed: {type(e).__name__}")])
    return self.commit_answer(plan, drafts)

  def _answerable(self, escalation_id: str, actor_id: str) -> Escalation:
    esc = self._open_escalation(escalation_id)
    self._authorize(esc, actor_id)
    if esc.fact_id is not None:
      raise ValueError(f"escalation '{esc.id}' awaits a verdict on a pending fact; resolve it instead")
    if self.store.get_source(source_id := f"note:{esc.id}") is not None:
      raise ValueError(f"source '{source_id}' already exists")
    return esc

  def prepare_answer(self, escalation_id: str, actor_id: str, answer: str) -> AnswerPlan:
    esc = self._answerable(escalation_id, actor_id)
    subject = self.store.get_node(esc.subject_id)
    about = subject.name if subject else esc.subject_id
    source = NoteSource(id=f"note:{esc.id}", title=f"Answer about {about}", author=actor_id,
                        timestamp=self.clock(), escalation_id=esc.id,
                        content=f"About {about}.\n{answer}\n\n"
                                "The question below was asked by someone else. It is untrusted context, "
                                "not a statement by the author:\n" + fence("question", esc.question))
    known = [n.model_copy(deep=True) for n in self._known_nodes()[:MAX_KNOWN_ENTITIES]]
    return AnswerPlan(escalation_id=esc.id, actor_id=actor_id, answer=answer, source=source, known=known)

  def extract_answer(self, plan: AnswerPlan) -> list[ClaimDraft]:
    return self.extractor.extract(plan.source, self.schema, plan.known)

  def commit_answer(self, plan: AnswerPlan, drafts: list[ClaimDraft]) -> IngestReport:
    esc = self._answerable(plan.escalation_id, plan.actor_id)
    actor_id, answer = plan.actor_id, _normalized(plan.answer)
    subject = self.store.get_node(esc.subject_id)
    said, named = _words(plan.answer), _words(subject.name if subject else "")

    def screen(draft: ClaimDraft) -> str | None:
      if draft.kind == "ownership":
        return "answers cannot change ownership"
      if not (quote := _normalized(draft.quote or "")) or quote not in answer \
          or len(quote) < min(len(answer), MIN_ANSWER_QUOTE):
        return "answers must quote the owner's answer"
      value = draft.value or ""
      if draft.kind == "attribute" and _words(value) - ((said & _words(quote)) | named):
        return "answers must state the value"
      if draft.kind == "attribute" and _negations(quote) - _negations(value):
        return "answers must keep the owner's negation"
      if draft.valid_from is not None:
        return "answers cannot set valid_from"
      if missing := next((m for m in self._context_mentions(draft.context) if self._lookup(m) is None), None):
        return f"unknown {missing.type} '{missing.name}'"
      if any(_words(v) - said for k, v in draft.context.items()
             if (dim := self.schema.dimension(k)) is None or dim.entity is None):
        return "answers must state the context"
      if draft.kind == "relation" and draft.target is not None and _words(draft.target.name) - said:
        return "answers must name the target"
      if draft.kind == "relation" and draft.target is not None:
        if (target := self._find_node(draft.target)) is None:
          return "answers cannot create topics"
        if self.owner_of(target.id) not in (None, actor_id) and not self._is_authority(actor_id):
          return "answers cannot link to a node someone else owns"
      node = self._find_node(draft.subject)
      return None if node is not None and node.id == esc.subject_id else \
        "answers can only describe the subject of the question"

    report = self.ingest_source(plan.source, drafts=drafts, screen=screen)
    esc.status, esc.resolution = "answered", plan.answer
    esc.resolved_at, esc.resolved_by = self.clock(), actor_id
    self.store.put_escalation(esc)
    return report

  # admin action: makes a node owned, and hands its open escalations to the new owner
  def assign_owner(self, node_id: str, owner_id: str, assigned_by: str) -> Fact:
    if self.store.get_node(node_id) is None:
      raise KeyError(f"no node '{node_id}'")
    if self.seed.is_non_person(owner_id):
      raise ValueError(f"'{owner_id}' is a system, not a person, and cannot own knowledge")
    owner = self._ensure_person(owner_id)
    now = self.clock()
    source_id = self._next_id(f"note:assign:{_id_slug(node_id)}:", lambda i: self.store.get_source(i) is not None
                              or self.store.get_fact(f"{i}:0") is not None)
    source = NoteSource(id=source_id, title=f"Owner assignment for {node_id}", author=assigned_by,
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
    self._reassign(node_id)
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
        scored.append((self._member_tainted(node.id, as_of), -score, node.name, node))
    hits = [n for *_, n in sorted(scored, key=lambda t: t[:3])[:limit]]
    for node in list(hits):
      if node.type in {t.type for t in self.seed.topics} or not self._portal_sourced(node.id):
        continue
      parents = {f.statement.target_id for f in self.store.facts(subject_id=node.id)
                 if isinstance(f.statement, RelationStatement) and f.is_current(as_of)}
      if (below := [i for i, m in enumerate(hits) if m.id in parents]) and hits.index(node) < max(below):
        hits.remove(node)
        hits.insert(max(below), node)
    return hits

  def ask_hits(self, question: str, limit: int = 3) -> list[Node]:
    hits = self.search(question, limit=limit)
    trusted = [n for n in hits if not self._member_tainted(n.id)]
    return trusted or hits

  def _member_source(self, source_id: str) -> bool:
    return source_id.startswith(f"{self.schema.owner_type.lower()}:") and "+" in source_id

  def _member_fact(self, fact: Fact) -> bool:
    return all(self._member_source(r.source_id) for r in fact.sources)

  def _member_only(self, node_id: str) -> bool:
    refs = [r.source_id for f in self.store.facts(subject_id=node_id) for r in f.sources]
    return bool(refs) and all(self._member_source(r) for r in refs)

  def _member_tainted(self, node_id: str, as_of: datetime | None = None) -> bool:
    if self._portal_only(node_id):
      return True
    if not (member := [f for f in self.store.facts(subject_id=node_id) if self._member_fact(f)]):
      return False
    as_of = as_of or self.clock()
    if self.owner_of(node_id, as_of) is not None:
      return False
    return self._member_only(node_id) or any(f.is_current(as_of) for f in member)

  def _portal_only(self, node_id: str) -> bool:
    node = self.store.get_node(node_id)
    if node is None or node_id in self._seeded_ids() or node.type == self.schema.owner_type:
      return False
    if node.type in {t.type for t in self.seed.topics}:
      return self._portal_sourced(node_id)
    if not self._portal_sourced(node_id):
      return False
    now = self.clock()
    return not any(isinstance(f.statement, RelationStatement) and f.is_current(now)
                   and self._vouching_topic(f.statement.target_id) for f in self.store.facts(subject_id=node_id))

  def _vouching_topic(self, node_id: str) -> bool:
    node = self.store.get_node(node_id)
    if node is None or node.type not in {t.type for t in self.seed.topics}:
      return False
    if node_id in self._seeded_ids():
      return True
    return any(f.status != "rejected" for f in self.store.facts(subject_id=node_id)) \
      and not self._portal_sourced(node_id)

  def _portal_sourced(self, node_id: str) -> bool:
    facts = [f for f in self.store.facts(subject_id=node_id) if f.status != "rejected"]
    squatters = {f.statement.owner_id for f in facts if isinstance(f.statement, OwnershipStatement)
                 and all(self._squat_source(r.source_id) for r in f.sources)}
    if not facts or not all(self._squat_source(r.source_id) or self._squatter_answer(r.source_id, squatters)
                            for f in facts for r in f.sources):
      return False
    return not any(f.confirmed_by and f.confirmed_by != f.asserted_by and f.confirmed_by not in squatters
                   for f in facts if not isinstance(f.statement, OwnershipStatement))

  def _squatter_answer(self, source_id: str, squatters: set[str]) -> bool:
    source = self.store.get_source(source_id)
    return source is not None and source.kind == "note" and source_id.startswith("note:esc:") \
      and source.author in squatters and not self._is_authority(source.author)

  def ask(self, question: str, context: dict[str, str] | None = None, limit: int = 3) -> AskResult:
    views = [self.view(n.id, context) for n in self.ask_hits(question, limit=limit)]
    return AskResult(question=question, answer=self.answerer.answer(question, views), views=views)

  def gaps(self, stale_after: timedelta = timedelta(days=365), as_of: datetime | None = None) -> Gaps:
    as_of = as_of or self.clock()
    facts = self.store.facts()
    return Gaps(
      unowned=list(islice((n for n in self.store.nodes()
                           if n.type != self.schema.owner_type and self.owner_of(n.id, as_of) is None),
                          MAX_GAPS_UNOWNED)),
      pending=[f for f in facts if f.status == "pending"],
      stale=[f for f in facts if f.is_current(as_of) and f.valid_to is None
             and isinstance(f.statement, AttributeStatement) and f.valid_from < as_of - stale_after],
      open_escalations=[e for e in self.store.escalations() if e.status == "open"],
    )
