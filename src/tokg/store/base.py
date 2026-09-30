# ABOUTME: GraphStore contract: dumb CRUD over nodes, facts, sources and escalations.
# ABOUTME: All semantics (temporal, ownership, resolution) live in KnowledgeGraph, not in stores.
from abc import ABC

from tokg.models import Escalation, Fact, Node, Source


class GraphStore(ABC):
  def put_node(self, node: Node) -> None:
    raise NotImplementedError("put_node should be implemented by subclasses")

  def get_node(self, node_id: str) -> Node | None:
    raise NotImplementedError("get_node should be implemented by subclasses")

  def nodes(self, type_: str | None = None) -> list[Node]:
    raise NotImplementedError("nodes should be implemented by subclasses")

  def put_fact(self, fact: Fact) -> None:
    raise NotImplementedError("put_fact should be implemented by subclasses")

  def get_fact(self, fact_id: str) -> Fact | None:
    raise NotImplementedError("get_fact should be implemented by subclasses")

  # subject_id / target_id filter to facts about a node / relation facts pointing at a node
  def facts(self, subject_id: str | None = None, target_id: str | None = None) -> list[Fact]:
    raise NotImplementedError("facts should be implemented by subclasses")

  def put_source(self, source: Source) -> None:
    raise NotImplementedError("put_source should be implemented by subclasses")

  def get_source(self, source_id: str) -> Source | None:
    raise NotImplementedError("get_source should be implemented by subclasses")

  def sources(self) -> list[Source]:
    raise NotImplementedError("sources should be implemented by subclasses")

  def put_escalation(self, escalation: Escalation) -> None:
    raise NotImplementedError("put_escalation should be implemented by subclasses")

  def get_escalation(self, escalation_id: str) -> Escalation | None:
    raise NotImplementedError("get_escalation should be implemented by subclasses")

  def escalations(self) -> list[Escalation]:
    raise NotImplementedError("escalations should be implemented by subclasses")
