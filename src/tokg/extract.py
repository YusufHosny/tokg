# ABOUTME: Extraction stage: source text -> ClaimDrafts that reference entities by (type, name).
# ABOUTME: KnowledgeGraph later resolves those mentions to nodes and validates them against the schema.
from abc import ABC
from datetime import date
from typing import Literal

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, Field

from tokg.llm import default_llm
from tokg.models import Node, Source
from tokg.schema import Schema


class EntityMention(BaseModel):
  type: str = Field(..., description="Entity type name, exactly as defined in the schema")
  name: str = Field(..., description="Canonical name of the entity; for people prefer their email")


class ClaimDraft(BaseModel):
  kind: Literal["attribute", "relation", "ownership"] = Field(
    ..., description="attribute: the subject has a value for an attribute; relation: the subject "
                     "is linked to a target entity; ownership: a person is responsible for the subject")
  subject: EntityMention = Field(..., description="The entity the claim is about")
  attribute: str | None = Field(default=None, description="For kind=attribute: attribute name from the schema")
  value: str | None = Field(default=None, description="For kind=attribute: the full, self-contained value")
  relation: str | None = Field(default=None, description="For kind=relation: relation name from the schema")
  target: EntityMention | None = Field(default=None, description="For kind=relation: the target entity")
  owner: str | None = Field(default=None, description="For kind=ownership: the owner's email or name")
  context: dict[str, str] = Field(
    default_factory=dict, description="Context dimensions this claim is scoped to (only schema "
                                      "dimensions; omit when it applies generally)")
  valid_from: date | None = Field(
    default=None, description="Date from which the claim holds, if the source states one; else omitted")
  quote: str | None = Field(default=None, description="Short verbatim excerpt from the source that supports it")
  asserted_by: str | None = Field(
    default=None, description="Email of the participant who made this statement when it is not the "
                              "source author (e.g. a decision in a meeting summary, a quoted reply)")


class Extraction(BaseModel):
  claims: list[ClaimDraft] = Field(default_factory=list)


class Extractor(ABC):
  def extract(self, source: Source, schema: Schema, known: list[Node]) -> list[ClaimDraft]:
    raise NotImplementedError("extract should be implemented by subclasses")


def get_system_prompt(schema: Schema) -> str:
  return f"""You extract organisational knowledge from a source document into claims for a
temporal, ownership-aware knowledge graph.

{schema.prompt_repr()}

Rules:
- Only use entity types, attributes, relations and context dimensions from the schema.
- Reuse the names of known entities when the source refers to them.
- Attribute values must be self-contained: a reader must understand them without the source.
- Scope a claim with context only when the source restricts where it applies.
- Emit an ownership claim when the source says who is responsible for / maintains / handles something.
- Include a short verbatim quote supporting each claim.
- Set asserted_by to the participant who actually made a statement when that is not the source author
  (meeting summaries written by a bot, quoted replies inside an email). Never attribute to bots or lists.
- Chit-chat, logistics and questions without an answer are noise: extract nothing from them.
- Extract nothing speculative; an empty list is a valid answer."""


def _known_line(n: Node) -> str:
  aliases = f" (aka {', '.join(n.aliases)})" if n.aliases else ""
  return f"- {n.type}: {n.name}{aliases}{f' — {n.description}' if n.description else ''}"


def get_user_prompt(source: Source, known: list[Node]) -> str:
  known_lines = "\n".join(_known_line(n) for n in known) or "(none yet)"
  return f"""Known entities (reuse these names):
{known_lines}

Source ({source.kind}) '{source.title}' by {source.author} on {source.timestamp.date()}
Recipients/attendees: {', '.join(source.recipients) or '(none)'}
{source.content}"""


class LLMExtractor(Extractor):
  def __init__(self, llm: BaseChatModel | None = None) -> None:
    self._llm = llm

  @property
  def llm(self) -> BaseChatModel:
    # built lazily so constructing a graph never spawns a CLI process
    if self._llm is None:
      self._llm = default_llm()
    return self._llm

  def extract(self, source: Source, schema: Schema, known: list[Node]) -> list[ClaimDraft]:
    chain = self.llm.with_structured_output(Extraction)
    result = chain.invoke([("system", get_system_prompt(schema)),
                           ("human", get_user_prompt(source, known))])
    return result.claims if isinstance(result, Extraction) else []
