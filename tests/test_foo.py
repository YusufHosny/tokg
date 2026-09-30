# ABOUTME: Replays the recorded Foo rig over examples/data and checks the data README's answer
# ABOUTME: key: current version, superseded history, traps held as pending, and the right owner.
import pytest
from conftest import DATA, FOO

from tokg.ingest import load_sources
from tokg.rig import Rig
from tokg.schema import Schema
from tokg.seed import Seed


@pytest.fixture(scope="module")
def graph():
  g = Rig.from_yaml(FOO / "rig.yaml").graph(Schema.from_yaml(FOO / "schema.yaml"),
                                               seed=Seed.from_yaml(FOO / "seed.yaml"))
  report = g.ingest(load_sources(DATA))
  assert report.skipped == []
  return g


def _summary(view):
  [fv] = [fv for fv in view.current if getattr(fv.fact.statement, "attribute", None) == "summary"]
  return fv


@pytest.mark.parametrize("policy, owner, current, superseded, traps", [
  ("policy:hire-non-eu", "person:sophie-claes-foo-be",
   "email-2025-07-15-001", {"meeting-2025-03-11-001", "wiki-2023-05-10-001"}, {"wiki-2024-09-01-002"}),
  ("policy:sick-leave-certificate", "person:marc-dubois-sdworx-com",
   "wiki-2023-03-01-001", {"wiki-2019-01-15-001"}, {"email-2026-01-20-001"}),
  ("policy:hardware-purchasing", "person:tom-verbeke-foo-be",
   "email-2026-04-16-001", {"email-2026-03-09-001", "wiki-2024-02-12-001"}, {"email-2026-04-14-001"}),
])
def test_answer_key(graph, policy, owner, current, superseded, traps):
  view = graph.view(policy, {"country": "BE"})
  assert view.owner.id == owner
  summary = _summary(view)
  assert summary.fact.id.startswith(current) and summary.trust == "confirmed"
  assert {h.id.rsplit(":", 1)[0] for h in summary.history} == superseded
  assert traps <= {fv.fact.id.rsplit(":", 1)[0] for fv in view.pending}


def test_previous_hires_are_examples(graph):
  view = graph.view("policy:hire-non-eu")
  examples = {fv.fact.subject_id for fv in view.incoming}
  assert {"example:hiring-ravi-kumar-backend-engineer-india",
          "example:hiring-camila-souza-account-executive-brazil"} <= examples


def test_hardware_is_temporal(graph):
  from datetime import UTC, datetime
  before = _summary(graph.view("policy:hardware-purchasing", as_of=datetime(2026, 2, 1, tzinfo=UTC)))
  assert before.fact.id.startswith("wiki-2024-02-12-001")


def test_unowned_company_topics_keep_their_search_rank(graph):
  assert graph.search("How do I connect to the office wifi and printer?", limit=1)[0].id == "policy:office-wi-fi-and-printers"
