# Build Prompt — ASTRA Live Runtime Demonstrator

**Hand this document to an implementation session verbatim.** It specifies a laptop-runnable,
panel-operable live demonstration of the currently implemented ASTRA runtime stack.

---

## 0 · The single most important instruction

**Do not build a simulation of ASTRA. Drive the real ASTRA.**

The trained checkpoints, the nine-layer runtime stack, the fault injectors and the calibrated
threshold all exist in this repository and all run on CPU in real time. A surrogate controller or a
re-implemented gate would be both weaker and dishonest in front of a panel. Every layer value shown
in the dashboard must come from an actual pipeline execution.

The only thing you are building is a **renderer and a control surface**. The computation already
exists.

---

## 1 · What already exists (use these, do not recreate)

### 1.1 Runtime entry point

```python
from training.closed_loop import drive_closed_loop

drive_closed_loop(
    policy=...,        # LearnedPolicy
    ticks=...,         # int
    seed=...,          # int
    observer=...,      # callable(TickSample) -> None, invoked once per tick
    fault=...,         # FaultInjector | None
    redundant=...,     # RedundantSensing | None
)
```

### 1.2 Trained artefacts (real, load them)

| artefact | path | what it is |
|---|---|---|
| PPO policy (P1) | `var/policy/synthetic.pt` | the actual trained Core-A proposer, loaded via `astra.layers.l4_proposer.learned.LearnedPolicy.load(Path(...))` |
| PINN twin | `var/twin/synthetic.pt` | the actual trained L5 physics twin |
| Calibration corpus | `var/calibration/synthetic.json` | the actual L6 conformal corpus |

Two further policies exist (`long.pt`, `jerkscaled.pt`) — expose them in a dropdown but default to
`synthetic.pt`, which is the only one with a validated calibration.

### 1.3 The frozen L6 threshold

**P1 threshold = 3.7024**, calibration version v3, source
`experiments/phase5_od8_h7/E18_R2/processed_results/verdict.json`.

Hard-code it with a comment naming that source. **The demo must contain no quantile computation.**
Recomputing a threshold live would silently invalidate the comparison with the recorded experiments.

### 1.4 Fault injection API — supports live injection natively

```python
from training.faults import FaultInjector, bias, drift, stuck_at, noise_burst, dropout, FaultChannel

injector.is_active(tick) -> bool
injector.drops_reading(tick) -> bool
injector.corrupt(payload, *, tick) -> dict[str, float] | None
injector.arm(spec) -> None          # <-- arms a new fault spec at runtime
```

`arm()` is the mechanism for live injection. Construct a `FaultInjector` with no specs at run start,
hold a reference to it, and call `arm(...)` from the UI thread when the operator presses **Inject
Fault**. No wrapper class is needed.

For the two **position** faults, injection is not through `FaultInjector` — it goes through the
redundant sensing path:

```python
from training.closed_loop import RedundantSensing, DEFAULT_CHANNEL_SIGMAS
from astra.kernel.enums import SensorModality

RedundantSensing.build(
    sigmas=DEFAULT_CHANNEL_SIGMAS, seed=seed,
    faulted=SensorModality.IMU, also_faulted=(SensorModality.GPS,),
    opens_at=<tick>, bias=<metres>, drift_per_tick=<metres per tick>,
)
```

This asymmetry is real and important: it is why a position fault was inert for 17 days in this
project. **Surface it in the UI** — the fault panel should show which injection path each fault
class uses.

### 1.5 Severity values already defined

`benchmarks.e18_evaluate.SEVERITIES` — use these exact values so the demo is comparable with the
recorded experiments:

| fault | low | medium | high | unit |
|---|--:|--:|--:|---|
| `position_bias` | 0.25 | 1.0 | 2.0 | m |
| `position_drift` | 0.5 | 2.0 | 4.0 | m final |
| `speed_bias` | 0.75 | 3.0 | 6.0 | m/s |
| `lateral_noise` | 5.0 | 25.0 | 50.0 | × σ |
| `speed_stuck` | — | (no magnitude parameter) | — | — |
| `imu_dropout` | — | (no magnitude parameter) | — | — |

**`speed_stuck` and `imu_dropout` have no severity axis.** Grey out the severity control for them
and show a tooltip saying so. Do not invent a severity scale — that would be fabrication.

---

## 2 · The DecisionRecord is the observability contract

Every tick, the observer receives a `TickSample` whose `.record` is a `DecisionRecord`. Its fields
map **one-to-one onto the nine layers**. This is the core insight of the demo: ASTRA already emits a
complete per-tick audit record, and the dashboard is a renderer for it.

| layer | field on `TickSample` / `.record` | what to display |
|---|---|---|
| — | `sample.tick`, `sample.speed_mps`, `sample.lane_deviation_m` | vehicle telemetry |
| — | `sample.measured_position_m`, `.measured_speed_mps`, `.measured_lateral_acceleration_mps2` | raw sensor readings (post-injection) |
| **L1** | `record.frame_health` — tuple of `(SensorModality, StreamHealth)` | per-channel health; NORMAL / DEGRADED / FAULT |
| **L2** | `record.fast_state` (`.mean`, `.covariance`), `record.fast_innovation` | estimated x/y/v/a; Mahalanobis distance |
| **L3** | `record.trust` (`.context_class`, trust index) | URBAN_CLEAR / HIGHWAY_CLEAR / DEGRADED_SENSOR |
| **L4** | `record.proposal` (`.command.values`, `.source.layer`) | π_prop steering + acceleration |
| **L5** | `record.prediction`, `record.prediction_admissible`, `record.twin_weights_digest` | π_twin, admissibility |
| **L6/L7** | `record.safety_verdict.gate_verdicts` | three gates: STATISTICAL, PHYSICAL, DETERMINISTIC — each has `.gate`, `.verdict`, `.evidence` |
| **L8** | `record.failsafe` | fail-safe posture |
| **L9** | `record.arbitration`, `record.issued` | final arbitration decision and issued command |

**Extracting the L6 non-conformity score and quantile:**

```python
score = quantile = float("nan")
sv = record.safety_verdict
if sv is not None:
    for gv in sv.gate_verdicts:
        if str(gv.gate).endswith("STATISTICAL"):
            for k, v in gv.evidence:
                if k == "non_conformity_score":
                    score = float(v)
                elif "quantile" in str(k):
                    quantile = float(v)
```

Note: `TickSample.live_score` is populated **only** when the FB2 shadow path runs, which this demo
does not enable. Read the score from the gate evidence as above. (Getting this wrong produced an
empty L6 column in an earlier experiment.)

---

## 3 · Architecture of the demonstrator

### 3.1 Dependency constraint — read this before choosing a framework

This repository has **deliberate lockfile discipline**. The measurement virtual environment is
pinned (numpy 2.5.1, torch 2.13.0) because every recorded latency and gate measurement was taken
against it. Adding Streamlit, Dash, Flask or matplotlib to that environment would put the recorded
results in question.

**Therefore: backend uses the Python standard library only** (`http.server`, `json`, `threading`,
`queue`), plus what ASTRA already imports. **Frontend is vanilla HTML/CSS/JS in a single file.** No
build step, no npm, no new pip installs.

This is not a limitation to work around — it is a requirement, and it also makes the demo trivially
runnable on any machine that can already run the project.

### 3.2 Process model

```
main thread
  └── http.server on 127.0.0.1:8765
        ├── GET  /            → serves the single-page dashboard
        ├── GET  /events      → Server-Sent Events stream of per-tick JSON
        └── POST /control     → {start|pause|reset|step|inject|clear|scenario}

worker thread
  └── drive_closed_loop(..., observer=push_to_queue)
        observer serialises each TickSample into a dict and puts it on a queue
        a pacing gate in the observer sleeps to hold ~20 Hz wall-clock
        (real ASTRA runs faster than real time; the demo must be watchable)
```

**Pacing:** the observer should sleep so ticks emit at roughly 20 Hz wall-clock, matching the
declared control rate. Provide a `--speed` multiplier (0.5×, 1×, 2×, 5×) so the operator can
accelerate the 160-second scenario during a demo.

**Pause/step:** implement with a `threading.Event`. The observer blocks on it. Step = set-then-clear.

**Reset:** terminate the worker, construct a fresh `FaultInjector` and `RedundantSensing`, restart.

### 3.3 Per-tick JSON contract

Emit exactly this shape on `/events`. Keep it flat and stable — the frontend depends on it.

```json
{
  "tick": 412,
  "t_sec": 20.6,
  "vehicle": {"speed": 11.42, "lateral": -0.31, "heading": 0.014,
              "accel": 0.08, "steer": -0.021},
  "sensors": {"imu_accel": 0.081, "imu_rate": 0.004,
              "gps_x": 231.4, "gps_y": -0.29, "gps_v": 11.40,
              "lidar_lane": -0.30, "can_speed": 11.41},
  "L1": {"status": "NORMAL", "health": {"IMU": "HEALTHY", "GPS": "HEALTHY",
         "LIDAR": "HEALTHY"}, "stale_ms": 12.0},
  "L2": {"status": "ACTIVE", "est_x": 231.3, "est_y": -0.30, "est_v": 11.40,
         "est_a": 0.08, "innovation": 0.1642},
  "L3": {"status": "ACTIVE", "context": "URBAN_CLEAR", "trust": 0.94},
  "L4": {"status": "ACTIVE", "steer": -0.021, "accel": 0.08},
  "L5": {"status": "ACTIVE", "steer": -0.019, "accel": 0.08, "delta": 0.0021},
  "L6": {"status": "PASS", "score": 3.6871, "threshold": 3.7024,
         "margin": -0.0153},
  "L7": {"status": "PASS", "speed_ok": true, "lat_accel_ok": true,
         "jerk_ok": true},
  "L8": {"status": "NORMAL", "posture": "NOMINAL"},
  "L9": {"status": "ACTIVE", "issued_steer": -0.021, "issued_accel": 0.08,
         "modified": false},
  "fault": {"active": false, "name": null, "channel": null,
            "severity": null, "path": null, "ticks_active": 0},
  "log": ["L6 — conformal gate evaluated: PASS (3.6871 < 3.7024)"]
}
```

`"modified"` on L9 is important: it is `true` when the issued command differs from π_prop. That is
the visual proof that Core-A does not drive the vehicle directly.

---

## 4 · Dashboard layout

Single page, dark professional theme, no scrolling during a demo. Six regions:

```
┌──────────────────────────────┬──────────────────────────────────────────┐
│  1  VEHICLE (2D top-down)    │  4  ASTRA PIPELINE  L1→L9 vertical       │
│     road, lane, car, trail   │     each layer: name, status chip,       │
│     speed / lateral / heading│     2-3 live values, highlight active    │
│     [START][PAUSE][STEP][RST]│     CORE-A ▓ boundary ▓ CORE-B shading   │
├──────────────────────────────┤                                          │
│  2  SENSORS                  │                                          │
│     IMU / GPS / LIDAR / CAN  │                                          │
│     health chips             ├──────────────────────────────────────────┤
├──────────────────────────────┤  5  GRAPHS (two stacked, shared x-axis)  │
│  3  FAULT INJECTION          │     (a) L6 non-conformity vs threshold   │
│     [fault ▾][severity ▾]    │     (b) L2 Mahalanobis distance          │
│     [channel ▾][duration]    │     fault region shaded                  │
│     [INJECT] [CLEAR]         ├──────────────────────────────────────────┤
│     FAULT ACTIVE banner      │  6  AUDIT TRAIL (scrolling, timestamped) │
│     injection path shown     │     + TEST RESULTS table                 │
└──────────────────────────────┴──────────────────────────────────────────┘
```

**Graph (a) is the centrepiece.** It must make the blind-spot finding legible: the score line, the
frozen threshold as a dashed horizontal, and the fault-active region shaded. When the operator
injects a sustained `imu_dropout`, the panel should *see* the line stay flat and below the threshold
while the shaded region is active.

**Graph (b) is the argument.** Mahalanobis distance at L2 responds to faults that L6 does not. That
side-by-side is the visual form of the project's central finding: evidence exists at one stage and
does not produce an operational alarm at another.

Draw both graphs on `<canvas>` with plain JS. No charting library.

---

## 5 · Scripted demonstrations

Three buttons, each a scripted sequence over the live pipeline.

### DEMO 1 — Normal driving  (~40 s)
No fault. Establishes what healthy looks like: all layers green, L6 score sits just under threshold,
L9 issues π_prop unmodified.

### DEMO 2 — Detected fault  (~60 s)
Inject `position_bias` at medium (1.0 m) at a chosen tick. Expected and observable: the score rises
clearly above threshold, L6 flips to VETO, L8 changes posture, L9 shows `modified: true` and issues a
different command from π_prop. **This is the "it works" demo.**

### DEMO 3 — Monitor blind spot  (~90 s)  ← the important one
Inject **sustained `imu_dropout`**. Expected and observable: L1 shows the IMU degraded, L2's
Mahalanobis distance moves, and **L6 keeps saying PASS** while the fault-active region is shaded on
the graph. No fallback triggers.

Then, still running, **clear the fault**. The score jumps and L6 fires — *after* the hazard has
passed.

**This contrast, live, is the entire contribution of the project.** Build the UI so the operator can
narrate it: fault in → monitor silent → fault out → monitor alarms.

### Labelling requirement for DEMO 3

Display persistently while it runs:

> **Illustrative live demonstration of the observed monitor-blind-spot mechanism.**
> Recorded experimental values (0.2 % alarm rate under 160 s sustained dropout, against a ~5 % clean
> baseline, n = 30 seeds) come from experiment E18-R3c. This single live run demonstrates the
> mechanism; it does not reproduce that experiment.

**Do not print the recorded research numbers as if the live run produced them.** The live run
produces its own numbers; show those, and cite the recorded ones separately as context.

---

## 6 · Honesty labelling — required, not optional

Every element in the UI carries one of three badges:

| badge | meaning | examples |
|---|---|---|
| **REAL** (green) | actual ASTRA code executing | all nine layers, PPO policy, PINN twin, conformal gate, fault injectors, frozen threshold, DecisionRecord values |
| **DEMO** (amber) | presentation-layer simplification | 2D road rendering, wall-clock pacing, colour choices, the audit-trail formatting |
| **PLANNED** (grey) | not implemented, shown for context only | self-trust plane, monitorability metric, phase-aware detector, E19, E20, comma2k19, CARLA |

If the demo is built as specified, **almost everything is REAL** — that is the point, and it is a
much stronger position in front of a panel than a mock-up.

Include a persistent footer:

> This demonstration executes the actual ASTRA runtime stack on a synthetic driving plant.
> Components labelled DEMO are presentation-layer only. Components labelled PLANNED are future work
> and are not implemented.

A **PROJECT STATUS** panel (collapsible) shows completed / in-progress / next / future exactly as
recorded in `experiments/phase5_od8_h7/EXPERIMENT_INDEX.md`, clearly framed as *project* status and
not simulation functionality.

---

## 7 · Test results table

Columns: Test · Fault · Injection path · Detected · Safety response · Status.

Populate it **from live runs only.** A row appears when the operator runs that fault. Detection is
computed by the demo's own logic: did L6 VETO at any point while the fault was active?

**Do not pre-populate with recorded experimental results.** If you want recorded values visible, put
them in a separate, clearly headed column or panel titled *"Recorded (E18-R3b / R3c, n = 30)"* so
the two can never be confused.

Also display the honest scope line beneath the table:

> Recorded scope: policy P1 only, synthetic plant, 160-second window. 3 of 6 faults detected under
> sustained injection; `speed_bias` and `speed_stuck` are not detected by this monitor at any tested
> severity.

---

## 8 · Deliverables

```
demo/
├── server.py              stdlib HTTP + SSE; drives drive_closed_loop in a worker thread
├── bridge.py              TickSample → JSON contract (section 3.3); the only serialisation point
├── scenarios.py           DEMO 1/2/3 scripted sequences
├── static/
│   ├── index.html         single-page dashboard
│   ├── app.js             SSE client, canvas graphs, control POSTs
│   └── style.css          dark professional theme
└── README.md              run instructions, panel script, REAL/DEMO/PLANNED matrix
```

Run with:

```bash
.venv/Scripts/python.exe -m demo.server
# then open http://127.0.0.1:8765
```

---

## 9 · Acceptance criteria

1. Dashboard opens, vehicle moves, all nine layers show live values from a real pipeline run.
2. Every L1–L9 value is traceable to a named `DecisionRecord` field — no value is synthesised in the
   frontend.
3. The L6 threshold displayed is exactly **3.7024** and appears nowhere as a computed quantity.
4. Injecting `position_bias` (medium) produces a visible score rise, an L6 VETO, and `L9.modified =
   true`.
5. Injecting sustained `imu_dropout` produces L1 degraded, L2 Mahalanobis movement, and **L6
   remaining PASS** throughout the fault-active region.
6. Clearing that fault produces a score spike and an L6 VETO *after* the fault region ends.
7. The severity control is disabled for `speed_stuck` and `imu_dropout`, with an explanatory tooltip.
8. The fault panel shows which injection path each fault uses (FaultInjector vs RedundantSensing).
9. Pause, step and reset all work without restarting the server.
10. No new packages are installed into the measurement venv. `pip freeze` is unchanged.
11. Every UI element carries a REAL / DEMO / PLANNED badge, and the footer disclaimer is present.
12. Closing the browser does not leave a worker thread running.

---

## 10 · What this demonstrator must never do

- Claim to reproduce the recorded experiments. One live run is one seed; the recorded results are
  n = 30 with pre-registered criteria.
- Print an "accuracy" figure. This is not a classification task.
- Show a detection rate without stating the injection mode (transient vs sustained). The same fault
  measured 99.1 % transient and 0.2 % sustained.
- Show the self-trust plane, monitorability metric or phase-aware detector as functioning. They are
  designed, not built.
- Guarantee detection. **Three of six faults are not detected**, and the demo is more valuable for
  showing that honestly than for hiding it.

---

## 11 · The message the demo must land

> We are not showing that a controller produces a command. We are showing the complete runtime
> safety chain around that command — injecting a fault into the sensing path, watching the evidence
> propagate through nine instrumented layers, and observing whether the safety monitor actually
> responds. Sometimes it does not, and that is what we measured.
