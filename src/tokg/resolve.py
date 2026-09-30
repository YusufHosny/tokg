# ABOUTME: Resolution stage: decide what a new Claim does to the graph given competing facts in
# ABOUTME: its slot — create, supersede, confirm, flag a conflict, escalate to the owner, or ignore.
from abc import ABC
from dataclasses import dataclass
from typing import Literal

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, Field

from tokg.llm import default_llm
from tokg.models import Claim, Fact, Node
from tokg.schema import Schema

DecisionAction = Literal["create", "supersede", "confirm", "conflict", "escalate", "ignore"]


class Decision(BaseModel):
  action: DecisionAction = Field(
    ..., description="create: new independent fact; supersede: the claim replaces the target facts "
                     "from its valid_from on; confirm: the claim restates a target fact (adds a "
                     "source); conflict: contradicts targets and it is unclear which is right; "
                     "escalate: plausible change but the owner must approve it; ignore: no-op")
  target_fact_ids: list[str] = Field(
    default_factory=list, description="Existing fact ids the action applies to")
  rationale: str = Field(..., description="One sentence, shown to users as the reason")
  question: str | None = Field(
    default=None, description="For conflict/escalate: the question to put to the owner")


@dataclass
class ResolutionInput:
  claim: Claim
  subject: Node
  candidates: list[Fact]  # active or pending facts in the claim's slot, any context
  owner_id: str | None
  # asserted by the owner or an org-wide authority, or the subject has no owner at all
  authoritative: bool
  schema: Schema


class Resolver(ABC):
  def resolve(self, inp: ResolutionInput) -> Decision:
    raise NotImplementedError("resolve should be implemented by subclasses")


# deterministic default: same value confirms; a newer different value in the same context
# supersedes when it is authoritative (owner, authority, or unowned subject), otherwise escalates
class RuleResolver(Resolver):
  def resolve(self, inp: ResolutionInput) -> Decision:
    claim = inp.claim
    same_ctx = [f for f in inp.candidates if f.status == "active" and f.context == claim.context]
    if match := next((f for f in same_ctx if f.statement == claim.statement), None):
      return Decision(action="confirm", target_fact_ids=[match.id],
                      rationale="Restates an existing fact.")
    if not same_ctx:
      return Decision(action="create", rationale="No existing fact in this slot and context.")
    latest = max(same_ctx, key=lambda f: f.valid_from)
    if claim.valid_from < latest.valid_from:
      return Decision(action="ignore", target_fact_ids=[latest.id],
                      rationale="Older than the current fact.")
    targets = [f.id for f in same_ctx]
    if inp.authoritative:
      return Decision(action="supersede", target_fact_ids=targets,
                      rationale="Newer authoritative statement replaces the previous one.")
    return Decision(
      action="escalate", target_fact_ids=targets,
      rationale="Newer statement from someone without authority over this topic; needs owner approval.",
      question=f"{claim.asserted_by or 'A source'} states '{claim.statement.describe()}' for "
               f"{inp.subject.name}, replacing '{latest.statement.describe()}'. Approve?")


def _fact_line(f: Fact) -> str:
  ctx = ", ".join(f"{k}={v}" for k, v in f.context.items()) or "general"
  return (f"- [{f.id}] ({f.status}, valid from {f.valid_from.date()}, context {ctx}, "
          f"asserted by {f.asserted_by}) {f.statement.describe()}")


def get_resolve_system_prompt() -> str:
  return """You maintain a temporal knowledge graph where every fact has an owner.
Given a NEW claim and the EXISTING facts competing for the same slot, decide what the claim does.
- Prefer supersede when the claim is newer and clearly replaces a target (e.g. a law or policy update).
- A claim may supersede facts in a different context when it overrides them (e.g. a new statutory
  rule overriding an older company-specific rule).
- Changes that are not authoritative (not the owner or an org authority) should be escalated.
- A non-authoritative claim that restates an existing fact is a confirm; one that contradicts the
  current fact is a conflict or escalate, never a supersede.
- Use conflict when two sources disagree and you cannot tell which is right.
- Only reference target ids that appear in the existing facts."""


def get_resolve_user_prompt(inp: ResolutionInput) -> str:
  c = inp.claim
  ctx = ", ".join(f"{k}={v}" for k, v in c.context.items()) or "general"
  existing = "\n".join(_fact_line(f) for f in inp.candidates) or "(none)"
  return f"""Subject: {inp.subject.type} '{inp.subject.name}' (owner: {inp.owner_id or 'none'})

NEW claim [{c.id}] (valid from {c.valid_from.date()}, context {ctx}, asserted by {c.asserted_by}, \
{'authoritative' if inp.authoritative else 'NOT the owner or an authority'}):
{c.statement.describe()}
Supporting quote: {c.source.quote or '(none)'}

EXISTING facts:
{existing}"""


class LLMResolver(Resolver):
  def __init__(self, llm: BaseChatModel | None = None, fallback: Resolver | None = None) -> None:
    self._llm = llm
    self.fallback = fallback or RuleResolver()

  @property
  def llm(self) -> BaseChatModel:
    if self._llm is None:
      self._llm = default_llm()
    return self._llm

  def resolve(self, inp: ResolutionInput) -> Decision:
    if not inp.candidates:
      return Decision(action="create", rationale="No existing fact in this slot.")
    chain = self.llm.with_structured_output(Decision)
    decision = chain.invoke([("system", get_resolve_system_prompt()),
                             ("human", get_resolve_user_prompt(inp))])
    if not isinstance(decision, Decision):
      return self.fallback.resolve(inp)
    known = {f.id for f in inp.candidates}
    decision.target_fact_ids = [t for t in decision.target_fact_ids if t in known]
    return decision
