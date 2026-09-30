# Prompt
This is the plan for our Tectonic Hackathon project (SD Worx track). Help me understand it and reason about it in full detail. I will get tasks from the team to implement parts of it and will ask questions along the way.


# Plan

## The challenge (SD Worx: "Unlock the Knowledge Within — Find it. Understand it. Trust it.")
> "How might we turn fragmented organisational knowledge into a trusted shared resource?"

SD Worx runs HR and payroll for 100,000+ customers across Europe, with payroll reach into 100+ countries. Their knowledge lives in policies, manuals, emails, Teams chats, workflows and experts' heads. Finding information is not the hard part: search returns ten answers and an AI assistant can summarise them. The hard part is knowing whether an answer is **reliable, current and relevant to this customer, country or situation**, and who to ask when documents are not enough.

Their own example of the friction: an urgent customer question comes in. The AI assistant finds three documents: one recently updated, one with no owner, and one that may apply to another country. Then a colleague shares contradictory information from a Teams conversation. The employee has found information but still cannot act with confidence.

The questions the challenge asks, and how we answer each one:

| SD Worx question | Our answer |
|---|---|
| What is current? | **Temporal**: every fact has a validity interval; newer facts supersede older ones, and the history stays auditable. |
| What is reliable / which answer should I trust? | **Ownership + provenance**: every fact has an accountable owner and links back to the raw sources it came from. An answer confirmed by its owner beats an unowned chat message. |
| What applies in this context? | **Schema-scoped facts**: facts are tagged with the context they apply to (country, contract type, customer, …) as defined by the domain schema. |
| Where are the gaps? | **Detection**: conflicts, missing owners, stale facts and unanswered questions show up as graph states, not buried text. |
| Who has relevant expertise? | **Ownership edges**: the graph answers "who do I ask" directly, and unresolved questions escalate to that person. |

This covers all four of their inspiration areas: **Trust** (provenance and ownership), **Capture** (ingestors), **Detect** (conflict and staleness), **Connect** (owners and escalation).

### How we frame it: start from the moment of doubt
SD Worx explicitly says: *don't start with prescribed technology, start with the moment of doubt*, and *don't hide complexity behind a black box, make trust visible*. So the pitch and demo lead with the employee's doubt ("which of these three answers do I trust?") and show how the system resolves it visibly: this is the current version, this is who owns it, these are the sources, this is what it replaced, and this is who to ask. The knowledge graph is how we do it, not what we pitch.

## The underlying problem: overwhelming data abundance (ODA)
Recording everything is now cheap, and LLMs made human-like text production unbounded. Organisations now have more meeting summaries, reports and chat logs than anyone can read, and their processes were not built for that volume. We call this the ODA problem. For a company, it shows up as:

* **Loss of data ownership**: agents can find an update in a meeting summary but cannot say who is responsible for it. This breaks maintenance, escalation and compliance.
* **Overlap and temporal decay**: three meeting summaries can contain contradicting decisions, and it is unclear which one is the latest.
* **Reading fatigue**: verbose, low-signal text gets skipped, the same way people rubber-stamp approval prompts. More data leads to less use.

## Our solution: tokg (temporal ownership knowledge graph)
An LLM extracts structured facts from unstructured sources (email, meeting notes, wiki, …) into a knowledge graph shaped by a domain schema. Three properties are built into the model itself:

1. **Temporal**: facts evolve. New information supersedes old, and nothing is silently overwritten.
2. **Ownership**: every fact has an owner, set at creation. Owners decide whose word counts, and they are the escalation target.
3. **Provenance**: every fact links to the source fragments it came from, so users can drill down and check it.

**Fixed human oversight budget**: humans bootstrap the graph (schema, initial owners). After that, ingestion keeps it up to date, and humans are only pulled in when the system escalates. Human effort stays bounded and decreases over time while the graph stays useful.

## Architecture

### The core library (`tokg`), which Yusuf is building
`tokg` is **domain-agnostic**. It knows nothing about hiring, HR or SD Worx. Every domain gets plugged in through a schema.

* **Schema format**: a declarative, buildable format for defining node types, edge types, their fields, and which fields scope a fact's context (e.g. `country`). The library provides the format and validation; each use case writes its own schema.
* **Ingestors**: an `Ingestor` interface that turns raw input into source documents. It ships with 3 examples (email, meeting summary, wiki page).
* **Extraction and resolution**: an LLM extracts candidate facts against the schema, then a resolver decides what to do with each one against the existing graph: *create*, *supersede*, *merge/confirm*, *conflict*, or **escalate to a human** (the owner). This uses LangChain `invoke` with structured output. The model backend is pluggable, including Claude Code through our `langchain_cli_agents` lib.
* **Rigged mode**: the whole extraction and resolution flow can be replaced by scripted, deterministic responses, so the demo video is reproducible and needs no live LLM.
* **Temporal model**: our own simplified model, not a production-grade one. Facts have `valid_from`/`valid_to` and a supersedes chain; the "current" view is a query, and history is always kept.
* **Persistence**: a `GraphStore` interface with an in-memory implementation (pickle for backup/restore) as the primary, plus a Neo4j implementation that we generate but do not test.
* **Interfaces**: a FastAPI server (for the demo app) and an MCP server built with FastMCP (so users can query the graph from their own agents).

### The demo (in `examples/`), which the rest of the team is building
* A domain schema for the SD Worx use case (e.g. HR processes and tribal knowledge: hiring in a given country, who to contact for X).
* Mock source data (emails, meeting notes, wiki pages) with planted contradictions, stale facts and ownerless documents.
* A web app (Vite + React + Tailwind, or Next.js) that talks to the tokg API.
* Demo scenarios, to be defined later. SD Worx's own stories (the "three documents plus a Teams message" moment, or a payroll consultant inheriting a client portfolio) are strong starting points because they match the challenge exactly.

Running example, for grounding only: *"How do I hire a non-EU citizen in Belgium?"* The answer needs the **current** single permit process (temporal), **previous hires** with their sources (provenance), and **which hiring manager to ask** (ownership).

### Build order
1. Core library: data model, schema format, store interface and in-memory store, ingestion, extract/resolve pipeline with rigged mode, API + MCP.
2. Library documentation, so the team can build the schema against it.
3. Schema, demo data, scenarios and demo app (in parallel, by the team).

## Hackathon constraints that affect the build
**Judging**: originality 30%, technical ability ("does it work?") 30%, fit to the challenge 30%, security 10%.

* **Security (Aikido AI code audit)**: it checks business-logic flaws, IDOR, authentication and authorisation. We run a baseline scan, fix the findings, and submit before/after screenshots. The API and MCP therefore need at least simple auth. Ownership doubles as authorisation: only a fact's owner can approve an escalated change, and no endpoint should let you bypass that. No API keys or secrets in the repo.
* **Submission (Builderbase)**: a short description, a **demo video under 3 minutes**, the GitHub repo link, and the Aikido screenshots.
* **Repo**: public until judging ends, and it must have a short README (what it is, how to run it, what is unfinished).
* Everything must be built during the hackathon time slot. Final means final.
* Optional partner tools: ElevenLabs (e.g. voice-over for the demo video), Google Cloud (credentials valid for 1 week), Cursor.
