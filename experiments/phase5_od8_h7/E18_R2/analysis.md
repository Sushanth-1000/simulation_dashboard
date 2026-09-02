# E18-R2 — Analysis

## Observed

**Thresholds (version 3), computed from clean calibration ticks 201–400, frozen before evaluation:**

| policy | v3 | v1 | n | non-finite |
|---|--:|--:|--:|--:|
| P1 | **3.7024** | 3.7095 | 6,000 | 0 |
| P3 | **3.3953** | 3.4000 | 6,000 | 0 |
| P2 | 6.0000 | 5.9024 | 6,000 | 0 |

**Held-out clean, per run (n = 30 per policy):**

| policy | runs in band | median FAR | IQR | pooled FAR | zero-alarm runs |
|---|:--:|--:|---|--:|--:|
| P1 | **13/30** | 3.00 % | [1.50 %, 5.38 %] | 5.82 % | 2 |
| P3 | 2/30 | 1.00 % | [0.50 %, 8.50 %] | 9.18 % | 4 |
| P2 | 0/30 | 0.00 % | [0.00 %, 0.00 %] | 8.37 % | 25 |

**Overdispersion diagnostic:**

| policy | observed per-run FAR SD | binomial (n=200) | ratio | effective ticks | alarm lag-1 autocorr |
|---|--:|--:|--:|--:|--:|
| P1 | 6.98 % | 1.66 % | **4.2x** | **11** | **+0.359** |
| P3 | 18.85 % | 2.04 % | **9.2x** | **2** | ~0 |

An ideal independent monitor at 5 % would yield **29.2/30** runs in band.

## Inferred

**Window matching was the right correction, and it was not sufficient.** P1 improved from 4/30 to
13/30 — the largest single improvement any scheme has produced — and its median run FAR moved from
0.00 % to 3.00 %, inside the band. The E18 window mismatch was therefore a real defect and fixing it
was worth doing. It simply was not the whole problem.

**P1 and P3 are limited by different mechanisms.** P1's alarms are temporally clustered
(lag-1 = +0.359), so 200 ticks behave like ~11 independent observations. P3's alarms are *not*
clustered (lag-1 ~ 0) yet its overdispersion is larger (9.2x, effective n = 2), which locates its
variance between runs rather than within them — consistent with the +0.909 baseline-offset
correlation measured in the E18 audit.

**This explains why R1 and R2 failed in opposite directions.** R1's per-run thresholds targeted P3's
mechanism and were defeated by estimation noise at n = 200. R2's pooled matched threshold helped P1,
whose mechanism is clustering, and removed the per-run adaptation that had been partially helping P3.
**Each scheme fixes one policy's mechanism and aggravates the other's.**

**No threshold can resolve either mechanism.** Both are properties of the score process. This is the
substantive conclusion of the E18 series.

## Hypothesised — not established

That an event-level alarm rule with persistence would recover P1. It targets the measured clustering
directly, but has not been tested, and its parameter would have to be pre-registered from the
autocorrelation structure rather than tuned against the resulting false-alarm rate.

That longer evaluation windows would recover P1. At 11 effective ticks per 200, matching an
independent 200-tick monitor implies roughly 3,600 ticks per run. This is arithmetic from the
measured effective sample size, not a demonstrated result.

## Confirmed predictions

`preregistration.md` §10 predicted the matched-window quantile would come out **lower** than v1,
because false alarms were concentrated early in the run at a fixed threshold. **Confirmed** for both
P1 (3.7095 -> 3.7024) and P3 (3.4000 -> 3.3953).

`preregistration.md` §3 recorded the expectation that **H1 holds for P1 and fails for P3**, on the
grounds that pooled calibration cannot correct a per-run offset. **Directionally confirmed** — P1
improved threefold, P3 did not improve — though P1's improvement fell short of the frozen bar.

## Deviations from the pre-registration

**None.** The window, estimator, eps, criterion and policies were all fixed in advance. No
alternative window was evaluated. P2 was computed for the record and is not claimed.
