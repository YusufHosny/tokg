# Recall: business overview

> **Find it. Understand it. Trust it.** Recall turns an organisation's scattered, contradictory and increasingly AI-generated text into knowledge people can act on: current, applicable to their case, sourced, and owned by someone they can ask.

Market figures are sourced (see the end). SAM, SOM, pricing, KPIs and the 5-year plan are our own estimates, and each one shows its working. This document and the demo video's business section share one set of figures, so change them in both places at once.

## 1. The problem

AI made producing text almost free. Meetings are transcribed and summarised, reports are generated, and every thread gets an AI recap. The ability to *trust* text has not scaled with its volume. We call this the **overwhelming data abundance** problem. In a company it shows up three ways:

- **No owner.** Assistants can find an update in a meeting summary but can't say who is accountable for it. Maintenance, escalation and compliance break down.
- **Contradiction and decay.** Three summaries hold three versions of a decision. Nothing marks which one is current, or whether it applies to *this* client or country.
- **Reading fatigue.** Verbose, low-signal text gets skipped, just as people rubber-stamp approval prompts. More information ends up meaning less use.

SD Worx's challenge brief describes the moment exactly. An urgent customer question comes in, and the assistant finds three documents: one recently updated, one without an owner, and one that may apply to another country. Then a colleague shares a contradicting Teams message. *"The information exists. Confidence does not come automatically."*

Knowledge workers already spend **3.2 hours a week** searching for information¹, and that was before AI-generated volume.

## 2. The product

Recall ingests email, meeting notes, wikis and documents into **TOKG**, a temporal ownership knowledge graph. Every answer comes with:

- **the current version**, with the older versions it replaced (and why) one click away;
- **the context it applies to**: country, region, client;
- **the evidence**, down to the exact clause or quote;
- **the person to ask**: the owner, plus the people who handled similar cases.

When sources disagree, Recall doesn't guess. A change from a non-owner waits for the owner's approval, and an unanswerable question goes to the owner. The owner's answer is fed back into the graph, so nobody has to ask again.

Recall runs as a web app for employees, an HTTP API, and an **MCP server**, so any AI agent (Claude, Copilot-style assistants, internal bots) can query trusted, cited knowledge instead of raw documents.

## 3. Why now

1. **Text volume has broken retrieval.** Search and RAG find everything but rank on similarity, not on validity, applicability or authority. Adding AI made the noise worse.
2. **LLMs made structured extraction cheap.** Turning unstructured text into a schema-shaped graph used to need armies of taxonomists. Now it needs a schema and a model.
3. **Agents need a source of truth.** As companies deploy agents that act on internal knowledge, grounding them in *current, owned* facts becomes a compliance issue, not a nice-to-have.

## 4. Market

| | Size | Basis |
|---|---|---|
| **TAM** | **$20.2B** knowledge-management software (2024), growing to **$62B by 2033** (13.6% CAGR)² | Global KM software market |
| **SAM** | **≈ €1.5B / year** | About **50,000** EU organisations with 250+ employees⁴ × **€30k** blended ACV. Europe first, because context-dependent rules (country, region, collective agreements) hurt most there. |
| **SOM (year 5)** | **≈ €30M ARR (2% of SAM)** | **1,200 organisations** × €25k ACV. Most arrive through HR/payroll partners: SD Worx alone serves **100,000+** client organisations and **6M+** payslips³, so 1% of one partner's base is already 1,000 organisations. |

Other research firms estimate the KM market at $15–25B for 2025 with 10–15% CAGR. We quote the Grand View figure and round down if challenged.

## 5. Beachhead: HR and payroll

We start where **rules change often, context matters most, and mistakes are costly**:

- labour law and social-security rules change yearly and differ by country and region;
- every client has its own work regulations, opt-outs and exceptions;
- a wrong answer means a payroll error, a compliance breach or an unhappy employee.

HR and payroll providers like SD Worx are the ideal channel. One provider serves a huge base of client organisations on the same statutory backbone. A **domain pack** built once (the Belgian HR/payroll schema, statutory sources, ownership map) is reused across thousands of clients, with only the client-specific layer (work regulations, opt-outs) differing. The demo scenarios come straight from this world, set in a fictional 46-person Ghent company, Lumivia NV, with SD Worx as its payroll provider:
- hiring non-EU employees under the single permit;
- single-day sick-leave certificates;
- hardware purchasing rules.

## 6. Business model

- **B2B SaaS**, tiered on **indexed knowledge nodes** and **query volume**, covering human and agent queries alike.
- **Private-cloud / on-prem deployments** for regulated customers. The core is a self-contained Python service, and the LLM backend is swappable.
- **Domain packs** as add-ons: schema, source connectors and ownership templates per domain and country. Order: BE HR/payroll → other EU countries → IT, finance and compliance.
- **Partner channel.** HR/payroll providers bundle Recall for their clients, with shared statutory content and client-specific layers.

| Tier | Price | For |
|---|---|---|
| **Team** | €1,500 / month | One department, up to 10k knowledge nodes, 3 source connectors |
| **Business** | €4,000 / month | Company-wide, up to 100k nodes, all connectors, MCP access for internal agents |
| **Enterprise** | from €60k / year | Private cloud, SSO, custom domain packs, audit exports |
| **Partner** | €8 / client organisation / month, revenue share | Providers like SD Worx bundling Recall into their client portal |

The blended ACV is about €30k. Expected gross margin is around 80%: the costly LLM work happens once, at ingest time, so each query mostly reads the graph.

### The fixed oversight budget
The core promise to a buyer: **human effort is bounded and decays while coverage grows.** People set up the schema and initial owners once. After that, owners only spend time on escalations: approving a change, resolving a conflict, answering a question. Every answer is written back, so the same question never escalates twice. A wiki's upkeep cost rises with its size. Recall's oversight cost stays bounded because only changes and open questions reach a person.

## 7. Competition and differentiation

| Category | Examples | What they do well | What they lack |
|---|---|---|---|
| Enterprise search / AI assistants | Enterprise search platforms, workplace copilots | Broad connectors, fast retrieval, summaries | No notion of validity over time, applicability, or accountable ownership. Contradictions are summarised, not resolved. |
| Wikis / knowledge bases | Confluence- and Notion-style tools | Human-curated pages | Drift and go stale, rely on manual upkeep, and don't scale to AI-generated volume. |
| Verified-knowledge tools | Card- or verification-based KM tools | Owners periodically verify content | Verification is manual and page-level, not extracted, per-fact or context-scoped. |
| GraphRAG / KG toolkits | Open-source GraphRAG and temporal-graph libraries | Graph extraction and retrieval | Developer libraries, not governed knowledge: no ownership, approvals or escalation loop. |

**Our edge:** ownership and time are part of the data model, not bolted on. Each fact is scoped to a context and linked to its source. Trust is explicit (`confirmed`, `unconfirmed` or `pending`). Governance is enforced by the graph itself, so every interface (the app, the API and AI agents over MCP) gets the same guarantees.

## 8. Go-to-market

1. **Pilot with one HR/payroll provider** (SD Worx track): one country pack (Belgium), 2 pilot client organisations, with payroll consultants as owners.
2. **Prove the oversight budget.** A 12-week pilot, measured against these targets:

   | KPI | Baseline | Week 4 | Week 12 |
   |---|---|---|---|
   | Questions answered without a human | n/a | 70% | **90%** |
   | Escalations per 100 questions | ~30 (every question goes to a colleague) | 15 | **< 5** |
   | Time to a trusted, sourced answer | hours to days | < 5 min | **< 1 min** |
   | Owner time spent on escalations | unmeasured | < 2 h / week | **< 1 h / week** |
   | Answers citing a current, owned source | n/a | 95% | **99%** |
3. **Expand through the provider's client base**, then add EU country packs.
4. **Go horizontal:** IT, finance and compliance packs, sold directly to mid/large organisations and through partners.

## 9. Roadmap

| Horizon | Product |
|---|---|
| **Now (hackathon POC)** | Temporal ownership graph core, schema format, email/meeting/wiki/document ingest, approval and escalation loop, HTTP API, MCP server, demo app |
| **Next** | Live Slack/Teams and mailbox listeners; proactive alerts when a meeting contradicts policy; owner inbox |
| **Then** | Country packs for EU HR/payroll; embedding-based retrieval and entity matching; production graph backend |
| **Later** | Horizontal domain packs (IT, finance, compliance); partner marketplace for domain packs |

### 5-year plan

| Year | Milestone | Customers | ARR | Team |
|---|---|---|---|---|
| **Y1** | Belgian HR/payroll pack; 2 paid pilots with one provider; seed round | 10 | €0.3M | 6 (4 founders + 2 engineers) |
| **Y2** | First partner bundle live; NL and FR packs | 60 | €1.5M | 15 (+ sales, solutions engineering, customer success) |
| **Y3** | 5 EU country packs; Slack/Teams listeners; Series A | 220 | €5.5M | 35 |
| **Y4** | IT and finance packs; second provider partner; DACH expansion | 550 | €13M | 70 |
| **Y5** | Compliance pack; domain-pack marketplace | 1,200 | €30M | 120 |

Team structure grows in stages:
- Engineering first: a core graph team and a connectors team.
- From Y2, a **domain-pack team** of legal and HR specialists who write the schemas and statutory sources. This is our content moat.
- From Y3, partner success and enterprise sales.

## 10. Risks and mitigations

| Risk | Mitigation |
|---|---|
| LLM extraction errors | Schema validation, mandatory source quotes, owner approval for changes, and a visible trust level on every fact |
| Owners ignore escalations | A bounded, low-volume inbox by design; unowned or stale knowledge reported as gaps; reassignment by admins |
| Data sensitivity (HR data) | Private-cloud deployment, swappable LLM backend, no secrets in code, authorisation enforced in the core |
| Incumbent copilots add "freshness" features | Ownership and approvals are a data-model property, not a UI feature; provider partnerships and domain packs create lock-in |

## Sources

1. Slite, *Enterprise Search Survey 2025*: https://slite.com/learn/enterprise-search-survey-findings
2. Grand View Research, *Knowledge Management Software Market*: $20.15B (2024) → $62.15B (2033), 13.6% CAGR.
3. SD Worx challenge brief, *Tectonic Hackathon Participants Guide* (2026): 10,000+ employees, 100,000+ customers, 6M+ payslips, payroll reach in 100+ countries.
4. Eurostat, *Structural business statistics by size class*: large enterprises (250+ employees) are about 0.2% of the EU's ~26M enterprises, so roughly 50,000 organisations (rounded).

---

*Recall is built by team **AlladinsAgents** (Yusuf Hussein, Karam Kokash, Ahmed Salheen and Alex Gretski, alpha leader) at the Tectonic 2026 hackathon in Leuven.*
