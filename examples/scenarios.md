# Demo Scenarios

Three scenarios for the SD Worx track, played out at **Lumivia NV**, a fictional 46-person software company in Ghent whose payroll is run by SD Worx. The mock data is in [`data/`](data/); its README has the full answer key.

Each scenario starts from a concrete *moment of doubt*: an employee has found information but cannot act on it with confidence. Each shows how tokg turns scattered, conflicting sources into one answer that is **current**, **owned** and **auditable**.

Every scenario has three parts:
- **Data sources**: the documents involved and where the knowledge is scattered.
- **Decision / problem**: why this is hard for a person, a wiki or a plain RAG assistant.
- **How we solve it**: what tokg does and what the user sees.

---

## Scenario 1: Hiring a non-EU citizen in Belgium

**User query:** *"How do I hire a non-EU citizen in Belgium?"*

### Data sources
| Document | Kind | Role |
|---|---|---|
| `wiki-2023-05-10-001` | Wiki (Sophie) | **Old state**: the hiring manager emails the single permit file to the region, about 4 months. |
| `meeting-2025-03-11-001` | Meeting summary (AI bot) | **New state**, buried in a long summary: online "Working in Belgium" platform, only Sophie submits, 2.5–3 months. Sophie is named owner. |
| `email-2024-02-06-001`, `email-2024-06-18-001` | Email | Previous hire: Ravi Kumar (India), old process, with lessons learned. |
| `email-2025-04-02-001`, `email-2025-07-15-001` | Email | Previous hire: Camila Souza (Brazil), new process, 11 weeks. |
| `wiki-2024-09-01-002` | Wiki (Elise) | **Trap**: a stale copy of the old process. |
| `portal-2026-06-02-001` | Portal ticket | An open hire request (Nigeria) waiting for HR. |

### Decision / problem
- The wiki still describes the old email-based process. Sophie said she would update it and never did. The current process exists only inside an auto-generated meeting summary, among paragraphs about employer branding and onboarding.
- A second wiki page (Elise's onboarding checklist) repeats the old process and looks just as official.
- The most useful knowledge, what the last two hires ran into, is buried in individual email threads.
- A hiring manager following the wiki would send a file that the region no longer accepts, and lose weeks.

### How we solve it
- **Temporal:** the `hire_non_eu` policy's `summary`/`steps` facts have a version history. The 2025 meeting decision **supersedes** the 2023 wiki version, and the old version stays visible with its dates.
- **Speaker attribution:** the meeting summary is written by `meeting-bot`, but the decision is credited to **Sophie**, an attendee and the owner. That makes it an authoritative update, not an anonymous claim.
- **Trap handled:** Elise's stale copy predates the change, so it only confirms the old version and cannot override the current one.
- **Examples:** Ravi's and Camila's hires are `Example` nodes linked `example_of` the policy, each with lessons and links to the original emails.
- **Ownership:** the answer ends with "submit through **Sophie Claes**". The past hires surface their hiring managers (Pieter, Amira) as people who have done it before.

---

## Scenario 2: Single-day sick leave and the doctor's note

**User query:** *"An employee called in sick for just today. Do they need to upload a doctor's note, or is an email notification enough?"*

### Data sources
| Document | Kind | Role |
|---|---|---|
| `wiki-2019-01-15-001` | Wiki (Laura) | **Old state**: work regulations Art. 7.3, a certificate within 48h for every absence. |
| `email-2022-11-30-001` | Email (Marc, SD Worx) | Legal bulletin: first-day exemption; companies under 50 employees can opt out. |
| `meeting-2023-01-17-001` | Meeting summary (AI bot) | Decision: Lumivia does **not** opt out. |
| `wiki-2023-03-01-001` | Wiki (Laura) | **New state**: Amendment No. 3 replaces Art. 7.3; Marc is the contact. |
| `email-2026-01-20-001` | Email (Elise) | **Trap**: "we are small, we ALWAYS need a doctor's note". |
| `portal-2025-11-04-001` | Portal ticket | Example: a one-day absence reported without a note. |

### Decision / problem
- Lumivia has 46 employees, so it *could* have opted out. Whether it did is recorded only in a management meeting summary and a signed amendment.
- The most recent message on the topic (Elise's all-staff reminder) is **wrong**, and it is the one people remember. Recency alone gives the wrong answer.
- The owner of this knowledge is external: the SD Worx payroll consultant, not anyone at Lumivia.

### How we solve it
- **Temporal:** Amendment No. 3 (valid from 2023-03-01) supersedes Art. 7.3. The history shows both, with the signed amendment as evidence.
- **Authority:** the amendment was authored by Laura (Head of Operations, who signs the work regulations). She is an org-wide **authority**, so her update is accepted even though Marc owns the topic.
- **Trap handled:** Elise is neither owner nor authority. Her contradicting email becomes a **pending** fact with an escalation to Marc. It is visible as "contested", but it never replaces the current rule.
- **Answer:** no note needed for a one-day absence (up to 3 times per calendar year). Inform the manager before 10:00 and register the absence in the portal. Contact: **Marc Dubois (SD Worx)**.

---

## Scenario 3: Remote office equipment and hardware expenses

**User query:** *"Can I buy a monitor on Amazon and expense up to €500?"*

### Data sources
| Document | Kind | Role |
|---|---|---|
| `wiki-2024-02-12-001` | Wiki (Laura) | **Old state**: €500 per year, expensed via Expensify. |
| `meeting-2026-03-05-001` | Meeting summary (AI bot) | The decision, buried in a long summary. |
| `email-2026-03-09-001` | Email (Laura) | **New state**: IT procurement portal only, from 16 March 2026; only Tom approves exceptions. |
| `email-2026-04-14-001` | Email thread | **Trap**: line manager Pieter says "just expense it". |
| `email-2026-04-16-001` | Email (Tom) | Tom corrects Pieter, confirming the policy and his ownership. |
| `email-2026-05-06-001` | Email (Jonas) | **Trap**: a rumour about expensing headsets under €100. |
| `portal-2026-03-20-001` | Portal ticket | Example: an equipment order approved by Tom. |

### Decision / problem
- The wiki still says "expense it". The change was announced by email and decided in a meeting.
- A line manager, someone employees reasonably trust, gives the wrong answer in writing. A rumour adds a third version.
- Employees need to know not just the rule, but that exceptions go to one specific person.

### How we solve it
- **Temporal:** the policy is valid from **16 March 2026** (the effective date in the email, not the send date). Asked "as of" February 2026, tokg returns the old rule; asked today, it returns the new one.
- **Authority and ownership:** Laura's announcement is authoritative. Pieter's reply and Jonas's rumour are not, so both become contested facts escalated to Tom. Tom's own reply **confirms** the current policy.
- **Answer:** no, order through the IT procurement portal. Exceptions go to **Tom Verbeke**, not the line manager.
