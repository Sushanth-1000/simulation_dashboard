# ASTRA — Master Research, IEEE Publication and Industry Demonstration Plan

**Revision 3** · 31 August 2026 · final methodological hardening pass
**Baseline** `3cda553` + artefacts regenerated 31 Aug
**Supersedes** revisions 1–2. Preserves their evidence classification, claim–evidence mapping,
failure-first stance, Simplex/CBF challenges, 30-seed design, fault taxonomy, severity study,
ablation, real-world validation, CARLA, failure analysis, reproducibility, industry track, red team
and publication gate. Everything below is **stricter**, never looser.

> **Rule 0.** No plan can guarantee acceptance. This one optimises for evidence that survives
> attack. Residual risk is enumerated in §25 and is not zero.

> **Rule 1.** Every figure here was produced by **running the code on 31 August 2026**. No marker is
> upgraded without the work being done.

---

## 1 · EXECUTIVE SUMMARY

ASTRA is a nine-layer runtime governance architecture with a working implementation (21,631 src LOC,
3,063 passing tests) and **no external evidence whatsoever** (`[M-ext]` = 0 of 30).

A Q2 referee returned 43/100, Reject-and-Resubmit. Today's audit found the committed reproduction
artefact non-functional, and re-measurement moved every published number while leaving 13 structural
findings intact.

**The publishable contribution is not the architecture.** It is (a) that estimator-absorbed faults
evade every downstream monitor, (b) that upstream placement buys *specificity* rather than latency,
and (c) four instruments that detect silent monitor failure. All three need a prior-art baseline
before they mean anything.

**Six P0 blockers open. IEEE readiness 34/100. Industry demo readiness 58/100.**

---

## 2 · CURRENT ASTRA STATE

### 2.1 Architecture — verified by inspection and by reading a live decision record

| Layer | Module | LOC | Record field | Runtime status |
|---|---|--:|---|---|
| L1 sensing | `l1_sensing` | 369 | `frame_health` | staleness classifier, 50 ms budget |
| L2 estimation | `l2_estimation` | 1,408 | `fast_state` | UKF; **also hosts median fusion and the residual monitor** |
| L3 trust | `l3_trust` | 1,148 | `trust` | trust index + context class |
| L4 proposer *(Core-A)* | `l4_proposer` | 1,326 | `proposal` | PPO + PID-Lagrangian |
| L5 twin | `l5_twin` | 711 | `prediction` | PINN |
| L6 statistical | `l6_statistical_gate` | 652 | `gate_verdicts` | **structurally cannot fire (OD-8)** |
| L7a deterministic | `l7_shield` | 341 | `gate_verdicts` | **0 vetoes / 2,800 ticks** |
| L7b physical | `l7b_physical` | 326 | `gate_verdicts` | 242 vetoes, one reason code |
| L8 fail-safe | `l8_failsafe` | 810 | `failsafe` | 4 postures, 2 counters |
| L9 arbitration | `l9_rcm` | 1,808 | `issued` | sole actuation authority |

**Two documentation errors found in code:** median fusion is in L2, not L1. Health is the *worse of*
L1 staleness and an L2 cross-modality residual, not freshness alone.

### 2.2 Implementation

3,063 passed · **2 failed** · **1 skipped** · 3 xfailed.
Skip = `import-linter` absent → the "twelve contracts" claim is **unverified**.
Failures = guard thresholds baselined to the retired policy.

### 2.3 The reproducibility defect

`var/policy/synthetic.pt`, force-committed 9 Aug as *"the policy the measurements were actually
taken with"*, predates ADR-0030/0032/0033. Measured: **200/200 ticks vetoed, 0.0300 m/s.** All five
checkpoints failed. Regenerated; loop closes. **Still uncommitted.**

### 2.4 Experiments completed

Seven benchmarks, **all at n = 1**. No prior-art baseline. No external dataset. No CARLA.

---

## 3 · CREDIBILITY / EVIDENCE MATRIX

| Claim | Marker | Proves | Does NOT prove | Evidence needed |
|---|---|---|---|---|
| Ten layers wired and exercised | `[M-code]` | software runs | correctness on a road | — |
| 3,063 tests pass | `[M-code]` | code matches its tests | **nothing scientific** | — |
| Twelve import contracts kept | **`[NOT DONE]`** | — | — | install `import-linter` |
| 4/6 faults ≡ control verdicts | **`[M-syn×2]`** | blind spot is structural | real sensors | E13 |
| Health specific, 0 FP | **`[M-syn×2]`** | upstream buys specificity | generality | E2, E13 |
| Trust fires on all 7 incl. control | `[M-syn]` | downstream is indiscriminate | generality | E2 |
| Redundancy 1.1655 → 0.1338 m | **`[M-syn×2]`** | median outvotes one liar | two liars; real sensors | E9-B |
| OD-8 zero overlap | **`[M-syn×2]`** | precondition fails here | fails on real data | E13 |
| L6, L7a issue 0 vetoes | `[M-syn]` | **complementarity unestablished** | that they are useless | E9-B |
| ASTRA worse on 4/7 | `[M-syn]` | governance has a cost | magnitude | E2 |
| Latency p99 9.4–11.2, max 140.4 ms | `[M-syn]` | **observed latency, idle host** | **no WCET, not real-time** | RTOS + WCET tooling |
| 27× on IMU dropout | **`[NOT DONE]` WITHDRAWN** | — | re-measured **< 2×** | remove |
| Gates complementary | **`[NOT DONE]`** | — | ablation refutes | E9-B |
| Any real-world validity | **`[NOT DONE]`** | — | — | E13 |
| **`[M-ext]`** | **0 of 30** | — | — | — |

**New marker `[M-syn×2]`** — held across independent artefact regeneration. Strictly weaker than
`[M-ext]`; strictly stronger than `[M-syn]`. **`[M-sim]`** is reserved for CARLA and is *not* a
synonym for `[M-ext]`.

---

## 4 · RESEARCH QUESTION

> **Does the position at which a runtime monitor draws its evidence, relative to state estimation,
> determine (a) which sensor faults it can detect, (b) its detection latency relative to hazard
> onset, and (c) its false-alarm rate on fault-free operation — and does this hold across
> governance architectures?**

Three measurable quantities. Clause (c) is where the strongest evidence sits and where the current
manuscript is silent. The final clause is what makes it a contribution rather than a system report.

---

## 5 · SCIENTIFIC HYPOTHESES

### H1 — Placement determines detectability
- **H1:** detection rate depends on whether a monitor reads pre- or post-estimation.
- **H0:** detection rate is independent of monitor position.
- **IV:** monitor position (pre/post estimation). **DV:** detection rate over the fault registry.
- **Unit:** the run. **n:** 30 seeds × 13 faults. **Test:** Wilcoxon signed-rank, paired by seed; BH q = 0.05.
- **Refuted if** any post-estimation signal matches the pre-estimation one on every fault class.

### H2 — Placement determines specificity
- **H2:** false-alarm rate on fault-free operation depends on monitor position.
- **H0:** FP rate is independent of position.
- **DV:** FP rate on the clean control per signal. **Current, n = 1:** health 0, trust > 0.
- **Refuted if** the difference does not survive 30 seeds.

### H3 — Estimator-absorbed faults create an observability blind spot that persists across downstream governance architectures

This is the central hypothesis and revision 1 stated it too loosely.

| Element | Definition |
|---|---|
| **H3** | For faults absorbed into a self-consistent state estimate, detection rate by any monitor reading only post-estimation state does not exceed chance, **irrespective of governance architecture** |
| **H0** | At least one post-estimation architecture (Simplex, CBF, ASTRA gates) detects estimator-absorbed faults at a rate significantly above the ungoverned reference |
| **IV** | governance architecture ∈ {Ungoverned, Simplex, CBF, ASTRA-gates-only, ASTRA-full} |
| **DV (primary)** | detection rate on the *absorbed* fault subset, per run |
| **DV (secondary)** | corridor departures; intervention rate; FP rate on control |
| **Confounders** | (i) policy identity — control by using one frozen policy for all arms; (ii) fault severity — stratify, do not pool; (iii) baseline tuning — pre-register each baseline's tuning procedure; (iv) redundancy masking a fault before any monitor sees it — hence the *gates-only* arm |
| **Experimental unit** | one run = one (architecture, fault, severity, seed) tuple. **Never a tick.** |
| **Fault population** | the *absorbed* subset of the §9 registry, defined **a priori** as faults leaving the frame fresh and well-formed: BIAS, DRIFT, STUCK_AT across all three channels |
| **Test** | Friedman across 5 architectures, then Wilcoxon post-hoc vs Ungoverned, BH q = 0.05 |
| **Effect size** | paired rank-biserial correlation; report with CI |
| **Interpretation** | H3 **supported** if no architecture exceeds Ungoverned at q = 0.05 with \|r\| > 0.2. H3 **refuted** if any does — and that refutation is the more valuable result, because it names a monitor that works |

**H3 must be capable of failing.** If Simplex detects what ASTRA misses, the paper reports that.

### 5.4 · Operational definition of an *estimator-absorbed fault*

Vague language here is the attack surface. The definition below is measurable and is fixed before
E9-B runs.

```
raw fault  →  observed sensor reading  →  estimator  →  estimated state  →  downstream monitor
```

A fault is **observable downstream** if the corruption survives estimation in a form a downstream
monitor can separate from nominal. A fault is **estimator-absorbed** if it does not.

**Operational criterion.** For fault *f* at severity *σ*, over 30 paired seeds, let
`D_f` be the distribution of the downstream decision statistic on faulted runs and `D_0` the same
statistic on matched clean runs. The fault is classified **absorbed** when **all three** hold:

| # | Criterion | Threshold |
|--:|---|---|
| 1 | Distributional overlap of `D_f` and `D_0` | **AUC ≤ 0.60** (near-chance separability) |
| 2 | Downstream verdict trace | veto count and reason codes **identical to the matched control** |
| 3 | Ground-truth harm is present | true deviation exceeds the clean run by ≥ 0.05 m at some tick |

Criterion 3 matters: a fault the plant shrugs off is not *absorbed*, it is *harmless*, and conflating
the two would inflate the absorbed set. All three are computed from stored per-run records, not from
judgement.

**Current status at n = 1:** `position_bias`, `position_drift`, `speed_stuck` and `speed_bias`
satisfy criterion 2. Criteria 1 and 3 are **not yet computed** — E9-B computes them. Until then the
absorbed set is *provisional* and is labelled as such wherever it appears.

### H4 — Conformal preconditions fail under deployment shift
H0: live non-conformity scores are exchangeable with the calibration corpus.
DV: overlap fraction. **Current: 0.0%, held across regeneration.** Descriptive; no formal test claimed.

### H5 — Governance carries a cost on fault-free operation *(failure-first)*
H0: governed and ungoverned deviation are equal absent a fault.
**Current: ASTRA worse on 4 of 7 arms at n = 1.** Reported whichever way it resolves.

---

## 6 · RESEARCH GAP

| Work | Approach | Limitation | ASTRA difference | Evidence needed |
|---|---|---|---|---|
| Simplex, L1Simplex | switch on a state predicate | decision module reads the estimate | health bypasses the estimator | **E4** |
| Sandboxing, Neural/black-box Simplex | reachability-certified switching | same dependency | as above | E4 |
| REDriver, runtime verification | STL over vehicle state | fidelity bounded by state fidelity | measures that bound | E9-B |
| Shielding, CBF | certificate over model state | corrupted estimate certifies wrong system | tests that directly | **E5** |
| Conformal OOD (Cai, CODiT) | detect input shift | **assumes** exchangeability | **measures** it on a live loop | E13 |
| FDI (Isermann), van Wyk | residuals after the filter | absorbed faults give in-band residuals | acts on the observation | E9-B |

---

## 7 · NOVELTY ASSESSMENT

### 7.1 · Engineering contribution versus scientific contribution

These are different things and conflating them is risk R1.

| | Engineering contribution | Scientific contribution |
|---|---|---|
| Question answered | *what did you build?* | *what did you learn that others can use?* |
| ASTRA's | nine layers, three gates, one-way channel, hash-chained audit, 21,631 LOC | the relationship between monitor placement, estimator absorption, observability and downstream governance |
| Evidence type | `[M-code]` | `[M-syn×2]`, needing `[M-ext]` |
| Reviewer weight at IEEE | low — integration is expected | high — this is what a paper is for |

**"Nine layers and three gates" is an engineering contribution and is not novelty.** It is reported
in the methods section and claimed as nothing more.

### 7.2 · Is the placement relationship the defensible scientific contribution?

**Conditionally yes — and the condition is not yet met.** The proposition is:

> Information lost or suppressed before a monitor's observation point cannot be recovered by that
> monitor, irrespective of its sophistication; an independent upstream evidence path can supply what
> the downstream path no longer carries.

| Support required | Status |
|---|---|
| The blind spot exists in ASTRA | **supported**, `[M-syn×2]`, 4 of 6 faults |
| Upstream signal is specific where downstream is not | **supported**, `[M-syn×2]` at n = 1 |
| The blind spot is **not ASTRA-specific** | **UNTESTED — E4/E5 decide it** |
| It holds on real data | **UNTESTED — E13** |

**If E4 shows Simplex detects what ASTRA misses, this contribution collapses** and the strongest
defensible alternative becomes C2 — the four instruments for detecting silent monitor failure, which
stands on evidence already in hand and does not depend on the placement claim. That fallback is
named now so it is not invented after an unfavourable result.

### 7.3 · Verdict

**NOVELTY INSUFFICIENT as currently framed.** Nine layers and three gates is composition. It becomes
sufficient only if **both** hold:

1. Reframed on C1–C3 below, and
2. **E4/E5 show established architectures share the blind spot** — making the finding about runtime
   assurance as a field rather than about one system.

**C1 — Placement determines specificity.** Health fires on exactly the fault it can observe, 0 FP;
trust fires on all seven arms including the clean control. *Currently unstated in the manuscript.*

**C2 — Four instruments for silent monitor failure.** Shadow-before-wiring; positive-control
ablation; measuring the conformal precondition; per-intervention vs per-tick reporting. Each found a
real defect.

**C3 — Conformal preconditions fail in deployment, measurably.** OD-8, held across regeneration.

**Rejected:** the architecture (engineering); median fusion (standard); the *latency* claim (refuted
by the project's own Table 4 — trust fires at +6, one tick later, not never).

---

## 8 · CLAIM–EVIDENCE MATRIX with MINIMUM-EVIDENCE RULE

| Claim | Min. experiment | Min. dataset | Min. statistics | Acceptable limitation | Status |
|---|---|---|---|---|---|
| Absorbed faults evade downstream monitors | E2 + E4 | synthetic | 30 seeds, Wilcoxon, effect size | one plant | **supported at n=1** |
| Upstream signal is specific | E2 + E8 | synthetic | 30 seeds, FP rate + CI | one fault type | **supported at n=1** |
| Blind spot persists across architectures | **E4 + E5** | synthetic | Friedman + post-hoc | 3 architectures | **UNTESTED** |
| Redundancy outvotes one liar | E9-B | synthetic | 30 seeds | single-fault only | **supported at n=1** |
| Conformal precondition fails | E13 | **comma2k19** | descriptive + overlap CI | one corpus | **supported (synthetic)** |
| Gates are complementary | E9-B | synthetic | Friedman | — | **UNSUPPORTED — remove** |
| 27× improvement | — | — | — | — | **REMOVE** |
| Governance improves outcomes | E2 | synthetic | 30 seeds | — | **REMOVE — worse on 4/7** |
| Real-time operation | — | — | — | — | **REMOVE** |
| 68-step margin | E2 in **one build** | synthetic | 30 seeds | — | **suggestive — cross-build** |

### 8.1 Claim-downgrade mechanism *(binding)*

When evidence is weaker than expected, exactly one of:

```
STRENGTHEN the experiment   |   DOWNGRADE the claim   |   REMOVE the claim
```

**Rewording to obscure weakness is prohibited.** Any downgrade is recorded in the manifest with the
measurement that forced it.

---

## 9 · FAULT TAXONOMY AND REGISTRY

### 9.1 What the injector actually supports

`training/faults.py` implements **5 kinds × 3 channels**. DROPOUT is frame-level. **13 realisable
faults; the current suite uses 6.** That gap is where "hand-picked faults" lands.

| | POSITION_Y | SPEED | LATERAL_ACCEL |
|---|:--:|:--:|:--:|
| **DROPOUT** | frame-level — **in suite** | — | — |
| **BIAS** | **in suite** | **in suite** | *unused* |
| **DRIFT** | **in suite** | *unused* | *unused* |
| **STUCK_AT** | *unused* | **in suite** | *unused* |
| **NOISE_BURST** | *unused* | *unused* | **in suite** |

**E9-B must run all 13.** Selecting 6 after seeing results is exactly the attack.

### 9.2 · Formal fault registry — 12 required fields

Frozen before E9-B. `docs/fault_registry.yaml` is the machine-readable source; the paper's table is
generated from it, never hand-written.

| Field | Requirement |
|---|---|
| `fault_id` | unique, stable across revisions (e.g. `F-POS-BIAS-M`) |
| `category` | sensor · estimator · model · policy · environment |
| `mechanism` | exact corruption applied to the reading |
| `injection_point` | exact location in the pipeline |
| `parameter` | the varied quantity and its unit |
| `severity` | low / medium / high, from §15.1 — **independently justified** |
| `duration` | ticks, fixed before the run |
| `expected_effect` | stated **before** the experiment; a wrong prediction is itself a result |
| `observability` | which layer can in principle see it |
| `ground_truth` | how a detection is scored correct |
| `applicable_architectures` | Ungoverned / Simplex / CBF / ASTRA — not every fault applies to every arm |
| `rationale` | why this fault belongs in the population |

**Worked example — the entry that must exist for the drift case:**

```yaml
- fault_id: F-POS-DRIFT-M
  category: sensor
  mechanism: linear ramp added to the POSITION_Y reading
  injection_point: sensor boundary, before L1
  parameter: ramp rate, m/s
  severity: medium                # 0.10 m/s -> 17 s to consume the corridor half-width
  duration: 200 ticks
  expected_effect: absorbed by median fusion; no per-tick residual exceeds threshold
  observability: L2 cross-modality residual, once the ramp exceeds RESIDUAL_LIMIT
  ground_truth: injected ramp is known; detection correct if flagged before corridor exit
  applicable_architectures: [ungoverned, simplex, cbf, astra]
  rationale: the canonical self-consistent slow lie; the class the paper claims is hardest
```

### 9.2.1 · Categories retained and rejected

| Category | Status | Reason |
|---|---|---|
| Sensor | **retained, 13 faults** | fully implemented in `training/faults.py` |
| Estimator | **retained as a gap, not runnable** | no injector; the class most likely to separate the gates |
| Model — calibration mismatch | **retained** | observable via OD-8 |
| Model — dynamics / context mismatch | **rejected for now** | no injector; would require a second plant |
| Policy | **retained as a gap** | Core-A is the untrusted component yet no experiment injects a faulty command |
| Environment | **rejected on this plant** | `RAIN_NIGHT` is unreachable by the classifier; CARLA only |

Rejecting a category with a reason is stronger than silently omitting it.

### 9.3 Classes NOT implemented — state as scope, do not pretend

**Estimation faults** (position/heading/velocity error, state inconsistency) — **not injectable
today.** This is the class most likely to separate the gates, since the gates sit downstream of
estimation. Its absence is why L6/L7a never fire and must be declared a limitation.

**Model faults** (dynamics/calibration/context mismatch) — only calibration mismatch is observable,
via OD-8.

**Policy faults** — Core-A is the untrusted component but no experiment injects a faulty *command*.

**Environment** — **`RAIN_NIGHT` is unreachable by the classifier.** `generate_calibration` reports:
*"needs an input the fast state vector does not carry."* One of three context classes can never be
calibrated. Environmental shift is untestable in the current design and CARLA is the only route.

---

## 10 · MASTER EXPERIMENT MATRIX

| ID | Experiment | Hypothesis | Type | Data | Baselines | Seeds | Primary metric | Test |
|---|---|---|---|---|---|--:|---|---|
| E1 | Reproducibility | — | — | synth | — | 1 | artefact check green | — |
| E2 | Multi-seed main | H1,H2,H5 | **confirmatory** | synth | ungoverned | 30 | detection rate | Wilcoxon+BH |
| **E4** | **Simplex** | **H3** | **confirmatory** | synth | Simplex | 30 | detection rate | Friedman+post-hoc |
| E5 | CBF | H3 | confirmatory | synth | CBF | 30 | detection rate | Friedman+post-hoc |
| E7 | Ablation | H1 | confirmatory | synth | 8 variants | 30 | final \|dev\| | Wilcoxon+BH |
| E8 | Placement | H1,H2 | confirmatory | synth | 3 signals × 13 faults | 30 | det/latency/FP | Wilcoxon+BH |
| **E9-A** | **Fault characterisation** | — | **exploratory** | synth | — | 30 | det/miss/FP/FN/latency | **descriptive only** |
| **E9-B** | **Fault population test** | **H3** | **confirmatory, pre-registered** | synth | 4 arch | 30 | detection on absorbed subset | Friedman+BH |
| E10 | Severity sweep | H1 | confirmatory | synth | — | 30 | det. rate vs severity | logistic fit + CI |
| E13 | comma2k19 replay | H4 | confirmatory | **real** | — | n/a | FP rate, overlap | descriptive + CI |
| E14 | CARLA closed loop | H1,H5 | confirmatory | CARLA `[M-sim]` | ungoverned | 10 | corridor departures | Wilcoxon |
| E15 | Failure analysis | H5 | exploratory | all | — | 30 | per-category | descriptive |
| E16 | Compute | — | — | synth | — | 15×2k | p50/p95/p99/max | descriptive |

**E9-A and E9-B are separate runs on separate seed blocks.** E9-A explores; E9-B tests a
pre-registered hypothesis on faults fixed before any result is seen. Findings from E9-A may
**not** be reported as confirmatory.

---

## 11 · STATISTICAL PLAN

### 11.1 What 30 seeds are, and are not

> **30 seeds provide repeated stochastic evaluation under one experimental model. They are not 30
> independent real-world trials.** They quantify variance *within* the model and say nothing about
> variance *across* models, plants or vehicles. Every multi-seed result remains `[M-syn]` or
> `[M-syn×2]` and never `[M-ext]`.

### 11.2 Unit of analysis — fixed before any run

**The experimental unit is one run.** A run = one (architecture, fault, severity, seed) tuple.

**Ticks are never observations.** A 400-tick run is one datum. Control steps within a trajectory are
strongly autocorrelated; treating 2,800 ticks as 2,800 samples is pseudoreplication and inflates
significance by roughly the autocorrelation length. Any statistic computed over ticks-within-a-run
is prohibited and its presence blocks submission.

### 11.3 Per-experiment specification

**No single test is prescribed for every endpoint.** The test is selected from the actual data
structure, declared in the manifest before the run.

| Endpoint | Data type | Unit | Structure | Test | Effect size | CI | Practical threshold |
|---|---|---|---|---|---|---|---|
| Detection (per fault) | binary | run | paired by seed | **McNemar** (2 arms) / **Cochran's Q** (>2) | odds ratio | exact binomial | Δ ≥ 0.10 |
| Detection rate (pooled) | proportion | run | independent within arm | **Wilson interval**, no test if degenerate | risk difference | Wilson | Δ ≥ 0.10 |
| Detection latency | continuous, **right-censored** (non-detections) | run | paired | **log-rank** on time-to-detection; Wilcoxon only if censoring < 10% | hazard ratio | bootstrap 10k | Δ ≥ 5 ticks (0.25 s) |
| Final \|deviation\| | continuous, bounded [0, ∞), skewed | run | paired by seed | **Wilcoxon signed-rank** | rank-biserial | bootstrap 10k | Δ ≥ 0.05 m |
| Veto count | count, overdispersed | run | paired | **negative binomial GLM** with seed as a blocking factor | rate ratio | profile likelihood | ratio ≥ 1.2 |
| FP rate on control | proportion, near-zero | run | independent | **Wilson interval**; no test at zero events | risk difference | Wilson | any non-zero is material |
| Corridor departures | count, mostly zero | run | paired | **exact McNemar** on any-departure | odds ratio | exact | any non-zero is material |
| Cross-architecture (H3) | binary | run | repeated measures, 5 arms | **Cochran's Q** → pairwise McNemar | odds ratio | exact | Δ ≥ 0.10 |

**Rules that hold across all endpoints.**

- Primary endpoint declared before the run; secondaries **never promoted** post hoc.
- Pairing by seed, fault, severity and injection tick. Break pairing only with a recorded reason.
- **Latency is right-censored** — a fault never detected has no latency. Discarding non-detections
  and testing the rest is survivorship bias; use time-to-event methods.
- **Degenerate distributions get intervals, not tests.** L6 and L7a currently produce all-zero
  detection; a p-value there is meaningless. Report Wilson intervals.
- Multiplicity: Benjamini–Hochberg, q = 0.05, **per hypothesis family** (H1, H2, H3 are separate
  families).
- Report median [Q1, Q3]. Never mean ± SD on bounded, skewed or bimodal data.
- **Temporal autocorrelation** within a run is handled by the run-level unit; no within-run statistic
  is computed. Repeated scenarios across seeds are the repeated-measures structure and are modelled
  as such (blocking factor), never pooled as independent.

**A result significant but below the practical threshold is reported as "statistically detectable,
practically negligible."**

---

## 12 · SIMPLEX BASELINE — specified so it cannot be accused of being weakened

| Property | Specification |
|---|---|
| Monitor input | **the same L2 state estimate ASTRA's gates receive** — this is the point |
| Placement | post-estimation, matching the literature |
| Switching condition | lateral deviation predicted to exceed 1.75 m within a 1 s horizon under the current command |
| Fallback | the same proportional controller ASTRA's L9 falls back to — identical, so the comparison isolates the *decision*, not the fallback |
| Stale-data handling | **none** — Simplex as published has no freshness check. Documented as its design, not a handicap |
| Threshold tuning | swept on a **seed block disjoint from evaluation**; tuning procedure recorded in the manifest |
| Information available | full state estimate, plant model, command |
| Information unavailable | raw frames, per-modality health |

**The question this must answer honestly:**

> **Does ASTRA provide measurable value over a substantially simpler safety architecture?**

If Simplex matches ASTRA on all endpoints, **that is the finding and it is reported.**

---

## 13 · CBF BASELINE — applicability first

### 13.1 · Verify-or-remove decision: **CONDITIONAL GO**

A weak baseline is worse than no baseline, so CBF is admitted only against an explicit check.

| Check | Finding | Verdict |
|---|---|---|
| Control-affine plant? | `training/environment.py`: `a_lat = steer × steer_effectiveness` — lateral acceleration is **linear in the steering command** | **pass** |
| Well-posed barrier? | h(y) = 1.75² − y² over the corridor; relative degree 2 (y → ẏ → ÿ ≈ a_lat) | **pass** |
| Discrete-time formulation? | 20 Hz fixed step; discrete-time exponential CBF is standard | **pass** |
| Intervention compatible? | QP filter emits a modified steer; L9 already accepts a substituted command | **pass** |
| Fair tuning achievable? | α must be swept on a **seed block disjoint from evaluation** | **conditional** |
| Assumptions hold under fault? | exact state and known dynamics — **both violated under sensor fault** | **this is what E5 tests** |

**Decision: GO, conditional on the tuning constraint.** If α cannot be tuned on a disjoint block
with the procedure recorded, **CBF = REMOVE** and the reason is documented. Shipping an untuned CBF
would manufacture a favourable comparison, which is risk R5.

| Property | Specification |
|---|---|
| State | (x, y, v, ψ, a_lat) from L2 |
| Barrier | h(x) = 1.75² − y², relative degree 2 → exponential CBF |
| Intervention | QP filter minimising ‖u − u_proposed‖² s.t. ḣ + αh ≥ 0 |
| Fallback | none — CBF modifies rather than replaces, matching its literature |
| Tuning | α swept on a disjoint seed block |
| Assumptions | exact state; known dynamics. **Both violated under sensor fault — that is precisely what E5 tests** |

**Retain.** E5 asks directly whether a certificate computed on a corrupted estimate certifies the
wrong system. That is on-thesis, not fashionable.

---

## 14 · ABLATION — placement, fusion and component separated

Confounding these three is attack R9. They are now separate studies.

### 14.1 Placement ablation — *where* is evidence read?

| Variant | Health source | Question |
|---|---|---|
| No health | — | baseline |
| Health from raw frames (**current**) | pre-estimation | the contribution |
| Health from post-estimation residual | post-estimation | **isolates placement with signal held constant** |

Row 3 is the decisive experiment and does not exist yet. Same detector, same threshold, moved.

### 14.2 Fusion ablation — *how* are signals combined?

| Variant | Fusion | Question |
|---|---|---|
| Single channel | none | baseline |
| Median of 3 | median | current |
| Mean of 3 | mean | is it *median* or merely *redundancy*? |

### 14.3 Component ablation — *what* if a part is removed?

Eight variants over H/R/G6/G7a/G7b as in revision 1, with `ablated_passes` positive control on every
disarmed row. All ×30 seeds.

**One variable at a time** unless the design is explicitly factorial and declared so.

---

## 15 · SEVERITY STUDY

**Severity is defined from physics and consequence, never from ASTRA's thresholds.** Defining
severity around a detector's own limits and then reporting where detection fails is circular.

### 15.1 · Severity ladder — independently justified

| Fault | Low | Medium | High | Basis (independent of ASTRA) |
|---|---|---|---|---|
| Position bias | 0.10 m | 0.50 m | 1.00 m | **Consequence:** fraction of the 1.75 m corridor half-width — 6%, 29%, 57%. A 1 m bias is over half the available margin |
| Dropout | 0.25 s | 0.50 s | 1.00 s | **Physical:** human reaction time is ~0.25 s; 1.0 s exceeds typical AV fallback-activation budgets |
| Drift | 0.02 | 0.10 | 0.30 m/s | **Consequence:** time to consume the corridor half-width at constant ramp — 87 s, 17 s, 5.8 s |
| Noise burst | 3σ | 10σ | 30σ | **Relative perturbation:** multiples of the declared channel σ. 3σ is the conventional outlier boundary |
| Stuck-at | 0.25 s | 0.50 s | 1.00 s | matches dropout, for cross-fault comparability |

**Two values changed from revision 1 and the reason is recorded.** Drift was 0.005/0.02/0.05 m/s,
chosen because 0.005 sits below `RESIDUAL_LIMIT / PATIENCE`. That is a threshold-derived ladder, not
a severity ladder. The replacement is derived from corridor-consumption time.

### 15.2 · Threshold-sensitivity study — separate experiment, honestly labelled

The old values are still worth running, but as a **different question**:

> **E10-T — Threshold sensitivity.** Sweep drift ∈ {0.002, 0.005, 0.01, 0.02, 0.05} m/s against
> `RESIDUAL_LIMIT` ∈ {0.15, 0.30, 0.45} m to locate the detector's floor as a function of its own
> parameter.

This is a **characterisation of ASTRA's detector**, not evidence about fault severity in the world.
It is reported as such and never merged into the severity results.

13 faults × 3 severities × 30 seeds. **Deliverable: detection-vs-severity curves, logistic fit with
CI, and the detection floor located on an independently defined axis.**

---

## 16 · REAL-WORLD DATASET STRATEGY

Datasets are **not** interchangeable evidence.

### 16.1 Automotive real-world evidence

**comma2k19** — the only candidate that maps to ASTRA's actual problem. Logged openpilot commands
**are** the proposals; replay through L1/L2/gates, record verdicts. No retraining.

| Chain | Value |
|---|---|
| Modality | steering angle, speed, wheel speeds, radar, IMU, dual-receiver GNSS |
| Labels | pose from fused sensors. **No fault labels** |
| Temporal | 1-minute segments, continuous |
| ASTRA input | logged command → L4 proposal slot; logged sensors → L1 |
| Ground truth | fused pose |
| **Claim validated** | **FP rate of each monitor on real sensor noise, and whether OD-8 persists against a real corpus** |
| **Limitation** | open-loop; no fault labels, so **no detection rate**; highway only |

#### 16.1.1 · comma2k19 claim-mapping test *(binding)*

| Question | Answer |
|---|---|
| What data are available? | logged openpilot commands, steering angle, speed, wheel speeds, radar, IMU, dual-receiver GNSS, 1-minute segments |
| What ASTRA inputs can be reconstructed? | L1 raw frames (IMU, GNSS, speed) and the L4 proposal slot (the logged command) |
| What ground truth exists? | fused pose from the recorded sensors |
| **What cannot be reconstructed?** | **fault labels** — nobody annotated when a sensor misbehaved; **counterfactual outcomes** — what would have happened had a veto fired; **lateral acceleration** as an independent channel |
| What experiment can be performed? | replay each logged command through L1 → L2 → gates; record verdicts; recompute the non-conformity distribution against the shipped corpus |
| **What claim does it support?** | (i) monitor **false-positive rate on real sensor noise**; (ii) whether the OD-8 distributional separation **persists against a real score distribution** |
| **What claim does it NOT support?** | detection rate (no labels) · any closed-loop consequence · any corridor-departure claim · that ASTRA improves safety · full autonomous-driving validation |

> **It is a replay of logged states and commands, not autonomous-driving validation.** Any sentence
> in the paper implying otherwise is a claim the dataset cannot carry.

### 16.2 Cross-domain supporting evidence

**ALFA** — real flights with ground-truth fault type and time. The only open source of labelled
faults.

> **ALFA is aerial. It may support a claim about *fault-detection method*; it may NOT be used as
> evidence that ASTRA works for road vehicles.** Report as cross-domain supporting evidence, clearly
> labelled.

### 16.3 Rejected

nuScenes, Waymo, KITTI, Argoverse 2, BDD100K, A2D2, PandaSet, DAIR-V2X — **perception** datasets
with box and track labels. ASTRA governs commands, not perception. **Not applicable.** Using one
would be a dataset that does not map to the claimed problem (attack R5).

### 16.4 Preferred alternative if comma2k19 fails go/no-go

Any dataset carrying **logged actuator commands with synchronised proprioceptive sensing**. If none
is accessible, the honest fallback is CARLA `[M-sim]` **explicitly labelled as not external
validation**, and the paper's scope narrows accordingly.

---

## 17 · DATASET GO/NO-GO GATE *(binding, before any commitment)*

```
[ ] Licence verified from the official source
[ ] Download/access verified end to end
[ ] Required modalities present
[ ] Required labels present (or absence documented and the claim narrowed)
[ ] Temporal structure adequate for per-tick replay
[ ] ASTRA input mapping defined and implemented
[ ] Ground truth defined
[ ] Evaluation metric defined
[ ] Leakage risk assessed (§21)
[ ] The specific claim being tested is written down
```

Any critical failure ⇒ **DATASET = NO-GO**, select an alternative, record why.

---

## 18 · EXTERNAL VALIDATION AND CARLA — different questions

| | Real-world replay | CARLA |
|---|---|---|
| Provides | real sensor distributions, real command distributions, **external validity** | controllable causal intervention, repeatability, **closed-loop consequence**, environmental stress |
| Cannot provide | consequence of intervention (open-loop) | external validity — it is still a simulator |
| Marker | **`[M-ext]`** | **`[M-sim]`** |
| Answers | *would ASTRA have vetoed this real command?* | *what happens after a veto?* |

> **`[M-sim]` is not `[M-ext]`.** CARLA results may never be described as real-world validation.
> A paper claiming otherwise is attack R8.

### 18.1 CARLA scenario specification — every scenario declares

`scenario_id · weather · traffic · fault · severity · injection_point · baseline · astra_variant ·
primary_metric · secondary_metrics · seed · causal_question`

Scenarios exist to answer a causal question, not to enlarge a table. Minimum viable set: 6 faults ×
{clear, rain, night} × {sparse, dense} × 10 seeds, with `RAIN_NIGHT` included **specifically**
because it is the context class the classifier cannot reach.

**Prerequisite:** E2, E4, E7 complete. CARLA cannot fix n = 1.

---

## 19 · FAILURE ANALYSIS — registry, not prose

Schema: `failure_id · scenario · fault · severity · architecture · observed_behaviour · root_cause ·
impact · mitigation · **retest_result** · remaining_limitation`

Every failure follows one of exactly three paths, and none of them is deletion:

```
EXPLAINED        root cause identified, reported as a bounded limitation
MITIGATED        fix applied, re-tested, retest_result recorded (pass or fail)
OPEN             neither; reported as an unresolved finding in the paper
```

| id | Observed failure | Root cause | Status |
|---|---|---|---|
| F-1 | ASTRA worse than ungoverned on 4 of 7 arms | unestablished | **open, must survive to the paper** |
| F-2 | L6 issues zero vetoes | OD-8: live scores outside the corpus | root cause known |
| F-3 | L7a issues zero vetoes | unestablished; bounds possibly unreachable | open |
| F-4 | `RAIN_NIGHT` unreachable | fast state lacks the required input | design limitation |
| F-5 | Committed artefact did not drive | artefact 3 ADRs stale | fixed 31 Aug |
| F-6 | Slow drift undetected below the residual floor | `RESIDUAL_LIMIT = 0.45` m vs 0.01 m/tick ramp | mitigation available (§32) |

**Deleting any of these to improve the narrative is prohibited.**

---

## 20 · REPRODUCIBILITY

Windows 11 · Python 3.12 · numpy 2.5.1 · torch 2.13.0 · SB3 2.9.0 · CPU for all synthetic work ·
`uv.lock` pins all three.

**Manifest emitted per result:**
```json
{"experiment_id":"","git_commit":"","dataset":"","dataset_version":"","split":"","seed":0,
 "policy_digest":"","twin_digest":"","config_hash":"","hardware":"","timestamp":"","command":"",
 "primary_endpoint":"","analysis_type":"exploratory|confirmatory"}
```

`config_hash` and `twin_weights_digest` exist. **`git_commit`, `seed` and `policy_digest` do not and
must be added** — without them no figure traces to a build.

**Open:** commit artefacts · install `import-linter` · re-baseline 2 guard tests · disclose all seeds
and thresholds.

---

## 21 · LEAKAGE AUDIT → `leakage_audit.md` *(blocking)*

| Leakage | Risk | Detection | Mitigation | Status |
|---|---|---|---|---|
| Calibration/test contamination | **High** | corpus and eval runs share a generator | disjoint seed blocks | **open** |
| Threshold tuning on evaluation data | **High** | thresholds chosen after seeing results | tune on a disjoint block, freeze | **open** |
| Baseline tuned on test | High | Simplex/CBF sweeps | disjoint block, record procedure | **open** |
| Seed leakage | Medium | policy-training seeds ∈ eval seeds | partition the seed space | **open** |
| Temporal leakage (comma2k19) | High | future frames in calibration | split by drive, preserve order | not started |
| Scenario leakage | Medium | same segment in two splits | split by chunk/route | not started |
| Preprocessing leakage | Low | statistics fitted on all data | fit on train only | not started |
| Hyperparameters from final results | High | post-hoc selection | freeze before E9-B | **open** |

**Unresolved critical leakage blocks submission.**

---

## 22 · INDUSTRY DEMONSTRATION

### 22.1 The deterministic five-minute script

```
1  Normal autonomous operation, seed shown on screen
2  Operator injects a fault from the menu
3  Fault becomes observable: raw frame goes stale
4  ASTRA detects: health → DEGRADED at +5 ticks
5  Trust and posture change: NOMINAL → DEGRADED → LIMP
6  Governance evaluates the proposed command
7  Veto or fallback, with the reason code displayed
8  Vehicle stays in the corridor
9  Audit record shown: timestamp, config hash, twin digest, chain hash
10 Reset — same seed, same result
```

**The contrast shot is the demo:** same fault, same seed, governance off → vehicle departs the lane.

### 22.2 Dashboard

| Panel | Content | Source |
|---|---|---|
| Vehicle | position, speed, heading, corridor | `fast_state` |
| Sensors | per-modality health, staleness | `frame_health` |
| Monitoring | trust index, context class, OOD counter | `trust`, `failsafe` |
| Governance | proposed vs issued, per-gate verdict, **reason code** | `proposal`, `gate_verdicts`, `issued` |
| Posture | NOMINAL → DEGRADED → LIMP → HALT | `failsafe.state` |
| Evidence | timestamp, config hash, twin digest, chain hash | audit record |
| Controls | inject dropout/bias/drift/noise/OOD + severity | injector |

### 22.3 Latency — reported honestly

Report **observed latency**: p50, p95, p99, maximum, with host and load stated.

> **Observed latency is not a worst-case execution-time guarantee.** Measured max 140.4 ms against a
> 50 ms period on an idle host. The dashboard must display "observed, idle host" beside any timing
> figure. Claiming determinism from these numbers is attack R12.

### 22.4 Value proposition

**Defensible:** runtime monitoring at the actuation boundary · per-decision audit with provenance ·
graduated degradation · fault injection as a test harness · evidence artefacts for a safety case.

**Prohibited:** regulatory compliance · ISO 26262 / SOTIF conformance · production readiness ·
real-time guarantees · any real-vehicle result.

**State plainly: research prototype, evaluated in simulation.**

---

## 23 · INDUSTRY READINESS

| Dimension | /10 | Note |
|---|--:|---|
| Technical credibility | 7 | real system, real audit trail |
| Demo quality | **2** | no scripted run |
| Reproducibility | 5 | fixed today, uncommitted |
| Latency | **3** | 140.4 ms observed max |
| Visualization | 5 | dashboard exists |
| Explainability | 8 | reason codes, provenance |
| Auditability | **9** | hash-chained, schema v10 |
| Scenario control | 6 | injector exists |
| Fault injection | 7 | 6 of 13 faults wired |
| Integration | 4 | Python prototype |
| Documentation | 8 | A-Z + REPRODUCE.md |
| Installation | 5 | needs pytest/hypothesis/import-linter beyond extras |

### INDUSTRY DEMO READINESS: **58 / 100**

### 23.1 Industry gate *(blocking for demo release)*
```
[ ] One-command startup          [ ] Deterministic scenario
[ ] Fault injection reliable     [ ] Dashboard accurate
[ ] Decision provenance visible  [ ] Fallback demonstrated
[ ] Logs generated               [ ] Latency measured and labelled "observed"
[ ] Documentation complete       [ ] Repeatable from a clean environment
```

---

## 24 · REVIEWER ATTACK MATRIX

| Attack | Vulnerability | Evidence needed | Experiment | Status |
|---|---|---|---|---|
| "Why not Simplex?" | **no baseline** | detection rate, both arch | E4 | **OPEN** |
| "Why not CBF?" | no baseline | as above | E5 | **OPEN** |
| "What's actually novel?" | disclaimed in §1.1 | C1–C3 + E4 | E4 | **OPEN** |
| "Why trust the synthetic plant?" | self-referential | real-data replay | E13 | **OPEN** |
| "Where is real-world validation?" | `[M-ext]` 0/30 | comma2k19 | E13 | **OPEN** |
| "How were faults selected?" | 6 of 13 used | full registry, pre-registered | E9-B | **OPEN** |
| "Are seeds independent?" | yes within model | §11.1 statement | — | mitigated by wording |
| "Are ticks pseudoreplicated?" | **real risk** | run-level unit fixed | §11.2 | mitigated |
| "Why nine layers?" | no per-layer ablation | component ablation | E7/§14.3 | partial |
| "What happens when ASTRA fails?" | 4/7 worse | failure registry | E15/§19 | partial |
| "Does conformal generalise?" | OD-8 says no | live vs nominal coverage | E13 | partial |
| "Why CARLA?" | could be seen as substitute | `[M-sim]` ≠ `[M-ext]` | §18 | mitigated |
| "Can this run in real time?" | max 140.4 ms | observed-only framing | E16/§22.3 | mitigated |
| "Can anyone reproduce it?" | artefacts uncommitted | commit + manifest | §20 | **OPEN** |

**Eight open. Each is a rejection on its own.**

---

## 25 · PUBLICATION RISK MATRIX

| ID | Risk | Severity | Prob. | Detection | Mitigation | Gate |
|---|---|---|--:|---|---|---|
| R1 | Novelty is architectural composition | Fatal | 85% | reviewer 1 | reframe C1–C3 + E4 | **P0** |
| R2 | Synthetic evidence dominates | Fatal | 95% | `[M-ext]` 0/30 | E13 | **P0** |
| R3 | Fault population hand-picked | Major | 70% | 6 of 13 used | E9-B pre-registered | **P0** |
| R4 | Simplex baseline too weak | Major | 40% | tuning record | §12 spec, disjoint tuning | P1 |
| R5 | Dataset doesn't map to the problem | Major | 30% | §16 chain | comma2k19 only; perception rejected | P1 |
| R6 | Seeds read as real-world trials | Major | 50% | wording | §11.1 statement | P1 |
| R7 | Conformal guarantee overstated | Major | 40% | coverage claim | nominal vs live separated | P1 |
| R8 | CARLA presented as real-world | Major | 40% | marker misuse | `[M-sim]` distinct | P1 |
| R9 | Ablation confounds placement/fusion | Major | 60% | design | §14 split into three | **P0** |
| R10 | Significance without practical significance | Important | 50% | reporting | thresholds pre-declared §11.3 | P2 |
| R13 | CBF baseline unfair or untuned | Major | 35% | tuning record | §13.1 conditional GO; remove if tuning is not disjoint | P1 |
| R14 | Production readiness overstated | Major | 30% | §22.4 wording | prohibited-claims list; "research prototype" stated | P1 |
| R15 | Latency claims exceed evidence | Major | 40% | max 140.4 ms vs 50 ms | observed-only framing, host and load stated | P1 |
| R11 | Negative results omitted | Fatal | 20% | failure registry | §19 binding | **P0** |
| R12 | Real-time / production claims | Major | 40% | §22.3 | observed-only | P1 |

---

## 26 · EXECUTION DEPENDENCIES

```
                        REPRODUCIBILITY (commit artefacts, import-linter, re-baseline)
                                    │
                ┌───────────────────┴───────────────────┐
                ↓                                       ↓
      30-SEED BASELINE (E2)                  DATASET ACQUISITION (comma2k19)
                │                                       │
                ↓                                       ↓
      SIMPLEX / CBF (E4, E5)                  DATASET GO/NO-GO (§17)
                │                                       │
                └───────────────┬───────────────────────┘
                                ↓
                    FAULT POPULATION (E9-A → E9-B)
                                ↓
              H3 / OBSERVABILITY TEST (cross-architecture)
                                ↓
                        SEVERITY STUDY (E10, E10-T)
                                ↓
                   ABLATION (E7, §14.1/.2/.3)
                                ↓
                    EXTERNAL VALIDATION (E13)
                                ↓
                          CARLA (E14)  [M-sim]
                                ↓
                     FAILURE ANALYSIS (E15)
                                ↓
                        STATISTICAL LOCK
                                ↓
                           CLAIM LOCK
                                ↓
                        PAPER RED TEAM
                                ↓
                          SUBMISSION
```

Dataset acquisition runs **in parallel** with E2/E4/E5. Do not serialise it.

---

## 27 · STATISTICAL LOCK

`STATISTICAL LOCK = TRUE` only when **all** hold:

```
[ ] All confirmatory experiments complete
[ ] Raw results frozen and hashed
[ ] Analysis scripts frozen and committed
[ ] Primary endpoints fixed before the runs (manifest proves it)
[ ] No test-set tuning remains
[ ] Analysis reproducible from raw results by one command
[ ] Exploratory (E9-A) and confirmatory (E9-B) outputs stored separately
```

**After lock, no result may be removed to improve the narrative.** Removal requires a documented
methodological defect, recorded with the defect.

---

## 28 · CLAIM LOCK

After statistical lock, every claim is assigned exactly one of:

```
SUPPORTED  |  PARTIALLY SUPPORTED  |  UNSUPPORTED  |  REMOVE
```

**Only SUPPORTED and PARTIALLY SUPPORTED may appear in the paper**, and PARTIALLY SUPPORTED must
carry its limitation in the same sentence.

---

## 29 · IEEE SUBMISSION GATE

Blocked if **any** remain:

```
[ ] any P0 unresolved                     [ ] critical reproducibility failure
[ ] critical leakage unresolved           [ ] unsupported central novelty claim
[ ] missing credible baseline             [ ] missing primary experiment
[ ] invalid statistical analysis          [ ] pseudoreplication present
[ ] unjustified fault population          [ ] critical dataset mismatch
[ ] overstated safety guarantee           [ ] overstated conformal guarantee
[ ] overstated real-time claim            [ ] fabricated or inferred evidence
[ ] statistical lock not achieved         [ ] claim lock not achieved
```

### 29.1 · The external-validity rule *(binding)*

> **Any claim of external validity requires real-world evidence. Synthetic results plus CARLA do not
> constitute real-world validation and may not be combined to imply it.**

| If the paper claims… | Then it requires… |
|---|---|
| behaviour on real sensor data | **E13 (comma2k19). Mandatory. No substitute.** |
| closed-loop consequence of a veto | E14 (CARLA), marked `[M-sim]` |
| behaviour on this plant only | E2–E10, scope stated in the title and abstract |

**CARLA is `strongly recommended` and may be deferred for a conference under genuine schedule
pressure. Real-world evidence is not optional when a real-world claim is made.** A paper without
E13 must narrow its title, abstract and conclusion to the simulated plant.

**Currently blocked on: P0 ×6, leakage ×5 open, no baseline, no external evidence.**

---

## 30 · INDUSTRY DEMO GATE

Blocked if:
```
[ ] fault injection unreliable      [ ] dashboard misleading
[ ] latency unmeasured or unlabelled[ ] logs incomplete
[ ] scenario non-reproducible       [ ] fallback not demonstrated
[ ] installation undocumented       [ ] system state cannot be explained
```

---

## 31 · FINAL SCORECARD

| Dimension | Current | Target | Blocking? | Required action |
|---|--:|--:|:--:|---|
| Scientific novelty | 3 | 7 | **YES** | reframe C1–C3, run E4 |
| Research question | 6 | 8 | no | §4 adopted |
| **Hypotheses** | **5** | 8 | **YES** | H3 needs the cross-architecture run; absorbed-set criteria uncomputed |
| Methodology | 7 | 8 | no | §14 split |
| **Fault population** | **3** | 8 | **YES** | E9-B, all 13 faults |
| Statistics | 2 | 8 | **YES** | E2, §11 |
| Baselines | 2 | 8 | **YES** | E4, E5 |
| Ablation | 7 | 9 | no | §14.1 placement row |
| **Real-world validation** | **0** | 6 | **YES** | E13 |
| Generalization | 0 | 5 | **YES** | E13 |
| CARLA | 1 | 6 | no | E14 `[M-sim]` |
| Failure analysis | 5 | 8 | no | §19 registry |
| Reproducibility | 4 | 9 | **YES** | commit + manifest |
| **Leakage control** | **2** | 8 | **YES** | 5 of 8 vectors open; `leakage_audit.md` not written |
| Paper | 7 | 8 | no | re-measure |
| **IEEE readiness** | **34/100** | 70 | — | above |
| **Industry readiness** | **58/100** | 75 | — | §22.1 script |

---

## 31.1 · SELF-AUDIT

Performed against `CREDIBILITY_MATRIX.md`, `conference.md` and the repository state.

**Scientific validity.** H3 is falsifiable — its H0 names a specific outcome (any architecture
exceeding the ungoverned reference) that the design can produce. E9-B is confirmatory with a frozen
fault set and a separate seed block from E9-A. The fault population is the full 13-cell injector
grid, not a selection. Severity is now derived from corridor-consumption time and multiples of
channel σ, with the threshold-derived ladder relabelled as E10-T. Statistics are selected per
endpoint, including censoring-aware methods for latency.
**Residual weakness:** the absorbed-fault criteria in §5.4 are *provisional* — criteria 1 and 3 have
not been computed on any run.

**External validity.** comma2k19 answers FP rate on real sensor noise and whether OD-8 persists —
and nothing else, because it has no fault labels. §16.1.1 states what it cannot support. CARLA is
`[M-sim]` throughout and §29.1 forbids combining it with synthetic results to imply real-world
validation.
**Residual weakness:** no dataset has passed the §17 go/no-go gate. Zero external evidence exists.

**Fairness.** Simplex receives the same estimate, the same fallback and disjoint-block tuning, and
§12 commits to reporting a null result. CBF is a conditional GO with an explicit removal criterion.
**Residual weakness:** neither baseline is implemented, so fairness is asserted, not demonstrated.

**Reproducibility.** Environment pinned; manifest schema defined.
**Residual weakness:** the working artefacts remain **uncommitted**; `git_commit`, `seed` and
`policy_digest` are absent from the record; `import-linter` is not installed, so the contracts claim
is unverified; two guard tests still fail.

**Publication.** Every claim in §8 carries a minimum-evidence rule and a status. Four claims are
marked REMOVE. All six failures in §19 are retained.
**Residual weakness:** the central novelty claim is unsupported until E4 runs.

**Industry.** The demo is deterministic by construction (fixed seed, scripted steps) and latency is
labelled observed-only.
**Residual weakness:** the script is specified but not implemented; nothing has been run end to end
from a clean environment.

---

## 32 · EXACT NEXT ACTION

> **Freeze the repository at a reproducible state, then execute the 30-seed baseline under a locked
> configuration.**

Concretely, in order, today:

```bash
# 1 — freeze reproducibility (30 seconds; nothing else works without it)
git add -f var/policy/synthetic.pt var/twin/synthetic.pt var/calibration/synthetic.json
git commit -m "Regenerate artefacts: the 9 Aug policy no longer drove against post-ADR-0033 code"

# 2 — close the unverified contract claim
.venv/Scripts/pip install import-linter && .venv/Scripts/python -m pytest tests/architecture -q

# 3 — re-baseline the two guard tests against the new policy

# 4 — then, and only then, the 30-seed sweep
for s in $(seq 1 30); do .venv/Scripts/python -m benchmarks.fault_study --seed $s --output var/seeds/$s; done
```

**Highest-upside side experiment, two hours, independent of the above:** lower `RESIDUAL_LIMIT` from
0.45 m in `training/redundant.py` and re-run the fault study. The drift ramps 0.01 m/tick and needs
45 ticks to cross the current limit; E-109 records this monitor separating a drifting channel at
5.3× and *identifying* it. If health starts catching BIAS and DRIFT, detection goes from 1 of 6
faults to 3 of 6 — and F-6 closes.
