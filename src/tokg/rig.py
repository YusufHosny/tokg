# ABOUTME: Rigged mode: scripted extraction, resolution and answers loaded from one YAML file, so a
# ABOUTME: demo runs deterministically with no LLM. Record mode captures a live LLM run into a rig.
from pathlib import Path
from typing import Self

import yaml
from pydantic import BaseModel, Field

from tokg.answer import Answerer, TemplateAnswerer
from tokg.extract import ClaimDraft, Extractor
from tokg.graph import KnowledgeGraph
from tokg.models import Node, Source
from tokg.resolve import Decision, ResolutionInput, Resolver, RuleResolver
from tokg.schema import Schema
from tokg.store import GraphStore
from tokg.views import Answer, NodeView


def _question_key(question: str) -> str:
  return " ".join(question.lower().split())


# claim ids are deterministic ('<source id>:<index in extractions[source id]>'), which is what
# lets `decisions` refer to claims before they exist
class Rig(BaseModel):
  extractions: dict[str, list[ClaimDraft]] = Field(default_factory=dict)
  decisions: dict[str, Decision] = Field(default_factory=dict)
  answers: dict[str, Answer] = Field(default_factory=dict)

  @classmethod
  def from_yaml(cls, path: str | Path) -> Self:
    return cls.model_validate(yaml.safe_load(Path(path).read_text()) or {})

  def extractor(self) -> "ScriptedExtractor":
    return ScriptedExtractor(self)

  def resolver(self, fallback: Resolver | None = None) -> "ScriptedResolver":
    return ScriptedResolver(self, fallback)

  def answerer(self, fallback: Answerer | None = None) -> "ScriptedAnswerer":
    return ScriptedAnswerer(self, fallback)

  def graph(self, schema: Schema, store: GraphStore | None = None, **kwargs) -> KnowledgeGraph:
    return KnowledgeGraph(schema, store=store, extractor=self.extractor(), resolver=self.resolver(),
                          answerer=self.answerer(), **kwargs)

  def save(self, path: str | Path) -> None:
    data = self.model_dump(mode="json", exclude_none=True, exclude_defaults=True)
    Path(path).write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100))

  # wrap live stages so everything they produce is written into this rig for later replay
  def record(self, graph: KnowledgeGraph) -> KnowledgeGraph:
    graph.extractor = RecordingExtractor(graph.extractor, self)
    graph.resolver = RecordingResolver(graph.resolver, self)
    graph.answerer = RecordingAnswerer(graph.answerer, self)
    return graph


class ScriptedExtractor(Extractor):
  def __init__(self, rig: Rig) -> None:
    self.rig = rig

  def extract(self, source: Source, schema: Schema, known: list[Node]) -> list[ClaimDraft]:
    return list(self.rig.extractions.get(source.id, []))


class ScriptedResolver(Resolver):
  def __init__(self, rig: Rig, fallback: Resolver | None = None) -> None:
    self.rig = rig
    self.fallback = fallback or RuleResolver()

  def resolve(self, inp: ResolutionInput) -> Decision:
    scripted = self.rig.decisions.get(inp.claim.id)
    return scripted.model_copy(deep=True) if scripted else self.fallback.resolve(inp)


class ScriptedAnswerer(Answerer):
  def __init__(self, rig: Rig, fallback: Answerer | None = None) -> None:
    self.answers = {_question_key(q): a for q, a in rig.answers.items()}
    self.fallback = fallback or TemplateAnswerer()

  def answer(self, question: str, views: list[NodeView]) -> Answer:
    scripted = self.answers.get(_question_key(question))
    return scripted.model_copy(deep=True) if scripted else self.fallback.answer(question, views)


class RecordingExtractor(Extractor):
  def __init__(self, inner: Extractor, rig: Rig) -> None:
    self.inner, self.rig = inner, rig

  def extract(self, source: Source, schema: Schema, known: list[Node]) -> list[ClaimDraft]:
    drafts = self.inner.extract(source, schema, known)
    self.rig.extractions[source.id] = drafts
    return drafts


class RecordingResolver(Resolver):
  def __init__(self, inner: Resolver, rig: Rig) -> None:
    self.inner, self.rig = inner, rig

  def resolve(self, inp: ResolutionInput) -> Decision:
    decision = self.inner.resolve(inp)
    self.rig.decisions[inp.claim.id] = decision
    return decision


class RecordingAnswerer(Answerer):
  def __init__(self, inner: Answerer, rig: Rig) -> None:
    self.inner, self.rig = inner, rig

  def answer(self, question: str, views: list[NodeView]) -> Answer:
    answer = self.inner.answer(question, views)
    self.rig.answers[question] = answer
    return answer
