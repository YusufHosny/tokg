# TOKG: technical overview

TOKG (temporal ownership knowledge graph) is the engine behind Recall. It is a domain-agnostic Python library. A use case supplies a **schema** (what kinds of things exist) and **sources** (raw text). TOKG returns **views**: the knowledge that is current, owned, sourced and applicable to a given context.

- [1. Why a temporal ownership graph](#1-why-a-temporal-ownership-graph)
- [2. Pipeline](#2-pipeline)
- [3. Data model](#3-data-model)
- [4. Resolution: how knowledge changes](#4-resolution-how-knowledge-changes)
- [5. Querying: what is current, and for whom](#5-querying-what-is-current-and-for-whom)
- [6. Human in the loop](#6-human-in-the-loop)
- [7. Schema format](#7-schema-format)
- [8. Sources and ingestors](#8-sources-and-ingestors)
- [9. LLM stages and rigged mode](#9-llm-stages-and-rigged-mode)
- [10. Interfaces: Python, HTTP, MCP, CLI](#10-interfaces-python-http-mcp-cli)
- [11. Security model](#11-security-model)
- [12. Tech stack and code map](#12-tech-stack-and-code-map)
- [13. Limitations and next steps](#13-limitations-and-next-steps)

---

## 1. Why a temporal ownership graph

Retrieval over raw documents (search, RAG) finds text but can't answer the questions that decide whether you can act on it:

| Question | Why plain retrieval fails | TOKG mechanism |
|---|---|---|
| *What is current?* | Three documents give three versions; similarity doesn't encode recency or supersession. | Facts have validity intervals and explicit `supersedes` chains. |
| *What applies to me?* | A rule for Brussels reads the same as one for Ghent. | Facts are scoped to **context** dimensions (country, region, client…). |
| *Whose word counts?* | A Teams message and a signed policy rank equally. | Every node has a temporal **owner**; changes from non-owners need approval. |
| *Can I verify it?* | Summaries detach claims from evidence. | Every fact carries source references with verbatim quotes. |
| *Who do I ask?* | Documents don't name accountable people. | Views return **contacts**: the owner, the owners of context entities, the owners of related cases. |

Knowledge graphs give structure; LLM extraction against a domain schema makes building one from unstructured text practical. TOKG adds two properties to the graph model itself: **time** and **ownership**.

## 2. Pipeline

```
 sources                extract                 materialize                 resolve                    apply
┌──────────┐   ┌───────────────────────┐   ┌─────────────────────┐   ┌──────────────────────┐   ┌────────────────────┐
│ .eml     │──▶│ Extractor             │──▶│ schema validation   │──▶│ Resolver             │──▶│ facts, supersession│
│ .md +    │   │ LLM | scripted (rig)  │   │ entity resolution   │   │ rules | LLM | rig    │   │ escalations        │
│ front-   │   │ → ClaimDraft[]        │   │ context → node ids  │   │ → Decision           │   │ (GraphStore)       │
│ matter   │   └───────────────────────┘   │ → Claim             │   └──────────────────────┘   └─────────┬──────────┘
└──────────┘                               └─────────────────────┘     ownership enforcement               │
                                                                                                         ▼
                     view(node, context, as_of) · search · ask · gaps · escalation actions  ◀── KnowledgeGraph
```

1. **Ingest.** Ingestors parse files into typed `Source` objects. `load_sources` sorts them chronologically, so older knowledge lands first and newer knowledge resolves against it.
2. **Extract.** The extractor turns one source into `ClaimDraft`s. A draft references entities by `(type, name)` and carries an optional context, an optional `valid_from` date stated in the source, and a supporting quote. The LLM is shown the schema and the names of known entities so it reuses them.
3. **Materialize.** The graph validates each draft against the schema (entity type, attribute, relation endpoints, context dimensions) *before* touching the store. An invalid claim is skipped with a reason and leaves no nodes behind. Valid drafts have their entities resolved to nodes (created if new), their context values normalised, and become a `Claim` with a deterministic id `<source id>:<index>`.
4. **Resolve.** The resolver sees the claim, the subject node, its current owner, and every **competing fact**: active or pending facts in the same *slot* (see §3), in any context. It returns a `Decision`.
5. **Apply.** The graph (not the resolver) executes the decision, enforces ownership, and writes facts and escalations.

Re-ingesting the same source is idempotent: its claim ids already exist, so it is skipped. Ingesting a *different* source under an existing id is refused, because sources are immutable evidence.

## 3. Data model

All persisted entities are Pydantic models in `tokg.models`.

### Nodes
`Node(id, type, name, aliases, description, created_at)`. The id is `<type>:<slug(name)>`, e.g. `policy:medical-certificate-for-sick-leave` or `person:jan-peeters-sdworx-example`. Nodes carry **no knowledge** of their own; everything they say lives in facts. This keeps every piece of knowledge temporal, owned and sourced.

### Sources
A discriminated union on `kind`. The shared fields are `id`, `title`, `author`, `timestamp`, `content` and `uri`.

| kind | extra fields | origin |
|---|---|---|
| `email` | `recipients` | `.eml` files |
| `meeting` | `attendees` | meeting summaries |
| `wiki` | `path` | wiki pages |
| `document` | `doc_type` | policies, work regulations, bulletins |
| `note` | `escalation_id` | human answers and admin actions, created by TOKG itself |

### Statements and slots
A fact's `statement` is one of three variants, also discriminated on `kind`. The **slot** decides which facts compete with each other:

| Statement | Slot | Semantics |
|---|---|---|
| `AttributeStatement(attribute, value)` | `(subject, "attribute", attribute)` | Single-valued per context; new values compete with old ones. |
| `RelationStatement(relation, target_id)` | `(subject, "relation", relation, target)` | Additive: `Case example_of Process A` and `…Process B` coexist. |
| `OwnershipStatement(owner_id)` | `(subject, "ownership")` | Single-valued; a handover supersedes the previous owner. |

Because ownership is an ordinary temporal fact, it is sourced (the wiki page that says who maintains a policy), versioned (handovers), and answerable historically: `owner_of(node, as_of=…)`.

### Facts
```
Fact
  id              = claim id ("<source id>:<n>")
  subject_id      → Node
  statement       AttributeStatement | RelationStatement | OwnershipStatement
  context         {dimension: value}, e.g. {"client": "client:acme-nv", "country": "BE"}
  valid_from      when it starts to hold (stated in the source, else the source timestamp)
  valid_to        set when superseded (= successor's valid_from)
  recorded_at     when TOKG learned it
  status          active | pending | rejected
  sources         [SourceRef(source_id, quote)]   ← grows when other sources confirm it
  asserted_by     the author of the first source
  confirmed_by    the owner, if they asserted or approved it
  supersedes      [fact ids] / superseded_by: fact id
  rationale       the resolver's one-line reason, shown to users
```
This makes the model *bi-temporal in spirit*: `valid_from`/`valid_to` record world time, and `recorded_at` records when TOKG learned the fact.

**Trust signal** (derived): `confirmed` (asserted or approved by the owner), `unconfirmed` (active, but from someone else), `pending` (awaiting approval).

### Escalations
`Escalation(id, reason, subject_id, question, assignee_id, fact_id, related_fact_ids, raised_by, status, …)`.
- `reason` is one of `approval`, `conflict` or `question`.
- `status` is one of `open`, `approved`, `rejected` or `answered`.
- Ids are deterministic: `esc:<fact id>` for fact escalations, `esc:q:<node>:<n>` for questions.

## 4. Resolution: how knowledge changes

A `Decision` has an `action`, `target_fact_ids`, a `rationale`, and a `question` (used for conflicts and escalations).

| action | effect on the graph |
|---|---|
| `create` | New active fact. |
| `supersede` | New active fact. Each target gets `valid_to = new.valid_from` and `superseded_by`. This may cross contexts, e.g. a national statute overriding a client-specific clause. |
| `confirm` | No new fact; the claim's source is appended to the target, and the target becomes confirmed if the owner said it. This is how duplicates collapse. |
| `conflict` | New **pending** fact plus a `conflict` escalation to the owner. |
| `escalate` | New **pending** fact plus an `approval` escalation to the owner. |
| `ignore` | No change, e.g. an older statement arriving after a newer one. |

Dispatch is an exhaustive `match` with `assert_never`, so adding an action without handling it is a type error.

**Resolvers:**
- **`RuleResolver`** (the default, deterministic). A same value in the same context gives `confirm`. No competitor in that context gives `create`. An older claim gives `ignore`. A newer claim gives `supersede` if the author is the owner or the node is unowned, and `escalate` otherwise.
- **`LLMResolver`** sends the claim and its competitors to an LLM with structured output. Target ids the LLM made up are filtered out, and an invalid response falls back to the rule resolver. This is where cross-context judgements live ("the 2022 law overrides this 2015 clause").
- **`ScriptedResolver`** returns decisions from a rig file keyed by claim id, and falls back to rules for everything else.

**Ownership enforcement is outside the resolver.** With `enforce_ownership=True` (the default), a `supersede` on an owned node, by someone other than the owner, is downgraded to `escalate` before it is applied. No resolver can bypass this: rules, an LLM, or a hand-written rig.

## 5. Querying: what is current, and for whom

`view(node_id, context=None, as_of=None) → NodeView`:

1. **Live facts** are those that are `active` and valid at `as_of` (default: now). Passing an older `as_of` gives time travel: "what was the rule in 2020?"
2. **Applicability.** A fact applies when every dimension it is scoped to matches the query context. An unscoped fact applies everywhere. Values of entity-backed dimensions are normalised, so `client=Acme NV` matches `client:acme-nv`.
3. **Ranking, per slot.** The most recent `valid_from` wins; ties go to the more specific fact (more context keys). Recency comes first because in practice newer general rules (a statute) override older specific ones (a legacy client clause). When a specific rule should win anyway (a later opt-out), it is also the newer one.
4. The **NodeView** returns:
   - `current`: the winner per slot, each with its sources and quotes, trust level, and supersession history;
   - `alternatives`: applicable facts that lost the ranking, never hidden;
   - `pending`: changes awaiting approval;
   - `other_contexts`: live facts scoped elsewhere, e.g. another client's opt-out;
   - `incoming`: relation facts pointing at this node, e.g. past cases of this process;
   - `owner`, `contacts` and open `escalations`.
5. **Contacts** are gathered from three places, each with a stated role: the node's owner; the owners of context entities (a `client` dimension backed by the `Client` type surfaces that client's payroll consultant); and the owners of related nodes from incoming relations (the hiring manager of a precedent case).

Other queries:
- **`search(text)`**: keyword overlap on node names, aliases and current attribute values, with name matches weighted higher.
- **`ask(question, context)`**: searches for the top nodes, builds their views, and hands them to the **answerer**. It returns an `AskResult` with the answer and the views, so the UI can render the drill-down.
- **`gaps()`**: unowned nodes, pending facts, stale facts (no change in over a year) and open escalations. This makes missing knowledge visible instead of silently absent.

## 6. Human in the loop

The oversight budget is spent only on escalations:

| Action | Who | Effect |
|---|---|---|
| `resolve_escalation(id, actor, "approve")` | assignee (owner) only | The pending fact becomes active and confirmed, and supersedes its targets. |
| `resolve_escalation(id, actor, "reject")` | assignee only | The pending fact becomes `rejected`; the old fact stays current. |
| `ask_owner(node, question, asked_by)` | anyone | Opens a `question` escalation assigned to the current owner. |
| `answer_escalation(id, actor, answer)` | assignee only | The answer becomes a `note` source and goes **through the normal pipeline**, so the next person gets it from the graph. |
| `assign_owner(node, person, assigned_by)` | admin (API) | Creates an ownership fact and hands the node's unassigned escalations to the new owner. |

Anyone else acting gets a `PermissionError`, which the API returns as `403`. An escalation with no owner cannot be acted on until an owner is assigned. That situation is itself reported by `gaps()`.

## 7. Schema format

```yaml
name: sdworx-hr
description: HR and payroll tribal knowledge.
owner_type: Person                  # the entity type owners are; added automatically if missing
entities:
  - name: Policy
    description: A rule employees or clients must follow.
    attributes:
      - {name: rule, description: The rule itself, stated completely.}
  - name: Process
    attributes: [{name: procedure}, {name: required_documents}, {name: processing_time}]
  - name: Case
    attributes: [{name: summary}]
  - name: Client
relations:
  - {name: example_of, source: [Case], target: [Process], description: A past instance of the process.}
context:
  - {name: country, description: ISO 3166 alpha-2 code.}
  - {name: region,  description: Flanders, Wallonia or Brussels.}
  - {name: client,  description: The client company., entity: Client}   # values resolve to Client nodes
```

- **Descriptions are functional.** They are rendered into the extraction and resolution prompts.
- **Validation** at load time rejects duplicate names, relations pointing at unknown entity types, and context dimensions referencing unknown types.
- **At ingest time**, `check_attribute`, `check_relation` and `check_context` reject claims that don't fit the schema.
- **Entity-backed context dimensions** (`entity: Client`) are what connect a query's context to people: the owner of the `Client` node becomes a contact.

## 8. Sources and ingestors

`Ingestor` is an abstract base with `load(path)`. The demo's mock data (`examples/data/`, fictional company Lumivia NV) is one JSON document per file, grouped by source: `email`, `meeting`, `wiki` and `portal` (tickets written by the mock employee portal in `examples/dummy-app/`). Three file formats are supported (bootstrapping owners from `people.json` is being integrated):

- **`JsonIngestor`** reads one JSON object per file: `{id, source, timestamp, author, recipients, title, body}`, where `source` is the kind and `body` the content. Top-level arrays, such as `people.json`, are skipped.
- **`EmailIngestor`** reads standard `.eml` files via the stdlib `email` parser. The id is `email:<stem>`, `From` is the author, `Date` the timestamp, and `To` and `Cc` the recipients.
- **`MarkdownIngestor`** reads `.md` files with YAML frontmatter. `kind` selects the source variant; the other keys map one-to-one onto its fields. `date` is accepted as an alias of `timestamp`, and the id defaults to `<kind>:<stem>`.

```markdown
---
kind: document
title: SD Worx Legal Bulletin — Medical certificate …
author: Sofie Claes <sofie.claes@sdworx.example>
date: 2022-11-28
doc_type: legal_bulletin
---
From 28 November 2022, employees in Belgium no longer need a medical certificate …
```

People are resolved by node id, then email alias, then name. `"Name <email>"`, a bare email, and a `person:` id all land on the same node.

## 9. LLM stages and rigged mode

Three stages can use an LLM. Each takes any LangChain `BaseChatModel` by dependency injection. The default is `ChatClaudeCLI` from [`langchain_cli_agents`](https://github.com/YusufHosny/langchain_cli_agents), which drives Claude Code headlessly, so no API key is needed. It is constructed lazily, so building a graph never starts a process.

| Stage | Output model | Guardrails | Fallback |
|---|---|---|---|
| `LLMExtractor` | `Extraction(claims: list[ClaimDraft])` | Schema check in materialize | `[]` |
| `LLMResolver` | `Decision` | Unknown target ids dropped; ownership enforcement | `RuleResolver` |
| `LLMAnswerer` | `Answer(answer, cited_fact_ids, contact_ids, caveats)` | Citations and contacts must come from the retrieved views | `TemplateAnswerer` |

Pydantic `Field(description=…)` doubles as the schema prompt for structured output.

**Rigged mode** makes a whole run deterministic and LLM-free. That is essential for a reproducible demo video and for tests. One YAML file (`Rig`) scripts all three stages:

```yaml
extractions:   # source id → ClaimDrafts
  document:legal-bulletin-sick-leave:
    - {kind: attribute, subject: {type: Policy, name: Medical certificate for sick leave},
       attribute: rule, value: "No doctor's note is needed for the first day …", context: {country: BE}}
decisions:     # claim id → Decision (unscripted claims use RuleResolver)
  document:legal-bulletin-sick-leave:0:
    {action: supersede, target_fact_ids: [document:acme-work-regulations:0], rationale: "…"}
answers:       # exact question → Answer (others use TemplateAnswerer)
  "An employee called in sick for just today. …": {answer: "…", contact_ids: [person:jan-peeters-sdworx-example]}
```

Scripting decisions ahead of time works because claim ids are deterministic. Rigged runs still go through schema validation and ownership enforcement, so a rig cannot demo something the real system would refuse.

## 10. Interfaces: Python, HTTP, MCP, CLI

**Python**
```python
KnowledgeGraph(schema, store=None, extractor=None, resolver=None, answerer=None,
               enforce_ownership=True, clock=utcnow)
```
Every dependency has a working default: `MemoryStore`, `LLMExtractor`, `RuleResolver`, `LLMAnswerer`. `clock` is injectable for tests and demos.

**HTTP (FastAPI).** Every route except `/health` needs `Authorization: Bearer <token>`.

| Method & path | Purpose |
|---|---|
| `GET /nodes?q=&type=` | Search or list nodes. |
| `GET /nodes/{id}?context=k=v&as_of=` | `NodeView` in a context, optionally at a past time. |
| `GET /facts/{id}`, `GET /sources/{id}` | Drill-down to a fact or its source. |
| `POST /ask` | `{question, context}` → `AskResult`. |
| `POST /ingest` | A list of `Source`s → `IngestReport`. |
| `GET /escalations?mine=&status=` | Escalation inbox. |
| `POST /escalations/{id}/resolve` | `{verdict: approve \| reject, note}`, owner only. |
| `POST /escalations/{id}/answer` | `{answer}`, owner only; the answer is ingested back. |
| `POST /nodes/{id}/questions` | Ask the owner. |
| `PUT /nodes/{id}/owner` | Assign an owner, admin only. |
| `GET /gaps`, `GET /schema`, `GET /me` | Overview endpoints. |

Error mapping: `KeyError`→404, `PermissionError`→403, `ValueError`→409. Mutations are serialised with a lock and trigger a snapshot save.

**MCP (FastMCP, stdio).** Tools: `search`, `view_node`, `ask`, `ask_owner`, `gaps`. The server acts as one fixed person (`--user`). Tools return errors as data instead of raising, so the calling agent can recover.

**CLI (Typer).** Commands: `tokg ingest`, `ask`, `serve`, `mcp` and `token`. `--rig` switches any of them to scripted mode.

## 11. Security model

Designed with the Aikido AI code audit in mind (authentication, authorisation, IDOR, business logic):

- **Authentication:** bearer tokens from `secrets.token_urlsafe(32)`. The registry stores only **SHA-256 hashes** mapped to `{person_id, role}`, and a token is shown once when minted.
- **Authorisation:** roles are `member` and `admin`. Owner-only actions are enforced in the graph core, not just the API, so every interface inherits them. Admins cannot approve on an owner's behalf; they can only assign owners.
- **No author forgery:** on `/ingest`, members' sources are re-authored as the caller. Otherwise a member could claim to be the owner and skip approval.
- **Immutable evidence:** a source id can't be re-ingested with different content.
- **Safe persistence:** snapshots are JSON validated by Pydantic, not pickle, so loading a snapshot cannot execute code. YAML is loaded with `safe_load`.
- **Bounded input:** request bodies have length limits, context parameters are validated, and CORS is opt-in per origin.
- **No secrets in the repo:** there are no API keys, `tokens.yaml` is gitignored, and the LLM runs through the local Claude Code login.

## 12. Tech stack and code map

| Layer | Choice |
|---|---|
| Language / tooling | Python 3.13, uv, pytest, pyright |
| Models / validation | Pydantic v2 (persisted entities, LLM I/O, API schemas) |
| LLM | LangChain Core `with_structured_output`; Claude Code via `langchain_cli_agents` (default), any `BaseChatModel` injectable |
| API | FastAPI + Uvicorn |
| Agent interface | FastMCP (Model Context Protocol, stdio) |
| Storage | In-memory store with JSON snapshots (supported); Neo4j driver store (available, untested) |
| CLI | Typer + Rich |
| Demo apps | Mock employee portal (Vite + React + Tailwind) as a live source; Recall web app (in progress) |

```
src/tokg/
  schema.py     domain schema format + validation + prompt rendering
  models.py     Node, Source variants, Statement variants, Claim, Fact, Escalation
  ingest.py     Ingestor ABC, EmailIngestor, MarkdownIngestor, load_sources
  extract.py    ClaimDraft, Extractor ABC, LLMExtractor + prompts
  resolve.py    Decision, Resolver ABC, RuleResolver, LLMResolver + prompts
  answer.py     Answerer ABC, TemplateAnswerer, LLMAnswerer
  graph.py      KnowledgeGraph: pipeline, ownership enforcement, escalations, views
  views.py      NodeView, FactView, Contact, Gaps, Answer, AskResult
  rig.py        Rig + scripted extractor/resolver/answerer
  store/        GraphStore ABC, MemoryStore, Neo4jStore
  api/          FastAPI app, token auth
  mcp.py        FastMCP server
  cli.py        tokg CLI
examples/data/        Lumivia NV mock sources (email, meeting, wiki, portal) + people.json + answer key
examples/dummy-app/   mock employee portal (Vite + React); its tickets become portal sources
tests/            LLM-free tests: pipeline, views, escalations, API auth, MCP, LLM stages (faked)
```

## 13. Limitations and next steps

**Limitations of the proof of concept:**
- **Entity resolution** is slug and alias matching. The LLM sees known names, but an early source can still create a differently named duplicate.
  - Next: seed canonical nodes from the schema, and add embedding-based matching.
- **Retrieval** is keyword-based.
  - Next: embeddings over node names and fact values, and graph-neighbourhood expansion.
- **Single structured calls** per LLM stage; the `rationale` is the only reasoning trace.
  - Next: a reason-then-extract two-pass mode for harder sources.
- **Storage:** the Neo4j store is written but untested, and the in-memory store is single-process.

**Next product steps:**
- live connectors (Slack/Teams, mailboxes, SharePoint) feeding `ingest_source`;
- proactive alerts when new sources contradict owned facts;
- a per-owner escalation inbox in the app.
