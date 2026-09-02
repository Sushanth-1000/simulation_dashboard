# E18-R1 — Pre-Registration

**Written before any R1 result existed.** Nothing below may be revised after inspecting R1 output.
A revision, if forced, is reported as a deviation in `analysis.md`, never as the original plan.

---

## 1 · Frozen success criterion

Carried unchanged from the brief:

| runs in band (of 30) | classification |
|---|---|
| **>= 24** | **PASS-P3** — P3 operationally VALID under the R1 protocol |
| 12 – 23 | **CONDITIONAL-P3** |
| < 12 | **FAIL-P3** |

"In band" means a run's false-alarm rate lies in **[eps/2, 2*eps] = [2.5 %, 10 %]**, the same band
used in E18. Unit of analysis is the **run**. Pooled tick-level FAR is reported as supplementary only.

## 2 · The window is not searched — it is determined

Per section 6 of the brief, no window-size search is performed. **Exactly one window definition is
run.**

**Definition: the run-local pre-injection prefix — ticks 0..199 of each run.**

The length is **not a free parameter**. It is fixed by `_FAULT_FIRST = 200`, the fault-onset tick set
in E17 long before OD-8 calibration was examined. Three consequences follow without any appeal to R1
outcomes:

1. **It is the longest clean prefix available in a faulted run.** Any longer window would include
   post-injection ticks and contaminate calibration with fault data.
2. **It is causally realizable.** A deployed system can calibrate on startup and then monitor; a
   threshold estimated from the whole run could not be computed before the run ended.
3. **It contains no future information relative to the evaluation window** (ticks 200..399).

**No alternative window length is evaluated.** If R1 fails, the failure is reported; a second window
length would be a new pre-registered experiment (E18-R2), not a retry.

## 3 · Calibration procedure — complete mathematical definition

For policy `p`, run `r` with per-tick scores `s_{r,1..400}`:

**Calibration window** `W_r = {s_{r,t} : 1 <= t <= 200}`, non-overlapping with the evaluation window,
one window per run, no sliding.

**Calibration sample size** `n_r = |{t in W_r : s_{r,t} finite}|`, nominally 200.

**Threshold** — the same finite-sample conformal order statistic as E18, applied run-locally:

    k_r = ceil((n_r + 1) * (1 - eps)),    eps = 0.05
    q_r = s_(k_r)  , the k_r-th value of W_r sorted ascending
    q_r = max(W_r) if k_r > n_r

**Update frequency:** once per run. The threshold is estimated at tick 200 and held constant for the
remainder of the run. **Thresholds are reset per run and are run-specific rather than
policy-specific**; policy enters only through which runs exist.

**Evaluation window** `E_r = {s_{r,t} : 201 <= t <= 400}`.

**Run-level false-alarm rate** on a clean run: `FAR_r = |{t in E_r : s_{r,t} > q_r}| / |E_r|`.

**Warm-up:** none discarded. All 200 prefix ticks enter calibration, including the first tick, which
classifies as `DEGRADED_SENSOR` rather than `URBAN_CLEAR`. Discarding a warm-up would improve apparent
stationarity and is indistinguishable from tuning.

**Transients:** not treated specially, for the same reason.

## 4 · Data separation

    per-run prefix (ticks 1..200, clean by construction)
        -> run-local threshold q_r
        -> FROZEN for that run
        -> evaluation on ticks 201..400 of the same run
        -> clean runs give FAR; faulted runs give detection

Calibration for a faulted run uses **that run's own pre-injection ticks**, which are clean because
injection begins at tick 200. No future data, no fault data, no other run's data, and no test outcome
enters any threshold.

## 5 · Datasets

| set | seeds | use |
|---|---|---|
| CLEAN TEST | `20261001 + i`, i = 0..29 | primary criterion — run-level FAR |
| FAULT TEST | `20260731 + i`, i = 0..29 | secondary — detection after recalibration |
| CALIBRATION (E18) | `20260901 + i` | **not used by R1** — R1 calibrates run-locally |

The E18 pooled calibration set becomes unnecessary under R1. It is retained untouched.

## 6 · Policies

R1 runs on **P1 and P3**.

- **P3** is the subject of the primary criterion.
- **P1** is the positive control: it already passes under E18 pooled calibration (21/30), so R1 must
  not *break* it. A P1 result below 21/30 would indicate the run-local estimator is too noisy, and is
  interpreted as evidence against H1 rather than as a P1 finding.
- **P2 is excluded and untouched**, per section 14 of the brief. It is not tuned for, not pooled, and
  not rescued. Its INVALID status stands.

## 7 · Integrity checks required before any result is accepted

Injection: faulted differs from clean at the delivered signal; intended modality modified; estimator
receives it; downstream extraction sees it.
Calibration: prefix contains no post-injection tick; no cross-run leakage; no fault-test
contamination; threshold fixed before that run's evaluation window is scored.
Run: exactly 30 runs per policy per condition; seed and policy identity preserved; no duplicates; no
missing runs; no stale samples.
Statistical: FAR computed per run; pooled tick-level FAR supplementary only; confidence intervals at
the run level; no pseudo-replication.

A failed check marks the affected result **INVALID**.

## 8 · Secondary analyses, specified now

1. E18 vs E18-R1 comparison on: pooled FAR, median run FAR, FAR IQR, runs in band, drift/SD,
   **threshold variability** (SD of `q_r` across runs — new under R1, undefined under E18).
2. Whether R1 genuinely improves *stability* or merely shifts the aggregate. The distinguishing test:
   does the **IQR of run-level FAR narrow**, not just the median move?
3. P3 bimodality mechanism (`audit_of_E18.md` §10) — does run-local calibration remove the
   correlation between run baseline and run FAR?
4. Detection and alarm suppression after recalibration. **Reported, never optimised.**

## 9 · What would make R1 INVALID rather than FAIL

Integrity failure; fewer than 30 runs per cell; discovery that the prefix window contains
post-injection data; or any evidence that a threshold was influenced by an evaluation outcome.

## 10 · Limitations accepted in advance

`n_r ~ 200` autocorrelated ticks is a small conformal calibration sample; the coverage guarantee is
correspondingly weak. One plant, two policies, simulation only — `[M-syn]`, `[M-ext]` remains 0 of 30.
Run-local calibration assumes the pre-injection prefix is representative of the post-injection window
under clean conditions; for P2 that assumption is known false, which is why P2 is excluded.
