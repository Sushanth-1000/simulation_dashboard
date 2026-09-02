# E18-R2 — Matched-Window Pooled Calibration

# VERDICT: PARTIAL-R2   |   GATE: DO NOT PROCEED TO E19

| | |
|---|---|
| Question | Does pooled calibration on the *matched* window (ticks 201–400) restore per-run stability? |
| Frozen criterion | P1 (positive control) >= 24/30 runs in band |
| **P1 result** | **13/30 -> PARTIAL-R2** (best of three schemes, still short) |
| P3 result | 2/30 -> **INVALID** |
| Thresholds (v3) | P1 **3.7024** · P3 **3.3953** · P2 6.0000 |
| Config hash | `a1dbf0fabb165fd5` |

## What R2 changed

Exactly one thing from E18 version 1: the calibration sample is drawn from **ticks 201–400** instead
of 0–399, matching the window the monitor is evaluated in. Same pooling, same estimator, same eps,
same seeds, **byte-identical score data** — so any difference is attributable to the window alone.

No new closed-loop runs were needed.

## Three schemes compared

| policy | v1 whole-run | v2 run-local | **v3 matched** |
|---|:--:|:--:|:--:|
| P1 runs in band /30 | 4 | 3 | **13** |
| P3 runs in band /30 | 5 | 9 | **2** |

**Best for P1, worst for P3** — because the two policies fail for different reasons.

## The decisive finding

An ideal monitor with independent ticks at 5 % would place **29.2/30** runs in band. The criterion is
achievable; the score process is what prevents it.

| policy | overdispersion vs binomial | effective ticks per run | alarm lag-1 autocorrelation |
|---|--:|--:|--:|
| P1 | **4.2x** | **11** of 200 | **+0.359** — alarms cluster |
| P3 | **9.2x** | **2** of 200 | ~0 — variance is between runs |

**P1 is limited by within-run alarm clustering; P3 by between-run baseline variation. Neither is a
calibration problem**, which is why three different calibration schemes could not fix either.

## Read in this order

1. `preregistration.md` — frozen criterion, and the expectation recorded before running
2. `analysis.md`
3. `limitations.md`
4. `final_decision.md` — **the verdict, the diagnostic, and the required repair**

## Next step

**Not another calibration scheme.** Repair B — longer evaluation windows — is a pure compute change
that discriminates between "not enough samples" and "wrong monitor" for both policies at once.
