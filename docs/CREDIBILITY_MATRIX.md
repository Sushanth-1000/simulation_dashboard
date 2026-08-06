# ASTRA — Credibility Matrix

**Purpose** One row per claim this project makes. Each row states the evidence behind it,
the provenance of that evidence, and what the claim does *not* license.

**Baseline commit** `30d40c2`
**Status** Working document. Rows are promoted as evidence lands; nothing is written in the
future tense to make it read as finished.
**Last reconciled** 2 August 2026, against the P0–P3.1 work.

### This document and `EVIDENCE.md`

They are not duplicates and must not become them. [`EVIDENCE.md`](EVIDENCE.md) is **the log**:
one row per measurement, the command that reproduces it on a clean checkout, the date. This
document is **the judgement**: one row per claim the project makes, what provenance that claim
rests on, and what it does not license.

So a number lives in exactly one place. The Evidence column below cites an `E-n` row rather
than restating a figure, because a figure restated in two documents is a figure that will be
stale in one of them — which is precisely what this reconciliation had to repair.

This is the Stage 7 evidence pack named as [NOT DONE] in
[`2030_2026-07-31_Tanay_S_status.md`](2030_2026-07-31_Tanay_S_status.md) §6.1.

---

## How to read this document

The single question a reviewer or a safety engineer will ask is *"where did that number come
from?"* Every row answers it with one of five markers.

| Marker | Meaning |
|:--:|---|
| **[M-ext]** | Measured against **external data this project did not author**. The only marker that supports an accuracy claim |
| **[M-syn]** | Measured, but on a plant this project also wrote. Demonstrates that a mechanism works; supports no accuracy claim |
| **[M-code]** | A measured property of the codebase itself. Provenance-neutral — true regardless of which plant it runs against |
| **[E]** | Engineering estimate. Not measured |
| **[NOT DONE]** | Outstanding. Named so it cannot be mistaken for complete |

### The distinction that governs everything below

The digital twin, the calibration corpus, and the trained policy **all descend from the same
kinematic bicycle model**. The generator and the judge agree by construction. Every **[M-syn]**
row therefore demonstrates that machinery runs — not that it is correct.

**[M-code]** rows are unaffected by this. Structural properties of the source are true whatever
the plant is, which makes them the only claims in this document that are fully supported today.

---

## Scoreboard

| Category | Rows | Best marker held |
|---|:--:|:--:|
| A · Structural assurance | 7 | **[M-code]** — fully supported |
| B · Runtime performance and stability | 6 | **[M-syn]** — mechanism shown |
| C · Control quality | 4 | **[M-syn]** — and confounded, see C-0 |
| D · **Gate efficacy — the central claims** | 6 | **[NOT DONE]** for the five that matter |
| CV · Calibration validity | 3 | **[M-syn]** |

> **Rows at [M-ext]: 0 of 26.**
>
> That number is the honest summary of this project's external validation, and moving it is
> the entire purpose of the plan in §7. No false-positive or false-negative rate appears
> anywhere in this document, because none has been measured and none can be until a row
> reaches [M-ext].

---

## A · Structural assurance

The strongest column. These hold regardless of plant, dataset, or policy.

| # | Claim | Marker | Evidence | Does **not** license |
|:--:|---|:--:|---|---|
| A-1 | Ten separation invariants, none left to code review | **[M-code]** | `astra invariants list` — 10/10 mechanically enforced; SI-1/2/4/5/9/10 STATIC, SI-3/7 RUNTIME, SI-6/8 TEST | That the invariants are the *right* ten |
| A-2 | Core-A cannot read a verdict (SI-5) | **[M-code]** | Capability pair — `ProposalWriter` exposes no read method; violation is a type error, not a convention | Protection against a compromised process outside the type system |
| A-3 | No PASS can suppress a VETO; an empty verdict set is a VETO (SI-3) | **[M-code]** | `Verdict.merge()`, runtime-enforced, covered by dedicated tests | That the gates *produce* correct verdicts — see §D |
| A-4 | Only L9 may construct an `IssuedCommand` (SI-7) | **[M-code]** | Runtime enforcement + import contract | Actuator-level authority; this is a software boundary |
| A-5 | Architecture contracts hold | **[M-code]** | `lint-imports` — 12 contracts kept, 0 broken | — |
| A-6 | Full static typing | **[M-code]** | `mypy --strict` clean over **143** source files | Runtime correctness |
| A-7 | Test suite and coverage | **[M-code]** | **2,672** tests, **98.10%** line coverage against a 95% gate — E-1 | **Correctness.** See D-0 — a fail-safe that did not fail safe survived all of this for the project's whole life |

> **Reproduce:** `make check` on a Linux/WSL2 host. The gate does not run on Windows —
> Smart App Control blocks the unsigned native extensions in `torch`, `mypy` and `grimp`.

---

## B · Runtime performance and stability

Measured over 100,000 continuous ticks. Provenance is synthetic, but these properties are
substantially plant-independent — memory boundedness and queue integrity do not depend on
what the vehicle was doing.

| # | Claim | Marker | Evidence | Does **not** license |
|:--:|---|:--:|---|---|
| B-1 | Ten-layer tick fits the budget | **[M-syn]** | Full tick p99 **≈6 ms** against a 50 ms period — E-2. The **1.98 ms** this row used to carry was never the full tick; it was retracted on 2 Aug and the subset it actually described is E-10 (0.811 ms for L1+L2+L7a+L8) | Hard-real-time determinism. Python, not an ECU. The two figures must never be compared |
| B-2 | Latency does not drift over long runs | **[M-syn]** | Soak 100k ticks: p99 **5.98 → 6.12 ms** between halves (×1.02) — E-8 | A WCET bound. This is a software p99, not a worst case |
| B-3 | Every rolling structure is genuinely bounded | **[M-syn]** | **+0.2 MiB** peak RSS growth over 100,000 ticks — E-7. The OOD counter was the one exception and is now bounded too (OD-5) | Behaviour beyond 100k ticks |
| B-4 | The evidence sink drops nothing | **[M-syn]** | **0 of 100,000** audit records dropped — E-9 | Tamper-evidence. The log is integrity-checked, not tamper-proof |
| B-5 | Cold path never blocks the hot path (SI-8) | **[M-code]** | Syscalls proven off the tick thread by test | Real-time scheduling guarantees |
| B-6 | Replay is byte-identical | **[M-syn]** | `StateRecorder` + `ReplayHarness`, verified | Determinism under concurrency beyond the tested envelope |

---

## C · Control quality

> ### C-0 · ~~Confound~~ — cleared 2 August 2026
>
> The confound was real: the trained policy stopped the vehicle within about five seconds, and
> every number in this section had been measured through it. **Fixed.** The action-rate penalty
> was applying to throttle and brake as well as steering, and the policy was undertrained; a
> controlled 2×2 established that *both* mattered (E-19). The retrained policy holds 13.0 m/s
> at 0.09 m mean deviation (E-14).
>
> The rows below were re-measured after that fix. The two that were not have been demoted
> rather than quietly refreshed, per maintenance rule 2.

| # | Claim | Marker | Evidence | Does **not** license |
|:--:|---|:--:|---|---|
| C-1 | A trained policy beats the deterministic placeholder | **[M-syn]** | Matched proposer vetoed on **1 tick in 300**; the placeholder on **299** — E-13. The **41.0% vs 59.8%** this row used to carry was measured through the C-0 policy, an unobservable lateral position, and a mismatched timestep; it is retracted, not refreshed | Any comparison to a real controller |
| C-2 | Lagrangian constraints are satisfied at training time | **[M-syn]** | C1 mean lane dev **0.0913 m** (budget 0.875) · C2 mean long. accel **0.0502 m/s²** (budget 4.000) · C3 collision rate **0.0000** — E-14 | Constraint satisfaction at runtime, on any other plant |
| C-3 | The veto rate is structurally excluded from the reward (SI-6) | **[M-code]** | `TrainingSignal` closed field set + `assert_signal_excludes_core_b` | — |
| C-4 | The twin predicts one-step dynamics | **[M-syn]**, **needs re-measure** | RMSE **7.3e-3** at 259 parameters — both predate [ADR-0019](adr/0019-one-twin-head-per-context.md), which gave the twin one output head per context. Weights digest still on every decision record | Prediction on real vehicle physics. Do not quote the parameter count until it is re-measured |

---

## D · Gate efficacy — the central claims

> ### D-0 · This section is empty, and that is the finding
>
> The architecture's core proposition is that three structurally independent gates catch
> semantically wrong commands. **No row here has evidence.** Nothing in the synthetic plant
> is out-of-distribution in the sense the statistical gate is calibrated for, so a
> false-positive or false-negative rate cannot be computed from it — not with more runs, not
> with more ticks.
>
> A-7 is the cautionary note, and 2 August 2026 sharpened it rather than softening it. A
> suite at 97.97% coverage with `mypy --strict` and 12 import contracts did **not** catch a
> fail-safe speed cap that reached no actuator (OD-2), a lateral position measured by nothing
> (OD-4), or a consolidation penalty set to a value that did nothing (E-28). All three were
> found by *running the system for a long time and reading the numbers*, not by the gate.
> Mechanical gates are cheap to satisfy and therefore weak as evidence.
>
> D-6 below is the first row this section has ever had. It arrived the same way.

| # | Claim | Marker | What would establish it |
|:--:|---|:--:|---|
| D-1 | **False-positive rate < 1%** | **[NOT DONE]** | Veto rate over real nominal driving that completed safely — comma2k19 |
| D-2 | **False-negative rate < 1%** | **[NOT DONE]** | Miss rate against ground-truth labelled faults — ALFA; or injected faults with known ground truth |
| D-3 | The three gates fail for structurally unrelated reasons | **[NOT DONE]** | Correlation of gate firings across a real corpus. Currently an argument from construction, not a measurement |
| D-4 | The statistical gate detects covariate shift | **[NOT DONE]** | MMD detector response across genuinely distinct real operating contexts |
| D-5 | Bounded safe exploration keeps the vehicle moving where a classical RTA halts | **[NOT DONE]** | ~~Contradicted by OD-6~~ — that contradiction is closed ([ADR-0016](adr/0016-exploration-may-not-override-a-deterministic-veto.md), E-11). Now genuinely untested rather than contradicted, and needs step 5 |
| D-6 | **Online adaptation would disarm the statistical gate** | **[M-syn]** + **[M-code]** | Over 100,000 ticks in one unchanging context, the score against the live twin is flat (1.1564 → 1.1560) while the score against a shadow twin FB2 adapted falls **40%** (1.1534 → 0.6962), monotonically — E-39. The mechanism is `[M-code]`: FB2's only labels are the proposer's commands, so `\|π_prop − π̂\|` shrinks by construction — E-38 | That FB2 *cannot* be made safe. It says the loop as specified must not be wired, and P3.1c proposes what replaces it |

---

## CV · Calibration validity

> Renumbered from **E-n** to **CV-n** on 2 August 2026. `EVIDENCE.md` numbers its rows `E-n`
> too, and once this document began citing them, "E-1" meant two different things in the same
> sentence. Renaming three rows was cheaper than living with that.

| # | Claim | Marker | Evidence | Does **not** license |
|:--:|---|:--:|---|---|
| CV-1 | Per-class conformal coverage matches target | **[M-syn]** | **94.9%–95.1%** against a 95% target, averaged over 200 random splits — E-12 | Coverage on real data. Exchangeability is assumed and adversarial perturbation violates it by construction |
| CV-2 | The conformal quantile is correctly implemented | **[M-code]** | Monte-Carlo verified correct to **0.15 pp**; uses ⌈(n+1)(1−ε)⌉ and returns `math.inf` rather than clamping | That the *scores* it thresholds are meaningful |
| CV-3 | Corpus provenance is verified, not merely stored | **[M-code]** | SHA-256 checksum verified at load (SI-9) | Tamper-evidence against an attacker with write access |

---

## Open defect register

Carried here deliberately. A credibility document that omits its own known defects is a
brochure. Every item below is from this project's own measurement, not external review.

**Five of the original six are closed as of 2 August 2026**, each fixed *and re-measured* as
maintenance rule 3 requires. They are struck through rather than deleted, per rule 2: a
register that shows only what is currently broken hides how much of it was found by the
project itself, which is the thing a reviewer most wants to know.

| # | Defect | Status | Invalidates |
|:--:|---|:--:|---|
| ~~**OD-1**~~ | Unbounded lane departure — 2,883 m at tick 100,000, every tick vetoed, FSM in HALT | **Closed.** Root cause was OD-4, not the policy: the vehicle left a 1.75 m lane while the *estimate* read zero. With lateral position observed, 100,000 ticks hold **0.0290 m** at a 0.1% veto rate, never leaving NOMINAL — E-22 | — |
| ~~**OD-2**~~ | **The fail-safe speed cap reaches no actuator.** A command recorded `SPEED_CAPPED` was bit-identical to one recorded `PROPOSED`; the vehicle accelerated 1.0 → 17.2 m/s *while in HALT* | **Closed.** The cap is projected onto the command last, after whatever governed, so it binds on the blocked path too. Driving the assembled pipeline into HALT now issues throttle 0.0, brake 1.0 — E-24 | — |
| **OD-3** | L7a never fired across 400,000 ticks. Trust Index pinned at exactly 1.00 for 99,000 consecutive ticks | **Half closed.** The Trust Index half is fixed — it was calibrated against L6's statistic rather than its own innovations, and now takes **90 distinct values**, mean 0.960 (E-23). **L7a is still open:** it vetoed once in ~500,000 ticks. P2.1 gave it a lane-corridor bound it *could* fire on, but no run has fired it — N-9 | Any claim that L7a contributes to the three-gate argument |
| ~~**OD-4**~~ | Lateral position dead-reckoned from an unobserved heading; `mean_estimator_error_m` reached **2.9 × 10⁶ m**. **The most consequential defect the project has found** — every other failure the first soak reported was downstream of it | **Closed.** A lateral-position measurement is published at σ = 0.1 m, where a real vehicle gets it from lane detection. Estimator error now **0.049 m** and flat | — |
| ~~**OD-5**~~ | The OOD counter is unbounded — 1,508 by tick 2,000, still climbing | **Closed**, and the finding was narrower than stated. Recovery was always bounded, because outside HALT the counter could never exceed the HALT threshold. What was unbounded was a number in every audit row that meant nothing above it. Clamped to `[0, θ_halt]`, which also lets the recovery bound be *stated*: ≤ 91 clean ticks, 4.6 s | — |
| ~~**OD-6**~~ | **Exploration out-ranks a VETO** — 99.8% of ticks issued a proposal under a blocking verdict | **Closed** by [ADR-0016](adr/0016-exploration-may-not-override-a-deterministic-veto.md). A gate with no basis to judge now ABSTAINs instead of vetoing, so there was no veto left to work around, and `issue()` tests the verdict before the envelope. **99,808 per 100,000 → 0** — E-11 | — |
| **OD-7** | **FB2 would disarm the statistical gate.** Its only training labels are the proposer's commands, so the twin regresses onto the thing it exists to be independent of. Measured in shadow: scores fall 40% in one unchanging context and are still falling | Open, **property of the code**. Not wired, so it harms nothing today | D-6, and any plan that wires FB2 as specified. P3.1c proposes estimating the control effectiveness instead |

**The pattern worth reading off this register:** every closed row was found by running the
system for a long time and reading the numbers, and none was found by the quality gate. Two of
them — OD-2 and OD-7 — were *inversions*, where the evidence log confidently recorded something
that had not happened. That is the failure mode this whole document exists to make visible.

---

## What this matrix does not claim

Carried forward from the Prototype & Demo Plan, because these constrain what may be said:

1. The **1.25 µs Core-B intercept latency is an analytical hardware bound**, not a measurement.
   Software latency is reported against the < 5 ms software target, never against that figure.
2. False positive/negative targets are **< 1%, not zero**. The argument is defence in depth
   through structurally independent gates, never "eliminates hallucination".
3. The **shared UKF state is an acknowledged residual common-cause channel** across all three
   gates — mitigated by the innovation monitor and FB1, not eliminated.
4. Conformal coverage **assumes exchangeability**, which adversarial perturbation violates by
   construction. That is why there is more than one gate.
5. The PINN twin is trained on **simulated dynamics**, not real vehicle physics.
6. Core-B is **Python processes, not fabricated hardware**. FPGA/ASIC is roadmap, not done.
7. **ASIL-D(D) is a design target, not an awarded rating.** An ASIL is the outcome of an
   assessed safety case; no ISO 26262 work products exist.
8. No security work exists — no threat model, no secure boot, no signed artefacts, no
   ISO/SAE 21434 work products.

---

## §7 · The promotion plan — how rows reach [M-ext]

Ordered by cost. None of it needs a GPU or a simulator.

> **Before any dataset below produces a number, partition it per
> [`DATA_SPLIT_PROTOCOL.md`](DATA_SPLIT_PROTOCOL.md).** Train, calibrate and test sets must be
> disjoint and split by drive, not by tick. A calibration set that overlaps the training set
> invalidates the conformal guarantee silently — risk RK-2 — and D-1 becomes meaningless
> without anything raising.

| Step | Dataset | Licence | Promotes |
|:--:|---|---|---|
| 1 | **comma2k19** — 33 h, 2,019 segments, CA-280 highway. `steering_angle`, `car_speed`, 4× wheel speed, radar, IMU, dual-receiver raw GNSS | **MIT** — unrestricted, commercial use permitted | **D-1** (false-positive rate), B-1/B-2 to [M-ext], C-1 |
| 2 | **highD** — 16.5 h, 110,000 vehicles, 45,000 km, 5,600 labelled lane changes, positioning error < 10 cm. Published at **ITSC 2018** for validation of automated driving | Free, non-commercial, per-request | CV-1, D-4 (OD-4 is closed, but real lateral ground truth would promote the fix) |
| 3 | **ALFA** — real Pixhawk/ArduPilot flights with **ground-truth fault type and time** | Research use | **D-2** (false-negative rate) — the only open source of labelled faults |
| 4 | Ablation over the existing `None` paths | — | Per-layer contribution: what each of nine layers earns |
| 5 | CARLA on a Linux GPU host | — | Closed-loop consequence, which logged replay cannot give |

> **The limitation of steps 1–3:** replaying a log is **open-loop**. You can measure *"would
> ASTRA have vetoed this real command?"*; you cannot measure *"what would have happened if it
> had."* This project has already been bitten by exactly that once — a 100% jerk-veto rate
> measured on an open-loop harness that pinned `a_now` at zero, retracted when the closed-loop
> figure turned out to be 1 tick in 400. Log replay produces D-1 and D-2 honestly. It does not
> retire OD-1 or OD-6, which are closed-loop findings and need step 5.

---

## For a partner evaluating ASTRA

This matrix is portable. Re-running it against your data is the deliverable of a
collaboration, and the first ask is deliberately small.

**What we need:** *N* hours of logged **(state, command)** pairs from nominal operation — the
signals your bus already records. No labels. No failure cases. No access to your controller.

**What we do not need, and never touch:** your control policy. L4 Core-A *is* your controller.
ASTRA governs whatever policy you already run; it does not replace, retrain, or read it.

**What gets fitted to you:** the L5 twin (your plant), the L3 calibration corpus (your
operating contexts), and the L7a/L7b physical constants (your vehicle limits). L1, L2, L6, L8
and L9 are largely domain-neutral.

**What comes back:** this table, with your name in the Dataset column and the [M-ext] marker on
rows D-1 and D-4 — starting with the false-positive rate, which is the number that decides
whether ASTRA is deployable on your fleet at all.

---

## Maintenance rules

1. **A row may only be promoted by a run that happened.** The command that produced it goes in
   the Evidence cell.
2. **Never delete a row to improve the scoreboard.** Demote it and say why.
3. **The open defect register is part of the document**, not an appendix. It is removed only
   when the defect is fixed and re-measured.
4. **[M-syn] never becomes [M-ext] by adding ticks.** Only a change of data provenance
   promotes a row.
5. Every claim made in a paper, a pitch, or an interview must trace to a row here. If it does
   not have a row, it is not a claim this project makes.
6. **Cite `EVIDENCE.md`, do not restate it.** The Evidence cell holds an `E-n` reference and
   the judgement about provenance; the figure itself lives in the log. This rule exists
   because the document spent a month carrying `1.98 ms`, `41.0% vs 59.8%` and `2,513 tests`
   after all three had been superseded — a number kept in two places is a number that will be
   wrong in one of them.
7. **Reconcile the register whenever a defect it names is fixed**, in the same change that
   fixes it. An open-defect register that overstates what is broken loses a reviewer's trust
   exactly as fast as one that understates it.
