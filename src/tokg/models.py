# ABOUTME: Core persisted entities: nodes, sources, temporal owned facts and escalations.
# ABOUTME: A Fact is a sourced Statement about a node, valid over [valid_from, valid_to) in a context.
import re
from datetime import UTC, date, datetime, time
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, Field


def utcnow() -> datetime:
  return datetime.now(UTC)


def as_utc(value: date | datetime) -> datetime:
  if isinstance(value, datetime):
    return value if value.tzinfo else value.replace(tzinfo=UTC)
  return datetime.combine(value, time(), tzinfo=UTC)


def _coerce_utc(value: object) -> object:
  if isinstance(value, str):
    value = datetime.fromisoformat(value)
  return as_utc(value) if isinstance(value, date) else value


UtcDatetime = Annotated[datetime, BeforeValidator(_coerce_utc)]


def slugify(text: str) -> str:
  return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


# ---------------------------------------------------------------------------------------------
# Nodes


class Node(BaseModel):
  id: str
  type: str
  name: str
  aliases: list[str] = Field(default_factory=list)
  description: str | None = None
  properties: dict[str, str] = Field(default_factory=dict, description="Display metadata, e.g. role")
  created_at: UtcDatetime = Field(default_factory=utcnow)

  @staticmethod
  def make_id(type_: str, name: str) -> str:
    return f"{type_.lower()}:{slugify(name)}"

  def matches(self, name: str) -> bool:
    key = slugify(name)
    return key == slugify(self.name) or any(key == slugify(a) for a in self.aliases)


# ---------------------------------------------------------------------------------------------
# Sources: the raw, unstructured material facts are extracted from


class SourceCommon(BaseModel):
  id: str
  title: str
  author: str = Field(..., description="'Name <email>', a bare email/name, or a person node id")
  timestamp: UtcDatetime
  content: str
  recipients: list[str] = Field(default_factory=list, description="Addressees / attendees")
  uri: str | None = None

  # people who took part in the source; a claim may only be attributed to one of them
  def participants(self) -> list[str]:
    return [self.author, *self.recipients]


class EmailSource(SourceCommon):
  kind: Literal["email"] = "email"


class MeetingSource(SourceCommon):
  kind: Literal["meeting"] = "meeting"


class WikiSource(SourceCommon):
  kind: Literal["wiki"] = "wiki"
  path: str | None = None


class DocumentSource(SourceCommon):
  kind: Literal["document"] = "document"
  doc_type: str | None = None


# a ticket submitted through an internal portal/form
class PortalSource(SourceCommon):
  kind: Literal["portal"] = "portal"


# a human answer to an escalation, fed back through the normal ingest pipeline
class NoteSource(SourceCommon):
  kind: Literal["note"] = "note"
  escalation_id: str | None = None


Source = Annotated[EmailSource | MeetingSource | WikiSource | DocumentSource | PortalSource | NoteSource,
                   Field(discriminator="kind")]
SourceKind = Literal["email", "meeting", "wiki", "document", "portal", "note"]


class SourceRef(BaseModel):
  source_id: str
  quote: str | None = Field(default=None, description="Exact excerpt/clause supporting the fact")


# ---------------------------------------------------------------------------------------------
# Statements: what a fact says. `slot` identifies what it is *about*; two facts in the same slot
# compete (one may supersede the other), facts in different slots coexist.


class AttributeStatement(BaseModel):
  kind: Literal["attribute"] = "attribute"
  attribute: str
  value: str

  def slot(self) -> tuple[str, ...]:
    return ("attribute", self.attribute)

  def describe(self) -> str:
    return f"{self.attribute} = {self.value}"


# relations are additive: the target is part of the slot, so "A example_of B" and
# "A example_of C" never compete
class RelationStatement(BaseModel):
  kind: Literal["relation"] = "relation"
  relation: str
  target_id: str

  def slot(self) -> tuple[str, ...]:
    return ("relation", self.relation, self.target_id)

  def describe(self) -> str:
    return f"{self.relation} -> {self.target_id}"


# ownership is single-valued and temporal: a handover supersedes the previous owner
class OwnershipStatement(BaseModel):
  kind: Literal["ownership"] = "ownership"
  owner_id: str

  def slot(self) -> tuple[str, ...]:
    return ("ownership",)

  def describe(self) -> str:
    return f"owned by {self.owner_id}"


Statement = Annotated[AttributeStatement | RelationStatement | OwnershipStatement,
                      Field(discriminator="kind")]


# ---------------------------------------------------------------------------------------------
# Claims and facts


# an extracted statement with entities resolved to node ids, not yet decided on
class Claim(BaseModel):
  id: str
  subject_id: str
  statement: Statement
  context: dict[str, str] = Field(default_factory=dict)
  valid_from: UtcDatetime
  source: SourceRef
  asserted_by: str | None = None


FactStatus = Literal["active", "pending", "rejected"]


class Fact(BaseModel):
  id: str
  subject_id: str
  statement: Statement
  context: dict[str, str] = Field(default_factory=dict)
  valid_from: UtcDatetime
  valid_to: UtcDatetime | None = None
  recorded_at: UtcDatetime = Field(default_factory=utcnow)
  status: FactStatus = "active"
  sources: list[SourceRef] = Field(default_factory=list)
  asserted_by: str | None = None
  confirmed_by: str | None = None
  supersedes: list[str] = Field(default_factory=list)
  superseded_by: str | None = None
  rationale: str | None = None

  @classmethod
  def from_claim(cls, claim: Claim, status: FactStatus, rationale: str | None = None,
                 supersedes: list[str] | None = None) -> "Fact":
    return cls(id=claim.id, subject_id=claim.subject_id, statement=claim.statement,
               context=dict(claim.context), valid_from=claim.valid_from, status=status,
               sources=[claim.source], asserted_by=claim.asserted_by, rationale=rationale,
               supersedes=list(supersedes or []))

  @property
  def slot(self) -> tuple[str, ...]:
    return (self.subject_id, *self.statement.slot())

  def valid_at(self, t: datetime) -> bool:
    return self.valid_from <= t and (self.valid_to is None or t < self.valid_to)

  def is_current(self, as_of: datetime) -> bool:
    return self.status == "active" and self.valid_at(as_of)

  # a fact applies when every dimension it is scoped to matches the query context;
  # an unscoped fact applies everywhere
  def applies_to(self, context: dict[str, str]) -> bool:
    return all(context.get(k) == v for k, v in self.context.items())


# ---------------------------------------------------------------------------------------------
# Escalations: where the bounded human oversight budget is spent


EscalationReason = Literal["approval", "conflict", "question"]
EscalationStatus = Literal["open", "approved", "rejected", "answered"]


class Escalation(BaseModel):
  id: str
  reason: EscalationReason
  subject_id: str
  question: str
  assignee_id: str | None = Field(default=None, description="Owner who must act; None means unowned")
  fact_id: str | None = Field(default=None, description="Pending fact awaiting a verdict")
  related_fact_ids: list[str] = Field(default_factory=list)
  raised_by: str | None = None
  status: EscalationStatus = "open"
  created_at: UtcDatetime = Field(default_factory=utcnow)
  resolved_at: UtcDatetime | None = None
  resolved_by: str | None = None
  resolution: str | None = None
