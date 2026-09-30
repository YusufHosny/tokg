# ABOUTME: Seed/bootstrap tests: canonical topics and owners, org-wide authorities, speaker
# ABOUTME: attribution restricted to participants, bots never owning or asserting, and record mode.
from datetime import datetime
from pathlib import Path

import pytest
from conftest import NOW, LUMIVIA, make_graph, rule

from tokg.extract import ClaimDraft, EntityMention
from tokg.models import MeetingSource
from tokg.rig import Rig
from tokg.schema import Schema
from tokg.seed import Seed

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
  g = Rig().graph(Schema.from_yaml(LUMIVIA / "schema.yaml"), seed=Seed.from_yaml(LUMIVIA / "seed.yaml"))
  assert g.owner_of("policy:hire-non-eu") == "person:sophie-claes-lumivia-be"
  assert g.owner_of("policy:sick-leave-certificate") == "person:marc-dubois-sdworx-com"
  assert g.owner_of("policy:hardware-purchasing") == "person:tom-verbeke-lumivia-be"
