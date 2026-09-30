# ABOUTME: In-memory GraphStore with JSON snapshots for backup/restore.
# ABOUTME: JSON instead of pickle so loading a snapshot can never execute code.
from pathlib import Path
from typing import Self

from pydantic import BaseModel, Field, TypeAdapter

from tokg.models import Escalation, Fact, Node, Source
from tokg.store.base import GraphStore


class _Snapshot(BaseModel):
  nodes: list[Node] = Field(default_factory=list)
  facts: list[Fact] = Field(default_factory=list)
  sources: list[Source] = Field(default_factory=list)
  escalations: list[Escalation] = Field(default_factory=list)


class MemoryStore(GraphStore):
  def __init__(self) -> None:
    self._nodes: dict[str, Node] = {}
    self._facts: dict[str, Fact] = {}
    self._sources: dict[str, Source] = {}
    self._escalations: dict[str, Escalation] = {}

  def put_node(self, node: Node) -> None:
    self._nodes[node.id] = node

  def get_node(self, node_id: str) -> Node | None:
    return self._nodes.get(node_id)

  def nodes(self, type_: str | None = None) -> list[Node]:
    return [n for n in self._nodes.values() if type_ is None or n.type == type_]

  def put_fact(self, fact: Fact) -> None:
    self._facts[fact.id] = fact

  def get_fact(self, fact_id: str) -> Fact | None:
    return self._facts.get(fact_id)

  def facts(self, subject_id: str | None = None, target_id: str | None = None) -> list[Fact]:
    return [f for f in self._facts.values()
            if (subject_id is None or f.subject_id == subject_id)
            and (target_id is None or getattr(f.statement, "target_id", None) == target_id)]

  def put_source(self, source: Source) -> None:
    self._sources[source.id] = source

  def get_source(self, source_id: str) -> Source | None:
    return self._sources.get(source_id)

  def sources(self) -> list[Source]:
    return list(self._sources.values())

  def put_escalation(self, escalation: Escalation) -> None:
    self._escalations[escalation.id] = escalation

  def get_escalation(self, escalation_id: str) -> Escalation | None:
    return self._escalations.get(escalation_id)

  def escalations(self) -> list[Escalation]:
    return list(self._escalations.values())

  def save(self, path: str | Path) -> None:
    snap = _Snapshot(nodes=self.nodes(), facts=self.facts(), sources=self.sources(),
                     escalations=self.escalations())
    Path(path).write_text(snap.model_dump_json(indent=2))

  @classmethod
  def load(cls, path: str | Path) -> Self:
    snap = TypeAdapter(_Snapshot).validate_json(Path(path).read_text())
    store = cls()
    for n in snap.nodes:
      store.put_node(n)
    for f in snap.facts:
      store.put_fact(f)
    for s in snap.sources:
      store.put_source(s)
    for e in snap.escalations:
      store.put_escalation(e)
    return store
