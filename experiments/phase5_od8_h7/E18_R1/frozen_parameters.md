# E18-R1 - Frozen Parameters

# CALIBRATION VERSION 2 - "R1-v2-runlocal"

Frozen before evaluation. **Version 1 (E18 pooled) is not overwritten and remains on record.**

## Parameters

| parameter | value | fixed by |
|---|---|---|
| Scheme | run-local (windowed) | `preregistration.md` section 2 |
| Calibration window | ticks 1-200 of each run | `_FAULT_FIRST`, set in E17 |
| Evaluation window | ticks 201-400 | same |
| eps | 0.05 | carried unchanged from E18 |
| Estimator | `ceil((n+1)(1-eps))`-th order statistic | carried unchanged from E18 |
| Update frequency | once per run, at tick 200 | `calibration_protocol.md` |
| Threshold scope | per run | `calibration_protocol.md` |
| Policies | P1, P3 | P2 excluded per section 14 of the brief |
| Acceptance band | [2.5 %, 10 %] | carried unchanged from E18 |
| Success criterion | >= 24/30 runs in band | brief section 3, frozen |

## Realised thresholds

Because thresholds are per run, there is no single frozen value. The realised distribution:

| policy | mean | SD | min | max | E18 version-1 fixed threshold |
|---|--:|--:|--:|--:|--:|
| P1 | 3.7296 | **0.0251** | 3.7000 | 3.7853 | 3.7095 |
| P3 | 3.3996 | **0.0135** | 3.3840 | 3.4308 | 3.4000 |

Per-run values are in `run_manifest.csv`, one row per run.

**The SD of the per-run threshold is comparable to the entire threshold headroom** (P1 0.0235,
P3 0.0170). That is the quantitative reason R1 failed, and it is visible in this table.

## Version history

| version | scheme | status |
|---|---|---|
| 1 | E18 pooled, whole-run calibration | frozen; **P1 verdict revised** by the window defect |
| 2 | E18-R1 run-local | frozen; **FAIL-P3** |
| 3 | E18-R2 matched-window pooled | **proposed**, not yet run |
