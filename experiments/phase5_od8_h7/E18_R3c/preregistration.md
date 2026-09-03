# E18-R3c — Pre-Registration (duration-matched control)

**Written 3 September 2026, before any run.** Nothing below may be revised after inspecting output.

---

## 1 · Why this experiment exists

E18-R3b found that four faults reach 100 % detection at a 160-second window, but that detection came
almost entirely from the **post-fault recovery transient**, not from the fault itself. The clearest
case: `imu_dropout` alarmed on 0.4 % of ticks *while the IMU was dropping out* (quieter than clean)
and 99.1 % of ticks immediately after it recovered.

That inference has one uncontrolled variable. In R3b the fault occupied only ticks 200–399 — 200 of
3,400 ticks. The rest of the window was recovery. **R3c removes that confound** by holding the fault
active for the entire evaluation window and comparing.

## 2 · The one change

`_build_injector` in `e18_evaluate.py` derives the fault's `last_tick` from `TICKS = 400`. R3c uses
a local builder that sets `last_tick = ticks - 1`, so the fault runs from tick 200 to the end of the
run. **Nothing else changes** — same frozen v3 threshold (P1 = 3.7024, not recomputed), same seeds,
same policy, same six faults at `medium` severity, same 3,400-tick runs, same run-level decision
boundary from R3's clean runs.

R3b (short fault, long window) and R3c (sustained fault) differ in exactly one thing: whether the
fault ever ends.

## 3 · Hypotheses — both informative, direction genuinely unknown

**H-aftermath** (R3b's mechanism is aftermath-only): a fault that never ends never produces an
aftermath, so `imu_dropout` detection stays **low** for the whole sustained window. This would mean a
**persistent sensor failure is permanently invisible to the monitor** — the sharpest safety finding
the project could produce.

**H-accumulation**: while the fault is active the estimator state stays corrupted continuously, and
the twin disagreement accumulates, so detection **rises over time** even without recovery. This would
mean the monitor eventually catches a sustained fault but is slow.

These make opposite predictions and I do not know which holds. That is the point of running it.

## 4 · Primary measurement — phase-resolved, as the ledger now requires

Per fault, mean score and alarm rate in nested windows measured **from fault onset**:
ticks 200–399, 400–999, 1000–1999, 2000–3399. The comparison of interest is R3c's during-fault
alarm rate against R3b's during-fault alarm rate at the same tick ranges.

**No single "detected" flag is treated as the result.** A window-aggregate rate is exactly what hid
the R3b mechanism, and the ledger now forbids it.

## 5 · Frozen criterion

This is a mechanism experiment, not a pass/fail gate. The pre-registered readings:

- If `imu_dropout` sustained-fault alarm rate stays **below 2×** the clean rate for the whole window
  → **H-aftermath supported**: sustained faults are invisible; R3b detection was aftermath.
- If it **rises past the run-level boundary** within the window → **H-accumulation supported**:
  sustained faults are eventually detected.
- `position_bias` / `position_drift` are the control: their score was already elevated *during* the
  fault in R3b, so sustained injection should keep them detected throughout. If it does not, the
  measurement is suspect.

## 6 · Integrity

Delivered-signal check on every run; frozen threshold hard-coded, never recomputed; per-tick series
stored; seed and policy identity recorded; drift/SD reported on each run. Fault is now active for the
whole window, so the `fault_reached_estimator` check applies to the whole window rather than a 200-
tick slice.

## 7 · What R3c cannot establish

Anything about P2/P3, other severities, or actionability. `[M-syn]` throughout. And it cannot
establish *why* the estimator behaves as it does — only whether a sustained fault is detected. The
mechanism at the estimator level would need L2-internal instrumentation this experiment does not add.

## 8 · Cost

180 faulted runs of 3,400 ticks with the fault active throughout. ~50 minutes.
