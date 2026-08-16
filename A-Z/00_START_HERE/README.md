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

**To repeat this yourself:** [`VERIFY_PROMPT.md`](VERIFY_PROMPT.md) is a
self-contained prompt for a fresh session. It carries the environment quirks, the
commands, the expected values, and the traps that have already cost time. Re-run
it whenever the code changes or an ADR lands — two ADRs once moved a headline
safety number with nothing announcing it, which is why it exists.

Every quantitative claim in passes 1–8 was **re-measured by running the code**,
not confirmed by reading the document it came from. What follows is the record of
that pass, including what it found wrong.

### What was run

| Command | Result |
|---|---|
| `make check` | **3,047 passed + 3 xfailed** in 80.15 s; `quality gate: PASSED` |
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

### Second verification pass — same day

The first pass covered about half the sections. This one ran the **nine
benchmarks that had never been executed**, repeated the latency measurement five
times, and fixed a probe that had silently returned `nan`.

**Ran:** `ablation` · `comparison` · `effectiveness` (twice) · `platform_transfer`
· `commissioning` · `whiteness` · `envelope` · `soak` at 20,000 ticks · plus five
latency repeats and a corrected estimator-error probe.

**Coverage after both passes: 15 of the 17 benchmarks executed.** The two
outstanding are `flake_hunt` (not run) and `detectors` (not runnable — it is a
library, exercised through `fault_study`).

**What it confirmed.** `E-153`'s peak estimator error reproduced **exactly** once
the estimate was read from `record.fast_state.mean[1]` rather than from fields
`TickSample` does not have: **1.1805 m** single-channel against **0.1323 m**
redundant, with the redundant clean and biased arms identical. ADR-0023's fix
holds — no platform HALTs. The effectiveness figures reproduced identically on
two consecutive runs.

**Five further corrections, and three are findings rather than staleness.**

| # | Was written | Measured | Where fixed |
|---|---|---|---|
| 8 | latency: 1 tick in 2,000 over budget | **0 to 31 per 2,000**, p99 ranging 2.768–10.460 ms across five runs | 19, 22, 25 |
| 9 | `E-63`: the estimator "returns 140.000 on every platform" | **117.929** and **164.443**. Does not reproduce | 16 |
| 10 | `E-64`: "tracks to within 1.7% — 111.341, 165.140" | **114.986** and **167.702** — within 2.7%, sign flipped | 16 |
| 11 | OD-12: "held SAFE_EXPLORATION for 520 ticks, counter 0 → 100" | Conflated a post-fix count with a pre-fix failure. `E-83`: HALT on **two platforms of five**, t398 and t404 | 04, 08, 15 |
| 12 | `ablation` and `comparison` listed but never run | Both run; see below | 15, 22, 28 |

**Finding one — a benchmark is dead and nobody noticed.** `benchmarks.whiteness`
refuses to run. Its `StationaryVehicleError` guard — added *after* the `E-143`
retraction — fires on the `imu_dropout` arm because the fail-safe correctly brings
the vehicle to **0.0000 m/s**. The guard cannot tell a policy that never drove
from a safety response that worked, and that second case became possible only
after ADR-0024 and ADR-0030 landed. **`E-143` cannot be regenerated today.**

**Finding two — on one fault the governance is the harm.** The ablation shows
`lateral_noise` at **1.307 m governed** against **0.138 m with L7b disarmed**, and
the comparison shows ungoverned Core-A at **0.148 m**. The physical gate's 126
vetoes are what put the vehicle off the lane. `E-56`'s *"on one fault ASTRA is
worse"* still holds — and has **moved to a different fault**, while ASTRA became
27× *better* on the one it used to name.

**Finding three — two gates contribute literally nothing.** `L6 off` and `L7a off`
are bit-identical to `governed` in **every cell** of both ablation tables.

**[INTERPRETATION]** The first pass found stale numbers. This one found a broken
guard, a refutation that no longer reproduces, and a fault on which the
architecture makes things worse. **The difference between the two passes is
entirely that the second one ran the code that had never been run** — which is
the same lesson `E-152`'s wrong command and this folder's own §22 keep producing.

---

### Third pass — the three defects worked, not just recorded

**1 · The whiteness guard is fixed and the benchmark runs again.** It now counts
the ticks on which **the loop was actually closed** — a command reached the
actuators *and* the vehicle was moving — instead of reading the run's final
speed, and it raises only when that count is zero. An arm below **30 live ticks**
is reported as thin, which is `E-161`'s shape applied to a second benchmark. Five
tests assert the rule, including the one that would have caught the original
defect. Re-run:

| arm | live ticks | lateral-acceleration CUSUM | alarm |
|---|---|---|---|
| control | 200 | 3.75 | — |
| **`position_drift`** | 200 | **3.75** | **—** |
| `imu_dropout` | **41** | 77.63 | +2 |
| `lateral_noise` | 200 | 888.92 | +1 |

**`position_drift` does not alarm — E-107 stands**, and the arm is now
*identical to the control to every printed digit*, because ADR-0033's redundancy outvotes the drift
before it reaches the estimator. `E-143`'s 1.03× separation is now exactly
**1.00×**: the refutation got stronger and its number needs updating.

**2 · The `lateral_noise` finding was diagnosed, and it refuted my own
explanation.** I had guessed at a latched steering correction. The trace shows the
steering axis moving by 4 milliradians while the rate limiter substitutes
**throttle 0, brake 1.0** — the lateral bound is being satisfied *longitudinally*,
by braking. And the vehicle **never leaves the corridor**: it peaks at 1.7179 m
against a 1.75 m bound, 3.2 cm inside, on zero ticks out. My earlier phrasing —
*"the vetoes put the vehicle off the lane"* — was wrong and is corrected in §15,
§22 and §28.

**3 · The soak now runs at full length.** 100,000 ticks, all ten criteria pass,
verdict **STABLE**: lane deviation 0.0285 → 0.0287 m, resident set **+0.1 MiB**,
`PROPOSED` on 99,958 ticks, fail-safe never leaving `NOMINAL`. Its per-tick p99 is
**8.599 → 7.757 ms** against the 10 ms budget — much closer to the 7.289 ms this
pass measured over contiguous runs than the 20,000-tick soak's 3.87 ms, which
corroborates the tail concern rather than softening it.

### What is still not verified

Stated so this record cannot itself become the thing it warns about:

- `flake_hunt` — long-running, not executed.
- `detectors` has no `main`; it is a library, and its output is the shadow-detector
  table inside `fault_study`, which was run. That table confirms the innovation
  detector is **silent on every scenario** and that `trust` raises a **false alarm
  on the control**.
- `envelope` runs, but **not against anything in this repository**: every retained
  log is audit schema **v1** and the benchmark requires **v7 or later**, so it
  refuses. Driving a fresh log and running it in the same process works and
  reports *"no exploration episodes"* on a clean run. This is `L13` and OD-14
  showing up a third time — **the archive cannot be mined retrospectively.**
- Historical figures that **cannot** be reproduced because the defect is closed:
  OD-1's 2,883 m, OD-5's 1,508, OD-6's 99,808 / 100,000, OD-4's 2.9 × 10⁶ m,
  FB2's 40%, FB3's 5.02%. These are traceable to `CREDIBILITY_MATRIX.md` and are
  labelled as history, not as current behaviour.
- Every `[INTERPRETATION]` in this folder. Those are arguments; running code says
  nothing about whether they are right.

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
