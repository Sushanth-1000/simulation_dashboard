# ASTRA Novelty Roadmap

**Written** 31 August 2026 · grounded in code executed today, not in documentation.
**Companion to** `conference_master_plan.md` rev. 3.

> **Constraint applied throughout.** Ideas are rejected if generic, buzzword-driven, already
> standard, unfalsifiable, or impressive-but-incremental. The objective is the **strongest
> scientific contribution per unit of implementation effort** — not the biggest system.

---

## 1 · Current Contribution Assessment

| Item | Status | Evidence |
|---|---|---|
| **A. Scientific problem** | An unverifiable learned controller issues commands; runtime monitors must judge them | — |
| **B. Research question** | Does monitor position relative to state estimation determine what it can detect? | rev. 3 §4 |
| **C. Hypotheses** | H1 detectability · H2 specificity · H3 cross-architecture · H4 conformal · H5 governance cost | rev. 3 §5 |
| **D. Architecture** | 10 modules, 21,631 LOC, all wired, all populate a per-tick record | **IMPLEMENTED**, verified 31 Aug |
| **E. Claimed contributions** | placement→specificity · four instruments · conformal precondition failure | — |
| **F. Strongest evidence** | 4/6 faults produce verdicts identical to control, **reproduced on a second independently trained policy** | **EMPIRICALLY VALIDATED** `[M-syn×2]` |
| **G. Weakest evidence** | Anything about real vehicles, real sensors, or other architectures | **UNSUPPORTED**, `[M-ext]` = 0/30 |
| **H. Current novelty** | Low. Authors disclaim new mechanism; nine layers is composition | **UNSUPPORTED** as novelty |
| **I. Publication risks** | novelty · no baseline · n=1 · synthetic only | 6 open P0 |
| **J. Industry value** | Auditability 9/10, explainability 8/10 — genuinely strong | **IMPLEMENTED** |

**Status honesty:** IMPLEMENTED ≫ EMPIRICALLY VALIDATED ≫ everything else. The gap between what is
built and what is demonstrated is the whole problem.

---

## 2 · Current Novelty Gaps

**Genuinely different today:** the *placement* framing (health computed before the estimator, every
gate after it) and four measurement instruments that each caught a real defect.

**Already well known — claim none of it:** nine-layer decomposition · three-gate voting · median
fusion of dissimilar channels · UKF state estimation · PPO with a Lagrangian constraint · PINN
surrogate · conformal OOD gating · hash-chained audit logs · graduated degradation. Every one is
standard.

**The uncomfortable truth:** strip the standard components and what remains is *an observation about
where a signal is computed*, supported by one plant and six faults. That is a workshop paper, not an
IEEE conference paper — **unless it becomes a measurable phenomenon rather than an anecdote.**

---

## 3 · Literature / Research Gap Categories

| Field | ASTRA's position | Gap that remains open |
|---|---|---|
| Runtime assurance (Simplex family) | same switching pattern, different evidence path | **nobody measures where fault information dies** |
| Fault detection / FDI | van Wyk observes filters absorb faults | observed qualitatively; **never quantified per stage** |
| Observability (control theory) | classical observability is about *state*, not *fault* | **fault observability through a learned pipeline is unformalised** |
| Conformal prediction | exchangeability assumed | ASTRA measures it — real gap, narrow |
| CBF / shielding | certificate over model state | **behaviour under corrupted state is under-studied** |
| Anomaly detection | detectors placed by convention | **placement is never treated as a design variable** |
| Safety cases | evidence assembled manually | mechanised evidence is documentation, not science |

**The one real gap:** *fault information loss through a processing pipeline is discussed
qualitatively everywhere and measured nowhere.*

---

## 4 · Candidate Research Directions (25)

| # | Idea | One-line scientific question |
|--:|---|---|
| 1 | **Fault Discriminability Profiling** | How much fault information survives each pipeline stage? |
| 2 | Monitor-placement optimisation | Can the best monitoring point be computed rather than chosen? |
| 3 | Adaptive monitor placement | Should the monitored representation switch at runtime? |
| 4 | Minimum Detectable Severity | What is the smallest fault a given placement can detect? |
| 5 | Compound-fault interaction | Is Effect(A+B) ≠ Effect(A)+Effect(B)? |
| 6 | Early-warning lead time | How long before a safety violation can degradation be seen? |
| 7 | Safety-complexity frontier | Safety benefit per unit of architectural complexity |
| 8 | Cross-policy invariance | Do findings persist across independently trained policies? |
| 9 | Cross-environment invariance | Do they persist synthetic → CARLA → real replay? |
| 10 | Fault vs legitimate shift | Can a fault be distinguished from weather/traffic change? |
| 11 | Uncertainty-aware governance | Should intervention depend on estimator covariance? |
| 12 | Counterfactual intervention benefit | What would have happened without the veto? |
| 13 | Causal attribution chain | fault → estimator → monitor → intervention → outcome |
| 14 | Runtime safety invariants | Can trust bounds / state consistency be empirically verified? |
| 15 | Estimator-induced information bottleneck | Is the filter an information bottleneck in Tishby's sense? |
| 16 | Redundancy vs placement decomposition | Is the benefit fusion or position? |
| 17 | Detector self-verification | Instruments that prove a null is real, not a broken detector |
| 18 | Per-intervention vs per-tick rate theory | Why do the two differ by ~600×? |
| 19 | Shadow-before-wiring as methodology | Formalise the discipline that caught FB2/FB3 |
| 20 | Gate abstention semantics | ABSTAIN vs PASS as an epistemic distinction |
| 21 | Safety evidence graph | Machine-readable claim→evidence→limitation |
| 22 | Automated safety-case generation | Evidence → GSN argument |
| 23 | Generalisation to any ML pipeline | Is this AV-specific or a property of learned pipelines? |
| 24 | Conformal recalibration under shift | Live requantilisation without self-disarming |
| 25 | Fault taxonomy by observability | Classify faults by *where they die*, not by mechanism |

---

## 5 · Ranked Novelty Matrix

Scored 1–10. Feasibility is *with what already exists in this repository*.

| ID | Idea | Novelty | Impact | Feasib. | Cost | Theory | Industry | Conf. | Q1 |
|--:|---|--:|--:|--:|--:|--:|--:|--:|--:|
| **1** | **Fault Discriminability Profiling** | **9** | **9** | **9** | **2** | **8** | 7 | **9** | **8** |
| 4 | Minimum Detectable Severity | 7 | 8 | 8 | 3 | 6 | 8 | 8 | 7 |
| 2 | Monitor-placement optimisation | 8 | 8 | 5 | 7 | 8 | 7 | 7 | 8 |
| 25 | Fault taxonomy by observability | 7 | 7 | 9 | 2 | 6 | 6 | 7 | 6 |
| 5 | Compound-fault interaction | 7 | 7 | 7 | 4 | 6 | 7 | 7 | 7 |
| 23 | Generalisation to ML pipelines | 8 | 9 | 4 | 8 | 8 | 5 | 6 | 9 |
| 6 | Early-warning lead time | 5 | 8 | 8 | 3 | 4 | 9 | 6 | 5 |
| 7 | Safety-complexity frontier | 6 | 7 | 6 | 5 | 5 | 8 | 7 | 6 |
| 8 | Cross-policy invariance | 5 | 7 | **10** | **1** | 3 | 6 | 6 | 6 |
| 16 | Redundancy vs placement | 6 | 7 | 9 | 2 | 5 | 5 | 7 | 6 |
| 12 | Counterfactual benefit | 4 | 7 | 9 | 2 | 4 | 9 | 6 | 5 |
| 19 | Shadow-before-wiring methodology | 6 | 6 | 9 | 1 | 4 | 8 | 6 | 6 |
| 10 | Fault vs legitimate shift | 6 | 8 | 4 | 7 | 6 | 8 | 6 | 7 |
| 17 | Detector self-verification | 5 | 5 | 9 | 1 | 4 | 5 | 5 | 4 |
| 18 | Per-intervention rate theory | 5 | 6 | 8 | 2 | 5 | 8 | 5 | 5 |
| 11 | Uncertainty-aware governance | 4 | 6 | 6 | 5 | 5 | 7 | 5 | 5 |
| 3 | Adaptive placement | 7 | 6 | 3 | 9 | 6 | 5 | 5 | 6 |
| 15 | Information bottleneck framing | 6 | 5 | 4 | 7 | 8 | 3 | 4 | 6 |
| 13 | Causal attribution | 5 | 6 | 4 | 7 | 7 | 6 | 5 | 6 |
| 24 | Conformal recalibration | 5 | 6 | 5 | 6 | 6 | 5 | 5 | 6 |
| 9 | Cross-environment invariance | 4 | 8 | 3 | 9 | 3 | 7 | 6 | 7 |
| 14 | Runtime invariants | 4 | 5 | 6 | 5 | 6 | 6 | 4 | 5 |
| 20 | Abstention semantics | 4 | 4 | 8 | 2 | 5 | 4 | 4 | 4 |
| 21 | Safety evidence graph | 3 | 4 | 7 | 4 | 2 | 7 | 3 | 3 |
| 22 | Automated safety case | 2 | 3 | 5 | 7 | 2 | 6 | 2 | 2 |

**Rejected outright:** 21, 22 (documentation, not science — a reviewer will say so); 3, 15 (scope
explosion for marginal return); 9 (blocked on CARLA, not a *novelty* contribution).

---

## 6 · Top 10

1 · 4 · 25 · 2 · 5 · 23 · 8 · 16 · 6 · 19

**Note the pattern:** the highest-scoring ideas are all *measurement* ideas, not *mechanism* ideas.
That is the correct read of this project. ASTRA's asset is an instrumented pipeline, not a novel
algorithm.

---

## 7 · Top 5, in detail

### 7.1 · Idea 1 — Fault Discriminability Profiling **(the strongest)**

**Novel because** fault-information loss through a processing pipeline is discussed qualitatively
across FDI, runtime assurance and anomaly detection, and quantified nowhere. Van Wyk *et al.* observe
that a filter absorbs faults; nobody measures *how much*, *where*, or *how fast*.

**Enabled by what exists:** `DecisionRecord` already carries every stage per tick — `frame_health`
(L1), `fast_innovation` (pre-settling residual), `fast_state` (L2), `trust` (L3), `proposal` (L4),
`prediction` (L5), `safety_verdict` (L6/7), `failsafe` (L8), `issued` (L9). **The instrumentation is
already built.**

**New component required:** an analysis script. That is all.

**Research question:** *How much of a fault's discriminative signal survives each stage of a learned
perception-estimation-governance pipeline, and where is it lost?*

**Hypothesis.** For estimator-absorbed faults, discriminability falls sharply at the estimator and
does not recover downstream. **H0:** discriminability is approximately constant across stages.

**Metric — Stage Discriminability.** For fault *f* at severity *σ*, stage *s*:

```
D_s(f,σ) = AUC( T_s | faulted , T_s | matched-clean )        D ∈ [0.5, 1.0]
```

where `T_s` is the stage-*s* decision statistic, paired by seed. Secondary: mutual information
`I(fault ; T_s)` where sample size permits. Derived quantities:

```
Retention        R_s = (D_s − 0.5) / (D_L1 − 0.5)
Absorption point A(f) = min{ s : D_s < 0.60 }
```

`A(f)` operationalises the "estimator-absorbed" definition in master-plan §5.4, so the two documents
share one criterion.

**Experiment.** All 13 registry faults × 3 severities × 30 seeds × 9 stages. Compute `D_s` per
(fault, severity, stage). Repeat for Simplex and CBF where a comparable statistic exists.

**Dataset:** synthetic first; comma2k19 replay for the stages reconstructable from logs.
**Baselines:** the pipeline itself is the comparison — each stage is a condition.
**Metrics:** `D_s`, `R_s`, `A(f)`, with bootstrap CIs.
**Statistics:** DeLong test for paired AUC differences between adjacent stages; BH across stages.

**Expected positive:** a *discriminability collapse curve* — high at L1, collapsing at L2, flat
thereafter, with the collapse stage differing by fault class.
**Expected negative:** discriminability roughly flat, meaning the estimator is not the bottleneck and
ASTRA's central story is wrong.
**Falsified if** `D_L2 ≈ D_L1` for absorbed faults, or if a downstream stage shows `D_s > D_L1`.

**Difficulty:** low — analysis over records the system already writes.
**Publication value:** high. **Industry value:** high; it tells an engineer *where to instrument*.

---

### 7.2 · Idea 4 — Minimum Detectable Severity (MDS)

**Novel because** detection thresholds are reported as accuracies, not as a *severity floor per
placement*. **Question:** for each fault class and monitor placement, what is the smallest severity
detected at ≥ 90% across seeds?
**Metric:** `MDS(f, placement)` from a logistic fit of detection on severity, with a CI.
**Falsified if** MDS is placement-invariant.
**Cost:** the severity sweep is already planned; MDS is a fit over it. **Difficulty: low.**

---

### 7.3 · Idea 25 — Fault taxonomy by observability, not mechanism

**Novel because** every taxonomy in the literature classifies faults by *how they corrupt* (bias,
drift, dropout). ASTRA can classify by **where they become unobservable** — a taxonomy indexed by
`A(f)` from Idea 1.
**Why it matters:** mechanism-based taxonomies do not predict detectability; an observability-based
one might. **Falsified if** faults with the same absorption point behave differently downstream.
**Cost:** free once Idea 1 exists. It *is* the interpretation of Idea 1.

---

### 7.4 · Idea 2 — Monitor-placement optimisation

**Novel because** placement is universally a design choice, never an optimisation.
**Question:** given `D_s` profiles, can the optimal placement be *computed*?
**Method:** choose *s* maximising `D_s` subject to a latency budget — a small constrained
optimisation over the measured profile.
**Risk:** with 9 stages this is argmax over 9 values, which a reviewer may call trivial. It only
becomes a contribution if it generalises to pipelines with many candidate points.
**Difficulty: medium. Defer to the journal version.**

---

### 7.5 · Idea 5 — Compound-fault interaction

**Novel because** the entire fault suite is single-fault; real degradation is rarely single-cause.
**Question:** is `Effect(A+B) ≠ Effect(A) + Effect(B)`?
**Design:** 2-factor factorial over the most informative fault pairs, 30 seeds, interaction term
from a two-way model on run-level outcomes.
**Enabled by:** `FaultSpec` composition — the injector already accepts a tuple of specs.
**Falsified if** all interactions are additive within CI.
**Difficulty: low-medium.** Strong candidate for the conference version.

---

## 8 · Strongest Single Contribution

> ### **Fault Discriminability Profiling — measuring where fault information dies in a learned pipeline.**

**Why it beats the others.**

| Criterion | Why Idea 1 wins |
|---|---|
| Novelty | The phenomenon is universally *asserted* and never *measured*. Idea 4 is a special case of it; 25 is its interpretation; 2 depends on it |
| Measurable contribution | Produces a curve, a metric, and an absorption point — not an anecdote |
| Feasibility | **The instrumentation already exists.** `DecisionRecord` carries all nine stages per tick |
| Experimental validation | Falsifiable by a flat curve; strengthened by 30 seeds and two architectures |
| Reviewer story | *"They measured where fault information is lost, and showed the estimator is the bottleneck"* — one sentence, one figure |
| Industry relevance | Answers *where should I put my monitor?* with a number |

**Decisive advantage:** it converts ASTRA's weakest asset — an assertion about placement — into its
strongest: a measured quantity with a curve. And it costs an analysis script, not an architecture.

---

## 9 · Novelty Upgrade — integration into the existing plan

```
CURRENT ASTRA
  gates read the estimate; health reads raw frames; 4/6 faults invisible
        ↓
NEW SCIENTIFIC QUESTION
  how much fault information survives each pipeline stage, and where is it lost?
        ↓
NEW METRIC
  D_s = AUC(faulted, clean) per stage · R_s retention · A(f) absorption point
        ↓
NEW EXPERIMENT  → E17, inserted after E9-B
  13 faults × 3 severities × 30 seeds × 9 stages
        ↓
BASELINES
  Simplex and CBF profiled at their own comparable stages (E4/E5 reused)
        ↓
ABLATION
  placement ablation (master-plan §14.1) becomes a *prediction test*:
  D_s predicts which placement detects — a falsifiable link
        ↓
REAL-WORLD  → E13
  profile the stages reconstructable from comma2k19 logs
        ↓
CARLA  → E14  [M-sim]
  does the collapse stage move under weather/traffic shift?
        ↓
NEW SCIENTIFIC CLAIM
  "In learned estimation pipelines, fault discriminability collapses at the estimator and does not
   recover downstream; the collapse point predicts which monitor placements can detect which faults."
```

**It reuses every experiment already planned.** E17 is analysis over data E2/E9-B already produce.

---

## 10 · New Hypotheses

**H6 — Discriminability collapse.** For estimator-absorbed faults, `D_L2 < D_L1 − 0.15` and
`D_s ≤ D_L2 + 0.05` for all s > L2. *H0: `D_s` constant across stages.*

**H7 — Absorption point predicts detectability.** A monitor at stage *s* detects fault *f* iff
`s < A(f)`. *H0: detection is independent of the monitor's stage relative to `A(f)`.* **This is the
falsifiable core** — it makes placement predictive rather than descriptive.

**H8 — Minimum Detectable Severity is placement-dependent.** `MDS(f, pre) < MDS(f, post)`.

---

## 11 · New Metrics

| Metric | Definition | Range | Interpretation |
|---|---|---|---|
| `D_s(f,σ)` | AUC separating faulted from matched-clean at stage *s* | [0.5, 1] | 0.5 = no information |
| `R_s` | (D_s − 0.5)/(D_L1 − 0.5) | [0, 1] | fraction of upstream signal retained |
| `A(f)` | first stage with D_s < 0.60 | stage id | **the absorption point** |
| `MDS(f, s)` | severity at 90% detection from a logistic fit | fault units | detection floor |
| `SCF` | safety benefit / component count | ratio | safety-complexity frontier (Idea 7) |

All computable from stored records. **No new instrumentation.**

---

## 12–16 · Experiments, Baselines, Datasets, Ablation, Statistics

**E17 — Discriminability profiling.** 13 × 3 × 30 × 9. Test: **DeLong** for paired AUC between
adjacent stages; BH across stages. Bootstrap CI, 10k.
**E18 — MDS.** Logistic fit of detection on severity per placement; CI on the 90% point.
**E19 — Compound faults.** 2-factor factorial, interaction term from a two-way model.

**Baselines:** Simplex and CBF profiled at equivalent stages — reuses E4/E5, no new runs.
**Datasets:** synthetic (all stages); comma2k19 (L1, L2, L3 only — no gate verdicts exist in logs).
**Ablation:** §14.1's placement row becomes a **prediction test** for H7 rather than a demonstration.
**Statistics:** AUC is bounded and paired — DeLong, not Wilcoxon. Where an AUC is degenerate (all
faulted = all clean), report the Wilson interval and no test.

---

## 17–19 · Three paper stories

### Story A — Conservative IEEE conference
**Contribution:** the blind spot + placement specificity, with Simplex as baseline.
**Experiments:** E2, E4, E7. **Complexity:** low. **Evidence burden:** 30 seeds + one baseline.
**Strength:** moderate. **Risk:** *"novelty is composition"* — survives only if Simplex also misses.

### Story B — Strong international conference **(recommended)**
**Contribution:** A + **E17 discriminability profiling** + MDS.
**Experiments:** E2, E4, E5, E7, E17, E18. **Complexity:** low-medium — E17 is analysis.
**Strength:** high. **Risk:** *"AUC per stage is just an ROC"* — defended in §20.

### Story C — Q1 journal
**Contribution:** B + comma2k19 + CARLA + compound faults + cross-pipeline generalisation.
**Experiments:** all, plus E13, E14, E19. **Complexity:** high. **Evidence burden:** external data
mandatory. **Strength:** high. **Risk:** scope; 3–4 months.

---

## 20 · Reviewer Red Team

**"This is not novel because ROC/AUC analysis of detectors is standard."**
It is. What is not standard is computing it **at every stage of one pipeline for the same fault** and
showing where it collapses. The unit of analysis is the *stage*, not the *detector*.
**Defeat it:** show `D_s` varying by > 0.3 across stages for the same fault — a single-detector ROC
cannot express that.

**"Information loss through a filter is obvious — that is what a filter does."**
Obvious qualitatively; unmeasured quantitatively. Nobody has published *how much* is lost, *where*,
or that the loss point **predicts** which monitors work.
**Defeat it:** H7. If `A(f)` predicts detection across faults and architectures, it is a law, not an
observation.

**"You only have one pipeline."**
Correct and it is the central weakness.
**Defeat it:** profile Simplex and CBF at their own stages (E4/E5). If the collapse appears in all
three, it is a pipeline property. **If it does not, report that** — and the contribution becomes
narrower and still true.

**"AUC needs balanced classes and enough samples."**
30 seeds × 3 severities = 90 faulted vs 90 clean per fault. Adequate for AUC with bootstrap CI, thin
for mutual information — which is why MI is secondary.

**"Your synthetic plant determines the answer."**
The strongest attack, unanswerable without E13.
**Defeat it:** profile the reconstructable stages on comma2k19. If the L1→L2 collapse appears on real
logs, the phenomenon is not an artefact of the plant.

---

## 21 · Keep / Modify / Remove / Add / Defer

**KEEP** — the nine-layer implementation · fault injector · shadow detectors · positive-control
ablation · hash-chained records · all five hypotheses · every negative result · the Simplex baseline.

**MODIFY** — placement ablation becomes a *prediction test* for H7 · "placement matters" becomes
"discriminability collapses at stage *s*" · master-plan §5.4's absorbed criteria adopt `A(f)`.

**REMOVE** — the 27× claim (already withdrawn) · gate complementarity · any real-time claim.

**ADD** — one analysis script computing `D_s`, `R_s`, `A(f)` · H6, H7, H8 · E17, E18 · one figure.

**DEFER** — monitor-placement optimisation (Idea 2) · adaptive placement (3) · information-bottleneck
framing (15) · cross-pipeline generalisation (23) — all to the journal version.

**Nothing is expanded architecturally. The upgrade is one script and one figure.**

---

## 22 · Final Contribution Stack

```
C1 — Phenomenon    fault discriminability collapses at the estimator and does not recover
C2 — Metric        D_s, R_s, A(f) — a measurable, reusable framework
C3 — Prediction    A(f) predicts which monitor placements detect which faults        (H7)
C4 — Validation    reproduced across two policies, three architectures, 30 seeds
C5 — Boundary      where it fails: absorbed faults below MDS; ASTRA worse on 4/7 arms
```

C5 is a contribution, not an apology. A paper that states where its method fails is harder to reject.

---

## 23 · Memorable Figure

**A single plot: discriminability `D_s` on the y-axis, pipeline stage on the x-axis, one line per
fault class.** Lines enter high at L1 and collapse at L2, staying flat across every downstream gate.
One line — the dropout — stays high because health reads before the estimator.

A reviewer understands the entire paper from that figure in five seconds. Nothing in the current
manuscript comes close.

---

## 24 · Memorable Experiment

**Profile the same fault through all nine stages and show the collapse.** Not a comparison of
methods — a measurement of a pipeline. Reviewers remember measurements of things nobody measured.

---

## 25 · Memorable Finding

> **In a learned estimation pipeline, fault information is not gradually degraded — it is lost at one
> identifiable stage, and no downstream monitor recovers it regardless of sophistication.**

**Memorable metric:** the **absorption point `A(f)`** — the stage at which a fault becomes
unobservable.

---

## 26 · Risks

| Risk | Mitigation |
|---|---|
| Curve is flat → central story wrong | **Report it.** A flat curve refutes the placement thesis and is publishable as a negative result |
| AUC dismissed as standard | Emphasise the *stage* as unit of analysis; H7's predictive claim |
| One pipeline only | Profile Simplex and CBF; comma2k19 for real stages |
| Sample size for MI | MI secondary; AUC primary |
| Scope creep | Only E17/E18 added; everything else deferred |
| comma2k19 exposes only 3 stages | Stated in advance; partial profile is still evidence |

---

## 27 · Implementation Roadmap

| Step | Work | Effort | Depends |
|---|---|---|---|
| 1 | Commit working artefacts | 30 s | — |
| 2 | Emit per-stage statistics into the audit record | 0.5 d | 1 |
| 3 | `benchmarks/discriminability.py` — compute D_s, R_s, A(f) | 1 d | 2 |
| 4 | Run on existing 7 arms, n = 1, **sanity check the curve exists** | 1 h | 3 |
| 5 | 30-seed sweep (E2) | 2 d | 1 |
| 6 | E17 full profile | 0.5 d | 3, 5 |
| 7 | Simplex + CBF profiles | reuse E4/E5 | E4, E5 |
| 8 | E18 MDS fit | 0.5 d | 6 |
| 9 | The figure | 0.5 d | 6 |

**Step 4 is the decision point.** If the curve is flat at n = 1, stop and reconsider before spending
a week on seeds. **Total to a conference-grade result: ~6 days**, most of it already planned.

---

## 28 · Final Recommendation

**Adopt Story B.** Add Fault Discriminability Profiling as the central contribution; keep the
existing architecture, experiments and negative results unchanged.

The recommendation is *not* to expand ASTRA. It is to **measure what ASTRA already instruments**. The
project's real asset was never the nine layers — it is a pipeline where the same fault can be
observed at every stage, and a record format that already stores all of them.

**The single highest-value next action after committing the artefacts:** implement
`benchmarks/discriminability.py` and run it on the seven existing arms at n = 1. One hour of work
tells you whether the collapse curve exists. If it does, the paper has a figure and a contribution.
If it does not, you have learned something more important than a submission.
