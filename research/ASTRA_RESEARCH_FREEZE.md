# ASTRA Research Freeze

**Written** 31 August 2026 · **Status** binding until a Go/No-Go condition in §20 fires.
**Basis** `conference_master_plan.md` rev. 3, `ASTRA_NOVELTY_ROADMAP.md`, `CREDIBILITY_MATRIX.md`,
and code executed 31 August.

> **This document exists to stop the project growing.** Everything not named here is out of scope.

---

## 0 · Filtering result

25 candidates scored on the weighted formula
`0.25N + 0.20S + 0.15F + 0.15E + 0.10V + 0.10R + 0.05I`.

| Rank | Idea | Score | Decision |
|--:|---|--:|---|
| 1 | **Fault Discriminability Profiling** | **8.70** | **KEEP — primary** |
| 2 | **Minimum Detectable Severity** | **7.80** | **KEEP — primary** |
| 3 | Cross-policy invariance | 7.35 | SUPPORTING |
| 4 | **Fault taxonomy by observability** | **7.25** | **KEEP — folded into C2/C3** |
| 5 | Compound-fault interaction | 7.15 | DEFER TO Q1 |
| 6 | Redundancy vs placement decomposition | 7.10 | SUPPORTING |
| 7 | Early-warning lead time | 7.00 | SUPPORTING |
| 8 | Monitor-placement optimisation | 6.85 | DEFER TO Q1 |
| 9 | Counterfactual intervention benefit | 6.80 | SUPPORTING |
| 10 | Shadow-before-wiring methodology | 6.70 | SUPPORTING |
| 11 | Generalisation to ML pipelines | 6.65 | DEFER TO Q1 |
| 12 | Safety-complexity frontier | 6.45 | DROP |
| 13 | Fault vs legitimate shift | 6.25 | DEFER TO Q1 |
| 14 | Per-intervention rate theory | 6.25 | SUPPORTING |
| 15 | Detector self-verification | 6.15 | SUPPORTING |
| 16 | Cross-environment invariance | 5.45 | DEFER TO Q1 |
| 17 | Uncertainty-aware governance | 5.35 | DROP |
| 18 | Adaptive monitor placement | 5.35 | DEFER TO Q1 |
| 19 | Conformal recalibration under shift | 5.25 | DROP |
| 20 | Abstention semantics | 5.15 | DROP |
| 21 | Runtime safety invariants | 5.10 | DROP |
| 22 | Causal attribution chain | 5.00 | DROP |
| 23 | Information-bottleneck framing | 4.80 | DROP |
| 24 | Safety evidence graph | — | **VETO A** — a feature, no scientific question |
| 25 | Automated safety-case generation | — | **VETO A** — documentation, not science |

**Veto B (unfalsifiable) claimed no candidates** — every scored idea has a stated refutation
condition.

---

## 1 · Final Research Question

> **In a learned estimation pipeline, at which processing stage is fault-discriminative information
> lost, and does that location predict which monitor placements can detect which faults?**

One question. Two clauses: a *measurement* and a *prediction*.

---

## 2 · Final Hypotheses

**H6 — Discriminability collapse.** For estimator-absorbed faults, `D_L2 < D_L1 − 0.15`, and
`D_s ≤ D_L2 + 0.05` for every stage s > L2.
*H0:* `D_s` is constant across stages within CI.

**H7 — The absorption point predicts detectability.** A monitor drawing evidence at stage *s*
detects fault *f* if and only if `s < A(f)`.
*H0:* detection is independent of the monitor's stage relative to `A(f)`.
**This is the load-bearing hypothesis.** It converts an observation into a prediction.

**H8 — Minimum Detectable Severity is placement-dependent.** `MDS(f, pre-estimation) < MDS(f,
post-estimation)` for absorbed fault classes.
*H0:* MDS is invariant to placement.

**H3 (retained from rev. 3) — the blind spot persists across architectures.** Ungoverned / Simplex /
CBF / ASTRA under matched conditions.

Four hypotheses. H1, H2, H4, H5 from rev. 3 remain as *supporting* results, not headline claims.

---

## 3 · Primary Contributions — maximum three

**C1 — A measurable phenomenon.** Fault-discriminative information is not gradually degraded through
a learned pipeline; it is lost at one identifiable stage, and no downstream monitor recovers it.
*Status:* **PARTIALLY VALIDATED** — 4/6 faults produce control-identical verdicts, `[M-syn×2]`.
The per-stage curve is **PLANNED**.

**C2 — A quantitative framework.** `D_s`, `R_s`, `A(f)`, `MDS(f,s)` — measurable, reusable, and
computable from records the system already writes. The observability-indexed fault taxonomy is the
interpretation of `A(f)`, not a separate contribution.
*Status:* **PLANNED.**

**C3 — A predictive relationship.** `A(f)` predicts which monitor placements detect which faults
(H7).
*Status:* **PLANNED.** This is what separates a paper from a system report.

**Nothing else enters the abstract.**

---

## 4 · Supporting Contributions

Strengthen C1–C3; never headline.

| # | Contribution | Role |
|--:|---|---|
| S1 | Simplex + CBF comparison (E4/E5) | is the collapse architecture-specific? |
| S2 | Cross-policy invariance | already have n = 2; cheapest generalisation evidence in the project |
| S3 | Redundancy vs placement decomposition | separates fusion effect from placement effect |
| S4 | Counterfactual governance-off/on | quantifies intervention benefit; also the demo |
| S5 | Early-warning lead time | industry-facing framing of `A(f)` |
| S6 | Shadow-before-wiring methodology | the instrument that caught FB2/FB3 |
| S7 | Detector self-verification | licenses the negative results |
| S8 | Per-intervention vs per-tick rates | reporting correction, ~600× |
| S9 | comma2k19 replay | external validity for the stages logs expose |
| S10 | CARLA closed loop `[M-sim]` | consequence, not validity |

---

## 5 · Deferred Q1 Extensions

Compound-fault interaction · monitor-placement optimisation · generalisation to non-AV ML pipelines ·
fault vs legitimate distribution shift · cross-environment invariance · adaptive placement.

Each builds on C1–C3 rather than replacing them. **None is implemented now.**

---

## 6 · Dropped Ideas

Safety evidence graph · automated safety-case generation *(both VETO A)* · safety-complexity frontier
· uncertainty-aware governance · conformal recalibration · abstention semantics · runtime invariants
· causal attribution · information-bottleneck framing.

Dropped for weak novelty, weak falsifiability, or scope cost exceeding contribution.

---

## 7 · Final Novelty Claim

> **Fault-information loss through a processing pipeline is discussed qualitatively across fault
> detection, runtime assurance and anomaly detection, and quantified nowhere. ASTRA measures it per
> stage, locates where it happens, and shows the location predicts which monitors work.**

**Engineering novelty:** none claimed. Nine layers is composition and is reported as methods.
**Scientific novelty:** the per-stage measurement and its predictive use.

---

## 8 · Required Metrics

```
D_s(f,σ) = AUC( T_s | faulted , T_s | matched-clean )       ∈ [0.5, 1.0]
R_s      = (D_s − 0.5) / (D_L1 − 0.5)                        ∈ [0, 1]
A(f)     = min{ s : D_s < 0.60 }                             absorption point
MDS(f,s) = severity at 90% detection, logistic fit            detection floor
```

Stages: L1 `frame_health` · L2a `fast_innovation` · L2b `fast_state` · L3 `trust` · L5 `prediction`
· L6/L7a/L7b `gate_verdicts` · L8 `failsafe`. **All already in `DecisionRecord`.**

---

## 9 · Required Experiments — the minimum set

### E17 — Discriminability profiling **(primary)**
Purpose: measure `D_s` per stage · H6 · IV: pipeline stage · DV: `D_s`, `R_s`, `A(f)` · Controls:
matched-clean run, same seed · Baselines: each stage is a condition · 30 seeds × 13 faults × 3
severities · synthetic · **DeLong test** for paired AUC between adjacent stages, BH across stages,
bootstrap CI 10k · **Falsified if** `D_L2 ≥ D_L1 − 0.05` for absorbed faults.

### E20 — Placement prediction **(primary)**
Purpose: test H7 · IV: monitor stage relative to `A(f)` · DV: binary detection · Controls: same
detector logic, only the input representation moves · **McNemar** paired by seed · odds ratio, exact
CI · **Falsified if** detection is uncorrelated with `s < A(f)` (φ < 0.3).

### E18 — Minimum Detectable Severity **(primary)**
Purpose: H8 · IV: severity × placement · DV: detection rate · logistic fit, CI on the 90% point ·
**Falsified if** MDS intervals overlap across placements.

### E4 — Simplex **(supporting, decides H3)**
As specified in master plan §12. **Falsified if** Simplex detects absorbed faults ASTRA misses.

### E2 — 30-seed baseline **(prerequisite)**
Everything above depends on it.

**Five experiments. No others for the conference version.**

---

## 10 · Required Baselines

Ungoverned · **Simplex** (mandatory) · CBF (conditional GO per master plan §13.1) · ASTRA
gates-only · ASTRA full.

Matched: same plant, policy, faults, severities, injection ticks, seeds, horizon, metrics.
Tuning on a **seed block disjoint from evaluation**, procedure recorded.

---

## 11 · Required Datasets

| Claim | Synthetic | Real replay | CARLA |
|---|:--:|:--:|:--:|
| C1 phenomenon exists | **sufficient** | strengthens | no |
| C2 metric is well-defined | **sufficient** | — | no |
| C3 prediction holds | **sufficient** | strengthens | no |
| Holds on real sensor data | insufficient | **mandatory** | no |
| Consequence of intervention | insufficient | no | **required** `[M-sim]` |

comma2k19 exposes L1, L2a, L2b only — no gate verdicts exist in logs. **A partial profile is still
evidence**, and the limitation is stated in advance.

---

## 12 · Statistical Analysis

Per-endpoint, from master plan §11. For the new experiments:

| Endpoint | Test | Effect size | CI |
|---|---|---|---|
| `D_s` adjacent-stage difference | **DeLong** (paired AUC) | ΔAUC | bootstrap 10k |
| Detection vs `s < A(f)` | **McNemar** | odds ratio, φ | exact |
| MDS | logistic fit | LD90 | profile likelihood |

Unit of analysis: **the run**. Ticks are never observations. BH q = 0.05 per hypothesis family.
Practical thresholds pre-declared: ΔAUC ≥ 0.15; detection Δ ≥ 0.10; MDS separation must exceed CI
width.

---

## 13 · Falsification Criteria

| Contribution | Convinces a skeptic | Falsified by | Shown non-generalisable by |
|---|---|---|---|
| **C1** | `D_s` drops > 0.3 at one stage and stays flat | flat curve within CI | collapse stage differs arbitrarily across policies |
| **C2** | `A(f)` is stable across seeds and policies | `A(f)` varies by > 2 stages across seeds | `A(f)` changes under CARLA/real data |
| **C3** | H7 holds for ≥ 11 of 13 faults | detection uncorrelated with `s < A(f)` | holds for ASTRA only, not Simplex/CBF |

---

## 14 · Reviewer Attack Responses

| Attack | Answer | Experiment |
|---|---|---|
| *"What is not novel — this is just ROC analysis"* | The unit is the **stage**, not the detector. A single ROC cannot express a curve across stages | E17: show `D_s` varying > 0.3 within one pipeline |
| *"This is engineering, not science"* | The metric and H7 are testable predictions; the architecture is explicitly not claimed as novelty | E20 |
| *"Why does this generalise?"* | Profile Simplex and CBF at their own stages | E4, E5 |
| *"Why trust the metric?"* | AUC with DeLong and bootstrap CI; MI reported as secondary where n permits | E17 |
| *"Could this be threshold selection?"* | Severity is defined from corridor-consumption time and channel σ, **not** from ASTRA's thresholds; the threshold-derived sweep is separately labelled **E10-T** | §15.1/15.2 master plan |
| *"Could this be one policy?"* | Already reproduced on two independently trained policies | S2, `[M-syn×2]` |
| *"Could this be the simulator?"* | **The strongest attack. Unanswerable without real data** | E13 — profile L1/L2 on comma2k19 |
| *"Why better than Simplex?"* | Possibly not. E4 decides and the result is reported either way | E4 |
| *"Why not just monitor raw sensors?"* | That *is* the finding. The contribution is showing **where** monitoring stops working and **why** | E17, E20 |

---

## 15 · Conference Scope

One research question (§1) · three primary contributions (§3) · five experiments (§9) · Simplex
mandatory · 30 seeds · comma2k19 partial profile · CARLA **excluded** from the conference version.

Estimated: **~10 working days** beyond the artefact commit, most of it already planned in rev. 3.

---

## 16 · Q1 Extension Scope

Conference version + CARLA closed loop + full comma2k19 + compound-fault interaction + placement
optimisation + cross-pipeline generalisation. **3–4 months. Not started until the conference version
is submitted.**

---

## 17 · Implementation Priority

```
1  commit working artefacts                                    30 s   BLOCKING
2  emit per-stage statistics into DecisionRecord                0.5 d
3  benchmarks/discriminability.py  →  D_s, R_s, A(f)            1 d
4  run on 7 existing arms, n = 1  →  DOES THE CURVE EXIST?      1 h    DECISION POINT
5  30-seed sweep (E2)                                           2 d
6  E17 full profile                                             0.5 d
7  Simplex baseline (E4)                                        3 d
8  E20 placement prediction                                     1 d
9  E18 MDS                                                      0.5 d
10 the figure                                                   0.5 d
```

**Step 4 gates everything.** One hour of work decides whether the paper has a contribution.

---

## 18 · What We Will NOT Build

No new neural network · no LLM · no additional anomaly detector · no additional sensors · no
additional fault *kinds* beyond the 13 already implemented · no new dashboard panels · no evidence
graph · no automated safety case · no adaptive placement · no formal verification · no additional
CARLA scenarios beyond the six faults · **no new architecture layers**.

**If a proposed change does not serve C1, C2 or C3, it is out of scope.**

---

## 19 · Final Research Story

> Runtime safety monitors are placed where engineers find it convenient. ASTRA measures what that
> choice costs. In a learned estimation pipeline, fault-discriminative information collapses at one
> identifiable stage; monitors downstream of it cannot recover the fault regardless of
> sophistication, and the collapse point predicts which placements will work. Measured across 13
> faults, three severities, 30 seeds, two independently trained policies and three governance
> architectures — with the cases where it fails reported alongside the cases where it holds.

**Memorable figure:** discriminability against pipeline stage, one line per fault class, collapsing
at the estimator.
**Memorable metric:** the **absorption point** `A(f)`.

---

## 20 · Go / No-Go Conditions

| Condition | Then |
|---|---|
| Step 4 curve is **flat** at n = 1 | **NO-GO on C1/C3.** Fall back to C2 (four instruments) as the primary contribution. Do not spend a week on seeds |
| Curve exists but `A(f)` unstable across seeds | **NO-GO on C3.** Keep C1 + C2, drop the predictive claim |
| Simplex detects what ASTRA misses (E4) | **Report it.** C1 narrows to ASTRA; the paper becomes a negative result about this architecture |
| comma2k19 fails the §17 go/no-go gate | Narrow the title and abstract to the simulated plant. **Do not substitute CARLA** |
| Artefacts remain uncommitted | **NO-GO on everything.** Nothing below step 1 can run |

---

## THE 70% DELETION TEST

> *If forced to delete 70% of ASTRA, what 30% preserves the strongest contribution?*

**KEEP — load-bearing for the science (~4,000 of 21,631 LOC):**

| Component | Why |
|---|---|
| Fault injector (`training/faults.py`) | without it there is no experiment |
| L1 sensing (369 LOC) | the pre-estimation observation point |
| L2 estimation + fusion + residual monitor (1,408) | **the absorption locus — the object of study** |
| L7b physical gate (326) | the only gate that fires; one downstream measurement point |
| `DecisionRecord` | the per-stage instrumentation that makes profiling possible |
| Closed-loop harness (`training/closed_loop.py`) | runs the experiment |

**DELETE OR DEFER — not load-bearing (~17,000 LOC):**

L9 RCM cold path, knowledge base, safe exploration (1,808) · L5 PINN twin (711) — serves only a gate
that cannot fire · L3 trust index (1,148) — measured today firing on all seven arms *including a
false alarm on the clean control*; it is not a working detector · L8's four-posture machine and
capability withdrawal (810) — two states suffice for the science · FB1–FB4 · the hash-chained audit
schema · the arbitration cold path.

**The uncomfortable conclusion, stated plainly:** roughly **80% of ASTRA is not required for its
strongest scientific contribution.** L6 and L7a are retained *only as measurement points and as
honest negative results*, not because they work.

**This is not an argument for deleting the code.** It is an argument for what the paper is about, and
for refusing every future addition that does not serve C1–C3. The architecture is the apparatus. The
contribution is the measurement.
