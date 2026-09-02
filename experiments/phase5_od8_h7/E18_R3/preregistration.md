# E18-R3 — Pre-Registration

**Written 3 September 2026, before any long run was executed.** Nothing below may be revised after
inspecting R3 output. A forced revision is reported as a deviation in `analysis.md`.

---

## 1 · The question

E18-R2 closed the calibration series: three schemes, best result 13/30 runs in band for P1 against
29.2/30 for an ideal monitor with independent ticks. The obstacle was located in the **score
process** rather than the threshold:

| policy | overdispersion vs binomial | effective ticks (of 200) | alarm lag-1 autocorr. |
|---|--:|--:|--:|
| P1 | 4.2x | 11 | +0.359 |
| P3 | 9.2x | 2 | ~0 |

Two explanations remain, and they have different consequences:

**A — precision-limited.** 200 ticks simply do not carry enough independent information. A longer
evaluation window would fix it, and the conformal score is usable.

**B — dynamics-limited.** The score's baseline wanders, or its correlation structure is such that
more ticks buy proportionally less. No window length fixes it, and the score is unsuitable as a
per-tick operational monitor.

**R3 discriminates A from B. That is its only job.**

## 2 · Hypotheses

**H1 (precision-limited):** per-run false-alarm rate variance falls as `1/sqrt(n)` with evaluation
window length, and P1 reaches the target band on at least 24 of 30 runs at the longest window.

**H0 (dynamics-limited):** per-run FAR variance plateaus above the level a binomial would predict,
and P1 does not reach 24/30 at any tested window length.

Both are live. The measured autocorrelation (+0.359 on P1) is consistent with A; the measured
between-run baseline spread (0.0132 on P1, 0.0277 on P3) is consistent with B.

## 3 · Design — one variable

**Independent variable: evaluation window length. Nothing else changes.**

- Threshold: the **frozen v3 values** from E18-R2, `P1 = 3.7024`, `P3 = 3.3953`. **No recalibration.**
  Recalibrating on longer runs would change calibration sample size *and* evaluation window
  simultaneously, and the result would be uninterpretable.
- eps = 0.05, estimator, scheme, acceptance band `[2.5 %, 10 %]`: all unchanged.
- Seeds: `20261001 + i`, i = 0..29 — the same clean-test seeds used in E18 and E18-R2, so the short
  windows reproduce the earlier numbers as an internal consistency check.
- Policies: **P1 and P3**. P2 is excluded and untouched, as in R1 and R2.

**One set of long clean runs, analysed at nested window lengths.** Runs are 3,400 ticks; the
evaluation window starts at tick 200 (the injection point in the faulted protocol, kept for
comparability) and is truncated to lengths:

    n in {200, 400, 800, 1600, 3200}

Nested windows share data, so the points are not independent of one another. They are not treated as
independent: the analysis reads the **trend**, and the 200-tick point is a reproduction check, not a
new observation.

## 4 · Primary criterion — frozen

**P1 runs in band at n = 3200:**

| runs in band (of 30) | classification |
|---|---|
| **>= 24** | **PASS-R3** — precision-limited. The conformal score is usable with a longer window |
| 12 – 23 | **PARTIAL-R3** — improving but not sufficient |
| < 12 | **FAIL-R3** — dynamics-limited |

P3 is reported at the same windows but is **secondary**; its dominant mechanism is between-run
baseline variation, which no window length addresses, and a P3 failure is therefore expected under
both H1 and H0 and discriminates nothing.

## 5 · The diagnostic that carries the scientific content

Counting runs in band is coarse. The mechanism test is the **scaling exponent**:

    fit  log SD(FAR_r)  =  a + b * log n

- **b ~ -0.5** — variance falls as `1/sqrt(n)`. Independent-sample behaviour. **Supports A.**
- **b ~ 0** — variance does not fall with more data. **Supports B.**
- **-0.5 < b < -0.1** — partial pooling; correlated but not degenerate. Report the value, do not
  round it to a story.

Reported alongside: realised `n_eff` at each window, and the ratio of observed to binomial FAR
variance.

## 6 · Confounder that must be measured, not assumed

**Longer runs may drift more.** P2 failed E18 on within-run drift (drift/SD = 1.28). If P1 develops
comparable drift at 3,400 ticks, then lengthening the window introduces the very mechanism it was
meant to escape, and the two are entangled.

**Mandatory measurement:** drift/SD computed on the long P1 and P3 runs, using the same first-half
versus second-half statistic as E18. If drift/SD exceeds 1.0 on P1, **R3 is reported as
INCONCLUSIVE rather than as a negative result** — the design could not isolate its variable.

## 7 · Integrity checks

| check | method |
|---|---|
| Frozen threshold used unchanged | hard-coded from `E18_R2/processed_results/verdict.json` |
| No recalibration | R3 contains no quantile computation |
| Seed identity preserved | recorded per run |
| Expected sample counts | 30 runs per policy, 3,400 ticks each, non-finite counted |
| Short-window reproduction | n = 200 must reproduce E18-R2's per-run FAR within sampling error |
| Run is the unit | FAR computed per run; pooled reported as supplementary only |

## 8 · What R3 cannot establish

That the monitor is useful. R3 is a clean-data false-alarm-stability experiment. Detection is not
measured, and a PASS licenses only the statement that longer windows restore controlled clean
behaviour on P1.

It also cannot rule out that 3,400 ticks is outside the plant's realistic operating envelope. A
window that only works at a length no real drive reaches is a negative result wearing a positive
result's clothes, and §6's drift check is the guard against reporting it as a win.

## 9 · Cost

60 clean runs of 3,400 ticks. No faulted runs — detection is not this experiment's question.
