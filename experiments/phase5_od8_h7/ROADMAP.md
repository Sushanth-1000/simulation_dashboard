# ASTRA Roadmap - Phase 5 and beyond

**Updated 1 September 2026.** Stages are gated. A stage is not entered because it exists here.

## Current position

    E17  fault observability            COMPLETE - heterogeneous; 1 of 6 well-posed absorption
    E17-Position  corrected injection   COMPLETE - absorption withdrawn, 0 of 12 cells
    E18  OD-8 calibration               COMPLETE - verdict revised; P1 withdrawn
    E18-R1  run-local calibration       COMPLETE - FAIL-P3; found E18 window defect
    E18-R2  matched-window calibration  COMPLETE - PARTIAL-R2; obstacle is the score process
    E18-R3  longer evaluation windows   <-- NEXT, and blocking
    E19  H7 monitor placement           BLOCKED - no calibrated monitor exists
    E20  lying sensor                   FUTURE
    comma2k19 / highD / CARLA           NOT STARTED, correctly

## The blocking chain

    a calibrated monitor
        -> operational detection that means something
            -> monitor placement (H7 / E19)
                -> external validation (comma2k19, highD)
                    -> adversarial extension (E20)
                        -> closed-loop validation (CARLA)

**Nothing below the first line can proceed until it is satisfied.** E18-R1 established that it is
not currently satisfied for any policy on the evaluation window.

## E18-R2 - the immediate next experiment

**Question:** does pooled calibration on the *matched* window (ticks 200-399) produce per-run-stable
false-alarm behaviour?

**Why this and not something else:** R1 failed on estimator variance, not on window matching. E18
failed on window mismatch, not on sample size. E18-R2 is the only untested combination - large
sample, correct window. One experiment, no search, about four minutes of compute since the runs
already exist.

**Frozen criterion:** >= 24/30 runs in band for P1, the positive control, reported for P3.

**If E18-R2 fails**, the honest conclusion is that the current OD-8 formulation cannot support a
per-run-stable operational monitor at this eps on this plant, and the contribution reframes around
that demonstrated limitation rather than around monitor placement.

## What is not on the roadmap

Additional fault families, additional datasets, and any adversarial work, until the calibration
question is closed. More datasets do not increase novelty and cannot substitute for a working
measurement instrument.


## Update, 1 September 2026 - the E18 calibration series is closed

Three calibration schemes have been tried and the obstacle is now identified:

| scheme | P1 runs in band | P3 runs in band |
|---|:--:|:--:|
| v1 pooled, whole run | 4/30 | 5/30 |
| v2 run-local windowed | 3/30 | 9/30 |
| v3 pooled, matched window | **13/30** | 2/30 |
| *ideal independent monitor* | *29.2/30* | *29.2/30* |

**The limit is the score process, not the threshold.** P1's alarms cluster within runs (lag-1
autocorrelation +0.359, ~11 effective ticks of 200); P3's baseline varies between runs (~2 effective
ticks). Each scheme that addresses one mechanism aggravates the other. **No further calibration
variant is warranted.**

### E18-R3 - longer evaluation windows

A pure compute change: extend runs so the evaluation window carries the independent information a
200-tick window does not. At ~11 effective ticks per 200, matching an independent 200-tick monitor
implies roughly 3,600 ticks. This separates "not enough samples" from "wrong monitor" for both
policies at once, and needs no new rule pre-registered.

If R3 recovers P1, the finding is a precision limit and E19 becomes possible. If it does not, the
contribution reframes around the demonstrated limitation:

> A conformal score that separates faulted from clean runs at high AUC can still fail to support a
> per-run-stable operational monitor, because its alarm process is temporally clustered and its
> baseline varies between runs. Statistical discriminability, calibration validity and operational
> stability are three distinct properties.
