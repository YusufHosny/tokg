# ABOUTME: Tests for the schema format, file ingestors and the in-memory store's JSON snapshots.
from pathlib import Path

import pytest
from conftest import DATA, OWNER, LUMIVIA, doc, make_graph, owns, rule

from tokg.ingest import EmailIngestor, JsonIngestor, MarkdownIngestor, load_sources
from tokg.models import EmailSource, MeetingSource, PortalSource
from tokg.rig import Rig
from tokg.schema import Schema
from tokg.store import MemoryStore


class TestSchema:
  def test_owner_type_is_added(self, schema):
    assert schema.entity("Person") is not None

  def test_rejects_unknown_relation_endpoints(self):
    with pytest.raises(ValueError, match="unknown entity types"):
      Schema.model_validate({"name": "x", "relations": [{"name": "r", "source": ["A"], "target": ["B"]}]})

  def test_rejects_duplicates(self):
    with pytest.raises(ValueError, match="duplicate entity"):
      Schema.model_validate({"name": "x", "entities": [{"name": "A"}, {"name": "A"}]})

  def test_checks(self, schema):
    assert schema.check_attribute("Policy", "rule") is None
    assert schema.check_attribute("Policy", "colour") is not None
    assert schema.check_relation("example_of", "Case", "Process") is None
    assert schema.check_relation("example_of", "Process", "Case") is not None
    assert schema.check_context({"planet": "Mars"}) is not None

  def test_example_schema_loads(self):
    s = Schema.from_yaml(LUMIVIA / "schema.yaml")
    assert s.relation("example_of").target == ["Policy"]
    assert "Policy" in s.prompt_repr()


EML = """From: Globex HR <hr@globex.example>
To: Lotte Janssens <lotte@sdworx.example>
Subject: Opt-out
Date: Wed, 15 Feb 2023 10:12:00 +0100
Content-Type: text/plain; charset=utf-8

We opt out.
"""


class TestIngest:
  def test_email(self, tmp_path: Path):
    (tmp_path / "globex-opt-out.eml").write_text(EML)
    [src] = EmailIngestor().load(tmp_path / "globex-opt-out.eml")
    assert isinstance(src, EmailSource)
    assert src.id == "email:globex-opt-out" and src.author == "Globex HR <hr@globex.example>"
    assert src.recipients == ["Lotte Janssens <lotte@sdworx.example>"]
    assert src.content == "We opt out." and src.timestamp.year == 2023

  def test_json_source_documents(self):
    [src] = JsonIngestor().load(DATA / "meeting" / "meeting-2025-03-11-001.json")
    assert isinstance(src, MeetingSource)
    assert src.id == "meeting-2025-03-11-001" and src.author == "meeting-bot@lumivia.be"
    assert "sophie.claes@lumivia.be" in src.participants()
    assert "Working in Belgium" in src.content

  def test_json_folder_skips_non_sources(self):
    sources = JsonIngestor().load(DATA)
    assert len(sources) == 34 and any(isinstance(s, PortalSource) for s in sources)
    with pytest.raises(ValueError, match="not a source"):
      JsonIngestor().load(DATA / "people.json")

  def test_markdown_frontmatter(self, tmp_path: Path):
    (tmp_path / "m.md").write_text("---\nkind: meeting\ntitle: Sync\nauthor: a@b.c\ndate: 2024-05-01\n"
                                   "recipients: [x@b.c]\n---\nbody")
    [src] = MarkdownIngestor().load(tmp_path / "m.md")
    assert src.id == "meeting:m" and src.kind == "meeting" and src.recipients == ["x@b.c"]
    (tmp_path / "README.md").write_text("no frontmatter")
    assert [s.id for s in MarkdownIngestor().load(tmp_path)] == ["meeting:m"]
    with pytest.raises(ValueError, match="not a source"):
      MarkdownIngestor().load(tmp_path / "README.md")

  def test_load_sources_is_chronological(self):
    sources = load_sources(DATA)
    assert len(sources) == 34
    assert sources[0].id == "wiki-2019-01-15-001" and sources[-1].id == "meeting-2026-08-20-001"


def test_snapshot_roundtrip(schema, tmp_path: Path):
  g = make_graph(schema, Rig(extractions={"doc:a": [owns(OWNER), rule("x", country="BE")]}))
  g.ingest([doc("doc:a", OWNER, "2021-01-01")])
  g.ask_owner("policy:sick-note", "q?", asked_by="person:x")
  g.store.save(tmp_path / "s.json")
  loaded = MemoryStore.load(tmp_path / "s.json")
  assert loaded.nodes() == g.store.nodes()
  assert loaded.facts() == g.store.facts()
  assert loaded.sources() == g.store.sources()
  assert loaded.escalations() == g.store.escalations()
