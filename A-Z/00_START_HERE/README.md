# A–Z — Read this first

This folder exists to take someone who knows **nothing** about ASTRA and bring them
to the point where they can sit with the people who built it, follow the
conversation, challenge a technical decision on its merits, and contribute.

It is not a summary. Summaries tell you what a system does. This is trying to
give you a **mental model** — enough that you could predict what the system does
in a situation nobody has described to you.

---

## The one rule this folder follows

**Nothing here is invented.**

Every claim is one of five things, and it is labelled:

| Label | Meaning |
|---|---|
| **[FACT]** | Traceable to code, a measurement in `docs/EVIDENCE.md`, or a decision record. The source is named |
| **[INTERPRETATION]** | A reading of the facts that the author of this folder believes, and which a reasonable person could disagree with |
| **[ASSUMPTION]** | Something the *system* assumes about the world. Usually traceable to `docs/ASSUMPTIONS.md` (A-1 … A-10) |
| **[OPEN]** | Genuinely not known, by anyone, today |
| **[UNVERIFIED]** | Stated somewhere in the project but not checked while writing this. Treat as a lead, not a fact |

If you find something unlabelled that reads like a claim, that is a defect in
this folder. Report it the same way you would a defect in the code.

### Why the rule matters more here than usual

This project's single most distinctive property is that **its documents are
honest about what is broken**. There is a register of 21 self-found defects, a
log of retracted claims, and evidence rows that say *"this measurement does not
license that conclusion"*. A knowledge base that smoothed over that would
misrepresent the thing it is describing.

On 15 August 2026 alone, three separate numbers were produced correctly from
observations nobody had checked were adequate, and all three had to be withdrawn
(`E-143`, `E-145`, `E-161`). That is the house style: measure, publish, and
retract in public when wrong. This folder inherits it.

---

## How the project's own documents relate to this folder

This folder **does not replace** them. It is a guided path *into* them. When you
want the authoritative answer, go to the source:

| Source document | The question it owns |
|---|---|
| `docs/ARCHITECTURE.md` | How the system is put together and why |
| `docs/EVIDENCE.md` | **Every number.** One row per measurement, with the command that reproduces it |
| `docs/CREDIBILITY_MATRIX.md` | **Every claim**, what evidence backs it, and what it does *not* license |
| `docs/DECISION_LOG.md` | Every decision that could have gone another way, and what the alternatives cost |
| `docs/adr/` | 34 architecture decision records — the full argument for each |
| `docs/ASSUMPTIONS.md` | A-1 … A-10, and what breaks if each is wrong |
| `docs/SEPARATION_INVARIANTS.md` | SI-1 … SI-10, the safety argument |
| `docs/THREAT_MODEL.md` | Adversary models and what the architecture does and does not stop |
| `docs/PAPER_ADHERENCE.md` | Where the paper and the code disagree, and which is right |
| `docs/CARLA_PLAN.md` | What happens next and why |

**The division of labour to remember:** a number lives in exactly one place, and
that place is `EVIDENCE.md`. Everything else cites it as `E-n`. If you see a
figure repeated in two documents, one of them is stale — that has happened before
and the convention exists because of it.

---

## Build status of this folder

This is being written in passes. **This table is the truth about what is
finished**, and it is maintained as the passes land — a knowledge base that
overstated its own completeness would be a poor start.

| # | Section | Status |
|---|---|---|
| 00 | START_HERE | **Written** |
| 01 | PROBLEM_AND_MOTIVATION | **Written** |
| 02 | PROJECT_HISTORY | **Written** |
| 03 | TIMELINE | **Written** |
| 04 | ARCHITECTURE_EVOLUTION | **Written** |
| 05 | CURRENT_ARCHITECTURE | **Written** |
| 06 | COMPONENTS | **Written** |
| 07 | DATA_FLOW | **Written** |
| 08 | INTERNAL_MECHANICS | *Pass 4* |
| 09 | ALGORITHMS | *Pass 4* |
| 10 | MATHEMATICS | *Pass 4* |
| 11 | UNCERTAINTY_AND_ERROR | *Pass 5* |
| 12 | SAFETY_AND_RELIABILITY | *Pass 5* |
| 13 | TESTING_AND_VALIDATION | *Pass 5* |
| 14 | SIMULATION | *Pass 5* |
| 15 | EXPERIMENTS | *Pass 6* |
| 16 | FAILED_APPROACHES | *Pass 6* |
| 17 | DECISION_LOG | *Pass 6* |
| 18 | CHALLENGE_LOG | *Pass 6* |
| 19 | TRADEOFFS | *Pass 7* |
| 20 | ALTERNATIVES | *Pass 7* |
| 21 | BENEFITS | *Pass 7* |
| 22 | LIMITATIONS | *Pass 7* |
| 23 | RUNTIME_BEHAVIOR | *Pass 4* |
| 24 | GLOSSARY | *Pass 8* |
| 25 | FAQ | *Pass 8* |
| 26 | INTERVIEW_QUESTIONS | *Pass 8* |
| 27 | RESEARCH_QUESTIONS | *Pass 8* |
| 28 | CURRENT_STATUS | *Pass 8* |
| 29 | REMAINING_WORK | *Pass 8* |
| 30 | MASTER_A_TO_Z_DOCUMENT | *Pass 9 — written last, because it is the through-line* |

---

## Where to start

Read [`Executive_Overview.md`](Executive_Overview.md) next — fifteen minutes, and
it gives you the shape of the whole thing.

Then follow [`Learning_Path.md`](Learning_Path.md), which orders the sections by
what depends on what rather than by folder number.

**Do not start at section 05 (the architecture).** It will look arbitrary. Almost
every part of it is the way it is because something specific went wrong, and the
history in 02–04 is what makes the design legible rather than a list of
components.
