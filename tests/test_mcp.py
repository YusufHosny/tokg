# ABOUTME: MCP server smoke test through FastMCP's in-memory client.
import asyncio
import threading
import time

from click import unstyle
from conftest import DATA, FOO, OTHER_ID, OWNER, OWNER_ID, doc, make_graph, owns, rule
from fastmcp import Client
from typer.testing import CliRunner

import tokg.answer
import tokg.mcp
from tokg.api.app import SlidingWindow
from tokg.cli import STORE_IN_USE, _store_lock, app
from tokg.graph import MAX_OPEN_ESCALATIONS_PER_AUTHOR
from tokg.mcp import READ_ONLY, create_mcp
from tokg.models import SourceRef
from tokg.rig import Rig
from tokg.store import MemoryStore
from tokg.views import Answer

NOTE_ID = "note:esc:q:policy-sick-note:0"
SECRET = "Secret salary of Bob?"


def test_mcp_tools(schema):
  g = make_graph(schema, Rig(extractions={"doc:a": [owns(OWNER), rule("no note day 1", country="BE")]}))
  g.ingest([doc("doc:a", OWNER, "2021-01-01")])
  mcp = create_mcp(g, OTHER_ID)

  async def run():
    async with Client(mcp) as c:
      names = {t.name for t in await c.list_tools()}
      found = await c.call_tool("search", {"query": "sick note"})
      view = await c.call_tool("view_node", {"node_id": "policy:sick-note", "context": {"country": "BE"}})
      missing = await c.call_tool("view_node", {"node_id": "policy:nope"})
      esc = await c.call_tool("ask_owner", {"node_id": "policy:sick-note", "question": "why?"})
      return names, found, view, missing, esc

  names, found, view, missing, esc = asyncio.run(run())
  assert names == {"search", "view_node", "ask", "ask_owner", "gaps"}
  assert found.structured_content["result"][0]["id"] == "policy:sick-note"
  assert view.structured_content["owner"]["name"] == "Olga Owner"
  assert "error" in missing.structured_content
  assert esc.structured_content["raised_by"] == OTHER_ID


def test_mcp_hides_foreign_escalations_and_caps_input(schema):
  g = make_graph(schema, Rig(extractions={"doc:a": [owns(OWNER), rule("no note day 1", country="BE")]}))
  g.ingest([doc("doc:a", OWNER, "2021-01-01")])
  g.ask_owner("policy:sick-note", "foreign?", asked_by="person:third")
  member, owner = create_mcp(g, OTHER_ID), create_mcp(g, OWNER_ID)

  async def run(mcp, calls):
    async with Client(mcp) as c:
      return [await c.call_tool(name, args, raise_on_error=False) for name, args in calls]

  own, view, ask, gaps, forged, long_q, wide_ctx = asyncio.run(run(member, [
    ("ask_owner", {"node_id": "policy:sick-note", "question": "mine?"}),
    ("view_node", {"node_id": "policy:sick-note"}),
    ("ask", {"question": "sick note"}),
    ("gaps", {}),
    ("ask_owner", {"node_id": "policy:sick-note", "question": "x", "asked_by": OWNER_ID}),
    ("ask_owner", {"node_id": "policy:sick-note", "question": "x" * 2001}),
    ("view_node", {"node_id": "policy:sick-note", "context": {f"k{i}": "v" for i in range(17)}}),
  ]))
  assert own.structured_content["raised_by"] == OTHER_ID
  assert [e["question"] for e in view.structured_content["escalations"]] == ["mine?"]
  assert [e["question"] for e in ask.structured_content["views"][0]["escalations"]] == ["mine?"]
  assert [e["question"] for e in gaps.structured_content["open_escalations"]] == ["mine?"]
  assert forged.is_error and long_q.is_error and wide_ctx.is_error
  assert len(g.store.escalations()) == 2

  [owner_view] = asyncio.run(run(owner, [("view_node", {"node_id": "policy:sick-note"})]))
  assert {e["question"] for e in owner_view.structured_content["escalations"]} == {"foreign?", "mine?"}


def test_mcp_masks_internal_errors(schema, monkeypatch):
  g = make_graph(schema, Rig())
  monkeypatch.setattr(g, "gaps", lambda: (_ for _ in ()).throw(RuntimeError("/srv/secret/path")))

  async def run():
    async with Client(create_mcp(g, OTHER_ID)) as c:
      return await c.call_tool("gaps", {}, raise_on_error=False)

  result = asyncio.run(run())
  assert result.is_error and "/srv/secret" not in result.content[0].text


def _run(mcp, calls):
  async def run():
    async with Client(mcp) as c:
      return [await c.call_tool(name, args, raise_on_error=False) for name, args in calls]

  return asyncio.run(run())


def test_mcp_hides_private_answer_notes(schema):
  g = make_graph(schema, Rig(extractions={"doc:owner": [owns(OWNER)], NOTE_ID: [rule("acme opts out")]}))
  g.ingest([doc("doc:owner", OWNER, "2020-01-01")])
  esc = g.ask_owner("policy:sick-note", SECRET, asked_by=OTHER_ID)
  g.answer_escalation(esc.id, OWNER_ID, "acme opts out")
  fact = next(f for f in g.store.facts() if any(r.source_id == NOTE_ID for r in f.sources))
  fact.sources[0].quote = f"{SECRET} acme opts out"
  g.store.put_fact(fact)
  calls = [("view_node", {"node_id": "policy:sick-note"}), ("ask", {"question": "sick note?"})]
  view, ask = _run(create_mcp(g, "person:stranger"), calls)
  for body in [view.structured_content, *ask.structured_content["views"]]:
    notes = [s for f in body["current"] for s in f["sources"] if s["ref"]["source_id"] == NOTE_ID]
    assert notes and all(s["source"]["content"] == "acme opts out" and s["ref"]["quote"] is None for s in notes)
    assert "Secret salary" not in str(body)
  view, ask = _run(create_mcp(g, OTHER_ID), calls)
  assert "Secret salary" in str(view.structured_content) and "Secret salary" in str(ask.structured_content)


def test_mcp_redacts_source_paths(schema):
  g = make_graph(schema, Rig(extractions={"doc:a": [owns(OWNER), rule("note always")]}))
  g.ingest([doc("doc:a", OWNER, "2021-01-01")])
  g.store.put_source(doc("doc:u", OWNER, "2022-01-01").model_copy(
    update={"uri": "/home/someone/tokg/examples/data/emails/u.eml"}))
  fact = next(f for f in g.store.facts() if f.statement.kind == "attribute")
  fact.sources.append(SourceRef(source_id="doc:u"))
  g.store.put_fact(fact)
  view, ask = _run(create_mcp(g, OTHER_ID), [("view_node", {"node_id": "policy:sick-note"}),
                                            ("ask", {"question": "sick note?"})])
  for body in [view.structured_content, *ask.structured_content["views"]]:
    uris = [s["source"]["uri"] for f in body["current"] for s in f["sources"] if s["source"]]
    assert "examples/data/emails/u.eml" in uris and "/home/someone" not in str(body)


def test_mcp_ask_owner_persists_through_callback(schema, tmp_path):
  g = make_graph(schema, Rig(extractions={"doc:a": [owns(OWNER)]}))
  g.ingest([doc("doc:a", OWNER, "2021-01-01")])
  path = tmp_path / "store.json"
  saves = []
  mcp = create_mcp(g, OTHER_ID, on_change=lambda: saves.append(g.store.save(path)))
  esc, missing = _run(mcp, [("ask_owner", {"node_id": "policy:sick-note", "question": "why?"}),
                            ("ask_owner", {"node_id": "policy:nope", "question": "why?"})])
  assert "error" in missing.structured_content and len(saves) == 1
  saved = MemoryStore.load(path).get_escalation(esc.structured_content["id"])
  assert saved is not None and saved.raised_by == OTHER_ID


def test_mcp_ask_owner_is_rate_limited(schema):
  now = [0.0]
  g = make_graph(schema, Rig(extractions={"doc:a": [owns(OWNER)]}))
  g.ingest([doc("doc:a", OWNER, "2021-01-01")])
  mcp = create_mcp(g, OTHER_ID, questions=SlidingWindow(2, 3600, clock=lambda: now[0]))
  ask = ("ask_owner", {"node_id": "policy:sick-note", "question": "why?"})
  results = _run(mcp, [ask, ask, ask])
  assert [("error" in r.structured_content) for r in results] == [False, False, True]
  assert len(g.store.escalations()) == 2
  now[0] = 3601.0
  [later] = _run(mcp, [ask])
  assert later.structured_content["raised_by"] == OTHER_ID
  defaults = _run(create_mcp(g, OWNER_ID), [ask] * 21)
  assert [("error" in r.structured_content) for r in defaults] == [False] * 20 + [True]


def test_mcp_rejected_ask_owner_keeps_budget(schema):
  g = make_graph(schema, Rig(extractions={"doc:a": [owns(OWNER)]}))
  g.ingest([doc("doc:a", OWNER, "2021-01-01")])
  for i in range(MAX_OPEN_ESCALATIONS_PER_AUTHOR):
    g.ask_owner("policy:sick-note", f"q{i}?", asked_by=OTHER_ID)
  saves = []
  mcp = create_mcp(g, OTHER_ID, on_change=lambda: saves.append(1), questions=SlidingWindow(1, 3600))
  ask = ("ask_owner", {"node_id": "policy:sick-note", "question": "why?"})
  capped, missing = _run(mcp, [ask, ("ask_owner", {"node_id": "policy:nope", "question": "why?"})])
  assert "open escalations" in capped.structured_content["error"]
  assert "no node" in missing.structured_content["error"] and saves == []
  g.store.put_escalation(g.store.escalations()[0].model_copy(update={"status": "answered"}))
  ok, limited = _run(mcp, [ask, ask])
  assert ok.structured_content["raised_by"] == OTHER_ID and saves == [1]
  assert limited.structured_content == {"error": "rate limit exceeded"}

def test_mcp_tools_are_serialised(schema, monkeypatch):
  g = make_graph(schema, Rig(extractions={"doc:a": [owns(OWNER), rule("note always")]}))
  g.ingest([doc("doc:a", OWNER, "2021-01-01")])
  mcp = create_mcp(g, OTHER_ID)
  active, peak, original = [0], [0], g.search

  def slow(*args, **kwargs):
    active[0] += 1
    peak[0] = max(peak[0], active[0])
    time.sleep(0.05)
    active[0] -= 1
    return original(*args, **kwargs)

  monkeypatch.setattr(g, "search", slow)
  search, ask = (asyncio.run(mcp.get_tool(name)).fn for name in ("search", "ask"))
  calls = [lambda: search("sick note"), lambda: ask("sick note?")] * 3
  workers = [threading.Thread(target=c) for c in calls]
  for w in workers:
    w.start()
  for w in workers:
    w.join(10)
  assert peak[0] == 1


def test_mcp_read_only_refuses_questions(schema):
  g = make_graph(schema, Rig(extractions={"doc:a": [owns(OWNER)]}))
  g.ingest([doc("doc:a", OWNER, "2021-01-01")])
  saves = []
  mcp = create_mcp(g, OTHER_ID, on_change=lambda: saves.append(1), read_only=True)
  esc, found = _run(mcp, [("ask_owner", {"node_id": "policy:sick-note", "question": "why?"}),
                          ("search", {"query": "sick note"})])
  assert esc.structured_content == {"error": READ_ONLY}
  assert found.structured_content["result"][0]["id"] == "policy:sick-note"
  assert g.store.escalations() == [] and saves == []


def test_mcp_gaps_redact_private_quotes(schema):
  g = make_graph(schema, Rig(extractions={"doc:owner": [owns(OWNER)], NOTE_ID: [rule("acme opts out")]}))
  g.ingest([doc("doc:owner", OWNER, "2020-01-01")])
  esc = g.ask_owner("policy:sick-note", SECRET, asked_by=OTHER_ID)
  g.answer_escalation(esc.id, OWNER_ID, "acme opts out")
  fact = next(f for f in g.store.facts() if any(r.source_id == NOTE_ID for r in f.sources))
  fact.status, fact.sources[0].quote = "pending", f"{SECRET} acme opts out"
  g.store.put_fact(fact)
  [stranger] = _run(create_mcp(g, "person:stranger"), [("gaps", {})])
  [asker] = _run(create_mcp(g, OTHER_ID), [("gaps", {})])
  assert stranger.structured_content["pending"] and "Secret salary" not in str(stranger.structured_content)
  assert "Secret salary" in str(asker.structured_content["pending"])


def _cli(*args):
  result = CliRunner().invoke(app, [*map(str, args)])
  return result.exit_code, " ".join(unstyle(result.output).split())


def _ingest_args(store):
  return ["ingest", DATA, "-s", FOO / "schema.yaml", "--seed", FOO / "seed.yaml", "--rig", FOO / "rig.yaml",
          "--store", store]


def test_cli_ingest_refuses_a_served_store(tmp_path):
  store = tmp_path / "store.json"
  with _store_lock(store) as locked:
    assert locked
    code, output = _cli(*_ingest_args(store))
  assert code == 1 and STORE_IN_USE in output and not store.exists()
  code, output = _cli(*_ingest_args(store))
  assert code == 0 and "34 sources, 58 claims" in output and store.exists()
  assert (tmp_path / "store.json.lock").stat().st_mode & 0o777 == 0o600


def test_cli_mcp_is_read_only_while_served(tmp_path, monkeypatch):
  store, made = tmp_path / "store.json", []

  class Server:
    def run(self, **_):
      pass

  def fake(graph, user, on_change=None, read_only=False):
    made.append((on_change, read_only))
    return Server()

  monkeypatch.setattr(tokg.mcp, "create_mcp", fake)
  args = ["mcp", "-s", FOO / "schema.yaml", "--seed", FOO / "seed.yaml", "--store", store, "--user", OTHER_ID]
  with _store_lock(store):
    assert _cli(*args)[0] == 0
  assert _cli(*args)[0] == 0
  (busy_save, busy), (free_save, free) = made
  assert busy and busy_save is None and not free and free_save is not None


def test_cli_ask_record_saves_only_the_rig(tmp_path, monkeypatch):
  store, record, saves = tmp_path / "store.json", tmp_path / "rec.yaml", []
  assert _cli(*_ingest_args(store))[0] == 0
  before = store.read_bytes()
  monkeypatch.setattr(tokg.answer.LLMAnswerer, "answer", lambda self, q, views: Answer(answer="recorded"))
  monkeypatch.setattr(MemoryStore, "save", lambda *a: saves.append(a))
  code, output = _cli("ask", "hiring?", "-s", FOO / "schema.yaml", "--seed", FOO / "seed.yaml",
                      "--store", store, "--record", record)
  assert code == 0 and "recorded" in output and saves == [] and store.read_bytes() == before
  assert list(Rig.from_yaml(record).answers) == ["hiring?"]


def test_mcp_ask_answers_from_redacted_views(schema, monkeypatch):
  g = make_graph(schema, Rig(extractions={"doc:a": [owns(OWNER), rule("note always")]}))
  g.ingest([doc("doc:a", OWNER, "2021-01-01")])
  g.ask_owner("policy:sick-note", SECRET, asked_by=OWNER_ID)
  seen, answer = [], g.answerer.answer
  monkeypatch.setattr(g.answerer, "answer", lambda q, views: seen.append(views) or answer(q, views))
  [ask] = _run(create_mcp(g, OTHER_ID), [("ask", {"question": "sick note?"})])
  assert [[v.node.id for v in views] for views in seen] == [["policy:sick-note"]]
  assert seen[0][0].escalations == [] and SECRET not in str(ask.structured_content)


def test_cli_token_refuses_plus_in_person_ids(tmp_path):
  tokens = tmp_path / "tokens.yaml"
  code, output = _cli("token", "person:a+b", "--tokens", tokens)
  assert code == 2 and "without '+'" in output and not tokens.exists()
  assert _cli("token", "person:a-b", "--tokens", tokens)[0] == 0 and tokens.exists()
