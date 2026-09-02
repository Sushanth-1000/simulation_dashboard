# E18-R2 — Pre-Registration

**Written 1 September 2026, before any R2 quantile was computed.** Nothing below may be revised
after inspecting R2 output. A forced revision is reported as a deviation in `analysis.md`.

---

## 1 · Why R2 exists

Two prior attempts failed for opposite reasons:

| | scheme | failure |
|---|---|---|
| **E18** (v1) | pooled, calibrated on ticks 0–399 | **window mismatch** — FAR measured over ticks 0–399, detection over 200–399. On the matched window P1 is 4/30 in band, median run FAR 0.00 % |
| **E18-R1** (v2) | run-local, ticks 1–200 per run | **estimator variance** — per-run threshold SD 0.0135–0.0251, comparable to the entire threshold headroom 0.0170–0.0235. P3 9/30, P1 3/30 |

R2 takes the **large sample** from E18 and the **window discipline** from R1. It is the only
untested combination of the two, and it is one experiment, not a search.

## 2 · Research question

Does pooled calibration on the **matched** window — ticks 200–399, the window in which detection
decisions are actually made — produce per-run-stable false-alarm behaviour?

## 3 · Hypotheses

**H1:** Calibrating on the same window the monitor is evaluated in will restore per-run false-alarm
behaviour to the target band for P1, the positive control.

**H0:** Window matching does not restore per-run stability, because the dominant obstacle is
between-run baseline variation rather than window mismatch.

**Both are live, and they are separable by policy.** The E18 audit measured between-run vs
within-run score variance: **P1 ratio 0.03, P3 ratio 0.67**. P1's runs share a baseline; P3's do
not. **The stated expectation, recorded before running: H1 holds for P1 and fails for P3**, because
pooled calibration cannot correct a per-run offset no matter which window it uses. If P1 also fails,
H0 holds and the OD-8 formulation is the problem rather than the calibration procedure.

## 4 · Primary criterion — frozen

**P1 (positive control): ≥ 24/30 runs in band.**

The positive control must be recovered before any P3 claim is meaningful. Band is unchanged:
`[eps/2, 2*eps] = [2.5 %, 10 %]`, eps = 0.05, unit of analysis is the **run**.

| P1 runs in band | classification |
|---|---|
| **≥ 24** | **PASS-R2** — matched-window calibration restores the positive control |
| 12 – 23 | **PARTIAL-R2** |
| < 12 | **FAIL-R2** — window matching is not the obstacle |

**P3 is reported against the same band but is secondary.** P3's classification carries forward the
E18-R1 boundaries (≥ 24 VALID, 12–23 CONDITIONAL, < 12 INVALID).

## 5 · Calibration procedure — complete definition

For policy `p`, pooling over the 30 clean **calibration** runs (seeds `20260901 + i`):

    C_p = { s_{r,t} : r in calibration runs of p ,  201 <= t <= 400 ,  s finite }
    n_p = |C_p|                                             (nominally 6,000)
    k_p = ceil( (n_p + 1) * (1 - eps) ) ,   eps = 0.05
    q_p = k_p-th smallest value of C_p

One threshold per policy, constant across runs and across time — identical in form to E18 version 1.
**The only change from version 1 is the tick range of the calibration sample:
200–399 instead of 0–399.**

Evaluation, on the held-out clean **test** runs (seeds `20261001 + i`):

    E_r = { s_{r,t} : 201 <= t <= 400 }
    FAR_r = |{ t in E_r : s_{r,t} > q_p }| / |E_r|

Warm-up: not applicable — the window begins at tick 200, well past any startup transient.
Transients: not treated specially.

## 6 · Why this window, and why it is not a search

The window is **not chosen**; it is the one the evaluation already uses, fixed by `_FAULT_FIRST = 200`
in E17. R2 does not select a window — it removes an inconsistency by making calibration use the
window evaluation was always using. **No alternative range is evaluated.**

## 7 · Data separation

    clean CALIBRATION runs, ticks 200-399   (seeds 20260901+)
        -> pooled quantile q_p
        -> FROZEN as calibration version 3
        -> held-out clean TEST runs, ticks 200-399   (seeds 20261001+)
        -> per-run FAR, primary criterion

No test outcome, no fault outcome and no R1 result influences `q_p`. The calibration and test seed
sets are disjoint and that disjointness is already asserted programmatically upstream.

## 8 · No new closed-loop runs

The existing `calibration.json` and `clean_test.json` contain all 400 ticks per run. R2 reuses them
and changes only which ticks enter the quantile. **This is deliberate and is a strength**: the score
data is byte-identical to E18's, so any difference in outcome is attributable to the calibration
window alone and to nothing else — not to a re-run, a reseed, or a code path change.

## 9 · Integrity checks

| check | how |
|---|---|
| Calibration window contains no pre-200 tick | index assertion |
| Calibration and test seeds disjoint | already asserted in the collector |
| No fault data in calibration | clean sets only; collector cannot inject |
| Threshold frozen before evaluation | quantile computed and written before per-run FAR is scored |
| Expected sample counts | 6,000 calibration ticks and 200 evaluation ticks per run per policy |
| No non-finite scores | counted and reported |
| Run-level FAR at the run unit | one value per run; pooled reported as supplementary only |

## 10 · Secondary analyses, specified now

1. Three-way comparison: E18 v1 (whole-run), R1 v2 (run-local), R2 v3 (matched pooled).
2. Whether the between-run baseline offset still predicts run FAR under R2 — the correlation that
   was +0.909 for P3 under v1 and −0.469 under v2.
3. Whether the early-window tail asymmetry noted in `E18_R1/analysis.md` is confirmed: does the
   matched-window quantile come out **below** the whole-run quantile? Predicted **yes**, because FAR
   was 10–14 % early and 0.8–2.7 % late at a fixed threshold.

## 11 · What R2 cannot establish

That the monitor is *useful*. R2 is a false-alarm-calibration experiment on clean data. Detection is
not re-measured here, and a PASS licenses only the statement that the monitor's clean behaviour is
controlled on the window it operates in.

P2 is untouched, as in R1. Its INVALID status under fixed-quantile calibration stands.
