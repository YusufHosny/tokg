# ABOUTME: Shared fixtures: a tiny schema, source/claim builders and a rigged graph with a fixed
# ABOUTME: clock, so every test is deterministic and LLM-free.
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tokg.extract import ClaimDraft, EntityMention
from tokg.graph import KnowledgeGraph
from tokg.models import DocumentSource
from tokg.rig import Rig
from tokg.schema import Schema

EXAMPLES = Path(__file__).parent.parent / "examples"
DATA = EXAMPLES / "data"
FOO = EXAMPLES / "foo"
NOW = datetime(2026, 9, 30, tzinfo=UTC)

OWNER = "Olga Owner <olga@corp.example>"
OWNER_ID = "person:olga-corp-example"
OTHER = "Nils Nobody <nils@corp.example>"
OTHER_ID = "person:nils-corp-example"


@pytest.fixture
def schema() -> Schema:
  return Schema.model_validate({
    "name": "test",
    "entities": [
      {"name": "Policy", "attributes": [{"name": "rule"}]},
      {"name": "Process", "attributes": [{"name": "procedure"}]},
      {"name": "Case", "attributes": [{"name": "summary"}]},
      {"name": "Client"},
    ],
    "relations": [{"name": "example_of", "source": ["Case"], "target": ["Process"]}],
    "context": [{"name": "country"}, {"name": "client", "entity": "Client"}],
  })


def doc(id_: str, author: str, when: str, content: str = "") -> DocumentSource:
  return DocumentSource(id=id_, title=id_, author=author, timestamp=datetime.fromisoformat(when),
                        content=content or id_)


def rule(value: str, subject: str = "Sick note", **context: str) -> ClaimDraft:
  return ClaimDraft(kind="attribute", subject=EntityMention(type="Policy", name=subject),
                    attribute="rule", value=value, context=context, quote=value)


def owns(owner: str, subject: str = "Sick note", type_: str = "Policy") -> ClaimDraft:
  return ClaimDraft(kind="ownership", subject=EntityMention(type=type_, name=subject), owner=owner)


def make_graph(schema: Schema, rig: Rig, **kwargs) -> KnowledgeGraph:
  return rig.graph(schema, clock=lambda: NOW, **kwargs)
