# ABOUTME: HTTP API tests: bearer auth, member vs admin rights, owner-only escalation actions and
# ABOUTME: the author-forging guard on /ingest.
import re
import threading
import time
from datetime import timedelta

import pytest
from conftest import NOW, OTHER, OTHER_ID, OWNER, OWNER_ID, doc, make_graph, owns, rule
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from tokg.api import Principal, TokenRegistry, create_app
import tokg.api.app
from tokg.api.app import BYTE_UNIT, MAX_ESCALATION_ID, MAX_MEMBER_SOURCES, RateLimits, SlidingWindow, _answer_rate, _principal
from tokg.extract import MAX_KNOWN_ENTITIES
from tokg.graph import MAX_OPEN_ESCALATIONS_PER_AUTHOR
from tokg.models import Escalation, Node, SourceRef
from tokg.rig import Rig

POLICY = "policy:sick-note"
DOC_B = f"{OTHER_ID}+doc:b"
DOC_M = f"{OTHER_ID}+doc:m"


@pytest.fixture
def setup(schema):
  g = make_graph(schema, Rig(extractions={
    "doc:owner": [owns(OWNER)], "doc:a": [rule("note always")], DOC_B: [rule("no note day 1")]}))
  g.ingest([doc("doc:owner", OWNER, "2020-01-01"), doc("doc:a", OWNER, "2021-01-01")])
  reg = TokenRegistry()
  tokens = {"owner": reg.add(Principal(person_id=OWNER_ID)),
            "other": reg.add(Principal(person_id=OTHER_ID)),
            "admin": reg.add(Principal(person_id="person:admin", role="admin"))}
  saves = []
  client = TestClient(create_app(g, reg, on_change=lambda: saves.append(1)))
  return client, tokens, g, saves


def h(token: str) -> dict[str, str]:
  return {"Authorization": f"Bearer {token}"}


def test_auth_required(setup):
  client, *_ = setup
  assert client.get("/health").status_code == 200
  assert client.get("/nodes").status_code == 401
  assert client.get("/nodes", headers=h("wrong")).status_code == 401


def test_view_with_context(setup):
  client, tokens, *_ = setup
  r = client.get(f"/nodes/{POLICY}", params={"context": ["country=BE"]}, headers=h(tokens["other"]))
  assert r.status_code == 200
  body = r.json()
  assert body["owner"]["id"] == OWNER_ID and body["context"] == {"country": "BE"}
  assert client.get("/nodes/policy:nope", headers=h(tokens["other"])).status_code == 404
  assert client.get(f"/nodes/{POLICY}", params={"context": ["bad"]}, headers=h(tokens["other"])).status_code == 422


def test_member_ingest_cannot_forge_author(setup):
  client, tokens, g, saves = setup
  forged = doc("doc:b", OWNER, "2022-01-01").model_dump(mode="json")
  r = client.post("/ingest", json=[forged], headers=h(tokens["other"]))
  assert r.status_code == 200
  assert r.json()["source_ids"] == [DOC_B] and g.store.get_source("doc:b") is None
  assert g.store.get_source(DOC_B).author == OTHER_ID
  assert g.store.get_fact(f"{DOC_B}:0").status == "pending"
  assert saves


def test_escalation_is_owner_only(setup):
  client, tokens, g, _ = setup
  client.post("/ingest", json=[doc("doc:b", OTHER, "2022-01-01").model_dump(mode="json")],
              headers=h(tokens["other"]))
  mine = client.get("/escalations", params={"mine": True}, headers=h(tokens["owner"])).json()
  url = f"/escalations/esc:{DOC_B}:0/resolve"
  assert [e["id"] for e in mine] == [f"esc:{DOC_B}:0"]
  body = {"verdict": "approve"}
  assert client.post(url, json=body, headers=h(tokens["other"])).status_code == 403
  assert client.post(url, json=body, headers=h(tokens["admin"])).status_code == 403
  r = client.post(url, json=body, headers=h(tokens["owner"]))
  assert r.status_code == 200 and r.json()["status"] == "approved"
  assert client.post(url, json=body, headers=h(tokens["owner"])).status_code == 409


def test_assign_owner_is_admin_only(setup):
  client, tokens, g, _ = setup
  body = {"owner_id": OTHER_ID}
  assert client.put(f"/nodes/{POLICY}/owner", json=body, headers=h(tokens["owner"])).status_code == 403
  assert client.put(f"/nodes/{POLICY}/owner", json=body, headers=h(tokens["admin"])).status_code == 200
  assert g.owner_of(POLICY) == OTHER_ID


def test_ask_and_questions(setup):
  client, tokens, *_ = setup
  r = client.post("/ask", json={"question": "sick note?"}, headers=h(tokens["other"]))
  assert r.status_code == 200 and r.json()["views"][0]["node"]["id"] == POLICY
  r = client.post(f"/nodes/{POLICY}/questions", json={"question": "Acme opt-out?"}, headers=h(tokens["other"]))
  assert r.json()["assignee_id"] == OWNER_ID and r.json()["raised_by"] == OTHER_ID


def test_web_app_is_served_without_leaking_data(setup):
  client, *_ = setup
  assert client.get("/", follow_redirects=False).headers["location"] == "/app/"
  page = client.get("/app/")
  assert page.status_code == 200 and "Recall" in page.text
  assert client.get("/app/base.css").status_code == 200
  assert client.get("/nodes").status_code == 401


def test_web_app_guards_policies_without_owner(setup):
  client, *_ = setup
  page = client.get("/app/").text
  calls = re.findall(r"\$\{([^{}]*)ownerCard\(([\w.]+)\)", page)
  assert len(calls) == 2 and all(guard == f"{arg} ? " for guard, arg in calls)
  assert "if (!btn || SCRIPTED || !m.owner) return;" in page


def test_security_headers(setup):
  client, tokens, *_ = setup
  page = client.get("/app/")
  assert "connect-src 'self'" in page.headers["content-security-policy"]
  assert "'unsafe-inline'" in page.headers["content-security-policy"]
  r = client.get("/nodes", headers=h(tokens["other"]))
  assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
  assert r.headers["content-security-policy"].startswith("default-src 'none'")
  assert r.headers["cache-control"] == "no-store"


def test_oversized_token_and_body_are_refused(setup):
  client, tokens, *_ = setup
  assert client.get("/nodes", headers=h("x" * 5000)).status_code == 401
  big = {"question": "q", "context": {"k": "v" * 3_000_000}}
  assert client.post("/ask", json=big, headers=h(tokens["other"])).status_code == 413
  many = {"question": "q", "context": {f"k{i}": "v" for i in range(50)}}
  assert client.post("/ask", json=many, headers=h(tokens["other"])).status_code == 422


def test_member_ingest_guards(setup):
  client, tokens, g, _ = setup
  note = {**doc("x", OTHER, "2022-01-01").model_dump(mode="json"), "kind": "note", "id": "member:x"}
  assert client.post("/ingest", json=[note], headers=h(tokens["other"])).status_code == 403
  for bad_id in ["note:seed", "note:esc:q:policy-sick-note:0", "seed:policy:sick-note", "q:policy-sick-note", "a b"]:
    body = [doc(bad_id, OTHER, "2022-01-01").model_dump(mode="json")]
    assert client.post("/ingest", json=body, headers=h(tokens["admin"])).status_code == 422
  batch = [doc(f"doc:n{i}", OTHER, "2022-01-01").model_dump(mode="json") for i in range(51)]
  assert client.post("/ingest", json=batch, headers=h(tokens["other"])).status_code == 422
  tampered = doc("doc:a", OWNER, "2021-01-01", content="tampered").model_dump(mode="json")
  assert client.post("/ingest", json=[tampered], headers=h(tokens["admin"])).status_code == 409
  assert g.store.get_source("note:seed") is None


def test_member_cannot_credit_the_owner_via_recipients(schema):
  said = rule("no note day 1").model_copy(update={"asserted_by": OWNER})
  g = make_graph(schema, Rig(extractions={"doc:owner": [owns(OWNER)], "doc:a": [rule("note always")],
                                          DOC_M: [said]}))
  g.ingest([doc("doc:owner", OWNER, "2020-01-01"), doc("doc:a", OWNER, "2021-01-01")])
  reg = TokenRegistry()
  token = reg.add(Principal(person_id=OTHER_ID))
  client = TestClient(create_app(g, reg))
  body = doc("doc:m", OTHER, "2022-01-01").model_copy(update={"recipients": [OWNER]}).model_dump(mode="json")
  assert client.post("/ingest", json=[body], headers=h(token)).status_code == 200
  fact = g.store.get_fact(f"{DOC_M}:0")
  assert fact.asserted_by == OTHER_ID and fact.status == "pending"


def test_member_context_scoped_claim_on_owned_node_is_pending(schema):
  g = make_graph(schema, Rig(extractions={"doc:owner": [owns(OWNER)], "doc:a": [rule("note always")],
                                          DOC_M: [rule("no note day 1", country="BE")]}))
  g.ingest([doc("doc:owner", OWNER, "2020-01-01"), doc("doc:a", OWNER, "2021-01-01")])
  reg = TokenRegistry()
  token = reg.add(Principal(person_id=OTHER_ID))
  client = TestClient(create_app(g, reg))
  body = doc("doc:m", OTHER, "2022-01-01").model_dump(mode="json")
  assert client.post("/ingest", json=[body], headers=h(token)).status_code == 200
  assert g.store.get_fact(f"{DOC_M}:0").status == "pending"
  assert g.store.get_escalation(f"esc:{DOC_M}:0").assignee_id == OWNER_ID
  view = client.get(f"/nodes/{POLICY}", params={"context": ["country=BE"]}, headers=h(token)).json()
  assert [fv["fact"]["id"] for fv in view["current"] if fv["fact"]["statement"]["kind"] == "attribute"] == ["doc:a:0"]


def test_escalations_are_visible_to_participants_only(setup):
  client, tokens, g, _ = setup
  reg = client.app.state.registry
  stranger = reg.add(Principal(person_id="person:stranger"))
  client.post(f"/nodes/{POLICY}/questions", json={"question": "Acme opt-out?"}, headers=h(tokens["other"]))
  for who in ["owner", "other", "admin"]:
    assert len(client.get("/escalations", headers=h(tokens[who])).json()) == 1
  assert client.get("/escalations", headers=h(stranger)).json() == []
  assert client.get(f"/nodes/{POLICY}", headers=h(stranger)).json()["escalations"] == []
  assert client.get("/gaps", headers=h(stranger)).json()["open_escalations"] == []


def _depends_on(dependant, call) -> bool:
  return any(d.call is call or _depends_on(d, call) for d in dependant.dependencies)


def test_every_route_requires_auth(setup):
  client, *_ = setup
  public = {"/health", "/"}
  routes = [r for r in client.app.routes if isinstance(r, APIRoute)]
  assert {r.path for r in routes if not _depends_on(r.dependant, _principal)} == public
  others = {getattr(r, "path", None) for r in client.app.routes if not isinstance(r, APIRoute)}
  assert others == {"/app"}


def test_source_uris_are_redacted(setup):
  client, tokens, g, _ = setup
  src = doc("doc:u", OWNER, "2022-01-01").model_copy(
    update={"uri": "/home/someone/tokg/examples/data/emails/u.eml"})
  g.store.put_source(src)
  fact = g.store.get_fact("doc:a:0")
  fact.sources.append(SourceRef(source_id="doc:u"))
  g.store.put_fact(fact)
  r = client.get("/sources/doc:u", headers=h(tokens["other"]))
  assert r.json()["uri"] == "examples/data/emails/u.eml"
  view = client.get(f"/nodes/{POLICY}", headers=h(tokens["other"])).json()
  uris = [s["source"]["uri"] for f in view["current"] for s in f["sources"] if s["source"]]
  assert "examples/data/emails/u.eml" in uris and not any(u and u.startswith("/") for u in uris)
  ask = client.post("/ask", json={"question": "sick note?"}, headers=h(tokens["other"])).json()
  assert not any(s["source"]["uri"] and s["source"]["uri"].startswith("/")
                 for v in ask["views"] for f in v["current"] for s in f["sources"] if s["source"])
  assert g.store.get_source("doc:u").uri == "/home/someone/tokg/examples/data/emails/u.eml"
  g.store.put_source(doc("doc:v", OWNER, "2022-01-01").model_copy(update={"uri": "C:\\data\\v.md"}))
  assert client.get("/sources/doc:v", headers=h(tokens["other"])).json()["uri"] == "v.md"
  assert client.get("/sources/doc:a", headers=h(tokens["other"])).json()["uri"] is None


def test_rate_limits(schema):
  now = [0.0]
  g = make_graph(schema, Rig(extractions={"doc:owner": [owns(OWNER)]}))
  g.ingest([doc("doc:owner", OWNER, "2020-01-01")])
  reg = TokenRegistry()
  token, other = reg.add(Principal(person_id=OTHER_ID)), reg.add(Principal(person_id=OWNER_ID))
  limits = RateLimits(requests=SlidingWindow(4, 60, clock=lambda: now[0]),
                      questions=SlidingWindow(2, 3600, clock=lambda: now[0]))
  client = TestClient(create_app(g, reg, rate_limits=limits))
  ask = {"question": "q?"}
  codes = [client.post(f"/nodes/{POLICY}/questions", json=ask, headers=h(token)).status_code for _ in range(3)]
  assert codes == [200, 200, 429]
  r = client.post("/ask", json=ask, headers=h(token))
  assert r.status_code == 200
  r = client.post("/ask", json=ask, headers=h(token))
  assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1
  assert client.get("/nodes", headers=h(token)).status_code == 200
  assert client.post("/ask", json=ask, headers=h(other)).status_code == 200
  now[0] = 61.0
  assert client.post("/ask", json=ask, headers=h(token)).status_code == 200
  assert client.post(f"/nodes/{POLICY}/questions", json=ask, headers=h(token)).status_code == 429


def test_default_rate_limits_are_generous(setup):
  client, tokens, *_ = setup
  limits = client.app.state.rate_limits
  assert limits.requests.limit >= 120 and limits.questions.limit >= 20
  assert limits.asks.limit >= 300 and limits.ingested.limit >= 200 and limits.reads.limit >= 600
  assert limits.ingested_bytes.limit * BYTE_UNIT == 5_000_000


def test_ingest_ask_and_read_budgets(schema):
  now = [0.0]
  clock = lambda: now[0]
  g = make_graph(schema, Rig(extractions={"doc:owner": [owns(OWNER)]}))
  g.ingest([doc("doc:owner", OWNER, "2020-01-01")])
  reg = TokenRegistry()
  member, peer = reg.add(Principal(person_id=OTHER_ID)), reg.add(Principal(person_id=OWNER_ID))
  admin = reg.add(Principal(person_id="person:admin", role="admin"))
  limits = RateLimits(requests=SlidingWindow(1000, 60, clock=clock), asks=SlidingWindow(2, 3600, clock=clock),
                      ingested=SlidingWindow(3, 3600, clock=clock), reads=SlidingWindow(2, 60, clock=clock))
  client = TestClient(create_app(g, reg, rate_limits=limits))
  batch = lambda *ids: [doc(i, OTHER, "2022-01-01").model_dump(mode="json") for i in ids]
  assert client.post("/ingest", json=batch("doc:1", "doc:2"), headers=h(member)).status_code == 200
  r = client.post("/ingest", json=batch("doc:3", "doc:4"), headers=h(member))
  assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1
  assert client.post("/ingest", json=batch("doc:3"), headers=h(member)).status_code == 200
  assert client.post("/ingest", json=batch("doc:4"), headers=h(member)).status_code == 429
  assert client.post("/ingest", json=batch(*[f"doc:a{i}" for i in range(5)]), headers=h(admin)).status_code == 200
  assert client.post("/ingest", json=batch(*[f"doc:b{i}" for i in range(4)]), headers=h(peer)).status_code == 429
  ask = {"question": "q?"}
  assert [client.post("/ask", json=ask, headers=h(member)).status_code for _ in range(3)] == [200, 200, 429]
  assert client.post("/ask", json=ask, headers=h(peer)).status_code == 200
  assert [client.get("/nodes", headers=h(member)).status_code for _ in range(3)] == [200, 200, 429]
  assert client.get(f"/nodes/{POLICY}", headers=h(peer)).status_code == 200
  now[0] = 3601.0
  assert client.post("/ingest", json=batch("doc:4"), headers=h(member)).status_code == 200
  assert client.post("/ask", json=ask, headers=h(member)).status_code == 200
  assert client.get(f"/sources/{OTHER_ID}+doc:1", headers=h(member)).status_code == 200


def test_api_docs_are_disabled(setup):
  client, *_ = setup
  for path in ["/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"]:
    assert client.get(path).status_code == 404


def test_extraction_errors_are_generic(setup, monkeypatch):
  client, tokens, g, _ = setup
  def boom(*_):
    raise TimeoutError("secret upstream detail at /home/x")
  monkeypatch.setattr(g.extractor, "extract", boom)
  r = client.post("/ingest", json=[doc("doc:t", OWNER, "2022-01-01").model_dump(mode="json")],
                  headers=h(tokens["admin"]))
  assert r.status_code == 200
  assert [o["error"] for o in r.json()["outcomes"]] == ["extraction failed"]


def test_as_of_and_limit_bounds(setup):
  client, tokens, *_ = setup
  for as_of in ["2021-06-01T00:00:00", "0001-01-01T00:00:00", "9999-12-31T23:59:59+00:00", "2021-06-01"]:
    assert client.get(f"/nodes/{POLICY}", params={"as_of": as_of}, headers=h(tokens["other"])).status_code == 200
  assert client.get(f"/nodes/{POLICY}", params={"as_of": "nope"}, headers=h(tokens["other"])).status_code == 422
  for limit in [0, 101, -1, 10**30]:
    assert client.get("/nodes", params={"limit": limit}, headers=h(tokens["other"])).status_code == 422


def test_tokens_must_be_bound_to_a_person(setup):
  client, tokens, *_ = setup
  reg = client.app.state.registry
  for bad in ["Olga Owner <olga@corp.example>", "olga@corp.example", "person:", "policy:sick-note"]:
    assert client.get("/nodes", headers=h(reg.add(Principal(person_id=bad)))).status_code == 403
  ghost = reg.add(Principal(person_id="person:ghost"))
  r = client.get("/me", headers=h(ghost))
  assert r.status_code == 200 and r.json() is None


def test_unowned_question_only_answerable_after_assignment(setup):
  client, tokens, g, _ = setup
  g.store.put_node(Node(id="client:acme", type="Client", name="Acme"))
  esc = client.post("/nodes/client:acme/questions", json={"question": "opt-out?"}, headers=h(tokens["other"])).json()
  assert esc["assignee_id"] is None
  url, body = f"/escalations/{esc['id']}/answer", {"answer": "yes"}
  assert [client.post(url, json=body, headers=h(tokens[who])).status_code
          for who in ["other", "owner", "admin"]] == [403, 404, 403]
  assert client.put("/nodes/client:acme/owner", json={"owner_id": OWNER_ID},
                    headers=h(tokens["admin"])).status_code == 200
  assert client.post(url, json=body, headers=h(tokens["other"])).status_code == 403
  assert client.post(url, json=body, headers=h(tokens["owner"])).status_code == 200


def test_escalation_on_missing_subject_is_refused(setup):
  client, tokens, g, _ = setup
  g.store.put_escalation(Escalation(id="esc:gone", reason="question", subject_id="policy:gone",
                                    question="?", assignee_id=OWNER_ID))
  r = client.post("/escalations/esc:gone/answer", json={"answer": "x"}, headers=h(tokens["owner"]))
  assert r.status_code == 409
  r = client.post("/escalations/esc:gone/resolve", json={"verdict": "approve"}, headers=h(tokens["owner"]))
  assert r.status_code == 409
  assert g.store.get_escalation("esc:gone").status == "open"


def test_answer_notes_are_private_to_the_escalation(schema):
  note_id = "note:esc:q:policy-sick-note:0"
  g = make_graph(schema, Rig(extractions={"doc:owner": [owns(OWNER)], note_id: [rule("acme opts out")]}))
  g.ingest([doc("doc:owner", OWNER, "2020-01-01")])
  reg = TokenRegistry()
  tokens = {"owner": reg.add(Principal(person_id=OWNER_ID)), "other": reg.add(Principal(person_id=OTHER_ID)),
            "admin": reg.add(Principal(person_id="person:admin", role="admin")),
            "stranger": reg.add(Principal(person_id="person:stranger"))}
  client = TestClient(create_app(g, reg))
  esc = client.post(f"/nodes/{POLICY}/questions", json={"question": "Secret salary of Bob?"},
                    headers=h(tokens["other"])).json()
  r = client.post(f"/escalations/{esc['id']}/answer", json={"answer": "acme opts out"}, headers=h(tokens["owner"]))
  assert r.status_code == 200 and g.store.get_source(note_id) is not None
  for who in ["owner", "other", "admin"]:
    r = client.get(f"/sources/{note_id}", headers=h(tokens[who]))
    assert r.status_code == 200 and "Secret salary" in r.json()["content"]
  r = client.get(f"/sources/{note_id}", headers=h(tokens["stranger"]))
  assert r.status_code == 404 and "Secret" not in r.text
  view = client.get(f"/nodes/{POLICY}", headers=h(tokens["stranger"])).json()
  ask = client.post("/ask", json={"question": "sick note?"}, headers=h(tokens["stranger"])).json()
  for body in [view, *ask["views"]]:
    notes = [s["source"] for f in body["current"] for s in f["sources"] if s["ref"]["source_id"] == note_id]
    assert notes and all(n["content"] == "acme opts out" for n in notes)
    assert "Secret salary" not in str(body)
  owner_view = client.get(f"/nodes/{POLICY}", headers=h(tokens["other"])).json()
  assert "Secret salary" in str(owner_view)
  g.store.get_source(note_id).escalation_id = "esc:missing"
  assert client.get(f"/sources/{note_id}", headers=h(tokens["owner"])).status_code == 404
  assert client.get(f"/sources/{note_id}", headers=h(tokens["admin"])).status_code == 200


def test_escalation_errors_do_not_name_the_assignee(setup):
  client, tokens, g, _ = setup
  client.post("/ingest", json=[doc("doc:b", OTHER, "2022-01-01").model_dump(mode="json")],
              headers=h(tokens["other"]))
  r = client.post(f"/escalations/esc:{DOC_B}:0/resolve", json={"verdict": "approve"}, headers=h(tokens["other"]))
  assert r.status_code == 403 and r.json()["detail"] == "not allowed" and OWNER_ID not in r.text
  esc = client.post(f"/nodes/{POLICY}/questions", json={"question": "q?"}, headers=h(tokens["other"])).json()
  r = client.post(f"/escalations/{esc['id']}/answer", json={"answer": "a"}, headers=h(tokens["other"]))
  assert r.status_code == 403 and OWNER_ID not in r.text


def test_answer_note_quotes_are_private_to_the_escalation(schema):
  note_id = "note:esc:q:policy-sick-note:0"
  g = make_graph(schema, Rig(extractions={"doc:owner": [owns(OWNER)], note_id: [rule("acme opts out")]}))
  g.ingest([doc("doc:owner", OWNER, "2020-01-01")])
  reg = TokenRegistry()
  tokens = {"other": reg.add(Principal(person_id=OTHER_ID)), "owner": reg.add(Principal(person_id=OWNER_ID)),
            "stranger": reg.add(Principal(person_id="person:stranger"))}
  client = TestClient(create_app(g, reg))
  esc = client.post(f"/nodes/{POLICY}/questions", json={"question": "Secret salary of Bob?"},
                    headers=h(tokens["other"])).json()
  client.post(f"/escalations/{esc['id']}/answer", json={"answer": "acme opts out"}, headers=h(tokens["owner"]))
  fact = next(f for f in g.store.facts() if any(r.source_id == note_id for r in f.sources))
  fact.sources[0].quote, fact_id = "Secret salary of Bob? acme opts out", fact.id
  g.store.put_fact(fact)

  def quotes(who: str) -> list[str | None]:
    view = client.get(f"/nodes/{POLICY}", headers=h(tokens[who])).json()
    ask = client.post("/ask", json={"question": "sick note?"}, headers=h(tokens[who])).json()
    fact = client.get(f"/facts/{fact_id}", headers=h(tokens[who])).json()
    refs = [s["ref"] for body in [view, *ask["views"]] for f in body["current"] for s in f["sources"]]
    refs += [r for body in [view, *ask["views"]] for f in body["current"] for r in f["fact"]["sources"]]
    return [r["quote"] for r in [*refs, *fact["sources"]] if r["source_id"] == note_id]

  assert (hidden := quotes("stranger")) and all(q is None for q in hidden)
  assert (shown := quotes("other")) and all(q == "Secret salary of Bob? acme opts out" for q in shown)


def test_member_source_ids_are_namespaced(setup):
  client, tokens, g, _ = setup
  squat = "portal-2026-10-01-001"
  body = [doc(squat, OTHER, "2022-01-01").model_dump(mode="json")]
  r = client.post("/ingest", json=body, headers=h(tokens["other"]))
  assert r.status_code == 200 and r.json()["source_ids"] == [f"{OTHER_ID}+{squat}"]
  assert g.store.get_source(squat) is None and g.store.get_source(f"{OTHER_ID}+{squat}") is not None
  again = [{**body[0], "id": f"{OTHER_ID}+{squat}"}]
  assert client.post("/ingest", json=again, headers=h(tokens["other"])).status_code == 200
  assert g.store.get_source(f"{OTHER_ID}+{OTHER_ID}+{squat}") is None
  r = client.post("/ingest", json=body, headers=h(tokens["owner"]))
  assert r.json()["source_ids"] == [f"{OWNER_ID}+{squat}"]
  r = client.post("/ingest", json=body, headers=h(tokens["admin"]))
  assert r.status_code == 200 and r.json()["source_ids"] == [squat]
  assert g.store.get_source(squat).author == OTHER
  long_id = [doc("x" * 190, OTHER, "2022-01-01").model_dump(mode="json")]
  assert client.post("/ingest", json=long_id, headers=h(tokens["other"])).status_code == 422


def test_member_ingest_is_charged_by_size(schema):
  now = [0.0]
  clock = lambda: now[0]
  g = make_graph(schema, Rig())
  reg = TokenRegistry()
  member, admin = reg.add(Principal(person_id=OTHER_ID)), reg.add(Principal(person_id="person:admin", role="admin"))
  limits = RateLimits(requests=SlidingWindow(1000, 60, clock=clock),
                      ingested_bytes=SlidingWindow(6, 3600, clock=clock))
  client = TestClient(create_app(g, reg, rate_limits=limits))
  sized = lambda id_, n: doc(id_, OTHER, "2022-01-01", content="x" * n).model_dump(mode="json")
  assert client.post("/ingest", json=[sized("doc:big", 50_001)], headers=h(member)).status_code == 413
  assert client.post("/ingest", json=[sized("doc:1", 2000), sized("doc:2", 2000)],
                     headers=h(member)).status_code == 200
  r = client.post("/ingest", json=[sized("doc:3", 2000)], headers=h(member))
  assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1
  assert client.post("/ingest", json=[sized("doc:4", 500)], headers=h(member)).status_code == 200
  assert client.post("/ingest", json=[sized("doc:5", 10)], headers=h(member)).status_code == 429
  assert client.post("/ingest", json=[sized("doc:a", 60_000)], headers=h(admin)).status_code == 200
  now[0] = 3601.0
  assert client.post("/ingest", json=[sized("doc:3", 2000)], headers=h(member)).status_code == 200


def _blocked_until_read(client, token, stall, call):
  started, release, result = threading.Event(), threading.Event(), {}

  def stalled(*args):
    started.set()
    release.wait(5)
    return stall(*args)

  worker = threading.Thread(target=lambda: result.setdefault("r", call(stalled)))
  worker.start()
  assert started.wait(5)
  begin = time.monotonic()
  read = client.get(f"/nodes/{POLICY}", headers=h(token))
  elapsed = time.monotonic() - begin
  release.set()
  worker.join(10)
  return read, elapsed, result["r"]


def test_lock_is_not_held_during_extraction(setup, monkeypatch):
  client, tokens, g, _ = setup
  original = g.extractor.extract

  def call(stalled):
    monkeypatch.setattr(g.extractor, "extract", stalled)
    return client.post("/ingest", json=[doc("doc:b", OTHER, "2022-01-01").model_dump(mode="json")],
                       headers=h(tokens["other"]))

  read, elapsed, ingested = _blocked_until_read(client, tokens["owner"], original, call)
  assert read.status_code == 200 and elapsed < 2
  assert ingested.status_code == 200 and ingested.json()["source_ids"] == [DOC_B]
  assert g.store.get_fact(f"{DOC_B}:0").status == "pending"


def test_lock_is_not_held_while_answering(setup, monkeypatch):
  client, tokens, g, _ = setup
  original = g.answerer.answer

  def call(stalled):
    monkeypatch.setattr(g.answerer, "answer", stalled)
    return client.post("/ask", json={"question": "sick note?"}, headers=h(tokens["admin"]))

  read, elapsed, asked = _blocked_until_read(client, tokens["owner"], original, call)
  assert read.status_code == 200 and elapsed < 2
  assert asked.json() == g.ask("sick note?", {}).model_dump(mode="json")


def test_ingest_extracts_in_order_and_reports_failures(setup, monkeypatch):
  client, tokens, g, _ = setup
  original = g.extractor.extract

  def flaky(source, *args):
    if source.id == "doc:c":
      raise RuntimeError("down")
    return original(source, *args)

  monkeypatch.setattr(g.extractor, "extract", flaky)
  batch = [doc("doc:c", OWNER, "2023-01-01"), doc("doc:a", OWNER, "2021-01-01"), doc("doc:d", OWNER, "2022-01-01")]
  r = client.post("/ingest", json=[d.model_dump(mode="json") for d in batch], headers=h(tokens["admin"]))
  assert r.json() == {"source_ids": ["doc:d"], "outcomes": [{"claim_id": "doc:c", "decision": None,
                                                             "error": "extraction failed"}]}
  assert g.store.get_source("doc:c") is None and g.store.get_source("doc:d") is not None


def test_gaps_redact_private_quotes(schema):
  note_id = "note:esc:q:policy-sick-note:0"
  g = make_graph(schema, Rig(extractions={"doc:owner": [owns(OWNER)], note_id: [rule("acme opts out")]}))
  g.ingest([doc("doc:owner", OWNER, "2020-01-01")])
  reg = TokenRegistry()
  tokens = {"other": reg.add(Principal(person_id=OTHER_ID)), "owner": reg.add(Principal(person_id=OWNER_ID)),
            "stranger": reg.add(Principal(person_id="person:stranger"))}
  client = TestClient(create_app(g, reg))
  esc = client.post(f"/nodes/{POLICY}/questions", json={"question": "Secret salary of Bob?"},
                    headers=h(tokens["other"])).json()
  client.post(f"/escalations/{esc['id']}/answer", json={"answer": "acme opts out"}, headers=h(tokens["owner"]))
  fact = next(f for f in g.store.facts() if any(r.source_id == note_id for r in f.sources))
  fact.status, fact.sources[0].quote = "pending", "Secret salary of Bob? acme opts out"
  g.store.put_fact(fact)
  stranger = client.get("/gaps", headers=h(tokens["stranger"])).json()
  assert stranger["pending"] and "Secret salary" not in str(stranger)
  assert "Secret salary" in str(client.get("/gaps", headers=h(tokens["other"])).json()["pending"])
  assert g.store.get_fact(fact.id).sources[0].quote is not None


def test_foreign_escalations_look_missing(setup):
  client, tokens, g, _ = setup
  stranger = client.app.state.registry.add(Principal(person_id="person:stranger"))
  client.post("/ingest", json=[doc("doc:b", OTHER, "2022-01-01").model_dump(mode="json")],
              headers=h(tokens["other"]))
  real, fake = f"esc:{DOC_B}:0", "esc:nope"
  for action, body in [("resolve", {"verdict": "approve"}), ("answer", {"answer": "a"})]:
    seen, missing = (client.post(f"/escalations/{i}/{action}", json=body, headers=h(stranger)) for i in (real, fake))
    assert seen.status_code == missing.status_code == 404
    assert seen.json()["detail"].replace(real, fake) == missing.json()["detail"]
  assert g.store.get_escalation(real).status == "open"
  assert client.post(f"/escalations/{real}/resolve", json={"verdict": "approve"},
                     headers=h(tokens["owner"])).status_code == 200


def test_long_escalation_ids_are_accepted(setup):
  client, tokens, g, _ = setup
  long_id = "esc:q:" + "x" * 280
  g.store.put_escalation(Escalation(id=long_id, reason="question", subject_id=POLICY,
                                    question="?", assignee_id=OWNER_ID))
  r = client.post(f"/escalations/{long_id}/answer", json={"answer": "yes"}, headers=h(tokens["owner"]))
  assert r.status_code == 200 and g.store.get_escalation(long_id).status == "answered"
  too_long = "e" * (MAX_ESCALATION_ID + 1)
  assert client.post(f"/escalations/{too_long}/resolve", json={"verdict": "approve"},
                     headers=h(tokens["owner"])).status_code == 422


def test_answers_are_rate_limited(setup):
  client, *_ = setup
  route = next(r for r in client.app.routes if isinstance(r, APIRoute) and r.path.endswith("/answer"))
  assert _depends_on(route.dependant, _answer_rate)


def test_member_ingest_charges_recipients(schema):
  g = make_graph(schema, Rig())
  reg = TokenRegistry()
  member = reg.add(Principal(person_id=OTHER_ID))
  limits = RateLimits(ingested_bytes=SlidingWindow(5, 3600))
  client = TestClient(create_app(g, reg, rate_limits=limits))
  recipients = [f"r{i}@{'x' * 290}.example" for i in range(20)]
  body = doc("doc:r", OTHER, "2022-01-01", content="x").model_copy(update={"recipients": recipients})
  r = client.post("/ingest", json=[body.model_dump(mode="json")], headers=h(member))
  assert r.status_code == 429 and g.store.get_source(f"{OTHER_ID}+doc:r") is None
  assert client.post("/ingest", json=[doc("doc:s", OTHER, "2022-01-01").model_dump(mode="json")],
                     headers=h(member)).status_code == 200


def test_concurrent_ingest_of_the_same_source_commits_once(setup, monkeypatch):
  client, tokens, g, _ = setup
  source = doc("doc:c", OWNER, "2022-01-01")
  extract = g.extractor.extract
  def racing(s, schema, known):
    g.ingest_source(source, drafts=[rule("note on day 2")])
    return [rule("note on day 3")]
  monkeypatch.setattr(g.extractor, "extract", racing)
  r = client.post("/ingest", json=[source.model_dump(mode="json")], headers=h(tokens["admin"]))
  assert r.json()["outcomes"] == [{"claim_id": "doc:c", "decision": None, "error": "already ingested"}]
  assert g.store.get_fact("doc:c:0").statement.value == "note on day 2"
  monkeypatch.setattr(g.extractor, "extract", extract)


def test_answer_extraction_runs_outside_the_lock(setup, monkeypatch):
  client, tokens, g, _ = setup
  esc = client.post(f"/nodes/{POLICY}/questions", json={"question": "Acme?"}, headers=h(tokens["other"])).json()
  url, seen = f"/escalations/{esc['id']}/answer", []
  def concurrent(s, schema, known):
    done = threading.Event()
    def read():
      seen.append(client.get(f"/nodes/{POLICY}", headers=h(tokens["other"])).status_code)
      done.set()
    threading.Thread(target=read).start()
    assert done.wait(5)
    g.assign_owner(POLICY, OTHER_ID, assigned_by="person:admin")
    return [rule("acme opts out")]
  monkeypatch.setattr(g.extractor, "extract", concurrent)
  r = client.post(url, json={"answer": "acme opts out"}, headers=h(tokens["owner"]))
  assert r.status_code == 404 and seen == [200]
  assert g.store.get_escalation(esc["id"]).status == "open" and g.store.get_source(f"note:{esc['id']}") is None
  def boom(*_):
    raise TimeoutError("secret upstream detail")
  monkeypatch.setattr(g.extractor, "extract", boom)
  r = client.post(url, json={"answer": "acme opts out"}, headers=h(tokens["other"]))
  assert [o["error"] for o in r.json()["outcomes"]] == ["extraction failed"]
  assert g.store.get_escalation(esc["id"]).status == "open"


def test_ingest_snapshots_only_the_known_nodes_extraction_sees(setup, monkeypatch):
  client, tokens, g, _ = setup
  for i in range(MAX_KNOWN_ENTITIES + 50):
    g.store.put_node(Node(id=f"case:c{i}", type="Case", name=f"C{i}"))
  seen = []
  monkeypatch.setattr(g.extractor, "extract", lambda s, schema, known: seen.append(known) or [])
  client.post("/ingest", json=[doc("doc:k", OWNER, "2022-01-01").model_dump(mode="json")], headers=h(tokens["admin"]))
  [known] = seen
  assert [n.id for n in known] == [n.id for n in g._known_nodes()[:MAX_KNOWN_ENTITIES]]
  assert all(n is not g.store.get_node(n.id) for n in known)


def test_members_cannot_ingest_far_future_sources(setup):
  client, tokens, g, _ = setup
  future = [doc("doc:f", OTHER, "2026-10-05").model_dump(mode="json")]
  r = client.post("/ingest", json=future, headers=h(tokens["other"]))
  assert r.status_code == 422 and g.store.get_source(f"{OTHER_ID}+doc:f") is None
  soon = [doc("doc:s", OTHER, "2026-09-30T12:00:00").model_dump(mode="json")]
  assert client.post("/ingest", json=soon, headers=h(tokens["other"])).status_code == 200
  assert client.post("/ingest", json=future, headers=h(tokens["admin"])).status_code == 200


def test_member_source_timestamps_are_clamped_to_now(setup):
  client, tokens, g, _ = setup
  soon = [doc("doc:s", OTHER, "2026-09-30T12:00:00").model_dump(mode="json")]
  assert client.post("/ingest", json=soon, headers=h(tokens["other"])).status_code == 200
  assert g.store.get_source(f"{OTHER_ID}+doc:s").timestamp == NOW
  client.post("/ingest", json=soon, headers=h(tokens["admin"]))
  assert g.store.get_source("doc:s").timestamp > NOW


def test_member_storage_is_capped(setup):
  client, tokens, g, _ = setup
  for i in range(MAX_MEMBER_SOURCES - 1):
    g.store.put_source(doc(f"{OTHER_ID}+doc:{i}", OTHER_ID, "2021-01-01"))
  two = [doc(f"doc:n{i}", OTHER, "2022-01-01").model_dump(mode="json") for i in range(2)]
  r = client.post("/ingest", json=two, headers=h(tokens["other"]))
  assert r.status_code == 429 and r.json()["detail"] == "storage quota exceeded"
  assert client.post("/ingest", json=two[:1], headers=h(tokens["other"])).status_code == 200
  assert client.post("/ingest", json=two[:1], headers=h(tokens["other"])).status_code == 200
  assert client.post("/ingest", json=two[1:], headers=h(tokens["other"])).status_code == 429
  assert client.post("/ingest", json=two[1:], headers=h(tokens["owner"])).status_code == 200


def test_ask_falls_back_to_the_template_answer(setup, monkeypatch):
  client, tokens, g, _ = setup
  def boom(*_):
    raise ValueError("unparseable model output")
  monkeypatch.setattr(g.answerer, "answer", boom)
  r = client.post("/ask", json={"question": "sick note?"}, headers=h(tokens["other"]))
  assert r.status_code == 200 and r.json()["answer"]["answer"]
  assert r.json()["views"][0]["node"]["id"] == POLICY


def test_error_responses_do_not_echo_exception_text(setup):
  client, tokens, g, _ = setup
  missing = client.get("/nodes/policy:secret-name", headers=h(tokens["other"]))
  assert missing.status_code == 404 and missing.json()["detail"] == "not found" and "secret" not in missing.text
  client.post("/ingest", json=[doc("doc:b", OTHER, "2022-01-01").model_dump(mode="json")], headers=h(tokens["other"]))
  url = f"/escalations/esc:{DOC_B}:0/resolve"
  assert client.post(url, json={"verdict": "approve"}, headers=h(tokens["owner"])).status_code == 200
  again = client.post(url, json={"verdict": "approve"}, headers=h(tokens["owner"]))
  assert again.status_code == 409 and again.json()["detail"] == "conflict" and DOC_B not in again.text


def test_member_searches_share_a_per_minute_budget(schema):
  now = [0.0]
  clock = lambda: now[0]
  g = make_graph(schema, Rig(extractions={"doc:owner": [owns(OWNER)]}))
  g.ingest([doc("doc:owner", OWNER, "2020-01-01")])
  reg = TokenRegistry()
  member, admin = reg.add(Principal(person_id=OTHER_ID)), reg.add(Principal(person_id="person:admin", role="admin"))
  client = TestClient(create_app(g, reg, rate_limits=RateLimits(searches=SlidingWindow(3, 60, clock=clock))))
  ask = lambda token: client.post("/ask", json={"question": "sick note?"}, headers=h(token)).status_code
  search = lambda token: client.get("/nodes", params={"q": "sick"}, headers=h(token)).status_code
  assert [search(member), ask(member), search(member), ask(member), search(member)] == [200, 200, 200, 429, 429]
  assert client.get("/nodes", headers=h(member)).status_code == 200
  assert [ask(admin) for _ in range(4)] == [200] * 4
  now[0] = 61.0
  assert ask(member) == 200
  assert RateLimits().searches.limit == 60 and RateLimits().searches.seconds == 60


def test_ask_answers_from_redacted_views(setup, monkeypatch):
  client, tokens, g, _ = setup
  g.ask_owner(POLICY, "Private question?", asked_by=OWNER_ID)
  seen = []

  def capture(question, views):
    seen.append(views)
    raise ValueError("no model")

  class Template:
    def answer(self, question, views):
      seen.append(views)
      return g.answerer.fallback.answer(question, views)

  monkeypatch.setattr(g.answerer, "answer", capture)
  monkeypatch.setattr("tokg.api.app.TemplateAnswerer", Template)
  r = client.post("/ask", json={"question": "sick note?"}, headers=h(tokens["other"]))
  assert r.status_code == 200 and len(seen) == 2
  assert all(v.node.id == POLICY and v.escalations == [] for views in seen for v in views)
  assert g.view(POLICY).escalations


def test_member_resend_of_a_clamped_source_is_already_ingested(schema):
  now = [NOW]
  g = Rig(extractions={f"{OTHER_ID}+doc:s": [rule("x", subject="Fresh")]}).graph(schema, clock=lambda: now[0])
  reg = TokenRegistry()
  member = reg.add(Principal(person_id=OTHER_ID))
  client = TestClient(create_app(g, reg, rate_limits=RateLimits(ingested=SlidingWindow(2, 3600))))
  send = lambda source: client.post("/ingest", json=[source.model_dump(mode="json")], headers=h(member))
  soon = doc("doc:s", OTHER, "2026-09-30T12:00:00")
  assert send(soon).status_code == 200 and g.store.get_source(f"{OTHER_ID}+doc:s").timestamp == NOW
  now[0] = NOW + timedelta(hours=1)
  assert send(soon.model_copy(update={"content": "rewritten"})).status_code == 409
  r = send(soon)
  assert r.status_code == 200 and r.json()["outcomes"] == []
  assert g.store.get_source(f"{OTHER_ID}+doc:s").timestamp == NOW
  assert send(doc("doc:t", OTHER, "2026-09-01")).status_code == 200
  assert send(doc("doc:u", OTHER, "2026-09-01")).status_code == 429


def test_person_ids_with_a_plus_are_refused(setup):
  client, *_ = setup
  reg = client.app.state.registry
  for bad in ["person:a+b", "person:+", f"{OTHER_ID}+x"]:
    assert client.get("/me", headers=h(reg.add(Principal(person_id=bad)))).status_code == 403


def test_ask_drops_member_tainted_views_when_a_trusted_hit_exists(schema):
  g = make_graph(schema, Rig(extractions={"doc:owner": [owns(OWNER)], "doc:a": [rule("note always")],
                                          DOC_M: [rule("sick note sick note", subject="Sick note doctor note policy")]}))
  g.ingest([doc("doc:owner", OWNER, "2020-01-01"), doc("doc:a", OWNER, "2021-01-01")])
  g.ingest([doc(DOC_M, OTHER, "2021-02-01")], trust_speakers=False)
  reg = TokenRegistry()
  client = TestClient(create_app(g, reg))
  token = reg.add(Principal(person_id=OWNER_ID))
  ask = lambda q: [v["node"]["id"] for v in client.post("/ask", json={"question": q}, headers=h(token)).json()["views"]]
  assert ask("sick note doctor policy") == [POLICY]
  assert ask("doctor") == ["policy:sick-note-doctor-note-policy"]


def test_rejected_requests_do_not_consume_budget(schema):
  now = [0.0]
  clock = lambda: now[0]
  g = make_graph(schema, Rig(extractions={"doc:owner": [owns(OWNER)]}))
  g.ingest([doc("doc:owner", OWNER, "2020-01-01")])
  reg = TokenRegistry()
  member = reg.add(Principal(person_id=OTHER_ID))
  limits = RateLimits(requests=SlidingWindow(1000, 60, clock=clock), ingested=SlidingWindow(3, 3600, clock=clock),
                      ingested_bytes=SlidingWindow(5, 3600, clock=clock), asks=SlidingWindow(2, 3600, clock=clock),
                      searches=SlidingWindow(1, 60, clock=clock), questions=SlidingWindow(2, 3600, clock=clock))
  client = TestClient(create_app(g, reg, rate_limits=limits))
  big = doc("doc:big", OTHER, "2022-01-01", content="x" * 6000).model_dump(mode="json")
  assert client.post("/ingest", json=[big], headers=h(member)).status_code == 429
  small = [doc(f"doc:{i}", OTHER, "2022-01-01").model_dump(mode="json") for i in range(3)]
  assert client.post("/ingest", json=small, headers=h(member)).status_code == 200
  ask = {"question": "q?"}
  assert [client.post("/ask", json=ask, headers=h(member)).status_code for _ in range(3)] == [200, 429, 429]
  now[0] = 61.0
  assert client.post("/ask", json=ask, headers=h(member)).status_code == 200
  for _ in range(MAX_OPEN_ESCALATIONS_PER_AUTHOR):
    g.ask_owner(POLICY, "q?", asked_by=OTHER_ID)
  url = f"/nodes/{POLICY}/questions"
  assert [client.post(url, json=ask, headers=h(member)).status_code for _ in range(3)] == [409] * 3
  for e in g.store.escalations():
    g.store.put_escalation(e.model_copy(update={"status": "answered"}))
  assert [client.post(url, json=ask, headers=h(member)).status_code for _ in range(3)] == [200, 200, 429]


def test_sliding_window_peek_does_not_charge():
  w = SlidingWindow(2, 60, clock=lambda: 0.0)
  assert w.peek("k", 2) is None and w.peek("k", 3) == 60
  assert w.hit("k", 2) is None and w.peek("k") is not None


def test_multi_window_charges_hold_one_lock():
  from tokg.api.app import _CHARGE_LOCK, _check_all, _throttle_all
  seen = []

  class Watched(SlidingWindow):
    def peek(self, key, cost=1):
      seen.append(("peek", _CHARGE_LOCK.locked()))
      return super().peek(key, cost)

    def hit(self, key, cost=1):
      seen.append(("hit", _CHARGE_LOCK.locked()))
      return super().hit(key, cost)

  p = Principal(person_id=OTHER_ID)
  a, b = Watched(5, 60, clock=lambda: 0.0), Watched(5, 60, clock=lambda: 0.0)
  _throttle_all(p, [(a, 1), (b, 1)])
  _check_all(p, [(a, 1)])
  assert seen == [("peek", True), ("peek", True), ("hit", True), ("hit", True), ("peek", True)]
  assert not _CHARGE_LOCK.locked()


def test_ingest_without_new_sources_does_not_save(setup):
  client, tokens, _, saves = setup
  stored = doc("doc:a", OWNER, "2021-01-01").model_dump(mode="json")
  assert client.post("/ingest", json=[stored], headers=h(tokens["admin"])).status_code == 200
  assert client.post("/ingest", json=[], headers=h(tokens["other"])).status_code == 200
  assert saves == []
  client.post("/ingest", json=[doc("doc:n", OTHER, "2022-01-01").model_dump(mode="json")], headers=h(tokens["other"]))
  assert saves == [1]


def test_member_storage_has_a_global_byte_cap(setup, monkeypatch):
  client, tokens, g, _ = setup
  monkeypatch.setattr(tokg.api.app, "MAX_MEMBER_STORAGE_BYTES", 6000)
  bulky = [doc("doc:big", OWNER, "2021-01-01", content="x" * 5000).model_dump(mode="json")]
  assert client.post("/ingest", json=bulky, headers=h(tokens["owner"])).status_code == 200
  small = [doc("doc:s", OTHER, "2022-01-01").model_dump(mode="json")]
  assert client.post("/ingest", json=small, headers=h(tokens["other"])).status_code == 200
  big = [doc("doc:t", OTHER, "2022-01-01", content="y" * 2000).model_dump(mode="json")]
  r = client.post("/ingest", json=big, headers=h(tokens["other"]))
  assert r.status_code == 429 and r.json()["detail"] == "storage quota exceeded"
  assert client.post("/ingest", json=big, headers=h(tokens["admin"])).status_code == 200


def test_member_storage_is_counted_once_and_skipped_without_new_sources(setup, monkeypatch):
  client, tokens, g, _ = setup
  sent = [doc("doc:s", OTHER, "2022-01-01").model_dump(mode="json")]
  assert client.post("/ingest", json=sent, headers=h(tokens["other"])).status_code == 200
  stored = g.store.get_source(f"{OTHER_ID}+doc:s")
  assert client.app.state.member_bytes == len(stored.model_dump_json().encode())
  monkeypatch.setattr(tokg.api.app, "MAX_MEMBER_STORAGE_BYTES", 0)
  monkeypatch.setattr(type(g.store), "sources", lambda self: pytest.fail("quota rescanned the store"))
  assert client.post("/ingest", json=sent, headers=h(tokens["other"])).status_code == 200
