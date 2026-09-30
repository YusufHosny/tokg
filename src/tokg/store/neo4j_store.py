# ABOUTME: Neo4j-backed GraphStore (untested). Each model is a labelled node holding its JSON,
# ABOUTME: plus SUBJECT/TARGET/OWNER edges so the graph is browsable in Neo4j Browser/Bloom.
from typing import Any

from pydantic import TypeAdapter

from tokg.models import Escalation, Fact, Node, Source
from tokg.store.base import GraphStore

_SOURCE = TypeAdapter(Source)


class Neo4jStore(GraphStore):
  def __init__(self, uri: str, user: str, password: str, database: str | None = None,
               driver: Any = None) -> None:
    if driver is None:
      from neo4j import GraphDatabase  # optional dependency: `uv sync --extra neo4j`
      driver = GraphDatabase.driver(uri, auth=(user, password))
    self._driver = driver
    self._database = database

  def close(self) -> None:
    self._driver.close()

  def _write(self, query: str, **params: Any) -> None:
    with self._driver.session(database=self._database) as session:
      session.execute_write(lambda tx: tx.run(query, **params).consume())

  def _read(self, query: str, **params: Any) -> list[str]:
    with self._driver.session(database=self._database) as session:
      return session.execute_read(lambda tx: [r["data"] for r in tx.run(query, **params)])

  def put_node(self, node: Node) -> None:
    self._write("MERGE (n:TokgNode {id: $id}) SET n.type = $type, n.name = $name, n.data = $data",
                id=node.id, type=node.type, name=node.name, data=node.model_dump_json())

  def get_node(self, node_id: str) -> Node | None:
    rows = self._read("MATCH (n:TokgNode {id: $id}) RETURN n.data AS data", id=node_id)
    return Node.model_validate_json(rows[0]) if rows else None

  def nodes(self, type_: str | None = None) -> list[Node]:
    rows = self._read("MATCH (n:TokgNode) WHERE $type IS NULL OR n.type = $type RETURN n.data AS data",
                      type=type_)
    return [Node.model_validate_json(r) for r in rows]

  def put_fact(self, fact: Fact) -> None:
    target = getattr(fact.statement, "target_id", None) or getattr(fact.statement, "owner_id", None)
    self._write(
      """
      MERGE (f:TokgFact {id: $id})
      SET f.subject_id = $subject_id, f.target_id = $target_id, f.kind = $kind,
          f.status = $status, f.data = $data
      WITH f
      MATCH (s:TokgNode {id: $subject_id})
      MERGE (f)-[:SUBJECT]->(s)
      WITH f
      OPTIONAL MATCH (t:TokgNode {id: $target_id})
      FOREACH (_ IN CASE WHEN t IS NULL THEN [] ELSE [1] END | MERGE (f)-[:TARGET]->(t))
      """,
      id=fact.id, subject_id=fact.subject_id, target_id=target, kind=fact.statement.kind,
      status=fact.status, data=fact.model_dump_json())

  def get_fact(self, fact_id: str) -> Fact | None:
    rows = self._read("MATCH (f:TokgFact {id: $id}) RETURN f.data AS data", id=fact_id)
    return Fact.model_validate_json(rows[0]) if rows else None

  def facts(self, subject_id: str | None = None, target_id: str | None = None) -> list[Fact]:
    rows = self._read(
      """
      MATCH (f:TokgFact)
      WHERE ($subject_id IS NULL OR f.subject_id = $subject_id)
        AND ($target_id IS NULL OR (f.kind = 'relation' AND f.target_id = $target_id))
      RETURN f.data AS data
      """, subject_id=subject_id, target_id=target_id)
    return [Fact.model_validate_json(r) for r in rows]

  def put_source(self, source: Source) -> None:
    self._write("MERGE (s:TokgSource {id: $id}) SET s.kind = $kind, s.data = $data",
                id=source.id, kind=source.kind, data=source.model_dump_json())

  def get_source(self, source_id: str) -> Source | None:
    rows = self._read("MATCH (s:TokgSource {id: $id}) RETURN s.data AS data", id=source_id)
    return _SOURCE.validate_json(rows[0]) if rows else None

  def sources(self) -> list[Source]:
    return [_SOURCE.validate_json(r) for r in self._read("MATCH (s:TokgSource) RETURN s.data AS data")]

  def put_escalation(self, escalation: Escalation) -> None:
    self._write("MERGE (e:TokgEscalation {id: $id}) SET e.status = $status, e.data = $data",
                id=escalation.id, status=escalation.status, data=escalation.model_dump_json())

  def get_escalation(self, escalation_id: str) -> Escalation | None:
    rows = self._read("MATCH (e:TokgEscalation {id: $id}) RETURN e.data AS data", id=escalation_id)
    return Escalation.model_validate_json(rows[0]) if rows else None

  def escalations(self) -> list[Escalation]:
    rows = self._read("MATCH (e:TokgEscalation) RETURN e.data AS data")
    return [Escalation.model_validate_json(r) for r in rows]
