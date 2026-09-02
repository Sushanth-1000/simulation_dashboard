> # ⚠ SUPERSEDED IN PART — 1 September 2026
> **The two position-fault rows in this document are invalid.** `D_L2a = 0.500` for
> `position_bias` and `position_drift` is 0.5 **by construction**: the redundant sensing path
> (ADR-0033) regenerates the position channel from ground truth, so the injected fault never
> reached the pipeline. C1 is **NOT ESTABLISHED**.
> See [E17_INVALIDATION.md](E17_INVALIDATION.md). The speed, lateral and dropout results are
> unaffected and stand.
>
> **The L6 "detection-without-response gap" claim is also withdrawn.** L6's score shifts by 0.016
> against a firing threshold 2.0 away, and the gate returns PASS on every tick, faulted or clean —
> it never made a detection to ignore. Root cause is OD-8, not wiring.
> See [E17_L6_CORRECTION.md](E17_L6_CORRECTION.md).

# E17 — Final Decision

**1 September 2026** · 90 profiles, 2,160 runs, 0 failures · pre-registered before execution

---

## 1 · C1 — stage-dependent fault absorption

# PARTIALLY SUPPORTED — strongly, for a narrow class

**Supported for the position-fault class**, with the strongest evidence this design can produce:

- `D_L1` 1.000 → `D_L2a` 0.500 on **90 of 90 runs**, identical to three decimals
- `A(f) = L2a` on **30/30 seeds × 3 policies**, well-posed on every seed
- effect 0.500 / 0.470, Holm-adjusted *p* ≤ 9.1 × 10⁻⁶
- **all 18 pre-registered falsification checks negative**
- reproduces on a policy operating in a completely different regime (P2, 87 % veto rate, one third the speed)

**Not supported as a general claim.** Four of the six faults do not show it, in four distinct ways:

| fault | what it does instead |
|---|---|
| `speed_bias` | absorbed at L2a, then **recovered at L6 to 0.963–0.994** |
| `speed_stuck` | absorbed, partly recovered at L6; unstable on P2 |
| `imu_dropout` | **non-monotonic** — no well-posed `A(f)` on any policy |
| `lateral_noise` | **persistent** — never absorbed at any stage |

**The honest claim is about position faults, not about faults.** That is a smaller claim than v18
makes and it is the one the data supports.

## 2 · C2 — the regime hypothesis

# NOT SUPPORTED

The pooled correlation was significant and in the predicted direction (ρ = −0.34, −0.46, *p* < 0.001).
A stated robustness check showed it to be a **Simpson's paradox**: within P2 the `speed_bias`
correlation is **+0.836**, opposite in sign to the pooled −0.341, and every within-policy
`speed_stuck` correlation is null.

Veto rate is almost perfectly confounded with policy identity — P2 spans [0.605, 0.990], P1 and P3
span [0.000, 0.510], **no overlap** — and the two policies with clean speed results have zero
variance in `D_L1` to explain.

The condition from `E17_SECOND_POLICY_DECISION.md` **is discharged**: regime was measured rather than
averaged away, and the answer is that this design cannot separate regime from policy. Details in
`E17_REGIME_ANALYSIS.md`.

## 3 · The finding I did not go looking for

**The conformal gate recovers a signal the estimator absorbed, and nothing downstream acts on it.**

`speed_bias`, P3: `L1 1.000 → L2a 0.513 → L3 0.508 → ` **`L6 0.963`** ` → L7 0.500 → L8 0.500`.
P2 reaches **L6 = 0.994**.

L6 separates faulted from clean at near-perfect accuracy. The deterministic gate and the fail-safe
posture then sit at chance. **~~ASTRA detects this fault and does not respond to it.~~ WITHDRAWN — see [E17_L6_CORRECTION.md](E17_L6_CORRECTION.md): the gate returns PASS on every tick and the score shift is 0.016 against a threshold 2.0 away.**

This is a claim about ASTRA's own wiring, it is measured rather than inferred, and it is arguably
more interesting than C1 — it is a concrete, reproducible governance defect found by instrumenting
the architecture rather than by reasoning about it. It also **complicates the absorption story**: the
information was not destroyed at L2a, since a downstream statistic recovers it. The correct framing
throughout is *"the evaluated representation does not retain discriminative evidence"*, never
*"information is destroyed"*.

## 4 · Decision on the paper

# GO — with the claim narrowed

Publishable as: **stage-wise fault discriminability profiling of a layered runtime-governance
architecture**, with three results —

1. **position faults are absorbed at the estimator**, reproducibly and policy-independently (n = 30 × 3);
2. **fault propagation is heterogeneous** — absorbed, recovered, non-monotonic and persistent classes
   all occur, and a single absorption metric is ill-posed for most of them;
3. ~~a detection-without-response gap at L6 → L7/L8~~ — **WITHDRAWN**, see [E17_L6_CORRECTION.md](E17_L6_CORRECTION.md). The real finding is that L6's threshold is unreachable (OD-8).

Result 2 is a methodological contribution and is what stops this being a one-number paper. Result 3
is the finding a practitioner would care about.

**Not publishable as:** a general claim that ASTRA absorbs faults at L2a. Two of six faults, one
plant, one severity, six of thirteen planned faults, simulation only.

## 5 · What must change in v18

| | current | required |
|---|---|---|
| L1 numbers | from the health-count defect | **replace with `results/E17_30SEED/tables/`** |
| evidence | n = 1, one policy | n = 30 × 3 policies, BCa CIs |
| claim scope | faults generally | **position faults specifically** |
| `A(f)` table | modal stage only | **modal + unique-absorption count** — four cells currently overstate stability |
| *p*-values | reported alone | **paired with effect sizes** — `lateral_noise` is *p* = 1.8e−06 at an effect of 0.019 |
| regime | absent | reported as a **negative** result |
| L6 | absent | **OD-8: the conformal threshold is unreachable** — not a response gap |
| marker | — | **`[M-syn]`; `[M-ext]` remains 0 of 30** |

## 6 · What this cannot support, stated plainly

Thirty seeds bought **reproducibility**, not external validity. Simulation-only, one plant, one
severity, three checkpoints. `[M-ext]` is still **0 of 30** and no number of seeds changes that. A
reviewer asking "does this hold outside your simulator?" gets the same answer as before the sweep.

The `lateral_noise` and `imu_dropout` behaviours are reported in full and were not removed for being
inconvenient. The regime result is reported as a failure of my own hypothesis.

## 7 · Next actions, in order

1. **Rebuild v18's results section** from `results/E17_30SEED/tables/` and `plots/`. The current
   numbers are stale and partly defective.
2. **Investigate the L6 → L7/L8 gap** — is the deterministic gate not consuming the conformal
   verdict, or consuming it and not escalating? This is a code question, answerable today, and it is
   the highest-value open item.
3. **Do not run more seeds.** More seeds of a confounded design buy nothing. Testing the regime
   mechanism needs veto rate varied *within* one policy by sweeping a gate threshold — which the
   freeze forbids, and which is therefore recorded as the next question rather than run.
4. comma2k19 and CARLA remain **not started**, which stays correct.

## 8 · Provenance

Pre-registration `results/E17_30SEED/manifests/PREREGISTRATION.md`, written before launch, fixing the
primary stage, primary faults, regime cut points, tests, corrections and three falsification criteria.
Raw output for all 90 runs retained. Zero runs dropped, zero failures, zero retries. Analysis code is
`benchmarks/e17_{sweep,stats,analyse,report}.py`.
