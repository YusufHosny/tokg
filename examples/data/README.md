# Mock data: Lumivia NV

Lumivia NV is a fictional software company in Ghent, Belgium, with 46 employees. SD Worx is its external payroll provider.

There is one JSON file per document, grouped by source (`email/`, `meeting/`, `wiki/`, `portal/`). Every file uses the same format:

```json
{
  "id": "email-2026-03-09-001",
  "source": "email | meeting | wiki | portal",
  "timestamp": "2026-03-09T09:00:00Z",
  "author": "laura.desmet@lumivia.be",
  "recipients": ["all@lumivia.be"],
  "title": "...",
  "body": "..."
}
```

Wiki pages have `recipients: []`. Meeting summaries are authored by `meeting-bot@lumivia.be`. Email replies are quoted inside `body`.

Files in `portal/` are tickets from the employee portal (`examples/dummy-app`). New tickets submitted in the app are written to that folder.

## Cast

| Person | Role | Owns |
|---|---|---|
| Sophie Claes | HR & Immigration Lead | Non-EU hiring / single permit |
| Marc Dubois (SD Worx) | Payroll Consultant for Lumivia | Work regulations, sick leave |
| Tom Verbeke | IT Asset Manager | Hardware purchases, exceptions |
| Laura De Smet | Head of Operations | Signs work regulations, sends policy emails |
| Pieter Janssens | Engineering hiring manager | - |
| Amira Haddad | Sales hiring manager | - |
| Elise Peeters | Office manager | Nothing (gives wrong info) |
| Lucas Maes, Nina Wouters, Jonas Mertens | Employees | - |
| Ravi Kumar (India), Camila Souza (Brazil) | Previous non-EU hires | - |

## Answer key (keep this away from the ingestors)

### Scenario 1: Hiring a non-EU citizen in Belgium

Query: "How do I hire a non-EU citizen in Belgium?"

| File | Role |
|---|---|
| `wiki-2023-05-10-001` | **Old state.** Hiring manager emails the file, about 4 months |
| `meeting-2025-03-11-001` | **New state**, buried in a long AI summary. Online platform, only Sophie submits, 2.5–3 months. Sophie is named owner |
| `email-2024-02-06-001`, `email-2024-06-18-001` | Previous hire: Ravi Kumar (old process, lessons learned) |
| `email-2025-04-02-001`, `email-2025-07-15-001` | Previous hire: Camila Souza (new process, 11 weeks) |
| `wiki-2024-09-01-002` | **Trap.** Stale copy of the old process by Elise |
| `portal-2026-06-02-001` | Open hire request (Nigeria) waiting for HR |

Expected answer: submit through the platform **via Sophie Claes**, with past hires as examples. The wiki page was never updated, so the system must prefer the 2025 meeting decision.

### Scenario 2: Single-day sick leave and doctor's note

Query: "An employee called in sick for just today. Do they need to upload a doctor's note, or is an email notification enough?"

| File | Role |
|---|---|
| `wiki-2019-01-15-001` | **Old state.** Art. 7.3: certificate within 48h for every absence |
| `email-2022-11-30-001` | SD Worx legal bulletin: first-day exemption, companies under 50 can opt out |
| `meeting-2023-01-17-001` | Decision: Lumivia does **not** opt out |
| `wiki-2023-03-01-001` | **New state.** Amendment no. 3 replaces Art. 7.3; Marc is the contact |
| `email-2026-01-20-001` | **Trap.** Elise (not an owner) says a note is always needed |
| `portal-2025-11-04-001` | Example: one-day absence without a note |

Expected answer: no note needed for a one-day absence (up to 3 times per calendar year). Inform the manager before 10:00 and register the absence in the portal. The contact is **Marc Dubois (SD Worx)**.

### Scenario 3: Remote office equipment and hardware expenses

Query: "Can I buy a monitor on Amazon and expense up to €500?"

| File | Role |
|---|---|
| `wiki-2024-02-12-001` | **Old state.** €500 per year via Expensify |
| `meeting-2026-03-05-001` | Decision, buried in a long AI summary |
| `email-2026-03-09-001` | **New state.** Portal only from 16 March 2026; only Tom approves exceptions |
| `email-2026-04-14-001` | **Trap.** Line manager Pieter says "just expense it" |
| `email-2026-04-16-001` | Tom corrects Pieter (confirms ownership) |
| `email-2026-05-06-001` | **Trap.** Rumour about expensing headsets under €100 |
| `portal-2026-03-20-001` | Example: equipment order approved by Tom |

Expected answer: no, order through the IT procurement portal. Exceptions go to **Tom Verbeke**, not the line manager.

### Expected graph (in terms of `examples/schema.py`)

| topic_key | Policy versions | Contested | Examples | Owner (bootstrap) |
|---|---|---|---|---|
| `hire_non_eu` | v1 from `wiki-2023-05-10-001` (superseded), v2 from `meeting-2025-03-11-001` (current) | none (`wiki-2024-09-01-002` only confirms v1, since it predates v2) | Ravi (v1), Camila (v2), Nigeria hire request | Sophie Claes |
| `sick_leave_certificate` | v1 from `wiki-2019-01-15-001` (superseded), v2 from `wiki-2023-03-01-001` (current, `valid_from` 2023-03-01) | Elise's email `email-2026-01-20-001` | Nina's one-day absence | Marc Dubois (external) |
| `hardware_purchasing` | v1 from `wiki-2024-02-12-001` (superseded), v2 from `meeting-2026-03-05-001` / `email-2026-03-09-001` (current, `valid_from` 2026-03-16) | Pieter's reply in `email-2026-04-14-001`, Jonas's rumour `email-2026-05-06-001` | Nina's keyboard order | Tom Verbeke |

Owners are seeded in `people.json` (`owns_topics`). Meeting summaries are authored by `meeting-bot@lumivia.be` and the newsletter by `comms@lumivia.be`. Neither is a person, so extraction must never use them as an owner. Take the owner from the content, or fall back to the bootstrap owner.

Run `python examples/validate_data.py` (needs pydantic) to check every file against `SourceDocument`.

### Noise

These should not produce facts: team lunch, parking, a US visa (ESTA) question, the coffee machine, holiday party, leaving early for a doctor, HDMI cable, fire drill, the newsletter, the Q2 all-hands, the sales pipeline, the product roadmap, and Wi-Fi/printers.

Some noise was chosen to match scenario keywords ("visa", "doctor", "hiring from outside the EU"), to test that retrieval doesn't match on keywords alone.

## Regenerating

The files are hand-written. Edit the JSON directly.
