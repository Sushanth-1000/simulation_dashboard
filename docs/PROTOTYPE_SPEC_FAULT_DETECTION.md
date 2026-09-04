# Prompt / Specification — ASTRA Fault-Detection Demonstrator

**Purpose:** build a runnable prototype that demonstrates the fault-detection capability of the
ASTRA runtime governance stack, suitable for a live major-project panel demonstration.

**Status of this document:** specification only. Hand this to an implementation session verbatim.

---

## 0 · Context the implementer must know

The ASTRA repository already contains a working nine-layer runtime governance stack and a
fault-injection testbed. **This prototype does not build new detection capability — it makes the
existing, already-measured capability visible and runnable in front of an audience.**

Existing components to reuse, not reimplement:

| what | where |
|---|---|
| Closed-loop driver | `training.closed_loop.drive_closed_loop(policy, ticks, seed, observer, fault, redundant)` |
| Transient fault injector (fault ends at tick 399) | `benchmarks.e18_evaluate._build_injector(fault, magnitude, seed)` |
| Sustained fault injector (fault runs whole window) | `benchmarks.e18r3c_sustained._injector_full(fault, mag, seed, ticks)` |
| Position-fault sensing path | `benchmarks.e18_evaluate._sensing` / `e18r3c_sustained._sensing_full` |
| Severity table | `benchmarks.e18_evaluate.SEVERITIES` |
| Run-level decision boundary | `benchmarks.e18r3b_detect.RUN_LEVEL_BOUND` |
| Trained policy | `var/policy/synthetic.pt` (this is P1) |

**Frozen constants that must be used and must NOT be recomputed:**

- L6 threshold for P1: **3.7024** (calibration version v3, from `E18_R2/processed_results/verdict.json`)
- Fault onset tick: **200** (`benchmarks.discriminability._FAULT_FIRST`)
- Control rate: **20 Hz**, so 3,200 ticks = 160 seconds
- Run-level decision boundary at n = 3200: **0.072484** (95th percentile of clean per-run alarm rate)

**How to read the non-conformity score from a tick:** the observer callback receives a `TickSample`.
The score lives in the STATISTICAL gate's evidence tuple:

```
sv = s.record.safety_verdict
for gv in sv.gate_verdicts:
    if str(gv.gate).endswith("STATISTICAL"):
        for k, v in gv.evidence:
            if k == "non_conformity_score":
                score = float(v)
```

---

## 1 · Objective

Produce a command-line prototype, `benchmarks/demo_detection.py`, that runs the real ASTRA pipeline
live and visualises what the L6 safety monitor sees while a sensor fault is active.

The demonstration must make three things legible to a non-specialist panel within ~90 seconds each:

1. **The monitor works** on faults it can detect.
2. **The monitor is silent** on faults it cannot — including for the entire duration of a persistent
   sensor failure.
3. **The difference is measurable and reproducible**, not anecdotal.

---

## 2 · Required demonstration scenarios

Implement exactly these five, selectable by a `--scenario` flag. All run on P1
(`var/policy/synthetic.pt`) at 3,400 ticks with the frozen threshold.

### Scenario A — `clean`
No fault. Establishes the baseline. Expected: alarm rate near 5 %, run-level verdict NO ALARM.

### Scenario B — `position_bias` (sustained, 1.0 m)
The success case. Expected: score rises well above threshold from shortly after tick 200 and stays
there; run-level verdict DETECTED; per-phase alarm rate 0.87 → 1.00.

### Scenario C — `lateral_noise` (sustained, ×25 σ)
Second success case, and the one that gets *stronger* over time. Expected: 0.41 during the first
200 ticks, rising to 1.00 in later phases; run-level verdict DETECTED.

### Scenario D — `imu_dropout` (sustained)
**The headline scenario.** A persistent IMU failure for 160 continuous seconds.
Expected: alarm rate ≈ 0.002 in every phase — *below* the clean baseline of ≈ 0.05. Run-level
verdict NO ALARM. The monitor is quieter than normal while the sensor is failing.

### Scenario E — `imu_dropout_transient`
Identical fault, but it stops at tick 399. Expected: alarm rate ≈ 0.004 during the fault, then
≈ 0.99 immediately afterwards. Run-level verdict DETECTED.

**Scenarios D and E side by side are the demonstration.** Same fault, same seed, same threshold;
the only difference is whether the fault ends. D is silent, E is loud. That contrast is the
project's central finding and it must be the visual centrepiece.

---

## 3 · Output requirements

### 3.1 Live terminal output

While the run executes, print a compact per-phase progress line. After completion, print a summary
block containing, for the run:

- fault name, injection mode (transient / sustained), severity, seed, policy
- frozen threshold used
- **phase-resolved alarm rate** for ticks 200–399, 400–999, 1000–1999, 2000–3399
- clean baseline alarm rate for comparison
- run-level alarm rate against the decision boundary 0.072484
- run-level verdict: **DETECTED** or **NO ALARM**
- mean non-conformity score per phase, and the threshold, so the margin is visible

### 3.2 A rendered time-series figure

Write an SVG to `results/DEMO/<scenario>.svg` showing:

- x-axis: tick (0 to 3,400), with a secondary label in seconds at 20 Hz
- y-axis: non-conformity score
- the per-tick score as a line
- a horizontal dashed line at the frozen threshold 3.7024, labelled
- a shaded vertical band marking the fault-active region
- for the transient scenario, a second shading style for the post-fault region
- annotation of the alarm rate in each phase

Use hand-written SVG (the project has no matplotlib in the measurement venv; see
`benchmarks/e18_final.py` for the existing SVG helper pattern to copy).

### 3.3 A side-by-side comparison figure

`--scenario compare` must run D and E on the same seed and produce
`results/DEMO/compare_sustained_vs_transient.svg` with two stacked panels sharing an x-axis, so the
silence-versus-alarm contrast is a single image.

---

## 4 · Technical requirements

- **Reuse the real pipeline.** The demo must call `drive_closed_loop` with the actual policy, twin,
  and gates. It must not simulate or replay stored scores.
- **Do not recompute any threshold.** Import or hard-code 3.7024 with a comment naming its source.
  The demo must contain no quantile computation.
- **Store per-tick scores** to `results/DEMO/<scenario>.json` so a figure can be regenerated without
  re-running.
- **Deterministic.** Default seed 20260731; a `--seed` flag may override. The same seed must give the
  same figure.
- **Runtime budget.** One 3,400-tick run takes roughly 15–20 s. `--scenario compare` runs two.
  Provide `--ticks` so a panel demo can be shortened if needed, but default to 3,400 and warn if a
  shorter run is used, because the 160-second window is load-bearing for the result.
- **Integrity check.** For every faulted run, verify the faulted arm differs from a clean arm at the
  estimator (compare mean estimated lateral position). Print PASS/FAIL. If FAIL, refuse to report a
  detection result — this is the project's standing rule and it must be enforced in code.

---

## 5 · Honesty constraints — these are requirements, not suggestions

The prototype must not overstate what ASTRA does. Specifically:

- **Never print "accuracy".** This is not a classification task. Report alarm rates and detection
  verdicts.
- **Never report a single aggregate detection rate without the phase breakdown.** A window-aggregate
  number hides the entire finding.
- **Always print the injection mode.** The same fault reads 99.1 % transient and 0.2 % sustained;
  a detection figure without the mode is not interpretable.
- **The summary must state the scope limits** in a footer line: policy P1 only, synthetic plant,
  160-second window, 3 of 6 faults detected under sustained injection.
- **Do not add a scenario for `speed_bias` or `speed_stuck` that implies detection.** If included at
  all, they must be labelled as undetectable by this monitor (0 % and 37 % respectively).

---

## 6 · Acceptance criteria

The prototype is complete when all of the following hold:

1. `python -m benchmarks.demo_detection --scenario clean` reports an alarm rate near 5 % and
   NO ALARM.
2. `--scenario position_bias` reports DETECTED with phase alarm rates rising to 1.00.
3. `--scenario lateral_noise` reports DETECTED with rates rising across phases.
4. `--scenario imu_dropout` reports **NO ALARM** with every phase alarm rate below the clean
   baseline.
5. `--scenario imu_dropout_transient` reports **DETECTED**, with the during-fault phase near 0.004
   and the following phase near 0.99.
6. `--scenario compare` produces a single two-panel SVG showing 4 and 5 together.
7. Every faulted run prints an integrity PASS.
8. All figures are valid SVG and render in a browser.
9. Numbers reproduce the values recorded in `experiments/phase5_od8_h7/E18_R3b` and `E18_R3c` within
   sampling variation for a single seed.

---

## 7 · Deliverables

- `benchmarks/demo_detection.py`
- `results/DEMO/*.svg` — one per scenario plus the comparison
- `results/DEMO/*.json` — per-tick scores for regeneration
- A short `results/DEMO/README.md` giving the exact commands to run each scenario during a
  panel demonstration, with expected output for each, so the presenter can verify before walking in.

---

## 8 · What this prototype is NOT

It is not a fault-detection product, not a real-time system, and not a claim that ASTRA detects
sensor faults in general. It is a faithful, reproducible demonstration of a measured capability and
a measured limitation, on one policy, in simulation.

The most important thing it demonstrates is the limitation.
