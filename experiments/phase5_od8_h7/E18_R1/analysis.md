# E18-R1 - Analysis

## Observed

**Primary criterion.** P3: **9 of 30** runs in band. P1 positive control: **3 of 30**.

**Comparison across calibration schemes**, run-level, clean held-out data:

| metric | E18 whole-run | E18 matched window | E18-R1 run-local |
|---|--:|--:|--:|
| P1 runs in band /30 | 21 | **4** | 3 |
| P1 median run FAR | 4.88 % | 0.00 % | 0.00 % |
| P1 FAR IQR width | 4.00 % | 1.00 % | 0.00 % |
| P3 runs in band /30 | 4 | 5 | **9** |
| P3 median run FAR | 1.00 % | 0.50 % | 0.50 % |
| P3 FAR IQR width | 11.81 % | 2.00 % | 2.50 % |
| Threshold SD (P1 / P3) | fixed | fixed | **0.0251 / 0.0135** |

**Baseline-offset dependence**, the mechanism R1 targeted:

| policy | E18 pooled | R1 run-local |
|---|--:|--:|
| corr(run mean score, run FAR) - P1 | +0.652 | **-0.174** |
| corr(run mean score, run FAR) - P3 | **+0.909** | **-0.469** |

**Pooled FAR by tick range**, at E18's frozen thresholds:

| policy | ticks 0-199 | ticks 200-399 | whole run |
|---|--:|--:|--:|
| P1 | 10.17 % | **0.78 %** | 5.47 % |
| P3 | 13.58 % | **2.73 %** | 8.16 % |
| P2 | 0.93 % | **8.42 %** | 4.67 % |

## Inferred

**The targeted mechanism was real and was removed.** P3's FAR was almost entirely determined by its
run's own baseline (corr +0.909); after run-local calibration that dependence is gone. The audit's
diagnosis in `audit_of_E18.md` section 10 is therefore confirmed, not merely consistent.

**Removing it did not produce a usable monitor.** Per-run threshold SD (0.0135-0.0251) is comparable
to the entire threshold headroom (0.0170-0.0235), so the per-run threshold is as uncertain as the
quantity it resolves. With `n_r = 200` autocorrelated ticks, the 191st order statistic sits near the
sample maximum and the estimate is biased high. The monitor over-covers: median run FAR 0.00-0.50 %
against 5 % nominal.

This is the failure mode written into `hypothesis.md` **before** the run - bias traded for variance,
with the variance winning. It is a pre-registered prediction of the null being borne out, not an
explanation constructed afterwards.

**R1 did not improve stability.** The pre-registered distinguishing test was whether the FAR IQR
narrows. P1's collapses to 0.00 % because nearly every run alarms zero times - degenerate uniformity,
not stability. P3's widened from 2.00 % to 2.50 %.

**E18's window mismatch is the more consequential finding.** A false-alarm rate is comparable to a
detection rate only if both describe the same operating condition. On the matched window, P1 - the
one policy E18 certified - has a median run FAR of 0.00 % and 4 of 30 runs in band.

## Hypothesised - not established

That E18-R2 (matched-window pooled calibration) will succeed. It combines the large sample size whose
absence caused R1 to fail with the window discipline whose absence caused E18's defect. That is a
reason to run it, not evidence that it works.

That the elevated FAR in ticks 0-199 is a startup transient. The mean score barely differs between
windows (P1: 3.6866 / 3.6763 / 3.6888 / 3.6877 across tick blocks), so the difference is in the upper
tail rather than in location. **Unresolved**, and it matters: if the tail is heavier early in a run,
a matched-window calibration will produce a *lower* threshold and a *higher* alarm rate, which is the
direction E18-R2 needs.

## Deviations from the pre-registration

**None.** One window definition was run, as specified. The criterion was not altered. The faulted
evaluation was omitted under the scoping rule stated in `preregistration.md` and section 17 of the
brief, because P3 was not recovered.
