# ABOUTME: Seed/bootstrap tests: canonical topics and owners, org-wide authorities, speaker
# ABOUTME: attribution restricted to participants, bots never owning or asserting, and record mode.
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from conftest import NOW, FOO, make_graph, rule

from tokg.extract import MAX_KNOWN_ENTITIES, ClaimDraft, EntityMention, get_user_prompt
from tokg.models import MeetingSource, Node
from tokg.rig import Rig
from tokg.schema import Schema
from tokg.seed import Seed
from tokg.store import MemoryStore

SEED = Seed.model_validate({
  "people": [
    {"id": "olga@corp.example", "name": "Olga Owner", "role": "HR lead", "owns_topics": ["sick_note"]},
    {"id": "laura@corp.example", "name": "Laura Lead", "role": "Head of Ops"},
    {"id": "elise@corp.example", "name": "Elise Else", "role": "Office manager"},
  ],
  "topics": [{"key": "sick_note", "type": "Policy", "name": "Sick note"}],
  "authorities": ["laura@corp.example"],
  "non_people": ["bot@corp.example"],
})
POLICY, OLGA, LAURA, ELISE = ("policy:sick-note", "person:olga-corp-example",
                              "person:laura-corp-example", "person:elise-corp-example")


def src(id_: str, author: str, when: str, recipients: list[str] | None = None) -> MeetingSource:
  return MeetingSource(id=id_, title=id_, author=author, timestamp=datetime.fromisoformat(when),
                       content=id_, recipients=recipients or [])


def graph(schema: Schema, extractions: dict) -> "object":
  return make_graph(schema, Rig(extractions=extractions), seed=SEED)


def test_bootstrap_topics_owners_and_people(schema):
  g = graph(schema, {})
  node = g.store.get_node(POLICY)
  assert node.name == "Sick note" and "sick_note" in node.aliases
  assert g.owner_of(POLICY) == OLGA
  assert g.owner_of(POLICY, as_of=datetime(2000, 1, 1).astimezone()) == OLGA
  assert g.store.get_node(OLGA).properties == {"role": "HR lead", "external": "false"}
  facts = len(g.store.facts())
  g._bootstrap()
  assert len(g.store.facts()) == facts


def test_bootstrap_rejects_unknown_topics(schema):
  with pytest.raises(ValueError, match="unknown seed topic"):
    make_graph(schema, Rig(), seed=Seed.model_validate({"people": [{"id": "a@b.c", "name": "A", "owns": ["nope"]}]}))
  with pytest.raises(ValueError, match="unknown type"):
    make_graph(schema, Rig(), seed=Seed.model_validate({"topics": [{"key": "k", "type": "Nope", "name": "K"}]}))


def test_authority_supersedes_and_confirms(schema):
  g = graph(schema, {"s:old": [rule("48h note always")], "s:new": [rule("no note on day 1")]})
  g.ingest([src("s:old", "laura@corp.example", "2019-01-01"), src("s:new", "laura@corp.example", "2023-03-01")])
  new = g.store.get_fact("s:new:0")
  assert new.status == "active" and new.supersedes == ["s:old:0"] and new.confirmed_by == LAURA


def test_non_owner_trap_is_escalated(schema):
  g = graph(schema, {"s:new": [rule("no note on day 1")], "s:trap": [rule("always a note")]})
  g.ingest([src("s:new", "olga@corp.example", "2023-03-01"), src("s:trap", "elise@corp.example", "2026-01-20")])
  assert g.store.get_fact("s:trap:0").status == "pending"
  assert g.store.get_escalation("esc:s:trap:0").assignee_id == OLGA


def test_speaker_attribution_in_bot_meeting(schema):
  said = rule("no note on day 1").model_copy(update={"asserted_by": "olga@corp.example"})
  g = graph(schema, {"s:old": [rule("48h")], "m:1": [said]})
  g.ingest([src("s:old", "elise@corp.example", "2019-01-01"),
            src("m:1", "bot@corp.example", "2023-01-17", ["olga@corp.example", "elise@corp.example"])])
  fact = g.store.get_fact("m:1:0")
  assert fact.asserted_by == OLGA and fact.status == "active" and fact.confirmed_by == OLGA
  assert g.store.get_node("person:bot-corp-example") is None


def test_speaker_must_be_a_participant(schema):
  forged = rule("no note on day 1").model_copy(update={"asserted_by": "olga@corp.example"})
  g = graph(schema, {"s:old": [rule("48h")], "m:1": [forged]})
  g.ingest([src("s:old", "olga@corp.example", "2019-01-01"),
            src("m:1", "elise@corp.example", "2023-01-17", ["laura@corp.example"])])
  fact = g.store.get_fact("m:1:0")
  assert fact.asserted_by == ELISE and fact.status == "pending"


def test_bot_author_without_speaker_needs_approval(schema):
  g = graph(schema, {"s:old": [rule("48h")], "m:1": [rule("no note on day 1")]})
  g.ingest([src("s:old", "olga@corp.example", "2019-01-01"), src("m:1", "bot@corp.example", "2023-01-17")])
  assert g.store.get_fact("m:1:0").asserted_by is None
  assert g.store.get_fact("m:1:0").status == "pending"


def test_bots_cannot_own(schema):
  bad = ClaimDraft(kind="ownership", subject=EntityMention(type="Policy", name="Sick note"), owner="bot@corp.example")
  g = graph(schema, {"m:1": [bad]})
  report = g.ingest([src("m:1", "olga@corp.example", "2023-01-17")])
  assert "cannot own" in report.skipped[0].error


def test_record_then_replay(schema, tmp_path: Path):
  live = Rig(extractions={"s:old": [rule("48h")], "s:new": [rule("no note on day 1")]}).graph(schema, seed=SEED)
  recording = Rig()
  recording.record(live)
  live.ingest([src("s:old", "olga@corp.example", "2019-01-01"), src("s:new", "olga@corp.example", "2023-03-01")])
  live.ask("sick note?")
  recording.save(tmp_path / "rig.yaml")

  replay = Rig.from_yaml(tmp_path / "rig.yaml")
  assert set(replay.extractions) == {"s:old", "s:new"} and replay.decisions["s:new:0"].action == "supersede"
  assert list(replay.answers) == ["sick note?"]
  g = replay.graph(schema, seed=SEED, clock=lambda: NOW)
  g.ingest([src("s:old", "olga@corp.example", "2019-01-01"), src("s:new", "olga@corp.example", "2023-03-01")])
  assert g.store.get_fact("s:new:0").supersedes == ["s:old:0"]


def test_example_seed_matches_example_schema():
  g = Rig().graph(Schema.from_yaml(FOO / "schema.yaml"), seed=Seed.from_yaml(FOO / "seed.yaml"))
  assert g.owner_of("policy:hire-non-eu") == "person:sophie-claes-foo-be"
  assert g.owner_of("policy:sick-leave-certificate") == "person:marc-dubois-sdworx-com"
  assert g.owner_of("policy:hardware-purchasing") == "person:tom-verbeke-foo-be"


def test_display_name_cannot_impersonate_a_person(schema):
  said = rule("no note on day 1").model_copy(update={"asserted_by": "Olga Owner"})
  g = graph(schema, {"s:old": [rule("48h")], "s:fake": [rule("no note on day 1")], "m:1": [said]})
  g.ingest([src("s:old", "olga@corp.example", "2019-01-01"),
            src("s:fake", "Olga Owner <olga@evil.example>", "2023-01-01"),
            src("m:1", "elise@corp.example", "2023-02-01", ["Olga Owner <olga@corp.example>"])])
  fake = g.store.get_fact("s:fake:0")
  assert fake.asserted_by == "person:olga-evil-example" and fake.status == "pending"
  assert g.store.get_node(OLGA).aliases == ["olga@corp.example"]
  assert g.store.get_fact("m:1:0").asserted_by == ELISE
  assert g._find_person("Olga Owner").id == OLGA and g._find_person("Olga Owner", by_name=False) is None
  assert g._find_person("Olga Owner <nobody@corp.example>") is None


def test_bare_name_owner_never_resolves_to_a_known_person(schema):
  g = graph(schema, {"s:1": [ClaimDraft(kind="ownership", subject=EntityMention(type="Policy", name="Expenses"),
                                        owner="olga-corp-example")]})
  g.ingest([src("s:1", "elise@corp.example", "2023-01-01")])
  assert g.owner_of("policy:expenses") == "person:olga-corp-example-0"


def test_known_entities_prompt_keeps_seeded_topics_and_is_capped(schema):
  g = graph(schema, {})
  ticks = iter(range(MAX_KNOWN_ENTITIES + 50))
  g.clock = lambda: NOW + timedelta(seconds=next(ticks))
  for i in range(MAX_KNOWN_ENTITIES + 50):
    g._ensure_node(EntityMention(type="Case", name=f"Case {i}"))
  known = g._known_nodes()
  assert known[0].id == POLICY and known[1].name == f"Case {MAX_KNOWN_ENTITIES + 49}"
  prompt = get_user_prompt(src("s:1", "olga@corp.example", "2023-01-01"), known)
  assert prompt.count("\n- ") == MAX_KNOWN_ENTITIES and '"Sick note"' in prompt


def test_bootstrap_adopts_a_squatted_person_id(schema):
  store = MemoryStore()
  store.put_node(Node(id=OLGA, type="Person", name="squatter"))
  g = make_graph(schema, Rig(), store=store, seed=SEED)
  node = g.store.get_node(OLGA)
  assert node.aliases == ["olga@corp.example"] and node.name == "Olga Owner"
  assert g.owner_of(POLICY) == OLGA and g.store.get_node(f"{OLGA}-0") is None
