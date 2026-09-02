# Phase 5 - Current Status

**Updated 1 September 2026**

| | |
|---|---|
| Active experiment | **E18 - OD-8 calibration** |
| Stage | Part 1 (calibration) complete; Part 2 (fault evaluation) running |
| E18 verdict so far | **PARTIAL** |
| E19 | Gated - may proceed on **P1 and P3 only** |
| E20 | Future |

## What E18 established

**Root cause of OD-8.** All three policies classify 99.75 % of ticks as `URBAN_CLEAR`. That context's
legacy corpus spans 3.8776-5.4380 while live clean scores span 2.40-7.45 with policy means of 3.686,
4.781 and 3.383. Conformal validity requires exchangeability between calibration and test data; it
did not hold.

**Corpus context scales differ by two orders of magnitude:**

| context | n | min | median | max |
|---|--:|--:|--:|--:|
| HIGHWAY_CLEAR | 1000 | 0.0785 | 0.0888 | 3.7144 |
| **URBAN_CLEAR** | 1000 | **3.8776** | **5.3199** | **5.4380** |
| DEGRADED_SENSOR | 1000 | 0.0782 | 0.1043 | 5.4031 |

**Clean score behaviour differs enormously by policy:**

| policy | mean | SD | frozen quantile | clean FAR (held out) | headroom |
|---|--:|--:|--:|--:|--:|
| P1 | 3.6860 | 0.0222 | **3.7095** | 5.47 % | 0.0235 |
| P2 | 4.7807 | 0.9220 | **5.9024** | 4.68 % | 1.1217 |
| P3 | 3.3830 | 0.0124 | **3.4000** | 8.23 % | 0.0170 |

P1 and P3 are near-deterministic; P2's spread is 40-75x larger.

**A global threshold reproduces OD-8 exactly** (q = 5.6449): 0.00 % clean false alarms on P1 and P3,
11.06 % on P2. This is why the defect is a policy-conditioning failure rather than a bad value.

**P2 fails the drift criterion.** First-half mean 4.1902, second-half 5.3711, drift/SD = 1.28. This
also retrospectively explains an earlier reading: P2 measured ~5.15 over ticks 200-400 and 2.56-4.46
over ticks 0-200. That was drift, not a regime property -- further undermining the already-withdrawn
H-regime claim.

## Immediate next steps

1. Complete E18 Part 2: detection probability, latency and threshold margin at the frozen thresholds,
   six faults x three severity levels x 30 seeds x 3 policies.
2. Write `final_decision.md` with the E19 gate decision.
3. Only then design E19, restricted to P1 and P3.
