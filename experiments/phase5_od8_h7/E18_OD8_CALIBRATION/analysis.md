# E18 — Analysis (Part 1: Calibration)

**1 September 2026.** Part 2 (fault evaluation against the frozen thresholds) follows once the
evaluation sweep completes. This part is complete and its conclusions do not depend on it.

---

## 1 · Observed

### 1.1 Root cause of OD-8, located

All three policies classify **99.75 % of ticks as `URBAN_CLEAR`** (the remainder is a single
`DEGRADED_SENSOR` tick at run start). The legacy corpus for that context spans **3.8776 – 5.4380**.
Live clean scores span **2.40 – 7.45** with policy means of 3.686 (P1), 4.781 (P2), 3.383 (P3).

The corpus's three context classes differ in scale by two orders of magnitude:

| context | n | min | median | max |
|---|--:|--:|--:|--:|
| HIGHWAY_CLEAR | 1000 | 0.0785 | 0.0888 | 3.7144 |
| **URBAN_CLEAR** | 1000 | **3.8776** | **5.3199** | **5.4380** |
| DEGRADED_SENSOR | 1000 | 0.0782 | 0.1043 | 5.4031 |

The gate was thresholding live data against a calibration distribution the live data was not drawn
from. **Conformal prediction's validity guarantee requires exchangeability; it did not hold.**

### 1.2 Clean score behaviour differs enormously by policy

| policy | mean | SD | min | max |
|---|--:|--:|--:|--:|
| P1 | 3.6860 | **0.0222** | 3.4506 | 3.8488 |
| P2 | 4.7807 | **0.9220** | 2.4033 | 7.4461 |
| P3 | 3.3830 | **0.0124** | 3.2133 | 3.4834 |

P1 and P3 are near-deterministic. **P2's spread is 40–75× larger.** Any single threshold must
therefore either sit inside P1/P3's razor-thin band or inside P2's wide one — it cannot do both.

### 1.3 The global scheme fails, and fails in the OD-8 pattern

Global quantile = **5.6449**:

| policy | clean FAR | nominal | verdict |
|---|--:|--:|---|
| P1 | **0.0000 %** | 5 % | never fires |
| P2 | **11.06 %** | 5 % | over-fires |
| P3 | **0.0000 %** | 5 % | never fires |

**This reproduces the original defect exactly** — unreachable on P1/P3, tripped on P2. It is direct
evidence that OD-8 is a *policy-conditioning* failure, not a bad threshold value. Had the legacy
corpus simply been regenerated globally, the defect would have survived.

### 1.4 Policy-conditional calibration works

| policy | frozen quantile | clean FAR (held out) | headroom |
|---|--:|--:|--:|
| P1 | **3.7095** | **5.47 %** | 0.0235 |
| P2 | **5.9024** | **4.68 %** | 1.1217 |
| P3 | **3.4000** | **8.23 %** | 0.0170 |

All three land inside the pre-registered band [2.5 %, 10 %]. **Criterion C1 passes.**

### 1.5 Exchangeability restored

AUC between calibration and held-out clean-test scores: **0.5154 / 0.5372 / 0.5277**. All near 0.5,
all far under the pre-registered 0.70 limit. **Criterion C2 passes.**

### 1.6 Temporal drift — the criterion that fails

| policy | 1st-half mean | 2nd-half mean | drift / SD |
|---|--:|--:|--:|
| P1 | 3.6850 | 3.6870 | 0.09 |
| P3 | 3.3831 | 3.3828 | 0.03 |
| **P2** | **4.1902** | **5.3711** | **1.28** |

**P2's within-run drift exceeds its between-run spread. Criterion C3 fails for P2 only.**

## 2 · Inferred

**The score is non-stationary on P2 and stationary on P1/P3.** A fixed quantile cannot deliver
uniform coverage against a drifting score: P2's alarm rate is necessarily lower early in a run and
higher late, even though the pooled rate (4.68 %) lands in band. The pooled figure is an average over
two different operating points, and averaging is exactly what hides this.

**This retrospectively explains an earlier observation.** P2's score measured ≈ 5.15 over ticks
200–400 and 2.56–4.46 over ticks 0–200. That was read at the time as a regime property. **It is
drift.** It also further undermines the already-withdrawn H-regime claim: P2's veto behaviour is a
function of *when in the run* you look, not only of how the policy drives.

**P1 and P3 now have headroom of 0.0235 and 0.0170** — down from ≈ 1.7–2.0 under the legacy
threshold. Fault-induced score shifts measured in E17 ranged 0.0005–0.24. Some of those will now
cross and some will not. **Which ones is the question Part 2 answers, and the threshold is frozen so
the answer cannot be engineered.**

## 3 · Hypothesised — not established here

That policy-conditional calibration is the *right* long-term design. It is what the evidence supports
under the pre-registered rule, but three policies is not a sample of policies, and a scheme that
requires per-policy calibration may not scale to a fleet. An alternative worth testing later is
conditioning on a measured operating statistic rather than on policy identity.

That P2's drift has a mechanical cause in the twin or the trajectory. Not investigated; E18 measures
the drift, it does not explain it.

## 4 · Deviations from the protocol

**None.** ε, the seed split, both schemes, the selection rule and all three fail criteria were fixed
in `protocol.md` before any calibration value was computed. The selection rule chose
policy-conditional because the global scheme failed C1, exactly as written.

## 5 · Verdict on the calibration stage

# PARTIAL

| criterion | result |
|---|:--:|
| C1 — clean false-alarm rate in band | **PASS** (all three policies) |
| C2 — calibration/test exchangeable | **PASS** (AUC ≤ 0.537) |
| C3 — drift within between-run spread | **FAIL on P2** (1.28); pass on P1, P3 |

**A valid operational monitor now exists for P1 and P3.** It does not for P2, whose score is
non-stationary within a run.

Per `protocol.md` §K, PARTIAL means policy dependence is itself the finding. The consequence for E19
is recorded in `final_decision.md`.
