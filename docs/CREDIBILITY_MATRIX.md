# ASTRA — Credibility Matrix

**Purpose** One row per claim this project makes. Each row states the evidence behind it,
the provenance of that evidence, and what the claim does *not* license.

**Baseline commit** `1236daf`
**Status** Working document. Rows are promoted as evidence lands; nothing is written in the
future tense to make it read as finished.
**Last reconciled** 15 August 2026, against ADR-0034 and the OD-8 re-measurement.

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
| C · Control quality | 4 | **[M-syn]** — re-measured after C-0 was cleared |
| D · **Gate efficacy — the central claims** | 10 | **[M-syn]** on three; **[NOT DONE]** for the five that matter |
| CV · Calibration validity | 3 | **[M-syn]** |

> **Rows at [M-ext]: 0 of 30.**
>
> That number is the honest summary of this project's external validation, and moving it is
> the entire purpose of the plan in §7. No false-positive or false-negative rate appears
> anywhere in this document, because none has been measured and none can be until a row
> reaches [M-ext].

---

## What moved between 5 and 9 August 2026

The scoreboard is a snapshot, and a snapshot cannot show the one thing a reviewer most needs
to know: **whether a project finds its own defects.** Four working days, stated in numbers.

**Five of the six defects the register held on the 5th are closed**, each fixed *and*
re-measured, none reported by anyone outside the project. Two more were opened during the same
run — OD-7 and OD-8 — which is why the register showed eight rows rather than six. **OD-9 was
added on the 9th** by the first fault the new injector ever ran, taking it to nine:

| | was | now |
|---|---|---|
| OD-1 lane departure | 2,883 m at tick 100,000, every tick vetoed, FSM latched in HALT | 0.0290 m, 0.1% veto rate, never leaves NOMINAL |
| OD-2 fail-safe speed cap | recorded on every capped tick, applied to no actuator; 17.2 m/s held *in HALT* | throttle 0.0, brake 1.0, pinned by a test through the assembled pipeline |
| OD-4 lateral position | dead-reckoned from an unobserved heading; estimator error reached 2.9 × 10⁶ m | measured at σ = 0.1 m; error 0.049 m and flat |
| OD-5 OOD counter | unbounded, 1,508 by tick 2,000 | bounded to `[0, θ_halt]`, and recovery now has a stated worst case of 91 ticks |
| OD-6 exploration vs VETO | 99,808 commands per 100,000 issued under a blocking verdict | **0** |

**Two dormant feedback loops were measured before being wired, and both would have broken the
gate they feed.** Neither was ever connected; neither affected a run.

- **FB2** regresses the twin onto the proposer's own commands. Run against a twin nothing
  reads, the non-conformity score falls **40%** in a context where nothing changed, while the
  live score stays flat to four decimal places (E-39). The twin's own module docstring names
  this as the way to disarm the statistical gate.
- **FB3** requantilises on scores the system generates itself. Its veto rate converges to
  **5.02%** — which is `significance_epsilon` exactly, because ε of any distribution lies
  above its own 1−ε quantile (E-40). The gate stops being a detector and becomes a fixed-rate
  sampler.

**One assumption was found already violated** — OD-8. The running system's scores sit *below
the minimum* of the corpus it is judged against, so the exchangeability the conformal guarantee
depends on does not hold, on synthetic data, today.

### The part that generalises

Not one of these was caught by the test suite, `mypy --strict`, or the 12 import
contracts. Every one was caught by running the system for a long time and reading the numbers,
or by running a mechanism in shadow and comparing it against the live one. Section A states
what mechanical gates buy; D-0 states what they do not, and this is the evidence for D-0.

Two of the defects were **inversions** — OD-2 and FB2 — where the evidence log confidently
recorded something that had not happened. Those are invisible to testing by construction,
because the system reports success. They are the reason this document exists.

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
| A-6 | Full static typing | **[M-code]** | `mypy --strict` clean over **166** source files — E-1 | Runtime correctness |
| A-7 | Test suite and coverage | **[M-code]** | **3,042** tests + 5 strict xfail against a 95% **aggregate** gate plus an 80% **per-file floor** — E-1, E-124 | **Correctness**, and until 11 August it did not license anything about a *particular* module either: the aggregate was always true and a file shipped at 10.3% under it (OD-17). See D-0 — a fail-safe that did not fail safe survived all of this for the project's whole life |

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

> ### C-0 · ~~Confound~~ — cleared 5 August 2026
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
> A-7 is the cautionary note, and the 5–9 August run sharpened it rather than softening it. A
> suite at 97.97% coverage with `mypy --strict` and 12 import contracts did **not** catch a
> fail-safe speed cap that reached no actuator (OD-2), a lateral position measured by nothing
> (OD-4), or a consolidation penalty set to a value that did nothing (E-28). All three were
> found by *running the system for a long time and reading the numbers*, not by the gate.
> Mechanical gates are cheap to satisfy and therefore weak as evidence.
>
> D-6 below was the first row this section ever had. It arrived the same way.
>
> **D-7 and D-8, added 9 August 2026, are the first rows produced by a fault rather than by a
> mechanism review** — and they do not soften the paragraph above. A miss rate still cannot be
> computed here, because six hand-chosen faults are not a population drawn from anything. What
> they establish is narrower and, as it turns out, more useful: *these particular faults, of
> the kind every real fleet sees, are not caught by any of the three gates*. The section is no
> longer empty. It is not yet a rate, and it will not be one before Phase 7.

| # | Claim | Marker | What would establish it |
|:--:|---|:--:|---|
| D-1 | **False-positive rate < 1%** | **[NOT DONE]** — but no longer inconsistent | The apparent contradiction with ε = 0.05 was a **units error in this row**, not a defect in the system. A veto runs the fallback for *one tick*; the posture does not degrade until the OOD counter crosses θ₁ = 10. Measured at the design point over 100,000 ticks: **4.97% of ticks vetoed, 0.008% outside NOMINAL** — two episodes in 83 minutes, both self-recovering, LIMP and HALT never reached (E-42). Per-tick is ε by construction and always will be; per-intervention is the number a fleet pays for. **[M-syn]**, so comma2k19 is still what promotes this row |
| D-2 | **False-negative rate < 1%** | **[NOT DONE]** | Miss rate against ground-truth labelled faults — ALFA; or injected faults with known ground truth |
| D-3 | The three gates fail for structurally unrelated reasons | **[NOT DONE]**, and now **partly contradicted** | Correlation of gate firings across a real corpus is still what would settle it. But the claim no longer stands unopposed: **OD-9** shows a common cause upstream of all three — every Core-B gate reads L2's fast estimate, so a fault the estimator absorbs is invisible to the whole of Core-B at once (E-48). The construction argument was about the gates' *logic* being unrelated, and it is; their *inputs* are not |
| D-4 | The statistical gate detects covariate shift | **[NOT DONE]** | MMD detector response across genuinely distinct real operating contexts |
| D-5 | Bounded safe exploration keeps the vehicle moving where a classical RTA halts | **[NOT DONE]** | ~~Contradicted by OD-6~~ — that contradiction is closed ([ADR-0016](adr/0016-exploration-may-not-override-a-deterministic-veto.md), E-11). Now genuinely untested rather than contradicted, and needs step 5 |
| D-6 | **Online adaptation would disarm the statistical gate** | **[M-syn]** + **[M-code]** | Over 100,000 ticks in one unchanging context, the score against the live twin is flat (1.1564 → 1.1560) while the score against a shadow twin FB2 adapted falls **40%** (1.1534 → 0.6962), monotonically — E-39. The mechanism is `[M-code]`: FB2's only labels are the proposer's commands, so `\|π_prop − π̂\|` shrinks by construction — E-38 | That FB2 *cannot* be made safe. It says the loop as specified must not be wired, and P3.1c proposes what replaces it |
| D-7 | **The gates do not detect a sensor fault that the estimator absorbs** | **[M-syn]** — the first row in this section produced by a *fault* rather than by a mechanism review | Six injected faults, each against a clean control at the same seed. Two put the vehicle outside its corridor — 4.199 m under a 200-tick IMU dropout, 2.025 m under a 2 m drift — with veto counts and reason codes **identical to the control's** and the fail-safe machine NOMINAL throughout (E-46, E-47). One, a 1 m position bias, moved the count 3 → 12 and produced the only statistical veto of the study (E-48) | A miss *rate*. Six hand-chosen faults are not a population, and two of the six did not stress what they named (E-50). It licenses the qualitative claim — *these faults are not caught* — and no number derived from it |
| D-8 | Availability survives a sensor fault | **[M-syn]** | **400 of 400** ticks issued a command in every scenario and in the control (E-49) | Anything about safety. It is quotable only next to D-7, and quoting it alone would be reporting the flattering half of one measurement — the same rule the false-positive rate is under |
| D-9 | **A stream-health gate would catch the worst measured fault; nothing catches the slow one** | **[M-syn]** | Three detectors run in shadow over the fault study, each a pure function of a `DecisionRecord`. Health fires on the IMU dropout at **+5 ticks** against a departure at **+73**; the innovation sequence fires only on the noise burst, at +84; the Trust Index catches both of those and nothing else. **Zero false alarms on the control.** The 2.025 m slow drift is silent on all three (E-51 – E-53) | That wiring any of them would be safe. None has authority over a verdict and none may acquire it before it has run in shadow against a *population* of faults rather than six chosen by hand — the rule FB2 and FB3 established, and the reason this row exists at all |
| D-10 | **The observable behaviour of the three-gate architecture is produced almost entirely by one gate** | **[M-syn]** | Ablation over four profiles x seven scenarios, 2,800 ticks each. Disarming **L7b** takes the veto count to **zero on six of seven scenarios**; **L6** contributes **one veto in 2,800 ticks**; **L7a contributes zero, everywhere**. Disarming any single gate moves the vehicle by at most **5 mm** (E-59, E-60) | That any gate is worthless. A gate that did not fire on the traffic it was shown has been shown to be *untested by that traffic*, not useless: L7a vetoed once in roughly 500,000 nominal ticks (N-9), and a 2,800-tick study finding zero is consistent with that rate rather than evidence against it. It also licenses nothing about compute — a disarmed gate still runs, by design |

---

## CV · Calibration validity

> Renumbered from **E-n** to **CV-n** on 5 August 2026. `EVIDENCE.md` numbers its rows `E-n`
> too, and once this document began citing them, "E-1" meant two different things in the same
> sentence. Renaming three rows was cheaper than living with that.

| # | Claim | Marker | Evidence | Does **not** license |
|:--:|---|:--:|---|---|
| CV-1 | Per-class conformal coverage matches target | **[M-syn]** | **94.9%–95.1%** against a 95% target, averaged over 200 random splits — E-12 | Coverage **on the live loop**, let alone on real data. E-41: the running system's scores sit *below the corpus minimum*, so it is not exchangeable with its own calibration set. E-12's splits were exchangeable by construction; the vehicle is not |
| CV-2 | The conformal quantile is correctly implemented | **[M-code]** | Monte-Carlo verified correct to **0.15 pp**; uses ⌈(n+1)(1−ε)⌉ and returns `math.inf` rather than clamping | That the *scores* it thresholds are meaningful |
| CV-3 | Corpus provenance is verified, not merely stored | **[M-code]** | SHA-256 checksum verified at load (SI-9) | Tamper-evidence against an attacker with write access |

---

## Open defect register

Carried here deliberately. A credibility document that omits its own known defects is a
brochure. Every item below is from this project's own measurement, not external review.

**Five of the original six are closed as of 10 August 2026**, and the register now holds **twenty-one rows** — sixteen closed, one reclassified, one partly closed, three open — each fixed *and re-measured* as
maintenance rule 3 requires. They are struck through rather than deleted, per rule 2: a
register that shows only what is currently broken hides how much of it was found by the
project itself, which is the thing a reviewer most wants to know.

| # | Defect | Status | Invalidates |
|:--:|---|:--:|---|
| ~~**OD-1**~~ | Unbounded lane departure — 2,883 m at tick 100,000, every tick vetoed, FSM in HALT | **Closed.** Root cause was OD-4, not the policy: the vehicle left a 1.75 m lane while the *estimate* read zero. With lateral position observed, 100,000 ticks hold **0.0290 m** at a 0.1% veto rate, never leaving NOMINAL — E-22 | — |
| ~~**OD-2**~~ | **The fail-safe speed cap reaches no actuator.** A command recorded `SPEED_CAPPED` was bit-identical to one recorded `PROPOSED`; the vehicle accelerated 1.0 → 17.2 m/s *while in HALT* | **Closed.** The cap is projected onto the command last, after whatever governed, so it binds on the blocked path too. Driving the assembled pipeline into HALT now issues throttle 0.0, brake 1.0 — E-24 | — |
| **OD-3** | L7a never fired across 400,000 ticks. Trust Index pinned at exactly 1.00 for 99,000 consecutive ticks | **Half closed.** The Trust Index half is fixed — it was calibrated against L6's statistic rather than its own innovations, and now takes **90 distinct values**, mean 0.960 (E-23). **L7a is still open:** it vetoed once in ~500,000 ticks. P2.1 gave it a lane-corridor bound it *could* fire on, but no run has fired it — N-9. **Re-measured 15 August 2026 against the rebuilt baseline, and it is broader than L7a.** A census over **2,800 ticks** — the clean arm plus all six faults, a suite built to break the gates — has `DETERMINISTIC` at **VETO 0** *and* `STATISTICAL` at **VETO 0**, with `PHYSICAL` carrying all **149** on a single reason code (E-162). Both silent gates **PASS** rather than `ABSTAIN`: they judge every tick and find nothing to object to, which is a finding about thresholds rather than an honest declaration of incompetence (E-163). **L6's silence has a known cause and it is OD-8** — its scores sit entirely below the corpus quantile, so it *cannot* veto (E-164). The two open rows explain each other | Any claim that L7a contributes to the three-gate argument |
| ~~**OD-4**~~ | Lateral position dead-reckoned from an unobserved heading; `mean_estimator_error_m` reached **2.9 × 10⁶ m**. **The most consequential defect the project has found** — every other failure the first soak reported was downstream of it | **Closed.** A lateral-position measurement is published at σ = 0.1 m, where a real vehicle gets it from lane detection. Estimator error now **0.049 m** and flat | — |
| ~~**OD-5**~~ | The OOD counter is unbounded — 1,508 by tick 2,000, still climbing | **Closed**, and the finding was narrower than stated. Recovery was always bounded, because outside HALT the counter could never exceed the HALT threshold. What was unbounded was a number in every audit row that meant nothing above it. Clamped to `[0, θ_halt]`, which also lets the recovery bound be *stated*: ≤ 91 clean ticks, 4.6 s | — |
| ~~**OD-6**~~ | **Exploration out-ranks a VETO** — 99.8% of ticks issued a proposal under a blocking verdict | **Closed** by [ADR-0016](adr/0016-exploration-may-not-override-a-deterministic-veto.md). A gate with no basis to judge now ABSTAINs instead of vetoing, so there was no veto left to work around, and `issue()` tests the verdict before the envelope. **99,808 per 100,000 → 0** — E-11 | — |
| **OD-8** | **The live loop is not exchangeable with its own calibration corpus.** Running non-conformity scores sit at **1.156**, below the corpus **minimum** of 1.158; the whole HIGHWAY_CLEAR distribution spans 1.158–1.189 over 1,000 samples. Exchangeability is the assumption the conformal guarantee rests on, and it is violated *in-house, on synthetic data*, before any external dataset is involved | **Still open, re-measured 15 August 2026 and worse.** The corpus was rebuilt through the corrected innovation covariance *and* redundant driven sensing — everything the score is built from moved — and the violation survived: `URBAN_CLEAR`, **999 live samples against 1,000 calibration, zero overlap**, live 3.3648–3.4083 against a corpus of 3.8758–5.4312 (E-159). Still below the corpus, the same direction as August, and proportionally further: 0.2% under the minimum then, **13% under now**. It is now measured by `benchmarks/exchangeability.py` rather than by reading two stale artefacts side by side (E-160). **Property of the artefacts** rather than of any trajectory | **CV-1 and every D-row.** Today's 0.089% veto rate is this mismatch, not evidence the gate discriminates. It is also the strongest argument for [`DATA_SPLIT_PROTOCOL.md`](DATA_SPLIT_PROTOCOL.md): the risk that document was written to prevent has already materialised once |
| ~~**OD-7**~~ | **FB2 would disarm the statistical gate.** Its only training labels are the proposer's commands, so the twin regresses onto the thing it exists to be independent of. Measured in shadow: scores fall 40% in one unchanging context and are still falling (E-39) | **Reclassified 15 August 2026 — this was never a defect.** It describes a loop that **is not wired and never was**, so no run has ever been affected and nothing in the system is wrong. What it is: a **standing constraint** on any future FB2, and it has been honoured twice. [ADR-0020](adr/0020-fb2-estimates-control-effectiveness.md) refused the specified design outright — its own status line reads *"do not wire as originally specified"* — and the replacement was then **also refuted by measurement**: fed the filtered estimate it returns **140.000 on every platform**, including plants whose true `B` is 112.0 and 168.0, because the UKF's process model already assumes `B` (E-63). Fed the raw measured response it tracks to within 1.7%, with a residual ~1.5% low *in the direction ADR-0020 names as dangerous* (E-64). The estimator is defined in `runtime/assembly.py` and instantiated **only** in `benchmarks/effectiveness.py`. **A refusal carried in the defect column overstates the register in the one direction that matters** — it makes a decision look like an outstanding fault | Any plan that wires FB2. The constraint stands: not as specified, and not from the filtered estimate |
| **OD-9** | **A sensor fault blinds Core-B and the proposer at once.** Every Core-B gate reads L2's fast estimate, and the proposer closes the loop on that same estimate — so it actively drives the corrupted number to the value the gates consider safe. Under an injected IMU dropout the vehicle spent 73 ticks outside its ±1.75 m corridor while the corridor bound read **0.023 m**; under a slow drift, 34 ticks against **0.235 m**. Verdict trace identical to the control in both. **Worse than first recorded:** the fault does not stay in the channel it entered — a frozen position reading is maximally self-consistent, so the filter grows confident in it and pushes the inconsistency into the one state nothing observes. True heading reaches 0.0686 rad while the estimate reports 0.0017 rad (E-58) | **Partly closed, 11 August 2026 — the consequence is arrested; the blindness is not.** [ADR-0024](adr/0024-sensor-integrity-is-a-second-counter-not-a-fourth-gate.md) gives L8 a **second counter** driven by `StreamHealth`, which L1 computes at the sensor boundary and is therefore the one input to the machine upstream of the common cause. Measured: the dropout's final deviation falls **4.199 m → 0.167 m**, inside the corridor it used to leave, with **DEGRADED at +5 ticks, LIMP at +15, HALT at +40** against a departure that begins at +73 — 1.65 s of margin (E-87, E-88). Zero false alarms; the control holds the counter at 0 across 400 ticks (E-89). **UPDATED 15 August 2026 — a fifth candidate was tried and is also silent (E-143).** The innovation **sequence** was the one statistic the earlier four had not tested: E-53 and E-105 both tested *magnitude*. Measured on a driving vehicle, a CUSUM on the signed residual separates the drift **1.03x** at every slack while separating the bias 12.8x–14.3x. **For several hours this row said the opposite**, because the run used a default path this session invented and fell back to a proposer that left the vehicle stationary with every tick vetoed — the one configuration where this row's own mechanism cannot operate (E-145, E-146). The false 7.35x was the mechanism's *absence* showing up as signal, which is why the corrected result is stronger evidence than a plain null. **The remaining two thirds are now argued rather than merely open.** Three independent mechanisms have been built and measured against the slow drift and all three are silent: the **innovation sequence** (E-53), **analytical redundancy** from a command-only estimate (E-94), and **cross-channel consistency** between the position and acceleration channels (E-106). Each fails for a reason that traces to one root -- *a self-consistent lie slower than the sensor noise cannot be distinguished from truth by any function of a single sensor chain*, because every quantity on the record is downstream of the same measurement and no rearrangement of downstream quantities creates information that was never upstream (E-107). **Redundancy is therefore not the convenient answer but the only one**, and this is the argument for it rather than an assertion. A fourth candidate, feeding the innovation gate's own flag to the integrity counter, was refuted before it was built: at gamma 7.5 it fires on tick 0 of **every** arm including the control and on no injected fault but the noise burst (E-105). **The row stays open for two reasons and both are asserted by tests.** *One* — this catches `DROPOUT` and nothing else: `StreamHealth` is computed from staleness, so a channel publishing a fresh, well-formed, wrong value stays HEALTHY, and the slow drift still ends **2.025 m** out with the integrity counter at **0** (E-90). *Two* — **no gate sees it even now**; the verdict trace under the fault is still identical to the control's. The response comes from outside the three-gate argument, not from within it, and a safety case must say so in those words. **The chosen fix was not the obvious one**, and the reasoning is the transferable part: *you cannot veto your way out of a lying sensor*, because L9's fallback controller reads the same corrupted estimate — a fourth gate would have exchanged one command computed from a lie for another. **Previously recorded, and still true of the faults this does not catch:** A dropout that *persists* produces no attributable veto at all and a **35.705 m** departure with the fail-safe NOMINAL throughout; the same fault *closing* at t600 is caught on the very tick the sensor recovers, escalating to HALT and braking to a stop (E-76). The architecture is not incapable of seeing this — it is unable to start until the corrupted channel stops being corrupted, by which point the vehicle is twenty lane-widths out. **Also with a measured remediation path.** P2.7 ran three candidate detectors in shadow: gating on **stream health** would catch the dropout at **+5 ticks against a 73-tick departure** — 3.4 s of margin, from a signal L1 already computes and no gate reads (E-51, E-52). The principled candidate, the innovation sequence, is **refuted by measurement**: a 1 cm/tick drift against a 0.1 m sigma never leaves the filter's expected band, so it is silent on exactly the fault it was wanted for (E-53). Found 9 August 2026 by the first fault the new injector ever ran (E-46, E-47, E-48). Not a coding error: the composition is correct at every layer and wrong as a whole, which is the third time this register has recorded that shape. `shield.py` states the hazard in its own docstring — *"this bound is only as good as the position estimate, and that is not a quibble"* — where it was written as a caveat and is now a measurement | **D-3** directly, and it is now also a **security** finding — `THREAT_MODEL.md` §5.1 records it as an attack primitive, since an adversary who can influence one sensor channel has a measured path to loss of lane position that produces clean evidence throughout. the gates do not fail for structurally unrelated reasons when the reason is upstream of all of them. Also the corridor bound P2.1a added, which cannot fire on a fault-caused departure |
| ~~**OD-10**~~ | **The innovation covariance omits `H Q Hᵀ`, inflating the Mahalanobis distance by a measured 1.24x at the median.** The UKF's update reuses the sigma points propagated through `fx`, whose spread carries no process noise, so `S` is short by exactly the process-noise term | **Open, and less severe than this row first said.** Filed on 10 August quoting the algebraic per-channel bound of **22.4x**; measuring it the same day gave a realised **1.53x on the smallest half of innovations, 1.23x on the tail, and 1.024x on the largest single distance** (E-71). The row is corrected rather than quietly amended, because a register that overstates what is broken loses trust as fast as one that understates it. **Inherited, not introduced**: the behaviour is FilterPy's and is in every number this project ever recorded | Nothing in verdict terms today, and now for a measured reason rather than an argued one: the corpus was calibrated on the same statistic, and the correction is smallest in the tail where vetoes are decided. What it still invalidates is the **name** — the archived `fast_innovation` is not a Mahalanobis distance, so it may not be compared against a chi-squared expectation, against a distance computed elsewhere, or **across a change to `Q`**, which is the one that would bite silently. **Closed 15 August 2026** by [ADR-0032](adr/0032-the-sigma-points-are-redrawn-after-the-process-noise-is-added.md): `predict` redraws the sigma points from the `Q`-inflated covariance, so the update observes a set whose spread is the full predicted covariance. A UKF has no `H` to add the term with — not having one is the point of the formulation — so redrawing is how the textbook carries it, and it fixes the **gain** as well as `S`. Measured 1.34x at the median and **1.02x at the maximum**, matching E-71's independent prediction of 1.024x (E-147). **The cost is real and recorded**: a correct filter trusts each measurement less, so final lane deviation went 0.0122 m → 0.1218 m (E-149). It also forced the corpus regeneration — 400/400 vetoed until it ran — and `make artifacts-check` caught that on its first day (E-148) |
| **OD-11** | **NFR5 is partly false: the core is automotive in four places.** The actuation space and command projector are not injectable — `assemble_pipeline` has 14 parameters and none accepts either; L2's process model is a bicycle model that propagates **zero heading change** for a platform turning on the spot; and `astra.kernel` names road friction, tyre wear, highways and rain | **Open**, found 10 August 2026 by building a differential-drive warehouse AGV and driving it at the pipeline (E-72 – E-75). **The claim holds for the gates**: L3, L6, L7a and L7b took the AGV unchanged, because every input they read is a number with a unit. It fails for the composition root, the process model and the vocabulary. **Walls 1 and 2 closed 15 August 2026** by [ADR-0034](adr/0034-the-composition-root-accepts-a-platform-instead-of-being-one.md): `assemble_pipeline` takes keyword-only `space` and `projector`, defaulted to the automotive implementations, and two **strict** xfails flipped to `XPASS` the moment they existed — 5 strict xfails down to 3 (E-156). **Writing an honest injection test found three couplings review had not named** (E-157): the projector, the *placeholder policy* — which indexes `speed_index` and `steer_index` into the space and which the xfail never mentioned — and `twin.control_effectiveness`, whose length **is** the channel count. The root now refuses a supplied space without a projector and a policy, where it can be acted on rather than as an index error deep in construction. **Walls 3 and 4 remain open**, and wall 3 is the one that matters: no amount of injection reaches a bicycle process model | **A-1 and NFR5 as written**, and the marketing sentence in `assembly.py`'s own docstring. It does *not* invalidate any measurement — every number in this pack was taken on the automotive platform the core is shaped for. What it invalidates is the claim that a **second** platform costs only an adapter |
| ~~**OD-12**~~ | **Bounded safe exploration halted the vehicle** — the one behaviour the architecture exists to differ from. On a platform the twin was never fitted to the twin mispredicts, so L6 and L7b veto; L9 finds no matching profile and declares `SAFE_EXPLORATION`; **L8 counts those same vetoes** and escalates NOMINAL → DEGRADED → LIMP → HALT, which is terminal. One condition, two owners, and the terminal answer won. Measured on two of five platforms at the same seed: **weak acceleration HALT at t398 after 520 exploring ticks and 352 vetoes; weak brakes HALT at t404 after 580 and 315. Both finished at 0.00 m/s under an arbitrator still reporting `SAFE_EXPLORATION` on the same tick** (E-83) | **Closed 11 August 2026** by [ADR-0023](adr/0023-the-ood-counter-freezes-during-bounded-exploration.md): the OOD counter freezes while exploration is engaged, conditioned on **posture** rather than on which gate vetoed — the latter is what SI-3 forbids and `machine.py` says so in its own docstring. **Veto authority is untouched**; what is suspended is escalation to a terminal posture while another layer owns the same condition. Re-measured: every platform finishes NOMINAL and moving, weak brakes at 16.58 m/s (E-85), and `benchmarks/platform_transfer.py` exits non-zero if one halts again. **Found by changing the plant** — the fourth distinct instrument, after the long soak, the shadow harness and the fault injector, and the cheapest of the four | The distinguishing sentence in `exploration.py`'s docstring and in every description of this architecture, which until 11 August was **false on every platform where exploration engaged for a sustained period**. It does *not* invalidate any other measurement: exploration engaged for 80 of 600 ticks on the calibrated platform, too briefly to reach θ₁ |
| ~~**OD-13**~~ | **The exploration envelope's speed cap was enforced against nothing.** `exploration_envelope` computes `speed_cap = nearest_certified_max × 0.5`; `restricted_space` turns the envelope into narrowed **channel** bounds, which limit how much throttle may be commanded on one tick and bound the resulting speed not at all. Measured in the same control arm: the weak-braking platform reached **23.43 m/s** — against the calibrated platform's 14.27 — with **zero** ticks marked `SPEED_CAPPED` (E-84) | **Closed 11 August 2026** by the same record. The cap flows through the projector seam P2.1 built for the fail-safe cap, so `SPEED_CAPPED` still means *a command the cap altered*. Re-measured: the weak-braking platform is held at **16.72 m/s across 105 capped ticks** — half the highway profile's 33.34 maximum, plus one tick of plant integration (E-86). **Filed separately from OD-12 because fixing that one alone would have made this one worse**: the halt was the only thing arresting the acceleration | The word *bounded* in "bounded safe exploration", and ADR-0016's consequence that "the envelope shrinks what may be issued" — true of the steering cone, false of speed. The steering restriction was never affected and is unchanged |
| ~~**OD-14**~~ | **The arbitration record could not say what context it was about.** `arbitrate()` receives a `RuntimeContextSignature`, searches the knowledge base with it, decides on it — and returned an `ArbitrationDecision` that did not carry it. So a record could read `SAFE_EXPLORATION, trust 0.62` and could not say **which context** produced that. The one question a reader of an arbitration record most wants to ask was unanswerable from the archive | **Closed 11 August 2026** by [ADR-0025](adr/0025-the-vehicle-proposes-calibration-work-never-a-calibration.md); audit schema **6 → 7**. Found while building the calibration proposer, which needs exactly that field — so the defect was found by trying to *use* the evidence rather than by reviewing it, which is the fifth distinct instrument this register has recorded. **Third time this shape has appeared**: `fast_innovation` at schema 3 (E-54) and `previous_digest` at 5 were both quantities the pipeline computed, consumed, and archived nowhere. A pipeline that *has* a number is not a pipeline whose *evidence* has it | **A-10**, which defines explainability for this project as decision provenance — the inputs a decision was taken on, recorded beside it. Every arbitration record written before schema 7 is missing it, and cannot be mined retrospectively |
| ~~**OD-15**~~ | **Partly closed 11 August 2026** by [ADR-0026](adr/0026-faulted-gets-a-producer-and-the-counter-needs-a-quorum.md): an `IntegrityMonitor` port, a median-fusing adapter and a residual monitor, with the drift's final deviation falling **2.025 m -> 0.042 m** and `FAULTED` produced for the first time (E-113, E-114). **What is now open is different and sharper: the escalation policy.** One faulted channel of three HALTs a vehicle that is driving well on the other two (E-116). Original text follows. **The five-modality sensor bus carries one measurement.** `_publish_state` computes one payload and publishes it byte-identical to all five modalities; the extractor reads the IMU alone and discards the rest. Five modalities, one sensor — so every cross-check that could catch a lying channel had nothing to check against, and *"unmeasurable here"* was written into three separate refutations on the strength of it (E-108) | **Open, and narrower than it was.** Both facts live in about thirty lines of **test harness**, not in the architecture: `FusedSensorFrame` already carries per-modality samples and `MeasurementExtractor` is an injectable port, so **nothing in `src/` changed** to demonstrate redundancy alongside the plant (E-109). What remains open is the harness itself: the pipeline is still *driven* by one channel, so redundancy is measured beside the vehicle rather than by it. **Closed 15 August 2026** by [ADR-0033](adr/0033-redundancy-is-the-driven-path-not-a-measurement-beside-it.md), which is that decision record: `drive_closed_loop` builds three independent position channels by default — σ 0.1 / 0.2 / 0.06, **deliberately unequal**, because identical sigmas model identical sensors and identical sensors share a failure mode — and `single_channel=True` is how a caller asks for one and **has to say so**. The clean run improved **6x**, 0.1034 m → 0.0168 m (E-152), which more than repays ADR-0032's control-quality cost. **A 1 m bias in one channel now never reaches the estimator**: peak estimator error 1.1805 m → 0.1323 m, final deviation 0.8387 m → **0.0168 m, the clean run's figure to four decimals** (E-153). What it does *not* buy is stated in the ADR: the three channels share the plant, so no channel count catches a plant-model error | **Every claim of sensor diversity**, and it sharpens **D-3**: the three gates were already known to share L2's estimate, and this says the *modalities feeding L2* were never distinct either. It also means `THREAT_MODEL.md` A-2's *"corrupt one sensor channel"* has been understating the ease — there is one channel to corrupt |
| ~~**OD-16**~~ | **The sensor-integrity counter was never written to the audit log.** ADR-0024 gave L8 two counters four days earlier and argued they must be reported separately — *"the gates refused forty commands" and "a sensor was dark for forty ticks" need different responses and one integer cannot say which happened* — and the field went onto the snapshot and not onto the record. Every archive between schema 6 and 8 therefore carries that argument's **conclusion and none of its evidence** (E-120) | **Closed 11 August 2026**, schema **7 → 8**. **Fourth instance of one shape in five versions**, after `fast_innovation` (v3), `previous_digest` (v5) and the arbitration signature (v7). Found the same way OD-14 was, one version earlier: **by building the tool that reads the evidence and watching it come up empty.** A pipeline that computes a number is not a pipeline whose evidence has it, and the only reliable way to notice is to try to *use* the archive for something | **ADR-0024's central claim, in every archive it wrote.** The mechanism was correct throughout — the counter escalated exactly as measured — but a reader of those logs could not confirm it, which for a certification artefact is the same as it not having happened |
| ~~**OD-17**~~ | **The coverage gate is an aggregate, so a module can ship with no tests.** `astra explain` landed at **10.3%** coverage and `make check` was green, because 94 uncovered statements against a codebase of several thousand move the aggregate by less than a tenth of a point (E-123). The gate asserted *"95% coverage"* and verified *"95% on average"* | **Closed 11 August 2026** by `make coverage-floor`, a per-file floor at 80% with `__main__.py` excluded **by name rather than by pattern**. Replayed against the defect: exit code 1, the file named (E-124). The module that caused it went **10.3% → 95.2%** across 29 tests (E-125). **The floor is deliberately far below the aggregate**: its job is to catch a module with no tests, and one set near 95% would fail three healthy files and be switched off within a week | **Nothing about the code's correctness, and something about every coverage claim this project has made.** A-7 cites the aggregate, and the aggregate was always true; what it never licensed was any statement about a *particular* module. Same shape as OD-2 and OD-7 — a check asserting more than it verifies — with the novelty that **the check was the quality gate itself** |
| ~~**OD-18**~~ | **The fail-safe treated every sensor as equally critical.** A camera failure HALTed the vehicle in two seconds exactly as an IMU failure did, although the extractor reads the IMU alone and the camera contributes nothing to the state estimate the gates read (E-126). ADR-0024 justified counting rather than quorum on **redundancy** grounds and was silent on **criticality**; ADR-0027 answered *how many may fail* and inherited the gap on *which ones matter* | **Closed 11 August 2026** by [ADR-0028](adr/0028-the-deployment-declares-which-sensors-are-critical.md): `critical_modalities`, a declaration in configuration because *which sensor feeds what* is platform knowledge NFR5 keeps out of the layers. **L8 counts; the deployment declares.** A modality outside the set is still **recorded** in every audit record — not counted is not not seen. Bit-identical by default and all 2,953 tests pass (E-128). **Found by a question a customer would ask** — *does it act differently depending on which sensor degraded?* — the third defect this week found that way, after OD-16 and OD-17, and none of the three by a test | **Nothing measured**, because no study ever failed a non-IMU modality. What it invalidated was a *claim I made in conversation* an hour earlier — that a failing sensor is *"named and acted on"* — which was right about the naming and too generous about the acting |
| ~~**OD-19**~~ | **The response was per-severity, never per-sensor.** ADR-0028 let a deployment say *this sensor does not matter*; it could not say *this sensor matters, but only this much*. Every effect the machine has — speed cap, lane-change permission, handover — reads `state`, and `state` comes from one integer, so a sensor's loss produced either the whole ladder or nothing (E-129). The response with the clearest per-sensor meaning — *lose the camera, stop offering lane changes, keep driving* — was **unrepresentable**. One integer was being asked two questions: *how bad is this getting* and *what is broken* | **Closed 15 August 2026** by [ADR-0029](adr/0029-capability-withdrawal-is-a-second-axis-not-a-third-counter.md): a second **axis**, not a third counter. `failsafe.capabilities` declares what each function requires; a function is withdrawn while any modality it requires is unhealthy, and the axes compose by **intersection** so withdrawal can only ever subtract — a set able to *grant* what the posture forbids would be a fourth gate with veto-override authority (SI-3). Three of five modalities now hold `NOMINAL` and decline only what they carry (E-131). The degradation table is **derived from the running machine** and flags **inert** sensors (E-132). Additive: 2,958 pre-existing tests pass untouched (E-133). **Found by a customer's question** — *can the car take a response based on the sensor degraded?* — the fourth this week, and none of the four by a test | **My first recommendation**, to defer this behind OD-15 on the grounds that four of five sensors feed nothing. Wrong, and recorded as wrong in the ADR: the map states what the vehicle **may do** when a sensor is unhealthy, not what the estimator reads, and camera health is real today (E-130) |
| ~~**OD-20**~~ | **Four health levels, two responses.** `StreamHealth` has told `DEGRADED`, `FAULTED` and `ABSENT` apart since Phase 1 — its own docstring says collapsing them *"loses that distinction"* — and L8 read one bit of it. Measured: a camera **arriving late** stopped the vehicle exactly as a camera that was **gone**, all three levels reaching HALT with φ = 40 (E-134). OD-18's shape one field in | **Closed 15 August 2026** by [ADR-0030](adr/0030-the-health-level-caps-how-far-the-posture-may-escalate.md): the deployment declares, per level, how far the posture may go. A stale camera now settles at **LIMP** and drives on; a dark one still HALTs (E-136). A ceiling was *rejected* for modalities one record earlier and is right here, because `StreamHealth` **is** a severity — how far past the staleness budget — where modality identity is not. Applied in one method because the counter reaches a posture from **three** call sites, and a cap on two of them is a fail-safe that escalates past its own ceiling | **Nothing measured** — no study had ever held a stream at `DEGRADED` rather than dropping it outright, which is why three years of `StreamHealth` docstrings could describe a distinction the machine did not make |
| ~~**OD-21**~~ | **An intermittently failing sensor was invisible, however long it failed.** The integrity counter moves +1 unhealthy / −1 healthy, so **any duty cycle at or below 50% nets to zero**. Measured over a full minute at 20 Hz: a camera dark on **alternate frames** — 600 of 1,200 ticks — held **NOMINAL** with the counter peaking at **1**; dark 3 frames in 13, NOMINAL with a peak of 3 (E-135). A duty-cycle detector with a 50% threshold, documented as a health detector | **Closed 15 August 2026** by [ADR-0031](adr/0031-decay-measures-the-duty-cycle-the-counter-cancels-out.md): a per-modality exponential average that converges to the duty cycle the counter cancels — 0.497 and 0.240 on those two cases (E-137). **Not the weighted counter this project keeps refusing**: it is a *fraction of recent frames*, with units, checkable against the hardware. **It drives nothing** — a decaying sensor is a service condition, and a vehicle that stopped for maintenance is OD-18 through another door. Not cleared by `reset`, or halt-reset-halt would launder a failing sensor clean | **The counter's own description.** It is not wrong — it answers *am I in trouble now* and the answer was no — but the machine had no quantity answering *is this sensor dying*, and the archive had none either, so a fleet's schema-9 logs cannot be mined for wear at all |

**The pattern worth reading off this register:** every closed row was found by running the
system for a long time and reading the numbers, and none was found by the quality gate. Two of
them — OD-2 and OD-7 — were *inversions*, where the evidence log confidently recorded something
that had not happened. That is the failure mode this whole document exists to make visible.

**OD-9 sharpens the pattern rather than extending it.** It was not found by running longer; a
hundred thousand nominal ticks would never have produced it, because nothing goes wrong in
them. It was found by making something go wrong *on purpose* and holding a control run beside
it. That is the third distinct instrument this project has needed — a long soak, a shadow
harness, and now an injected fault with recorded ground truth — and each found a class of
defect the previous two could not see.

**OD-12 and OD-13 add the fourth, and it is the cheapest of the four: change the plant.** Half a
million ticks of soak never produced either, because the soak drives the vehicle the twin was
fitted to, and on that vehicle exploration engages for 80 ticks in 600 — too briefly to reach
θ₁ and too briefly to accelerate. Weaken the brakes and the same code halts at t404 having first
reached 23.43 m/s. No new instrumentation was required; the run harness already accepted an
`EnvironmentSpec` and nothing had ever passed it a different one.

They also repeat this register's most persistent shape, now for the fourth time: **the
composition is correct at every layer and wrong as a whole.** L8 counting vetoes is correct. L9
declaring exploration is correct. Neither knows the other is answering the same question. OD-4,
OD-9 and OD-6 have the same structure, and it is the argument for why this architecture needs
runtime evidence rather than more unit tests — every one of these passed every test that existed
when it was written.

---

## What this matrix does not claim

Carried forward from the Prototype & Demo Plan, because these constrain what may be said:

1. The **1.25 µs Core-B intercept latency is an analytical hardware bound**, not a measurement.
   Software latency is reported against the < 5 ms software target, never against that figure.
2. False positive/negative targets are **< 1%, not zero**. The argument is defence in depth
   through structurally independent gates, never "eliminates hallucination". **The < 1% is
   currently unreachable by construction:** `significance_epsilon` is 0.05, so a correctly
   functioning conformal gate vetoes 5% of exchangeable nominal traffic. See D-1.
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
