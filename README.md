# Recall

**Find it. Understand it. Trust it.** Organisational knowledge that stays current, owned and sourced.
*Built on **TOKG**, a temporal ownership knowledge graph.*

![Recall answering a question with the current process, its sources and the person to ask](docs/assets/demo.gif)

Companies now produce more text than anyone can read: emails, meeting summaries, wikis and policy documents, and more and more of it is AI-generated. Search and AI assistants can find all of it. What they can't tell you is which version is current, whether it applies to your case, or whose word counts. The information exists, but people can't act on it with confidence.

Recall ingests those scattered sources and turns them into a knowledge graph of facts. Each fact records when it is valid, who owns it, and the exact quote it came from. When a new source contradicts an old one, TOKG either supersedes the old fact while keeping its history, or escalates the change to the owner for approval. So a question gets one answer that applies to *your* context, with the evidence behind it and the person to ask when the documents run out.

## What it does

- **Temporal**: every fact is valid over a date range. Newer knowledge supersedes older without deleting it, so you can see what was true on any date and why it changed.
- **Ownership**: every piece of knowledge has an accountable owner, and handovers are tracked too. A change from a non-owner stays *pending* until the owner approves it, and the graph enforces this, not the LLM.
- **Grounding**: every fact links to its source document and the exact supporting quote. Answers may only cite facts that were actually retrieved, and anything else is dropped.
- **Human in the loop**: approvals, conflicts and open questions are sent to the owner. Their answers are fed back in as new sources, so the next person gets the answer from the graph instead of from the owner. People are only pulled in when needed, which keeps the human oversight budget fixed.
- **Automated extraction**: an LLM (Claude Code via LangChain) extracts facts according to a domain schema written in YAML. The core library is domain-agnostic.
- **Denoising**: repeated statements merge into one fact with several sources. Superseded versions and facts for other contexts move out of the way instead of competing with the answer. Anything that doesn't fit the schema is dropped with a reason.

## Example: hiring a non-EU developer

> *"How do I hire a non-EU citizen in Belgium?"* (a hiring manager at Lumivia NV, a 46-person software company in Ghent)

The knowledge is scattered:
- a 2023 wiki page ("the hiring manager emails the file, about 4 months");
- a 2025 meeting where the process changed, buried in a long AI-generated summary;
- a stale copy of the old process that someone else put on the wiki later;
- the email threads of two previous hires.

Search returns all of it. Recall returns one answer:

| | Recall's answer |
|---|---|
| **Current process** | Apply through the regional online platform. **Only Sophie Claes (HR & Immigration) submits.** It takes about 2.5–3 months. |
| **Why this version** | The March 2025 meeting decision **superseded** the 2023 wiki process. The old version is still in the history, with its dates. The stale wiki copy only restates the old process, so it can't override the newer decision. |
| **Precedent** | Ravi Kumar (India, old process, with lessons learned) and Camila Souza (Brazil, new process, 11 weeks). Each links to the emails it came from. |
| **Evidence** | The exact passage in the meeting summary, and the exact lines of each email. |
| **Ask** | **Sophie Claes**, owner of the process. |

The mock data comes with two more scenarios ([`examples/data/README.md`](examples/data/README.md)), each with a planted trap:
- **Single-day sick leave**: no doctor's note is needed. The trap is a colleague who isn't the owner saying a note is always required. The owner is Marc Dubois of SD Worx.
- **Hardware purchases**: order through the IT portal, not Amazon plus an expense claim. The trap is a line manager saying "just expense it". The owner is Tom Verbeke.

## Setup

Requires [uv](https://docs.astral.sh/uv/) and Python 3.13+. For live LLM mode you also need the [Claude Code](https://claude.com/claude-code) CLI, logged in. No API key is needed. The mock employee portal needs Node 20+.

```bash
git clone https://github.com/YusufHosny/tokg && cd tokg
uv sync --all-extras
uv run pytest                # the test suite needs no LLM
```

## Usage

The Lumivia config is in `examples/lumivia/`:
- `schema.yaml` defines the domain.
- `seed.yaml` is the human bootstrap: people from `examples/data/people.json`, canonical topics, initial owners and authorities.
- `rig.yaml` is a recorded run for deterministic replay.

**Build the graph and ask.** `--rig` replays the recorded extraction, decisions and answers, so no LLM is needed:

```bash
FLAGS="-s examples/lumivia/schema.yaml --seed examples/lumivia/seed.yaml --store lumivia.snapshot.json --rig examples/lumivia/rig.yaml"
uv run tokg ingest examples/data $FLAGS
uv run tokg ask "How do I hire a non-EU citizen in Belgium?" $FLAGS -c country=BE
```

**Live mode.**
- Drop `--rig` to extract and answer with Claude Code. Set `TOKG_MODEL` to change the model (default `sonnet`).
- Add `--llm-resolve` to let the LLM resolve updates too.
- `--record PATH` runs live and writes everything into a new rig file for replay. It can't be combined with `--rig`.

**HTTP API**, for the web app:

```bash
uv run tokg token person:sophie-claes-lumivia-be --tokens tokens.yaml --role admin   # prints a token once
uv run tokg serve $FLAGS --tokens tokens.yaml --cors http://localhost:5173
curl -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"question": "How do I hire a non-EU citizen in Belgium?", "context": {"country": "BE"}}' localhost:8000/ask
```

**MCP**: query Recall from your own agent (e.g. Claude Code):

```bash
claude mcp add recall -- uv run --directory "$PWD" tokg mcp $FLAGS --user person:pieter-janssens-lumivia-be
```

**Mock employee portal.** New tickets are written to `examples/data/portal/` and become a new source for Recall:

```bash
cd examples/dummy-app && npm install && npm run dev    # http://localhost:5173
```

**As a library:**

```python
from tokg import KnowledgeGraph, Schema, load_sources
from tokg.seed import Seed

graph = KnowledgeGraph(Schema.from_yaml("examples/lumivia/schema.yaml"),  # in-memory store, Claude Code extraction
                       seed=Seed.from_yaml("examples/lumivia/seed.yaml"))  # bootstraps people, topics, owners
graph.ingest(load_sources("examples/data"), workers=8)                   # parallel extraction, chronological resolution
result = graph.ask("How do I hire a non-EU citizen in Belgium?", {"country": "BE"})
result.answer, result.views[0].owner, result.views[0].contacts   # the answer, who owns it, who to ask
```

More detail: [`docs/technical.md`](docs/technical.md) (how TOKG works, the data model and the stack) · [`docs/business.md`](docs/business.md) (market, model and roadmap).

**Unfinished:** the Recall web app is still in progress. The Neo4j store is included but untested; the in-memory store with JSON snapshots is the supported backend.

## Team

Made by team **AlladinsAgents** (Yusuf Hussein, Karam Kokash, Ahmed Salheen and Alex Gretski, *alpha leader*) at the **Tectonic 2026 hackathon in Leuven**, for the SD Worx challenge *"Unlock the Knowledge Within"*.
