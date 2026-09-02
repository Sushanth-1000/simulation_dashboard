# E18-R1 - Calibration Protocol

Complete mathematical definition. A reviewer should be able to reproduce this without reading the
implementation.

## Notation

For policy `p` and run `r`, let `s_{r,t}` be the STATISTICAL gate's `non_conformity_score` at tick
`t`, for `t = 1..400`. Fault onset, where applicable, is tick 200 (`_FAULT_FIRST`).

## Windows

    calibration window   W_r = { s_{r,t} : 1   <= t <= 200 }
    evaluation window    E_r = { s_{r,t} : 201 <= t <= 400 }

Non-overlapping, one window pair per run, no sliding, no re-estimation within a run.

`W_r` is clean by construction in both clean and faulted runs, since injection begins at tick 200.

## Threshold

    n_r = |{ t in W_r : s_{r,t} finite }|                    (nominally 200)
    k_r = ceil( (n_r + 1) * (1 - eps) ),      eps = 0.05
    q_r = s_(k_r)                             the k_r-th smallest value of W_r
    q_r = max(W_r)                            if k_r > n_r

This is the same finite-sample conformal order statistic used in E18, applied run-locally rather
than pooled. With `n_r = 200` and `eps = 0.05`, `k_r = 191`.

## Update frequency and scope

Estimated once, at tick 200, and held constant for the remainder of that run. **Thresholds are reset
per run and are run-specific.** Policy enters only through which runs exist; there is no
policy-level threshold under R1.

## Alarm rule and run-level false-alarm rate

    alarm at tick t  <=>  s_{r,t} > q_r ,   t in E_r

    FAR_r = |{ t in E_r : s_{r,t} > q_r }| / |E_r|      on a clean run

## Acceptance band

A run is **in band** iff `FAR_r` lies in `[eps/2, 2*eps] = [0.025, 0.10]`.

## Warm-up and transients

**Not discarded.** All 200 prefix ticks enter calibration, including the first tick of each run,
which classifies as `DEGRADED_SENSOR` rather than `URBAN_CLEAR`. Discarding a warm-up would improve
apparent stationarity and would be indistinguishable, from outside, from tuning.

## Why this window and no other

The length is fixed by `_FAULT_FIRST = 200`, set in E17 long before OD-8 calibration was examined.
It is the longest clean prefix available in a faulted run; it is causally realizable, since a
deployed system can calibrate on startup; and it contains no information from the evaluation window.
**No alternative window length was evaluated**, per section 6 of the brief.
