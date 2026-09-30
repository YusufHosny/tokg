# ABOUTME: In-memory GraphStore with JSON snapshots for backup/restore.
# ABOUTME: JSON instead of pickle so loading a snapshot can never execute code.
from pathlib import Path
from typing import Self

from pydantic import BaseModel, Field, TypeAdapter

from tokg.models import Escalation, Fact, Node, Source
from tokg.safeio import MAX_SNAPSHOT_BYTES, read_bytes, write_text_atomic
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
    self._seq: dict[str, int] = {}
    self._fact_keys: dict[str, tuple[str, str | None]] = {}
    self._by_subject: dict[str, dict[str, None]] = {}
    self._by_target: dict[str, dict[str, None]] = {}
    self._sources: dict[str, Source] = {}
    self._escalations: dict[str, Escalation] = {}

  def put_node(self, node: Node) -> None:
    self._nodes[node.id] = node

  def get_node(self, node_id: str) -> Node | None:
    return self._nodes.get(node_id)

  def nodes(self, type_: str | None = None) -> list[Node]:
    return [n for n in self._nodes.values() if type_ is None or n.type == type_]

  def put_fact(self, fact: Fact) -> None:
    keys = (fact.subject_id, getattr(fact.statement, "target_id", None))
    if (old := self._fact_keys.get(fact.id)) != keys:
      if old is not None:
        self._unindex(fact.id, *old)
      self._by_subject.setdefault(keys[0], {})[fact.id] = None
      if keys[1] is not None:
        self._by_target.setdefault(keys[1], {})[fact.id] = None
      self._fact_keys[fact.id] = keys
    self._seq.setdefault(fact.id, len(self._seq))
    self._facts[fact.id] = fact

  def _unindex(self, fact_id: str, subject_id: str, target_id: str | None) -> None:
    for index, key in ((self._by_subject, subject_id), (self._by_target, target_id)):
      if key is not None and (ids := index.get(key)) is not None:
        ids.pop(fact_id, None)
        if not ids:
          del index[key]

  def get_fact(self, fact_id: str) -> Fact | None:
    return self._facts.get(fact_id)

  def facts(self, subject_id: str | None = None, target_id: str | None = None) -> list[Fact]:
    if subject_id is None and target_id is None:
      return list(self._facts.values())
    targeted = self._by_target.get(target_id, {}) if target_id is not None else None
    ids = list(targeted or {}) if subject_id is None else \
      [i for i in self._by_subject.get(subject_id, {}) if targeted is None or i in targeted]
    return [self._facts[i] for i in sorted(ids, key=self._seq.__getitem__)]

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
    write_text_atomic(path, snap.model_dump_json(indent=2))

  @classmethod
  def load(cls, path: str | Path) -> Self:
    snap = TypeAdapter(_Snapshot).validate_json(read_bytes(path, MAX_SNAPSHOT_BYTES))
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
