# ABOUTME: HTTP API tests: bearer auth, member vs admin rights, owner-only escalation actions and
# ABOUTME: the author-forging guard on /ingest.
import pytest
from conftest import OTHER, OTHER_ID, OWNER, OWNER_ID, doc, make_graph, owns, rule
from fastapi.testclient import TestClient

from tokg.api import Principal, TokenRegistry, create_app
from tokg.rig import Rig

POLICY = "policy:sick-note"


@pytest.fixture
def setup(schema):
  g = make_graph(schema, Rig(extractions={
    "doc:owner": [owns(OWNER)], "doc:a": [rule("note always")], "doc:b": [rule("no note day 1")]}))
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
  assert g.store.get_source("doc:b").author == OTHER_ID
  assert g.store.get_fact("doc:b:0").status == "pending"
  assert saves


def test_escalation_is_owner_only(setup):
  client, tokens, g, _ = setup
  client.post("/ingest", json=[doc("doc:b", OTHER, "2022-01-01").model_dump(mode="json")],
              headers=h(tokens["other"]))
  mine = client.get("/escalations", params={"mine": True}, headers=h(tokens["owner"])).json()
  assert [e["id"] for e in mine] == ["esc:doc:b:0"]
  body = {"verdict": "approve"}
  assert client.post("/escalations/esc:doc:b:0/resolve", json=body, headers=h(tokens["other"])).status_code == 403
  assert client.post("/escalations/esc:doc:b:0/resolve", json=body, headers=h(tokens["admin"])).status_code == 403
  r = client.post("/escalations/esc:doc:b:0/resolve", json=body, headers=h(tokens["owner"]))
  assert r.status_code == 200 and r.json()["status"] == "approved"
  assert client.post("/escalations/esc:doc:b:0/resolve", json=body, headers=h(tokens["owner"])).status_code == 409


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
