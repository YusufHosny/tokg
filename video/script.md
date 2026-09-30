# Voice-over Script

**For the voice recording.** Record **4 separate files**, one per section, named as below. Use WAV or high-quality MP3, 48 kHz, in a quiet room. Leave about 1 s of silence at the start and end of each file.

- **Pace:** calm and clear, about 150 words per minute. Section 1 is deadpan and meme-like: short pauses after each line are part of the joke.
- **`/`** marks a short pause. **`//`** marks a longer beat (about 1 s).
- **Pronunciation:**
  - **TOKG**: spell it out as "T-O-K-G".
  - **SD Worx**: "S-D Works".
  - **Ghent**: "Gent".
  - **MCP**: "M-C-P".
  - **Neo4j**: "Neo-four-J".
  - **Recall**: the product name. `[TBD before recording]`

If a line runs long, keep the rhythm and don't rush. Timings get adjusted to your audio, not the other way round.

---

## 01_hook.wav (target 30 s, deadpan)

This is Bob. //
Bob is a hiring manager at a Belgian tech company. //
Bob wants to hire a developer from Nigeria. //
The wiki is from 2023. / The AI assistant finds three versions of the process. / The real one is buried in a meeting summary. / And nobody knows who owns it. //
Don't be like Bob. //
Bob went crazy.

---

## 02_product.wav (target 30 s, upbeat, confident)

This time, Bob asks Recall. /
He gets the current process, / the new online platform, not the 2023 wiki, / Camila's hire from last year, with the emails behind it, / and Sophie, the one person who owns the process. //
Nina learns a single sick day needs no doctor's note, / confirmed by Marc at SD Worx. /
And Lucas learns the old Amazon budget is gone, / and orders his monitor through the new IT portal.

---

## 03_tech.wav (target 60 s, clear, explanatory)

Under the hood is TOKG: / a temporal ownership-grounded knowledge graph. //
Companies now produce more text than anyone can read. / Search finds everything, / but can't tell what's current, / what applies to you, / or whose word counts. //
Step one: ingest. / Emails, meeting notes, wiki pages and documents become facts, / shaped by a domain schema. //
Step two: resolve. / Every new fact is checked against the graph. / It confirms what's known, / supersedes an older version while keeping the history, / or, if a non-owner changes a rule, / goes to the owner for approval. //
Every fact carries three things: / when it's valid, / who owns it, / and the exact quote it came from. //
Step three: serve. / FastAPI powers the app, / and an M-C-P server lets any AI agent query the graph and cite its sources. / It runs in memory for zero setup, / or on Neo4j. //
Answers you can trust, / and a person to ask when the documents run out.

---

## 04_business.wav (target 55 s, confident, a little slower on the numbers)

Why now? / AI made text free to produce, / but trust didn't scale with it. / Knowledge management is already a twenty-billion-dollar market, / and none of it was built for AI-generated volume. //
We start where rules change most and mistakes cost most: / HR and payroll. / One partner like SD Worx reaches over a hundred thousand client organisations, / so every domain schema we build is reused thousands of times. //
We sell B2B SaaS, / priced on indexed knowledge and query volume, / with private-cloud deployments for regulated customers. / The promise is a fixed oversight budget: / people set it up once and answer the occasional escalation, / and the graph keeps itself current. //
Next come live Slack and Teams listeners, / and alerts the moment a meeting contradicts policy. //
Recall. / Find it. / Understand it. / Trust it.
