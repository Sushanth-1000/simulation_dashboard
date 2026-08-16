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
| 08 | INTERNAL_MECHANICS | **Written** |
| 09 | ALGORITHMS | **Written** |
| 10 | MATHEMATICS | **Written** |
| 11 | UNCERTAINTY_AND_ERROR | **Written** |
| 12 | SAFETY_AND_RELIABILITY | **Written** |
| 13 | TESTING_AND_VALIDATION | **Written** |
| 14 | SIMULATION | **Written** |
| 15 | EXPERIMENTS | **Written** |
| 16 | FAILED_APPROACHES | **Written** |
| 17 | DECISION_LOG | **Written** |
| 18 | CHALLENGE_LOG | **Written** |
| 19 | TRADEOFFS | **Written** |
| 20 | ALTERNATIVES | **Written** |
| 21 | BENEFITS | **Written** |
| 22 | LIMITATIONS | **Written** |
| 23 | RUNTIME_BEHAVIOR | **Written** |
| 24 | GLOSSARY | **Written** |
| 25 | FAQ | **Written** |
| 26 | INTERVIEW_QUESTIONS | **Written** |
| 27 | RESEARCH_QUESTIONS | **Written** |
| 28 | CURRENT_STATUS | **Written** |
| 29 | REMAINING_WORK | **Written** |
| 30 | MASTER_A_TO_Z_DOCUMENT | *Pass 9 — written last, because it is the through-line* |

---

## Verification pass — 16 August 2026

Every quantitative claim in passes 1–8 was **re-measured by running the code**,
not confirmed by reading the document it came from. What follows is the record of
that pass, including what it found wrong.

### What was run

| Command | Result |
|---|---|
| `make check` | **3,042 passed + 3 xfailed** in 80.15 s; `quality gate: PASSED` |
| `make typecheck` | `Success: no issues found in **167** source files` |
| `make contracts` | **12 kept, 0 broken** |
| `make coverage-floor` | every file at or above 80%; aggregate **97.47%** |
| `make artifacts-check` | *twin, corpus and policy present; the vehicle drives* |
| `python -m benchmarks.gate_census` | STATISTICAL 2800/0/0 · PHYSICAL 2651/**149**/0 · DETERMINISTIC 2800/0/0 |
| `python -m benchmarks.exchangeability` | `URBAN_CLEAR` **0.0% inside**; `DEGRADED_SENSOR` `n=1`, too few to judge |
| `python -m benchmarks.degradation` | 5 modalities, all critical, all HALT at φ 40, capabilities withdrawn per modality |
| `python -m benchmarks.fault_study` | see the corrections below |
| `python -m benchmarks.redundancy` | shadow residual table; faulted channel separates at +41 / +28 ticks |
| `python benchmarks/latency.py` | four-layer hot path p99 **0.442 ms** |
| `pytest tests/integration/test_closed_loop_faults.py` | 10 passed |
| `pytest tests/unit/test_l8_failsafe.py -k recovery_is_bounded` | passed — the 91-tick bound holds |
| direct drive, `single_channel` on and off | clean **0.1034 → 0.0168 m**; 1 m bias **0.8387 → 0.0168 m** |
| direct drive, `pipeline_duration_ns` | full tick p50 **2.214** · p99 **7.289** · max **57.063 ms** |

### What reproduced exactly

The gate census to the veto, the reason code and the abstention count. The
exchangeability ranges to four decimals. **The strongest claim in this folder —
that a 1 m bias in one of three channels leaves the final deviation at 0.0168 m,
the clean run's figure to four decimals — reproduced exactly.** The recovery bound,
the schema version, the counts of ADRs, invariants, assumptions, credibility rows
and register rows, and the three structural guards (`artifacts-check` driving,
`StationaryVehicleError`, the 30-sample floor) all held.

### What did not, and was corrected

| # | Was written | Measured | Where fixed |
|---|---|---|---|
| 1 | coverage 97.56%, mypy over 166 files | **97.47%**, **167 files** | 13, 25, 28 |
| 2 | *"no end-to-end latency measurement exists"* | It exists and reproduces: full tick p99 **7.289 ms**, max **57.063 ms** | 19, 22, 25, 28, 29 |
| 3 | OD-8 quoted at `HIGHWAY_CLEAR` 1.156 vs 1.158 | Superseded 15 Aug; today `URBAN_CLEAR` **3.3648–3.4083** vs **3.8758–5.4312** | 09, 28 |
| 4 | dropout *"HALT at +40"* | **HALT never happens.** The counter reaches 40; ADR-0030's ceiling maps `DEGRADED → LIMP` | 04, 07, 13, 14, 17, 21, 23, 26, 28 |
| 5 | dropout deviation 0.167 m | **0.062 m** — ADR-0033 made redundancy the driven path | as above |
| 6 | `position_bias` 0.931 m, `position_drift` 2.025 m | Both now **0.017 m**, indistinguishable from the control | 28 |
| 7 | `Verdict.merge`: *"empty ⇒ VETO"* | True, and incomplete — abstentions are stripped first, so **all-abstain ⇒ VETO** too | 24 |

**The two findings worth carrying forward.**

**A code change moved a headline safety number and nothing announced it.** ADR-0030
and ADR-0033 between them changed OD-9's measured response — the deviation
improved and the deepest posture got *shallower* — and neither ADR, nor the audit
schema, nor the config hash records that the number moved. This is the same defect
§22 records as L13, showing up a second time in a different place.

**A defect in the source documents, not just this folder.** `E-152` cites
`python -m benchmarks.redundancy` as the command that produces its 0.1034 →
0.0168 m figures. It does not — that script prints the shadow residual table. The
figures come from `drive_closed_loop(single_channel=...)`. The numbers are right;
the reproduction command is wrong, which is exactly the failure `EVIDENCE.md`'s
one-command-per-row convention exists to prevent.

**[INTERPRETATION]** Passes 1–8 were written from the project's own documents,
and those documents were accurate **on the day each row was written**. Six of the
seven corrections above are staleness of that kind: measurements taken before
15 August that two ADRs then superseded without saying so. That is not a
documentation failure so much as the thing this folder's own §22 warns about —
**the dangerous claims are the ones that keep looking reassuring after they stop
being true.**

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
