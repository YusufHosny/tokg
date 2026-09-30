# Demo Video Storyboard (final draft)

**Hard limit:** under 3:00 (Builderbase rule). **Target:** 2:55, which leaves 5 s of margin.
**VO pace:** about 150 words per minute, so roughly 2.5 words per second. Every section below fits its word budget.
**Product name:** `{NAME}` is a placeholder; replace it everywhere once the name is chosen. The core tech is always called **TOKG**.

| # | Section | Time | Length | Built from |
|---|---|---|---|---|
| 1 | Hook: "This is Bob" | 0:00–0:30 | 30 s | HTML stickman scenes |
| 2 | Product: Bob uses {NAME}, plus Sara & Tom | 0:30–1:00 | 30 s | Screen recording of the demo app (rigged mode) + 2 HTML cards |
| 3 | Tech: TOKG | 1:00–2:00 | 60 s | Animated HTML architecture diagram |
| 4 | Business | 2:00–2:55 | 55 s | HTML slides (style taken from the reference deck) |

Cast:
- **Bob**: hiring manager at a Belgian tech company. *Scenario 1: hiring a non-EU developer.*
- **Sara**: SD Worx payroll consultant. *Scenario 2: doctor's note for single-day sick leave.*
- **Tom**: engineer. *Scenario 3: the old Amazon budget limit for work purchases has been replaced by the new IT portal.*

---

## 1. Hook: "This is Bob" (0:00–0:30)

Meme style: white background, black stickman, big plain sans-serif captions, deadpan narration. Each caption appears exactly as the VO says it.

| Time | Visual | On-screen text | VO |
|---|---|---|---|
| 0:00–0:03 | Stickman Bob sits at a desk with a laptop and waves. | **This is Bob.** | "This is Bob." |
| 0:03–0:07 | Same shot; a small name badge pops up. | **Bob is a hiring manager at a Belgian tech company.** | "Bob is a hiring manager at a Belgian tech company." |
| 0:07–0:11 | Bob types. A search bar appears on the laptop: *"How do I hire a non-EU developer in Belgium?"* | **Bob wants to hire a Brazilian developer.** | "Bob wants to hire a Brazilian developer." |
| 0:11–0:21 | The laptop screen floods and speeds up: Slack pings, email threads, a wiki page stamped **"Last edited 2019"**, a PDF **"Single permit DRAFT 2022"**, meeting notes, and an AI chat giving **3 different answers**. The result counter ticks up to **47 results**. Bob's head starts to shake. | *(no caption; the floating documents are the text)* | "The wiki is from 2019. The AI assistant finds three versions of the process. A meeting note says the opposite. And nobody knows who owns it." |
| 0:21–0:22 | Hard cut to black. | | *(silence / record-scratch SFX)* |
| 0:22–0:25 | Black screen, white text. | **Don't be like Bob.** | "Don't be like Bob." |
| 0:25–0:30 | White text on black, then cut to Bob in a hospital bed with a heart-monitor line. SFX: monitor beep. | **Bob went crazy.** | "Bob went crazy." |

*Word count: 53 (budget: ~60, since the pauses are part of the joke).*

---

## 2. Product: "Be like new Bob" (0:30–1:00)

**0:30–0:47: Bob in {NAME}.** This is a real screen recording of the demo app in **rigged mode**, driven by a script, so every take is identical. A small stickman-Bob avatar sits in the corner to connect it to the hook.

| Time | Visual (screen recording) | VO |
|---|---|---|
| 0:30–0:33 | Bob, back and healthy, at his laptop. Hard cut into the app. He types the same question. | "This time, Bob asks {NAME}." |
| 0:33–0:38 | Answer card: **Single permit, Flanders**. Badge: *"Current since 2026-03 · supersedes 2 older versions"*. The older versions appear struck through on a small timeline. | "He gets the current single permit process for Flanders, not the 2019 wiki," |
| 0:38–0:42 | "Previous hires" panel: 2 case cards. Click one; the source email opens with the supporting quote highlighted. | "two previous hires with the emails behind them," |
| 0:42–0:47 | "Who to ask" chip: the owner's avatar, name, *"Owner · HR Mobility"*, and an **Ask owner** button. | "and the one person who owns the process." |

**0:47–1:00: Sara & Tom.** Two quick stickman cards, each followed by a flash of the same answer UI.

| Time | Visual | VO |
|---|---|---|
| 0:47–0:53 | Stickman **Sara** with a phone ("sick today"). Card: an old 48-hour doctor's-note clause, struck through, pointing to the *statutory first-day exemption*, with the badge *"Client opt-out? Ask: payroll consultant"*. | "Sara checks a client's old doctor's-note rule against the new sick-leave law." |
| 0:53–1:00 | Stickman **Tom** with an Amazon cart and a monitor. Card: *"€500 Amazon budget: superseded"* pointing to **"Order via the new IT portal"**, with the IT owner's avatar. | "And Tom learns the old Amazon budget is gone, and orders through the new IT portal." |

*Word count: 62 (budget: ~75).*

---

## 3. Tech: TOKG (1:00–2:00)

A single animated architecture diagram that builds up left to right as the VO explains each step. The labels come straight from the codebase, so what judges see matches the repo.

```
 Email ─┐
 Meetings ─┤→  Schema-guided   →  Resolve              →  Temporal Ownership   →  FastAPI  →  {NAME} app
 Wiki ─┤     extraction         (confirm / supersede /     Knowledge Graph          FastMCP  →  any AI agent
 Docs ─┘                         escalate to owner)        (TOKG)
```

| Time | Visual | VO |
|---|---|---|
| 1:00–1:06 | Title card: **TOKG, Temporal Ownership-Grounded Knowledge Graph.** | "Under the hood is TOKG: a temporal ownership-grounded knowledge graph." |
| 1:06–1:16 | A pile of documents grows; three icons light up and turn red: ⏱ *current?* · 📍 *applies to me?* · 👤 *whose word?* | "Companies now produce more text than anyone can read. Search finds everything, but can't tell what's current, what applies to you, or whose word counts." |
| 1:16–1:24 | **Step 1, Ingest.** Source icons flow into "Schema-guided extraction" and come out as small fact chips. | "Step one: ingest. Emails, meeting notes, wiki pages and documents become facts, shaped by a domain schema." |
| 1:24–1:38 | **Step 2, Resolve.** A new fact chip meets an old one. Three branches animate in turn: ✅ confirm, ⏭ supersede (old chip slides into a history stack), 🙋 escalate (a chip flies to an owner avatar, who approves it). | "Step two: resolve. Every new fact is checked against the graph. It confirms what's known, supersedes an older version while keeping the history, or, if a non-owner changes a rule, goes to the owner for approval." |
| 1:38–1:46 | Zoom into one fact node with three labelled tags: **valid from / to** · **owner** · **source quote**. | "Every fact carries three things: when it's valid, who owns it, and the exact quote it came from." |
| 1:46–1:56 | **Step 3, Serve.** The graph connects to FastAPI (the app) and FastMCP (a Claude/agent logo). Small storage toggle: *in-memory ⇄ Neo4j*. | "Step three: serve. FastAPI powers the app, and an MCP server lets any AI agent query the graph and cite its sources. It runs in memory for zero setup, or on Neo4j." |
| 1:56–2:00 | The whole diagram pulses once. | "Answers you can trust, and a person to ask when the documents run out." |

*Word count: ~147 (budget: ~150).*

---

## 4. Business (2:00–2:55)

HTML slides in the style of the reference deck. The VO carries the story and the slides carry the numbers. The hiring/structure plan appears **on the slide only** (not narrated) to stay within time.

| Time | Slide | On-slide content | VO |
|---|---|---|---|
| 2:00–2:14 | **Why now** | "AI made text free. Trust didn't scale." · Knowledge workers spend **3.2 h/week** searching for information¹ · KM tools were built for human-written volume. | "Why now? AI made text free to produce, but trust didn't scale with it. Knowledge management is already a twenty-billion-dollar market, and none of it was built for AI-generated volume." |
| 2:14–2:27 | **Market & go-to-market** | **TAM** $20.2B KM software (2024) → $62B by 2033, 13.6% CAGR² · **SAM** `[TO FILL: EU mid/large regulated orgs × ACV]` · **SOM / wedge** HR & payroll providers: SD Worx alone serves **100,000+** client orgs and **6M+** payslips³ | "We start where rules change most and mistakes cost most: HR and payroll. One partner like SD Worx reaches over a hundred thousand client organisations, so every domain schema we build is reused thousands of times." |
| 2:27–2:42 | **Business model** | B2B SaaS, tiered on **indexed knowledge nodes + query volume** · Private-cloud deployment for regulated customers · Domain packs (schemas): BE HR/payroll → EU countries → IT, finance, compliance · **Fixed oversight budget** chart: human effort decays while coverage grows | "We sell B2B SaaS, priced on indexed knowledge and query volume, with private-cloud deployments for regulated customers. The promise is a fixed oversight budget: people set it up once and answer the occasional escalation, and the graph keeps itself current." |
| 2:42–2:50 | **Roadmap & team** | Roadmap: multi-source pipeline → live Slack/Teams listeners → proactive contradiction alerts · 5-year hiring/structure table `[TO FILL]` | "Next come live Slack and Teams listeners, and alerts the moment a meeting contradicts policy." |
| 2:50–2:55 | **End card** | **{NAME}** · *Find it. Understand it. Trust it.* · repo link · team names | "{NAME}. Find it. Understand it. Trust it." |

*Word count: 128 (budget: ~135).*

Sources for the slide footnotes:
1. Slite, *Enterprise Search Survey 2025*: https://slite.com/learn/enterprise-search-survey-findings
2. Grand View Research, *Knowledge Management Software Market*: $20.15B (2024) → $62.15B (2033), 13.6% CAGR. Other firms estimate $15–25B for 2025 at 10–15% CAGR, so round down if challenged.
3. SD Worx challenge brief (Tectonic participants guide).

### Draft numbers to fill in (team to verify)
- **SAM, bottom-up:** (number of EU organisations with 250+ employees in HR-heavy or regulated sectors) × (ACV, e.g. €20–40k). Look up the first number on Eurostat (*"enterprises by size class"*) before putting it on a slide.
- **SOM:** reach through 1–2 HR/payroll provider partners. For example, 1% of SD Worx's 100k clients = 1,000 orgs × a small-tier ACV.
- **5-year plan (slide only):** Y1 founders + 2 engineers, 2 pilots with a provider → Y2 first domain pack sold, sales + solutions engineer → Y3 3–4 country packs, CS team → Y4–5 horizontal packs (IT/finance), partner channel. Replace with the team's real plan.

---

## Changes from the pre-draft (and why)
- **The hook is now the "This is Bob" meme** instead of the split-screen voice-over, per your description. The pre-draft's points (outdated draft, no owner, wasted days) are kept inside the flood shot.
- **Removed "80% drop in policy escalations".** It's an invented metric, and judges will ask where it comes from. The business slide uses sourced numbers only; the rest is marked `[TO FILL]`.
- **"Production-ready Neo4j" became "or on Neo4j".** The Neo4j store exists but is untested, and the repo is public and will be judged.
- **Business VO ends on SD Worx's own tagline**, "Find it. Understand it. Trust it.", for fit with the challenge brief (30% of the score).
- Scenario 3 (Amazon budget → IT portal) comes from your draft. `examples/scenarios.md` still has it as TBD, so the team should add it there so the mock data covers Tom's shot.
