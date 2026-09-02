# E18 — OD-8 Calibration: Hypothesis, Protocol, Pre-Registration

**Written 1 September 2026, before any calibration value was computed.**
Nothing below may be revised once calibration output is inspected. If a rule proves wrong, the
revision is reported as a deviation in `analysis.md`, never as the original plan.

---

## A · Research question

**Can the L6 statistical gate be calibrated so that it operates as a valid conformal monitor — a
controlled false-alarm rate on clean data — across the three tested policies?**

The objective is **not** to maximise fault detection. It is to establish a valid operational monitor
first. A gate tuned to catch faults is not a conformal gate.

## B · Hypothesis

**H-E18:** the OD-8 failure is a **calibration-set provenance** problem, not a threshold-value
problem. Recalibrating from clean runs generated under the same conditions as live operation will
produce a threshold whose empirical clean false-alarm rate matches its nominal ε within sampling
error.

## C · Null hypothesis / what would count against it

**H0-E18:** clean scores are not exchangeable even within a single policy under identical
conditions — e.g. they drift within a run — so no fixed quantile achieves nominal coverage.

E18 **FAILS** if any of these hold after recalibration:

1. Empirical clean false-alarm rate falls outside **[ε/2, 2ε]** for any policy under the selected
   calibration scheme.
2. Calibration and test clean scores are distinguishable at **AUC > 0.70** — i.e. still not
   exchangeable across disjoint seed sets.
3. Within-run drift exceeds the between-run spread, making a fixed threshold meaningless.

A FAIL is a real outcome and stops progression to E19. It is not a reason to retune.

## D · Variables

| type | variable |
|---|---|
| **Independent** | calibration scheme (global / policy-conditional); policy (P1, P2, P3) |
| **Dependent** | conformal quantile; empirical clean false-alarm rate; exchangeability AUC; headroom |
| **Controlled** | ε = 0.05; ticks = 400; plant model; twin checkpoint; context classifier; score definition; software versions |
| **Nuisance** | seed; within-run temporal position; context-class assignment |

## E · Environment

| | |
|---|---|
| Environment | synthetic plant, `training/closed_loop.drive_closed_loop`, redundant sensing (ADR-0033 default) |
| Policies | P1 `synthetic.pt`, P2 `long.pt`, P3 `jerkscaled.pt` |
| Faults | none during calibration — **clean runs only** |
| Ticks | 400 per run |
| Score | `non_conformity_score` from the STATISTICAL gate's evidence tuple |
| Context | as assigned by L3; recorded per tick, not assumed |

### Split — the leakage control

| set | seeds | n runs | use |
|---|---|--:|---|
| **CALIBRATION** | `20260901 + i`, i = 0…29 | 30 × 3 policies | compute the quantile |
| **CLEAN TEST** | `20261001 + i`, i = 0…29 | 30 × 3 policies | measure false-alarm rate |
| **FAULT TEST** | `20260731 + i`, i = 0…29 | 30 × 3 × 6 faults | evaluate detection — **only after freezing** |

**All three seed sets are disjoint.** Calibration seeds are new and have never been used in this
project. The fault-test seeds are the E17 set, retained so results are comparable.

**The quantile is computed from CALIBRATION only. No fault data touches it.**

## F · Calibration schemes compared

Decided in advance; the evidence chooses between them, not preference.

1. **Global** — one quantile from clean scores pooled across all three policies.
2. **Policy-conditional** — one quantile per policy.

Both are computed and both reported. **Selection rule, fixed now:** prefer *global* unless its clean
false-alarm rate falls outside [ε/2, 2ε] for at least one policy, in which case prefer
*policy-conditional*. Preferring the simpler scheme unless it demonstrably fails is stated in advance
so the choice is not made by looking at which gives nicer detection numbers.

Context-conditional calibration is retained as the existing Mondrian structure: quantiles are
computed **within the context class actually observed**, which the diagnostic shows is `URBAN_CLEAR`
for ~99.5 % of ticks.

## G · Threshold definition

ε = **0.05**. The conformal acceptance region is `{score ≤ q_{1−ε}}`, so the quantile is the
**95th percentile** of calibration scores, using the existing `conformal_quantile` implementation
unchanged.

ε = 0.05 is chosen as the conventional default and because a 5 % clean-tick alarm rate is already
generous for a per-tick safety monitor. **It is not chosen by looking at what makes the gate fire.**

## H · Freeze

Once computed, the quantile is written to `configuration.md` and **frozen**. No subsequent change is
permitted without opening a new experiment (E18-R1). The freeze happens **before** any faulted run is
evaluated.

## I · Integrity checks — required before any result is accepted

1. Fault injection reaches the delivered signal (the standing rule from E17).
2. Expected sample counts: 400 ticks × runs, no missing or stale samples.
3. No NaN / Inf in scores.
4. Context-class distribution recorded per run, not assumed.
5. Calibration and test seed sets verified disjoint, programmatically.
6. Clean/fault separation verified at the estimator input.

## J · Measurements

Per policy, per scheme:

- clean score distribution — mean, SD, min, max, quantiles
- conformal quantile and its bootstrap CI
- **empirical clean false-alarm rate** on the held-out CLEAN TEST set
- headroom = quantile − mean clean score
- **exchangeability check**: AUC(calibration scores, clean-test scores). Near 0.5 means exchangeable
- **temporal behaviour**: score vs tick index, and first-half vs second-half means — included because
  the diagnostic suggested within-run drift

## K · Decision rule

**PASS** — all three FAIL criteria in §C avoided, under at least one pre-specified scheme.
**PARTIAL** — passes for some policies and not others; policy dependence is then a finding.
**FAIL** — no scheme achieves controlled false alarms. E19 does not start. E18-R1 is designed.

## L · Known limitations, stated in advance

One plant model · three policies is not a sample of policies · synthetic only, `[M-syn]` ·
ε = 0.05 is a convention, not a safety requirement derived from a hazard analysis · per-tick alarms
are not the same as per-event alarms, and this experiment does not model alarm persistence ·
calibrating on clean data cannot establish that the gate is *useful*, only that it is *valid*.
Usefulness is E19's question.
