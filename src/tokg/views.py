# ABOUTME: Read models returned by KnowledgeGraph queries: a node's current knowledge in a context,
# ABOUTME: with trust signals, history, sources and contacts. These are the API/MCP response shapes.
from typing import Literal

from pydantic import BaseModel, Field

from tokg.models import Escalation, Fact, Node, Source, SourceRef

Trust = Literal["confirmed", "unconfirmed", "pending"]


class SourcedRef(BaseModel):
  ref: SourceRef
  source: Source | None = None


class FactView(BaseModel):
  fact: Fact
  trust: Trust = Field(..., description="confirmed: asserted or approved by the owner")
  sources: list[SourcedRef] = Field(default_factory=list)
  history: list[Fact] = Field(default_factory=list, description="Versions it superseded, newest first")


class Contact(BaseModel):
  person: Node
  role: str = Field(..., description="Why this person is relevant, e.g. 'owner of Acme'")


class NodeView(BaseModel):
  node: Node
  owner: Node | None = None
  context: dict[str, str] = Field(default_factory=dict)
  current: list[FactView] = Field(default_factory=list, description="Winning fact per slot")
  alternatives: list[FactView] = Field(
    default_factory=list, description="Other applicable active facts that lost the ranking")
  pending: list[FactView] = Field(default_factory=list, description="Awaiting owner approval")
  other_contexts: list[FactView] = Field(
    default_factory=list, description="Active facts scoped to contexts that don't apply here")
  incoming: list[FactView] = Field(
    default_factory=list, description="Relation facts from other nodes pointing at this node")
  contacts: list[Contact] = Field(default_factory=list)
  escalations: list[Escalation] = Field(default_factory=list)


class Gaps(BaseModel):
  unowned: list[Node] = Field(default_factory=list)
  pending: list[Fact] = Field(default_factory=list)
  stale: list[Fact] = Field(default_factory=list)
  open_escalations: list[Escalation] = Field(default_factory=list)


class Answer(BaseModel):
  answer: str = Field(..., description="Direct, concise answer to the question")
  cited_fact_ids: list[str] = Field(default_factory=list, description="Fact ids the answer relies on")
  contact_ids: list[str] = Field(default_factory=list, description="Person node ids to contact")
  caveats: list[str] = Field(
    default_factory=list, description="Uncertainty, pending changes or missing knowledge to flag")


class AskResult(BaseModel):
  question: str
  answer: Answer
  views: list[NodeView] = Field(default_factory=list)
