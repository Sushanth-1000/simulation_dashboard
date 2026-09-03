# E18-R3b — Pre-Registration

**Written 3 September 2026, before any faulted long run was executed.** Nothing below may be revised
after inspecting output.

---

## 1 · Why this experiment decides whether R3 was worth anything

E18-R3 established that P1 has stable clean-data behaviour at a 160-second window: 30/30 runs inside
the target false-alarm band. **That is half a monitor.** A monitor has two jobs — don't cry wolf, and
catch the wolf — and R3 tested only the first.

R3b tests the second, at the same window, against the same frozen threshold.

The prior is not encouraging on two of the six faults. At n = 200, E18 measured on P1:

| fault | detection at n=200 | mean score shift | shift / σ (σ = 0.0097) |
|---|--:|--:|--:|
| `position_bias` / `position_drift` | 100 % | large | large |
| `lateral_noise` | 90 % | +0.1425 | ≈ +14.7 |
| `speed_bias` | 57 % (93 % at high severity) | −0.0033 | ≈ −0.34 |
| `imu_dropout` | **3 %** | −0.0069 | ≈ **−0.71** |
| `speed_stuck` | 67 % | −0.0005 | ≈ **−0.05** |

**Three of these shifts are negative** — the fault moves the score *away* from the alarm region. That
is the alarm-suppression finding (11 of 28 cells, all p < 0.05), and a longer window should make
suppression *more* reliable, not less.

## 2 · Hypotheses

**H1:** at n = 3200, faults whose score shift is large and positive reach ≥ 90 % detection at the
frozen threshold, because a longer window resolves a persistent shift that 200 ticks could not.

**H2 (the suppression prediction):** faults whose shift is negative do **not** improve, and
`imu_dropout` detection stays at or below its n = 200 value. A longer window gives more evidence of a
shift in the wrong direction.

**H0:** detection does not improve for any fault, i.e. the longer window buys false-alarm stability
and nothing else. R3's PASS would then be of limited practical value.

## 3 · Design — one variable

**Independent variable: evaluation window length only.** Everything else matches E18's faulted
evaluation.

- Threshold: **frozen v3, P1 = 3.7024.** No recalibration. This module computes no quantile.
- Policy: **P1 only** — the one policy with a validated monitor. P2 and P3 are untouched.
- Faults: all six, at their **`medium`** severity, which is the E17-comparable level.
- Seeds: `20260731 + i`, i = 0..29 — the E18 fault-test set, so n = 200 results are directly
  comparable.
- Runs: **faulted arm only.** Clean behaviour at this window is already established by R3 (30/30 in
  band); re-running it would double the compute to re-measure a settled quantity.
- Window: ticks 200–3399, evaluated also at nested lengths 200/400/800/1600/3200 so the detection
  trend is visible, exactly as R3 did for false alarms.

## 3b · Amendment, made before execution

**The detection criterion in the first draft of this document was broken and is corrected here.**

That draft defined a run as *detected* if any tick alarmed. At a 5 % per-tick false-alarm rate, the
probability of at least one alarm over 200 ticks is ≈ 1.0, so **every run detects — including clean
ones.** A one-seed smoke test returned 100 % detection for all six faults, `imu_dropout` included,
which E18 measured at 3 %. The criterion was measuring window length, not faults.

**Corrected criterion.** A faulted run counts as detected if its **alarm rate exceeds the 95th
percentile of the clean per-run alarm-rate distribution** at the same window, taken from E18-R3's 30
clean P1 runs:

| window | clean median | **decision boundary (p95)** |
|---|--:|--:|
| 200 | 3.00 % | **18.50 %** |
| 400 | 3.87 % | **14.05 %** |
| 800 | 4.69 % | **11.08 %** |
| 1600 | 5.00 % | **8.86 %** |
| 3200 | 5.84 % | **7.25 %** |

This fixes the run-level false-positive rate at 5 % by construction, which is what makes detection
rates at different windows comparable.

It also exposes the mechanism the experiment is testing: **the boundary tightens from 18.5 % to
7.25 % as the window grows**, so a faulted run has a far lower bar to clear at n = 3200. If detection
improves, that is why.

**This amendment was made before any faulted long run was executed**, on the basis of a smoke test
that produced an obviously impossible result. It is a correction to a broken instrument, not a
change made after seeing an outcome. The boundary is derived from *clean* R3 data only; no faulted
data informed it.

## 4 · Criteria — frozen

**Primary:** number of faults reaching ≥ 90 % detection at n = 3200.

| faults ≥ 90 % | classification |
|---|---|
| **≥ 4 of 6** | **PASS-R3b** — the long window produces a useful monitor |
| 2 – 3 | **PARTIAL-R3b** |
| ≤ 1 | **FAIL-R3b** — R3's stability gain does not convert into detection |

**Secondary, and treated as a falsification test rather than a success:**

> **If `speed_stuck` or `imu_dropout` reaches ≥ 90 % detection, that is a red flag, not a win.**

Their shifts are −0.05σ and −0.71σ — away from the alarm region. No honest accumulation of evidence
recovers a signal that is both tiny and directionally wrong. Detection there would indicate the
longer window is producing alarms from drift or noise rather than from the fault, and would call the
whole result into question rather than improving it. This is stated now so it cannot be reported as
success later.

## 5 · Measurements

Per run: detection (any alarm in window), alarm rate, first-alarm latency in ticks and seconds,
threshold margin, and the per-tick score series.

**Per-tick scores are stored this time.** R3 stored only per-run summaries, which meant a corrected
threshold could not be evaluated without a fresh 35-minute run. At roughly 2–3 MB per experiment
that was a false economy, and it is corrected here.

## 6 · Confounders

- **Drift.** R3 measured drift/SD at 0.05 on P1's long clean runs, so the window itself is not
  drift-prone. Faulted runs are measured for drift too, and a faulted run whose drift/SD exceeds 1.0
  is flagged.
- **Longer exposure is not more fault.** The fault magnitude is unchanged; only observation time
  grows. A detection improvement therefore reflects statistical power, not a stronger fault.
- **Latency is not free.** A fault detected at tick 3,000 was undetected for 150 seconds. Detection
  rate alone would hide that, so latency is reported alongside and in seconds, not just ticks.

## 7 · Integrity checks

Delivered-signal check on every faulted run (`fault_reached_estimator`); frozen threshold hard-coded
and never recomputed; seed and policy identity recorded per run; expected sample counts; non-finite
scores counted; run is the unit of analysis.

## 8 · What R3b cannot establish

Anything about P2 or P3. Anything about severities other than `medium`. Anything about actionability
— whether firing improves the vehicle's behaviour is unmeasured and out of scope. And it remains
`[M-syn]`: one plant, simulation, `[M-ext]` still 0 of 30.

## 9 · Cost

180 faulted runs of 3,400 ticks. Roughly 50 minutes.
