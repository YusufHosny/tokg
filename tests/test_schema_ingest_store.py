# ABOUTME: Tests for the schema format, file ingestors and the in-memory store's JSON snapshots.
import stat
from pathlib import Path

import pytest
import yaml
from conftest import DATA, NOW, OWNER, FOO, doc, make_graph, owns, rule

from tokg.ingest import EmailIngestor, JsonIngestor, MarkdownIngestor, load_sources
from tokg.models import AttributeStatement, EmailSource, Fact, MeetingSource, Node, PortalSource, RelationStatement
from tokg.rig import Rig
from tokg.schema import Schema
from tokg.seed import Seed
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
    s = Schema.from_yaml(FOO / "schema.yaml")
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
    assert src.id == "meeting-2025-03-11-001" and src.author == "meeting-bot@foo.be"
    assert "sophie.claes@foo.be" in src.participants()
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


def test_store_indexes_follow_overwrites():
  store = MemoryStore()
  store.put_fact(Fact(id="f1", subject_id="a", statement=RelationStatement(relation="r", target_id="t"), valid_from=NOW))
  store.put_fact(Fact(id="f2", subject_id="a", statement=AttributeStatement(attribute="x", value="1"), valid_from=NOW))
  store.put_fact(Fact(id="f1", subject_id="b", statement=RelationStatement(relation="r", target_id="u"), valid_from=NOW))
  assert [f.id for f in store.facts(subject_id="a")] == ["f2"]
  assert [f.id for f in store.facts(subject_id="b", target_id="u")] == ["f1"]
  assert store.facts(target_id="t") == [] and store.facts(subject_id="a", target_id="u") == []
  assert [f.id for f in store.facts()] == ["f1", "f2"]


def test_empty_slugs_never_collide():
  first, second = Node.make_id("Policy", "!!!"), Node.make_id("Policy", "???")
  assert first.startswith("policy:h-") and first != second
  assert Node.make_id("Policy", "Sick note") == "policy:sick-note"
  assert not Node(id=first, type="Policy", name="!!!").matches("???")


class TestGuards:
  def test_email_without_date_names_the_file(self, tmp_path: Path):
    (tmp_path / "a.eml").write_text(EML.replace("Date: Wed, 15 Feb 2023 10:12:00 +0100\n", ""))
    (tmp_path / "b.eml").write_text(EML.replace("Wed, 15 Feb 2023 10:12:00 +0100", "not a date"))
    for name in ("a.eml", "b.eml"):
      with pytest.raises(ValueError, match=f"{name}: missing or invalid Date header"):
        EmailIngestor().load(tmp_path / name)

  def test_folder_scan_skips_symlinks_out_of_root(self, tmp_path: Path):
    outside, root = tmp_path / "outside", tmp_path / "root"
    outside.mkdir()
    root.mkdir()
    (outside / "secret.eml").write_text(EML)
    (root / "inside.eml").write_text(EML)
    (root / "leak.eml").symlink_to(outside / "secret.eml")
    (root / "dir").symlink_to(outside, target_is_directory=True)
    assert [s.id for s in EmailIngestor().load(root)] == ["email:inside"]

  def test_oversized_and_non_regular_files_are_rejected(self, tmp_path: Path, monkeypatch):
    monkeypatch.setattr("tokg.ingest.MAX_SOURCE_BYTES", 10)
    (tmp_path / "a.eml").write_text(EML)
    with pytest.raises(ValueError, match="larger than 10 bytes"):
      EmailIngestor().load(tmp_path / "a.eml")
    with pytest.raises(ValueError, match="not a regular file"):
      JsonIngestor().parse(tmp_path)

  def test_folder_file_count_is_capped(self, tmp_path: Path, monkeypatch):
    monkeypatch.setattr("tokg.ingest.MAX_FOLDER_FILES", 1)
    (tmp_path / "a.eml").write_text(EML)
    (tmp_path / "b.eml").write_text(EML)
    with pytest.raises(ValueError, match="more than 1"):
      EmailIngestor().load(tmp_path)

  def test_yaml_alias_bomb_and_unsafe_tags_are_rejected(self, tmp_path: Path):
    bomb = "a: &a [x, x, x, x, x, x, x, x, x]\n" + "".join(
      f"{c}: &{c} [{', '.join([f'*{p}'] * 9)}]\n" for p, c in zip("abcdefgh", "bcdefghi"))
    (tmp_path / "m.md").write_text(f"---\n{bomb}---\nbody")
    with pytest.raises(ValueError, match="more than 1000000 values"):
      MarkdownIngestor().load(tmp_path / "m.md")
    (tmp_path / "evil.yaml").write_text("name: !!python/object/apply:os.system ['true']\n")
    with pytest.raises(yaml.YAMLError):
      Schema.from_yaml(tmp_path / "evil.yaml")

  def test_deep_json_is_rejected(self, tmp_path: Path):
    (tmp_path / "d.json").write_text("[" * 100_000 + "]" * 100_000)
    with pytest.raises(ValueError, match="d.json: invalid JSON"):
      JsonIngestor().load(tmp_path / "d.json")

  def test_unterminated_frontmatter_names_the_file(self, tmp_path: Path):
    (tmp_path / "m.md").write_text("---\nkind: meeting\n")
    with pytest.raises(ValueError, match="m.md: unterminated frontmatter"):
      MarkdownIngestor().load(tmp_path / "m.md")

  def test_seed_people_file_must_be_relative_data(self, tmp_path: Path):
    (tmp_path / "seed.yaml").write_text("people_file: /etc/passwd\n")
    with pytest.raises(ValueError, match="relative path"):
      Seed.from_yaml(tmp_path / "seed.yaml")
    (tmp_path / "seed.yaml").write_text("people_file: notes.txt\n")
    with pytest.raises(ValueError, match="people_file must be one of"):
      Seed.from_yaml(tmp_path / "seed.yaml")
    (tmp_path / "people.json").write_text('[{"id": "a@b.c", "name": "A"}]')
    (tmp_path / "seed.yaml").write_text("people_file: people.json\n")
    assert [p.id for p in Seed.from_yaml(tmp_path / "seed.yaml").people] == ["a@b.c"]

  def test_saves_are_atomic_and_owner_only(self, tmp_path: Path):
    target = tmp_path / "s.json"
    target.write_text("old")
    target.chmod(0o644)
    MemoryStore().save(target)
    Rig().save(tmp_path / "rig.yaml")
    for p in (target, tmp_path / "rig.yaml"):
      assert stat.S_IMODE(p.stat().st_mode) == 0o600
    assert sorted(p.name for p in tmp_path.iterdir()) == ["rig.yaml", "s.json"]
    assert MemoryStore.load(target).nodes() == []

  def test_save_replaces_symlink_instead_of_following_it(self, tmp_path: Path):
    victim = tmp_path / "victim.txt"
    victim.write_text("keep")
    (tmp_path / "s.json").symlink_to(victim)
    MemoryStore().save(tmp_path / "s.json")
    assert victim.read_text() == "keep" and not (tmp_path / "s.json").is_symlink()

  def test_invalid_snapshot_is_rejected(self, tmp_path: Path):
    (tmp_path / "s.json").write_text('{"nodes": [{"id": 1}]}')
    with pytest.raises(ValueError):
      MemoryStore.load(tmp_path / "s.json")


def test_yaml_merge_key_bombs_are_rejected(tmp_path: Path):
  lines = ["a0: &a0 {k: 1}"] + [f"a{i}: &a{i} {{<<: [*a{i - 1}, *a{i - 1}]}}" for i in range(1, 40)]
  (tmp_path / "bomb.yaml").write_text("\n".join(lines))
  with pytest.raises(ValueError, match="merge keys"):
    Schema.from_yaml(tmp_path / "bomb.yaml")
