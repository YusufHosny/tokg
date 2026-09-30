# ABOUTME: KnowledgeGraph pipeline tests: resolution outcomes, ownership enforcement, escalation
# ABOUTME: authorization, answers flowing back, and context/time-aware views.
from datetime import UTC, datetime

import pytest
from conftest import NOW, OTHER, OTHER_ID, OWNER, OWNER_ID, doc, make_graph, owns, rule

from tokg.extract import ClaimDraft, EntityMention
from tokg.models import AttributeStatement
from tokg.resolve import Decision
from tokg.rig import Rig

POLICY = "policy:sick-note"


def owned_graph(schema, extra: dict | None = None, decisions: dict | None = None, **kw):
  rig = Rig(extractions={"doc:owner": [owns(OWNER)], **(extra or {})},
            decisions={k: Decision.model_validate(v) for k, v in (decisions or {}).items()})
  g = make_graph(schema, rig, **kw)
  g.ingest([doc("doc:owner", OWNER, "2020-01-01")])
  return g


def test_create_then_owner_supersedes(schema):
  g = owned_graph(schema, {"doc:a": [rule("note always")], "doc:b": [rule("no note day 1")]})
  g.ingest([doc("doc:a", OWNER, "2021-01-01"), doc("doc:b", OWNER, "2022-01-01")])
  old, new = g.store.get_fact("doc:a:0"), g.store.get_fact("doc:b:0")
  assert new.status == "active" and new.supersedes == ["doc:a:0"] and new.confirmed_by == OWNER_ID
  assert old.superseded_by == "doc:b:0" and old.valid_to == new.valid_from
  view = g.view(POLICY)
  assert [fv.fact.id for fv in view.current if fv.fact.statement.kind == "attribute"] == ["doc:b:0"]
  rule_view = next(fv for fv in view.current if fv.fact.id == "doc:b:0")
  assert [f.id for f in rule_view.history] == ["doc:a:0"]
  assert rule_view.trust == "confirmed"


def test_same_value_confirms_and_adds_source(schema):
  g = owned_graph(schema, {"doc:a": [rule("note always")], "doc:b": [rule("note always")]})
  report = g.ingest([doc("doc:a", OTHER, "2021-01-01"), doc("doc:b", OWNER, "2022-01-01")])
  assert [o.decision.action for o in report.outcomes if o.decision] == ["create", "confirm"]
  fact = g.store.get_fact("doc:a:0")
  assert [r.source_id for r in fact.sources] == ["doc:a", "doc:b"]
  assert fact.confirmed_by == OWNER_ID
  assert g.store.get_fact("doc:b:0") is None


def test_non_owner_change_is_escalated_to_owner(schema):
  g = owned_graph(schema, {"doc:a": [rule("note always")], "doc:b": [rule("no note day 1")]})
  g.ingest([doc("doc:a", OWNER, "2021-01-01"), doc("doc:b", OTHER, "2022-01-01")])
  assert g.store.get_fact("doc:b:0").status == "pending"
  esc = g.store.get_escalation("esc:doc:b:0")
  assert esc.reason == "approval" and esc.assignee_id == OWNER_ID and esc.raised_by == OTHER_ID
  view = g.view(POLICY)
  assert [fv.fact.id for fv in view.pending] == ["doc:b:0"]
  assert any(fv.fact.id == "doc:a:0" for fv in view.current)


def test_scripted_supersede_by_non_owner_is_downgraded(schema):
  g = owned_graph(schema, {"doc:a": [rule("note always")], "doc:b": [rule("no note day 1")]},
                  decisions={"doc:b:0": {"action": "supersede", "target_fact_ids": ["doc:a:0"],
                                         "rationale": "rigged"}})
  g.ingest([doc("doc:a", OWNER, "2021-01-01"), doc("doc:b", OTHER, "2022-01-01")])
  assert g.store.get_fact("doc:b:0").status == "pending"
  assert g.store.get_fact("doc:a:0").valid_to is None


def test_enforcement_can_be_disabled(schema):
  g = owned_graph(schema, {"doc:a": [rule("note always")], "doc:b": [rule("no note day 1")]},
                  decisions={"doc:b:0": {"action": "supersede", "target_fact_ids": ["doc:a:0"],
                                         "rationale": "rigged"}}, enforce_ownership=False)
  g.ingest([doc("doc:a", OWNER, "2021-01-01"), doc("doc:b", OTHER, "2022-01-01")])
  assert g.store.get_fact("doc:b:0").status == "active"


def test_older_claim_is_ignored(schema):
  g = owned_graph(schema, {"doc:a": [rule("new")], "doc:b": [rule("old").model_copy(
    update={"valid_from": datetime(2019, 1, 1).date()})]})
  report = g.ingest([doc("doc:a", OWNER, "2021-01-01"), doc("doc:b", OWNER, "2022-01-01")])
  assert report.outcomes[-1].decision.action == "ignore"


class TestEscalations:
  @pytest.fixture
  def g(self, schema):
    g = owned_graph(schema, {"doc:a": [rule("note always")], "doc:b": [rule("no note day 1")]})
    g.ingest([doc("doc:a", OWNER, "2021-01-01"), doc("doc:b", OTHER, "2022-01-01")])
    return g

  def test_only_assignee_can_resolve(self, g):
    with pytest.raises(PermissionError):
      g.resolve_escalation("esc:doc:b:0", OTHER_ID, "approve")

  def test_approve_activates_and_supersedes(self, g):
    esc = g.resolve_escalation("esc:doc:b:0", OWNER_ID, "approve", note="correct")
    assert esc.status == "approved" and esc.resolved_by == OWNER_ID
    new, old = g.store.get_fact("doc:b:0"), g.store.get_fact("doc:a:0")
    assert new.status == "active" and new.confirmed_by == OWNER_ID
    assert old.superseded_by == "doc:b:0"
    with pytest.raises(ValueError):
      g.resolve_escalation("esc:doc:b:0", OWNER_ID, "approve")

  def test_reject_keeps_old_fact(self, g):
    g.resolve_escalation("esc:doc:b:0", OWNER_ID, "reject")
    assert g.store.get_fact("doc:b:0").status == "rejected"
    assert g.store.get_fact("doc:a:0").valid_to is None

  def test_unknown_escalation(self, g):
    with pytest.raises(KeyError):
      g.resolve_escalation("esc:nope", OWNER_ID, "approve")


def test_question_answer_flows_back_into_graph(schema):
  answer_drafts = [rule("opt-out filed", client="Acme")]
  g = owned_graph(schema, {"note:esc:q:policy-sick-note:0": answer_drafts})
  esc = g.ask_owner(POLICY, "Did Acme opt out?", asked_by=OTHER_ID)
  assert esc.assignee_id == OWNER_ID and esc.reason == "question"
  with pytest.raises(PermissionError):
    g.answer_escalation(esc.id, OTHER_ID, "yes")
  report = g.answer_escalation(esc.id, OWNER_ID, "Yes, Acme filed an opt-out.")
  assert g.store.get_escalation(esc.id).status == "answered"
  assert report.outcomes[0].decision.action == "create"
  fact = g.store.get_fact("note:esc:q:policy-sick-note:0:0")
  assert fact.confirmed_by == OWNER_ID and fact.context == {"client": "client:acme"}


def test_assign_owner_hands_over_unassigned_escalations(schema):
  g = make_graph(schema, Rig())
  g.ingest([doc("doc:x", OTHER, "2021-01-01")])
  g._ensure_node(EntityMention(type="Policy", name="Sick note"))
  esc = g.ask_owner(POLICY, "who owns this?", asked_by=OTHER_ID)
  assert esc.assignee_id is None
  with pytest.raises(PermissionError):
    g.answer_escalation(esc.id, OTHER_ID, "me")
  g.assign_owner(POLICY, OWNER, assigned_by="person:admin")
  assert g.owner_of(POLICY) == OWNER_ID
  assert g.store.get_escalation(esc.id).assignee_id == OWNER_ID


def test_ownership_handover_by_owner(schema):
  g = owned_graph(schema, {"doc:h": [owns(OTHER)]})
  g.ingest([doc("doc:h", OWNER, "2023-01-01")])
  assert g.owner_of(POLICY) == OTHER_ID
  assert g.owner_of(POLICY, as_of=datetime(2022, 1, 1, tzinfo=UTC)) == OWNER_ID


def test_invalid_claims_are_skipped_without_debris(schema):
  bad = [
    ClaimDraft(kind="attribute", subject=EntityMention(type="Nope", name="x"), attribute="rule", value="v"),
    ClaimDraft(kind="attribute", subject=EntityMention(type="Policy", name="Ghost"), attribute="colour", value="v"),
    ClaimDraft(kind="relation", subject=EntityMention(type="Policy", name="Ghost"), relation="example_of",
               target=EntityMention(type="Process", name="P")),
    rule("v", subject="Ghost", planet="Mars"),
    ClaimDraft(kind="ownership", subject=EntityMention(type="Policy", name="Ghost")),
  ]
  g = make_graph(schema, Rig(extractions={"doc:bad": bad}))
  report = g.ingest([doc("doc:bad", OTHER, "2021-01-01")])
  assert len(report.skipped) == len(bad)
  assert g.store.get_node("policy:ghost") is None and g.store.facts() == []


def test_reingest_is_idempotent_but_rewrites_are_refused(schema):
  g = owned_graph(schema, {"doc:a": [rule("note always")]})
  g.ingest([doc("doc:a", OWNER, "2021-01-01")])
  report = g.ingest([doc("doc:a", OWNER, "2021-01-01")])
  assert report.outcomes == [] and report.source_ids == []
  with pytest.raises(ValueError):
    g.ingest([doc("doc:a", OWNER, "2021-01-01", content="tampered")])


class TestViews:
  @pytest.fixture
  def g(self, schema):
    g = owned_graph(schema, {
      "doc:legacy": [rule("48h note always", client="Acme")],
      "doc:law": [rule("no note on day 1", country="BE")],
      "doc:optout": [rule("note from day 1", client="Globex")],
      "doc:clients": [owns("jan@corp.example", "Acme", "Client"), owns("lotte@corp.example", "Globex", "Client")],
      "doc:case": [ClaimDraft(kind="relation", subject=EntityMention(type="Case", name="Hire 1"),
                              relation="example_of", target=EntityMention(type="Process", name="Permit")),
                   owns("hm@corp.example", "Hire 1", "Case")],
    })
    g.ingest([doc("doc:legacy", OWNER, "2015-01-01"), doc("doc:law", OWNER, "2022-11-28"),
              doc("doc:optout", OWNER, "2023-03-01"), doc("doc:clients", OWNER, "2024-01-01"),
              doc("doc:case", OWNER, "2025-01-01")])
    return g

  def _rule(self, view) -> str:
    rules = [fv.fact.statement for fv in view.current if isinstance(fv.fact.statement, AttributeStatement)]
    assert len(rules) == 1
    return rules[0].value

  def test_most_recent_applicable_fact_wins(self, g):
    assert self._rule(g.view(POLICY, {"client": "Acme", "country": "BE"})) == "no note on day 1"
    assert self._rule(g.view(POLICY, {"client": "Globex", "country": "BE"})) == "note from day 1"

  def test_losing_and_out_of_context_facts_stay_visible(self, g):
    view = g.view(POLICY, {"client": "Acme", "country": "BE"})
    assert [fv.fact.id for fv in view.alternatives] == ["doc:legacy:0"]
    assert [fv.fact.id for fv in view.other_contexts] == ["doc:optout:0"]

  def test_time_travel(self, g):
    view = g.view(POLICY, {"client": "Acme", "country": "BE"}, as_of=datetime(2020, 1, 1, tzinfo=UTC))
    assert self._rule(view) == "48h note always"

  def test_context_entity_owner_is_a_contact(self, g):
    view = g.view(POLICY, {"client": "Acme", "country": "BE"})
    assert [c.person.id for c in view.contacts] == [OWNER_ID, "person:jan-corp-example"]

  def test_incoming_relations_surface_case_owners(self, g):
    view = g.view("process:permit")
    assert [fv.fact.subject_id for fv in view.incoming] == ["case:hire-1"]
    assert [c.person.id for c in view.contacts] == ["person:hm-corp-example"]

  def test_search_and_ask(self, g):
    assert g.search("sick note rules")[0].id == POLICY
    result = g.ask("Do I need a sick note?", {"client": "Acme", "country": "BE"})
    assert result.views[0].node.id == POLICY
    assert "no note on day 1" in result.answer.answer

  def test_gaps(self, g):
    gaps = g.gaps(as_of=NOW)
    assert [n.id for n in gaps.unowned] == ["process:permit"]
    assert {f.id for f in gaps.stale} == {"doc:law:0", "doc:optout:0", "doc:legacy:0"}
