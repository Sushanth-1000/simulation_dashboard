# ASTRA — Evidence

**Living document.** One row per claim the project makes, the run that produced
it, the command that reproduces it, and the date. A number that is not in this
table has not been measured, and a number here that cannot be reproduced by its
command is a defect in this table.

**Last verified** 2 August 2026, commit `a5a707d`+, on WSL2 Ubuntu / CPython
3.12.13 / CPU only.

> **The caveat that governs every row in the first table.** The plant, the digital
> twin and the calibration corpus all descend from the same kinematic bicycle
> model. The generator and the judge agree by construction, so **no
> false-positive or false-negative rate exists and none can exist** until the
> CARLA work in Phase 7. Everything below demonstrates that the machinery works.
> None of it demonstrates that the gates catch what they claim to.

---

## Reproducing everything in this document

```bash
# in WSL2 -- the gate does not run on the Windows host (Smart App Control)
uv sync --all-groups --all-extras --python 3.12
uv run python -m compileall -q .venv/lib/python3.12/site-packages
make check
uv run python benchmarks/latency.py
uv run python -m benchmarks.soak --ticks 100000 --window 1000
uv run python -m benchmarks.flake_hunt   # ~40 min under load
make verify-install
```

Artefacts land in `var/soak/<name>/` — `windows.jsonl` (one row per 1,000 ticks),
`summary.json`, `soak.png`, and the full `audit/` evidence log.

---

## Measured

| # | Claim | Value | Produced by | Date |
|:--:|---|---|---|:--:|
| E-1 | Quality gate is green | **2,675 tests, 97.99% coverage**, `ruff` + `mypy --strict` over 140 files + **12** import contracts, 0 broken | `make check` | 2 Aug |
| E-2 | The closed loop is stable over a long run | **All ten soak criteria pass over 100,000 ticks** | `python -m benchmarks.soak --ticks 100000 --window 1000` | 2 Aug |
| E-3 | A command is issued on every tick | **100,000 of 100,000**, and 400,000 of 400,000 across the four runs of the day | as E-2 | 2 Aug |
| E-4 | The proposer's commands are accepted | `PROPOSED` on **99,997** ticks; **3** vetoed, all answered by the rate limiter. Veto rate 3×10⁻⁵, which the console rounds to 0.0% — the JSON is authoritative | as E-2, `summary.json` | 2 Aug |
| E-5 | Lane keeping | mean \|deviation\| **0.0332 m** over the whole run; 0.0331 across warm windows, drift +0.0001 m | as E-2, `summary.json` | 2 Aug |
| E-6 | The fail-safe machine stays nominal | Never leaves `NOMINAL` across 100,000 ticks | as E-2 | 2 Aug |
| E-7 | No unbounded growth in any rolling structure | Resident set **+0.2 MiB** peak over 100,000 ticks | as E-2 | 2 Aug |
| E-8 | Per-tick cost does not grow | Full-pipeline p99 **9.50 → 9.32 ms** between halves (×0.98) | as E-2 | 2 Aug |
| E-9 | Evidence archive is complete | **0** audit records dropped by the sink's bounded queue across 100,000 records | as E-2 | 2 Aug |
| E-10 | Hot-path software latency | L1+L2+L7a+L8 combined p99 **0.811 ms** against a 10 ms budget; every stage within budget | `python benchmarks/latency.py` | 2 Aug |
| E-11 | No command is issued under a blocking verdict | **0**, from 99,808 per 100,000 before ADR-0016 | as E-2, `proposals_issued_under_veto` in `windows.jsonl` | 2 Aug |
| E-12 | Conformal coverage is arithmetically correct | Per class, shuffled split: **94.9–95.1%** against a 95% nominal, mean over 200 splits | `python -m training.generate_calibration --policy var/policy/synthetic.pt` | 2 Aug |
| E-13 | The statistical gate discriminates between proposers | Matched proposer vetoed on **1 tick in 300**; the placeholder, off-distribution, on **299** | `pytest tests/integration/test_closed_loop_policy.py` | 2 Aug |
| E-14 | The trained policy holds speed and lane in its own environment | Return **936.8/1000**, mean \|deviation\| **0.0913 m**, mean \|long. accel\| **0.0502 m/s²**, all three constraints satisfied | `python -m training.train_policy` | 2 Aug |
| E-15 | The proposer respects the jerk bound far better after rescaling | Peak lateral jerk **150 → 60 → 16.7 m/s³** across three retrains | as E-14 | 2 Aug |
| E-16 | The L1 atomicity test detects the defect it names | Hoisting the clock read out of the lock fails it **6 runs of 6**; the other **2,543** tests all pass | mutation, recorded in `tests/unit/test_l1_sensor_bus.py` | 2 Aug |
| E-17 | CARLA installs and imports on the project's interpreter (assumption A-8) | `carla==0.9.16` installs on **CPython 3.12.13**/Linux with no dependency tree; `Client`, `World`, `Vehicle`, `Sensor`, `Transform`, `Location`, `Rotation`, `VehicleControl`, `WorldSettings` all present; a `Client` constructs and fails to connect with `RuntimeError`, correctly, with no server running | `uv venv --python 3.12 ~/carlacheck && uv pip install --python ~/carlacheck/bin/python carla==0.9.16` | 2 Aug |
| E-22 | The closed loop is stable **under sensor noise** | All ten criteria over 100,000 ticks with readings drawn at the declared sigmas: `PROPOSED` on **99,911** ticks, `RATE_LIMITED` on 89, lane deviation **0.0290 → 0.0298 m**, fail-safe never leaving NOMINAL, resident +0.1 MiB, p99 ×0.81 | `python -m benchmarks.soak --ticks 100000 --window 1000` | 2 Aug |
| E-23 | The Trust Index is a graded index, not a flag | Distinct values across 8,001 ticks: **2 → 5 → 90**. Mean 0.960, p05 0.902, p50 0.964, p95 1.000 | as E-22, `trust.trust_index` in the audit log | 2 Aug |
| E-18 | The Trust Index and the gate were calibrated against incompatible statistics | Gate scores span **1.155–1.191**; innovations span **0.518–7.497** (clear) and **7.549–154.8** (degraded). Sharing one distribution pinned the Trust Index to **2 distinct values across 4,001 ticks**. Separating them gave 5; matching the filter's `R` to the injected noise on top gave 90 — see E-23 | `python -m training.generate_calibration --policy var/policy/synthetic.pt`, then read `innovations` in the corpus | 2 Aug |
| E-26 | The L1 concurrency flake does not reproduce under heavier load than the one that found it | **220 runs, 220 passes, no hangs**: 20 full-suite runs (76.8-100.2 s each) and 200 runs of the threaded tests alone (2.0-4.8 s each), under `stress-ng --cpu 32` on 16 cores. Absence of evidence, not evidence of absence -- a 1%-per-run race survives 220 runs about one time in nine | `python -m benchmarks.flake_hunt --repeats 20 --focus-repeats 200`, `var/flake/p22-campaign/summary.json` | 2 Aug |
| E-27 | The frozen-install check detects the defect it names | Adding `import numpy` to `src/astra/kernel/units.py` makes `make verify-install` fail with `ModuleNotFoundError` and exit 1. Without it, a bare venv holding only pydantic imports the kernel and contracts cleanly | `make verify-install` | 2 Aug |
| E-28† | The configured EWC penalty did nothing at all | At `ewc_lambda` 0 and 150, forgetting after 4,000 samples of a second context was **0.038972** and **0.038951** -- identical to four decimals. Cause was the anchor, re-taken every buffer flush, not the value; see ADR-0018 | superseded -- see † | 2 Aug |
| E-29† | With the anchor held across a context, EWC responds monotonically | Forgetting relative to unregularised: **0.86** at 1e2, **0.30** at 1e3, **0.081** at 1e4, **0.026** at 1e6, **0.018** at 1e8 -- no cliff over six orders of magnitude. Before the fix the only useful value was 1e6 and 3e6 was *worse than zero* (2.33x) | superseded -- see † | 2 Aug |
| E-30† | Catastrophic forgetting is real in this twin | An offline-trained twin knows the highway to **0.000247** mean absolute command error; 4,000 unregularised samples of a second context take it to **0.039219**, a **159x** degradation | superseded -- see † | 2 Aug |
| E-33 | Per-context heads make forgetting exactly zero | Adapting 4,000 rain samples into the rain head leaves the highway prediction **bit-for-bit unchanged** -- the assertion is `==`, not a tolerance. The same rain driven through the *highway* head still destroys it | `pytest tests/unit/test_l5_forgetting.py` | 2 Aug |
| E-34 | Separating the heads costs nothing in adaptation | The rain head closes at least as much of the context gap as a shared head does, because it sees the same gradients. The elastic penalty it replaced gave up a proportional unit of plasticity for every unit of retention (E-32) | as E-33 | 2 Aug |
| E-36 | Running FB2 in shadow changes nothing about the run | 100,000 ticks with `--shadow-fb2` are numerically identical to the run without it: same lane-deviation trace **0.0290 -> 0.0298 m**, same origin split **99,911 PROPOSED / 89 RATE_LIMITED**, all ten criteria pass, live twin digest constant | `python -m benchmarks.soak --ticks 100000 --window 1000 --shadow-fb2` | 2 Aug |
| E-37 | FB2 drifts the twin substantially even with nothing to adapt to | In a **single unchanging context**, twin divergence **0.0094 -> 0.2360** over 100,000 ticks, peak 0.2387, 100 distinct shadow digests. Growth per quarter +0.0622, +0.0627, +0.0542, +0.0474 -- decelerating ~0.87x/quarter, extrapolating to ~0.5, comparable to the whole steering range. Not converged after 83 minutes of simulated driving | as E-36, `mean_shadow_divergence` in `windows.jsonl` | 2 Aug |
| E-38 | FB2's only training labels are the proposer's commands | `_consolidate`'s data term is `MSE(predicted, applied)` where `applied` is the issued command. `train_twin.py` by contrast labels from physics, `steer = lateral / gain`. `twin.py`'s module docstring names training the twin on the proposer as the way to disarm the statistical gate | source, `src/astra/layers/l5_twin/twin.py` and `training/train_twin.py` | 2 Aug |
| E-39 | FB2 would disarm the statistical gate | Over 100,000 ticks in one unchanging context the score against the **live** twin is flat -- **1.1564 -> 1.1560** -- while the score against a shadow twin FB2 adapted falls **1.1534 -> 0.6962**, a **40% collapse**, monotone and still falling. Same run, same ticks; the only difference is which twin the score is computed against. Against the corpus's HIGHWAY_CLEAR quantile of **1.179**, headroom to a veto goes from **x1.02** to **x1.69** -- an anomaly would have to be 69% above the twin's prediction to trip the gate, against 2% today | `python -m benchmarks.soak --ticks 100000 --window 1000 --shadow-fb2`, `mean_live_score` / `mean_shadow_score` in `windows.jsonl` | 2 Aug |
| E-40 | Online requantilisation drives the veto rate to epsilon, by construction | FB3 in shadow over 100,000 ticks: quantile **1.1720 -> 1.1575**, converged within 2 windows and stable thereafter; veto rate it would have produced **5.02%** steady, against **0.089%** today. 5.02% is `significance_epsilon` = 0.05 -- calibrate on the distribution you are then tested against and epsilon of it exceeds the 1-epsilon quantile whether or not anything is wrong | `python -m benchmarks.soak --ticks 100000 --window 1000 --shadow-fb2`, `var/soak/p32-fb3/windows.jsonl` | 2 Aug |
| E-41 | The live loop is not exchangeable with its calibration corpus | Live non-conformity scores sit at **1.156**, below the corpus **minimum** of 1.158; the whole HIGHWAY_CLEAR distribution spans **1.158-1.189** over 1,000 samples. Today's 0.089% veto rate is that mismatch, not evidence the gate is discriminating. E-12's coverage was measured on shuffled splits *of the corpus* and does not transfer | read `var/calibration/synthetic.json`; `mean_live_score` in `var/soak/p32-fb3/windows.jsonl` | 2 Aug |
| E-24 | The fail-safe speed cap constrains an actuator | Driving the **assembled** pipeline into HALT (whose cap is 0.0 m/s) at 45 m/s: every tick in HALT issues throttle **0.0**, brake **1.0**, origin `SPEED_CAPPED`. A nominal drive issues nothing so labelled. Before P2.1 the identical situation issued a bit-identical command to the uncapped path — see finding F2 | `pytest tests/integration/test_full_pipeline.py -k halt_actually_brakes` | 2 Aug |

† **Historical, not reproducible from the current tree.** These three measured the
elastic-weight-consolidation penalty, which [ADR-0019](adr/0019-one-twin-head-per-context.md)
deleted along with `ewc_lambda`. They are kept because they are the evidence *for*
that decision, and a table that silently dropped the measurements behind its own
changes would be a worse record than one carrying a footnote. The behaviour E-30
describes is still reproducible as the control arm of E-33.

### Controlled comparisons

| # | Question | Result | Date |
|:--:|---|---|:--:|
| E-25 | Does removing the OOD counter's ceiling get caught? | **Yes.** Deleting the `min` fails exactly the two tests that name it — `test_the_counter_never_climbs_past_the_halt_threshold` and `test_the_ceiling_is_the_halt_threshold_and_not_some_multiple_of_it` — and the other 2,641 pass | 2 Aug |
| E-31 | Would rescaling the EWC penalty work instead of re-anchoring it? | **No, measured.** Normalising the Fisher by its mean shifts the useful window from 1e6 to 1e4 without widening it -- still one decade, still a cliff at 10x -- and the best protection available drops from **0.084** to **0.309** of unregularised. Strictly worse than tuning alone | 2 Aug |
| E-32 | Does EWC protect the old context selectively, or just slow all learning? | **Just slows everything.** Forgetting divided by fraction-of-gap-closed, across lambda 0 to 1e5: **0.00184, 0.00184, 0.00186, 0.00186, 0.00194** -- constant. Structural: a 16->2 linear readout gives a Fisher-weighted penalty no disjoint subspace to exploit. Open as P3.1a, held as a strict xfail | 2 Aug |
| E-35 | Interference when one head serves two contexts | **0.85 units of highway accuracy lost per unit of rain gained.** With a head each, 0.00 | 2 Aug |
| E-19 | Does the action-rate penalty need restricting to steering, or just more training? | **Both.** 2×2 at fixed seed: 98k/all-channels stops (return 549); 786k/all-channels stops (671); 98k/steer-only stops; 786k/steer-only holds 13.0 m/s (986) | 2 Aug |
| E-20 | Does regenerating the corpus from the deployed policy matter? | **Yes.** HIGHWAY_CLEAR quantile **1.18 → 2.43**; the threshold in production was less than half what the deployed proposer routinely produces | 2 Aug |
| E-21 | Is the veto latch a property of the policy? | **No.** Three policies — one that stopped the car, one holding 13 m/s at 0.03 m, one with an explicit jerk penalty — all reached the identical terminal state | 2 Aug |

---

## Not demonstrated

Listed because an evidence pack without this section is a sales document. Nothing
below is claimed anywhere in the repository as measured; where a document does
claim it, that is a defect and is named.

| # | Not demonstrated | Why not, and what would demonstrate it |
|:--:|---|---|
| N-1 | **Any false-positive or false-negative rate for any gate** | The plant, twin and corpus share one set of equations. Requires Phase 7 (CARLA) |
| N-2 | **Gate independence** — that three structurally different failure modes exist | Requires the validation drive where FGSM fires exactly one gate and IMU corruption fires two for different reasons. Worse: L6 and L7b both score proposal-against-twin, so a common cause is already visible in measurement |
| N-3 | **The 1.25 µs Core-B intercept** | An analytical AbsInt aiT bound for RTL that does not exist. Not measurable by a Python prototype and must never be quoted as measured |
| N-4 | **ASIL-D(D)** | A design target. An ASIL is the outcome of an assessed safety case |
| N-5 | **Coverage on real driving** | E-12 shows the quantile arithmetic is right, against a corpus drawn from a world the twin already models |
| N-6 | **Domain independence (NFR5, assumption A-1)** | Asserted and structurally defended, never tested. Needs a non-automotive profile through the pipeline without touching `src/astra/` outside adapters |
| N-14 | **That the gate's false-positive rate can be under 1%** | `significance_epsilon` is **0.05**, and a correctly functioning conformal gate vetoes epsilon of exchangeable nominal traffic by construction (E-40). D-1 in the credibility matrix targets **< 1%**. The two are incompatible; the decision is which one moves |
| N-7 | **Two of four feedback loops** | FB1 is wired. **FB4 is too** -- `training/closed_loop.py` steps the plant with whatever L9 issued, which is what makes a veto change the trajectory; it lives in the harness rather than `src/` because it is prototype-only and has no deployment counterpart. FB2 and FB3 have no callers, and both were measured in shadow and found to break the gate they feed (E-39, E-40). This row previously said three of four were unwired, which was wrong about FB4 |
| ~~N-8~~ | ~~**The fail-safe speed cap constrains anything**~~ | Closed by P2.1 — now E-24. What remains undemonstrated is enforcement under an *injected fault* rather than a deliberately provoked one: open as P4.2 |
| N-9 | **The deterministic shield's contribution** | L7a vetoed **once** in ~500,000 ticks. It is a state monitor and cannot see a lane departure. The corridor bound added by P2.1 gives it one that it can, but no run has yet fired it |
| N-10 | **Tamper-evidence of the evidence log** | Integrity-checked, not tamper-evident. No threat model, no signed artefacts, no key management |
| N-11 | **Anything about a real vehicle** | The UKF has met only synthetic dynamics. Technical-debt item 1 |
| N-12 | **The paper's §5 validation drive** | 21 minutes, seven phases, 47 evidence tuples — never run. Recorded in `WORK_PLAN.md` §1.1 |

---

## Claims in the repository that this table contradicts

Feeding [`PENDING.md`](PENDING.md) P1.4, documentation sync.

| Where | Claim | Status |
|---|---|---|
| `README.md` | "2 513 tests, 97.97% coverage" | **Corrected 2 Aug** to 2,675 / 97.99% (E-1) |
| `README.md` | "Full ten-layer tick p99 **1.98 ms**" | **Corrected 2 Aug.** The soak measures **9.3 ms** p99 for the full tick; `benchmarks/latency.py` measures a *subset* (L1+L2+L7a+L8) at 0.811 ms (E-10). Neither was "the full ten-layer tick" at 1.98 ms, and the two must not be compared |
| `README.md` | "Closed-loop over 400 ticks: trained policy 41.0% veto rate and 0.383 m mean lane deviation vs 59.8% / 0.836 m" | **Corrected 2 Aug.** Measured with a policy that stopped the vehicle, an unobservable lateral position, a corpus harvested from a different proposer, and a plant integrating 2.5× fast. Superseded by E-4, E-5, E-13 |
| `docs/PROJECT_STATE_AND_ROADMAP.md` | Contract, certification-field and layer-status counts | **Open.** Not re-verified since 31 July |
| `docs/1144_2026-07-31_Sushanth_status.md` | Superseded by the 20:30 ledger | **Open.** Should be marked as such |

---

## How to add a row

A row needs a **command that reproduces it on a clean checkout**. If the figure
came from a one-off script, either commit the script or do not add the row.
Prefer citing the artefact path (`var/soak/<name>/summary.json`) over a number
retyped by hand — retyping is where the last set of stale figures came from.
