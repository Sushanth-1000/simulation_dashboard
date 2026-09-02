# E18-R1 — Final Decision

**1 September 2026** · 60 clean runs (P1, P3 × 30 seeds) · run-local calibration
**Criterion frozen in `preregistration.md` before any R1 result existed.**

---

# VERDICT: FAIL-P3

**P3: 9 of 30 runs in band.** The frozen criterion required **≥ 24/30** for PASS and **≥ 12/30** to
remain CONDITIONAL. 9 is below both.

---

# AND: A DEFECT IN E18 THAT REVISES ITS VERDICT

R1 surfaced an inconsistency in E18 that E18's own analysis did not catch.

**E18 measured false-alarm rate over ticks 0–399 and detection over ticks 200–399.** The two
headline quantities were computed on different windows.

| policy | FAR ticks 0–199 | **FAR ticks 200–399** (where detection is measured) | whole run (what E18 validated) |
|---|--:|--:|--:|
| P1 | 10.17 % | **0.78 %** | 5.47 % |
| P3 | 13.58 % | **2.73 %** | 8.16 % |
| P2 | 0.93 % | **8.42 %** | 4.67 % |

On the **matched** window, per-run:

| policy | E18 whole-run | **E18 matched** | R1 run-local |
|---|:--:|:--:|:--:|
| P1 runs in band | **21/30** | **4/30** | 3/30 |
| P1 median FAR | 4.88 % | **0.00 %** | 0.00 % |
| P3 runs in band | 4/30 | 5/30 | **9/30** |
| P3 median FAR | 1.00 % | 0.50 % | 0.50 % |

**E18's "P1 VALID" does not survive window matching.** On the window where detection decisions are
actually made, P1's median run never alarms at all and only 4 of 30 runs sit in the target band. The
monitor is far more conservative in the evaluation window than its calibration implied.

This is the sixth defect of the same family found in this project — a statistic computed over a
population that does not match the claim it supports. It is recorded, not quietly folded in.

## 1 · Was the correct window ambiguous?

Partly, and that is the lesson. `E18/protocol.md` §J specified *"empirical clean false-alarm rate on
the held-out CLEAN TEST set"* **without naming a tick range**. The implementation used the whole run;
the detection code used the post-injection window. Neither was wrong on its own terms, and the
pre-registration did not force them to agree.

**The operationally correct choice is the matched window.** A false-alarm rate is only comparable to
a detection rate if both describe the same operating condition. Reporting whole-run FAR alongside is
legitimate as supplementary information; using it to certify a monitor whose detection is measured
elsewhere is not.

## 2 · Why R1 failed

H1 predicted that removing the between-run baseline offset would stabilise P3. **The mechanism worked
and the criterion still failed.**

Evidence the mechanism worked as designed:

| | E18 pooled | R1 run-local |
|---|--:|--:|
| corr(run baseline, run FAR) — P1 | +0.652 | **−0.174** |
| corr(run baseline, run FAR) — P3 | **+0.909** | **−0.469** |

The baseline-offset dependence that `audit_of_E18.md` §10 identified is **gone**. P3's FAR is no
longer predicted by its run's mean score.

**But the estimation variance it cost exceeded the bias it removed** — exactly the failure mode
pre-registered in `hypothesis.md`:

> run-local calibration trades between-run bias for estimation variance. Each threshold is estimated
> from 200 ticks instead of 12,000, and those 200 ticks are autocorrelated.

Threshold SD across runs: **P1 0.0251, P3 0.0135** — comparable to or larger than each policy's
entire threshold headroom (0.0235, 0.0170). The per-run threshold is as uncertain as the quantity it
is trying to resolve.

The consequence is systematic over-coverage. With `n_r ≈ 200` autocorrelated ticks, the 191st order
statistic sits near the sample maximum, so the estimated quantile is biased high and the monitor
under-alarms: **median run FAR 0.00 % on P1 and 0.50 % on P3**, against a 5 % nominal.

**The positive control confirms it.** P1 went from 4/30 to 3/30 in band under R1. Per
`preregistration.md` §6, a P1 result that does not improve is evidence against H1 rather than a P1
finding. It did not improve.

## 3 · Secondary analysis — did R1 improve stability or just move the aggregate?

The pre-registered distinguishing test was whether the **IQR of run-level FAR narrows**.

| | E18 matched | R1 run-local |
|---|--:|--:|
| P1 IQR width | 1.00 % | **0.00 %** |
| P3 IQR width | 2.00 % | 2.50 % |

P1's IQR collapses to zero because nearly every run now alarms zero times — that is degenerate
uniformity, not stability. P3's IQR **widened slightly**. **R1 did not improve stability.**

## 4 · P3 bimodality — resolved as a mechanism, not as a fix

The E18 bimodality **is** explained: a per-run baseline offset (corr +0.909) whose spread (0.0277)
exceeds the threshold headroom (0.0170). R1 removed that dependence (corr → −0.469).

**Removing the mechanism did not produce a usable monitor**, because the replacement estimator is too
noisy at the available sample size. The mechanism is resolved; the calibration problem is not.

## 5 · P2

Untouched, as required. Not tuned for, not pooled, not rescued. Its INVALID status under fixed-quantile
calibration stands. Note in passing, from the window analysis: P2's matched-window FAR is 8.42 %,
inside the band — but its within-run non-stationarity (drift/SD 1.28) is the reason it fails, and that
is unaffected by window choice.

## 6 · Preserved results

- **Alarm suppression** — not re-measured, since the faulted evaluation was not run (see §7). The
  E18 result stands as recorded: 11 of 28 cells, all p < 0.05.
- **`D_s` ≠ operational detection** — unchanged. E19's predictor is **not** modified.

## 7 · Why the faulted evaluation was not run

`preregistration.md` and §17 of the brief scope faulted runs to *establishing that a recovered P3
monitor remains operational*. **P3 was not recovered.** Running 1,260 faulted runs against a
calibration that fails its primary criterion would produce detection numbers for a monitor that is
not validly calibrated — precisely the category of result this project has already had to withdraw
twice. Approximately 90 minutes of compute was deliberately not spent.

## 8 · Decision

# FAIL-P3

P3: **9/30**, below the frozen threshold of 12/30 for CONDITIONAL. The R1 procedure is sound, the
mechanism it targeted was real and was removed, and the resulting monitor is still not calibrated.

R1 is **not INVALID** — no integrity check failed, all 60 runs completed, seeds and policies are
preserved, and no leakage occurred. It is a clean negative result.

## 9 · Gate to E19

# DO NOT PROCEED

§21's stop condition assumed P1 = VALID. **After window matching, P1 is 4/30 runs in band with a
median run FAR of 0.00 %.** No policy currently has defensible run-level false-alarm behaviour on the
window where detection is measured.

Proceeding to E19 now would measure monitor placement using an instrument that is not calibrated on
the window it operates in. E18's own conclusion — that `D_s` must not be substituted for operational
detection — applies with equal force to an operational-detection measurement taken from an
uncalibrated monitor.

## 10 · Minimum required repair

**E18-R2 — matched-window pooled calibration.** One change, pre-registered, no search:

1. **Calibrate on ticks 200–399 of the clean calibration runs** (seeds `20260901+`), pooled across
   runs as in E18. This matches the calibration population to the evaluation window, which is the
   defect §1 identifies, while keeping the large sample size whose absence caused R1 to fail.
2. Freeze as **calibration version 3**. Versions 1 and 2 remain on record.
3. Re-measure per-run FAR on the held-out clean test set, **ticks 200–399**.
4. Success criterion, fixed now: **≥ 24/30 runs in band for P1** (the positive control must be
   recovered first) and reported for P3.

**Rationale, available before the outcome:** R1 failed on estimator variance, not on the idea of
window matching. E18 failed on window mismatch, not on sample size. E18-R2 takes the large sample
from E18 and the window discipline from R1. It is the only combination of the two not yet tested, and
it is one experiment, not a search.

**Estimated cost:** ~4 minutes of compute — the calibration runs already exist and only the quantile
and its evaluation change.

If E18-R2 also fails, the honest conclusion is that **the current OD-8 formulation cannot support a
per-run-stable operational monitor at this ε on this plant**, and the contribution reframes around
that limitation rather than around monitor placement.
