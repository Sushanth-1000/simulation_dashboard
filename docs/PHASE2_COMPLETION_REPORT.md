# Phase 2 — Engineering Completion Report

**Phase:** 2, Sensing, State Estimation & the Replay Spine
**Status:** Complete except the CARLA adapter, which is deferred for a stated reason (§7)
**Date:** 29 July 2026
**Scope delivered:** L1, L2, the replay spine, and the resolution of the project's
highest-rated technical risk.

---

## 1. The headline: R-6 is resolved, and it dissolved

Finding R-6 — the documents mandate CARLA 0.9.14, whose Python client ships for CPython ≤ 3.8,
while this project floors at 3.12 — was the single most consequential unresolved risk in the
project (RK-1). Three routes had been named and none evaluated: upgrade CARLA, use a community
wheel, or run a Python 3.8 sidecar bridged over IPC.

**None of them is needed.** CARLA **0.9.16**, released 2025-09-16, publishes official
`cp310`/`cp311`/`cp312` wheels to PyPI. Verified directly against `https://pypi.org/pypi/carla/json`
on 2026-07-29:

| Version | Uploaded | Wheel Python tags |
|---|---|---|
| 0.9.14 | 2022-12-24 | `cp27`, `cp37`, `cp38` |
| 0.9.15 | 2023-11-14 | `cp27`, `cp37`, `cp38`, `cp39`, `cp310` |
| **0.9.16** | **2025-09-14** | **`cp310`, `cp311`, `cp312`** |

R-6's premise expired between the writing of ADR-0003 and today. No sidecar, no IPC hop, no
unofficial binary, and the 10 ms budget is untouched. The full spike is in
[`spikes/R6-carla-interpreter.md`](spikes/R6-carla-interpreter.md); the decision is
[ADR-0015](adr/0015-carla-interpreter-strategy.md).

**A new constraint replaced it, and it is real.** CARLA has no macOS build and its wheels carry no
`macosx` tag, so `pip install carla` fails on Darwin regardless of interpreter. Simulator work
needs a Linux x86-64 host with an NVIDIA GPU. This is why the adapter is deferred (§7) and why
"build against fakes first" became a requirement rather than a preference.

---

## 2. What was built

| Module | Responsibility |
|---|---|
| `layers/l1_sensing/bus.py` | Thread-safe multi-modality fusion; per-modality staleness against FR1's 50 ms budget; out-of-order rejection; canonical sample ordering |
| `layers/l2_estimation/measurement.py` | The `Measurement` record and the `MeasurementExtractor` seam that keeps payload knowledge out of the core |
| `layers/l2_estimation/models.py` | Kinematic bicycle process model; slow-state random walk |
| `layers/l2_estimation/filter.py` | The dual-rate UKF and the innovation monitor |
| `replay/tape.py` | The tape format, the payload codec, canonical serialisation |
| `replay/recorder.py` | `StateRecorder` |
| `replay/harness.py` | `ReplayHarness` and `ReplayClock` |
| `benchmarks/latency.py` | Reproducible software latency measurement |
| `stubs/filterpy/` | Local type stubs; also the enumeration a FilterPy qualification argument starts from |

9 788 lines of source, 12 946 lines of tests.

Three design decisions carry most of the weight:

**Staleness is measured from acquisition, and a late-arriving *older* reading is rejected.** If the
bus accepted whichever sample arrived last, a delayed old reading would replace a fresh one and the
measured staleness of that stream would travel backwards — a stale stream would look healthy, which
is the exact fault FR1 exists to catch. Superseded arrivals are counted, never silently dropped.

**The tape records inputs and contains no wall-clock reading.** Replaying inputs reproduces
outputs; recording outputs would only let them be re-read. And any creation timestamp would differ
on every recording, defeating byte-comparison in the one artefact whose purpose is byte-comparison.

**The measurement carries the state layout it addresses.** A slow-state measurement has indices
0, 1, 2 that are perfectly valid in the fast filter, so applying one there raises nothing and
writes road friction into the state as position and speed. Carrying the layout makes that
detectable; checking it in the filter is what makes carrying it worth anything (§5, bug 3).

---

## 3. Exit criteria

| Criterion | Result |
|---|---|
| A recorded run replays to a byte-identical stream | **Met.** 300-tick synthetic drive, uneven sensor rates; the replayed tape is byte-identical by SHA-256 and every frame compares equal. |
| The UKF is validated in isolation against ground truth before anything downstream is wired | **Met**, against a *synthetic* vehicle — see the honest qualification below. |
| Fast-filter latency measured, target < 1 ms, reported as a software measurement | **Met.** |

**Latency**, measured on macOS 15.7.3 / arm64, CPython 3.12.3, 2 000 samples after 200 warm-up
ticks, via [`benchmarks/latency.py`](../benchmarks/latency.py):

| Stage | p50 | p95 | p99 | max | budget |
|---|---|---|---|---|---|
| L1 acquire (fusion) | 0.003 | 0.004 | 0.004 | 0.028 | 1.0 |
| L2 `update_fast` (UKF) | 0.119 | 0.135 | 0.200 | 0.465 | 1.0 |
| L1 + L2 combined | 0.122 | 0.139 | 0.203 | 0.469 | 10.0 |

All figures in milliseconds. The combined p99 uses **0.4%** of the 50 ms tick period. These are
**software measurements**. They are not, and must never be reported as, the 1.25 µs Core-B figure,
which is an analytical hardware WCET bound (AbsInt aiT, 500 MHz, 627 cycles) that a Python
prototype cannot measure at all.

**Tracking accuracy**, synthetic vehicle at 20 m/s, 120 ticks straight then 180 ticks in a steady
3 m/s² turn, with Gaussian sensor noise:

- final position error **0.36 m** after 298 m travelled
- heading error **0.0085 rad**
- speed error **0.020 m/s**
- `P_f` positive definite on every tick
- innovation monitor quiet throughout; mean Mahalanobis distance 1.38

**The honest qualification.** The roadmap's criterion says "against CARLA ground truth". This was
validated against a *synthetic* kinematic vehicle, because CARLA does not run on the available
machine. That is a weaker claim, and it is weaker in a specific way: the synthetic vehicle
integrates the same kinematics the filter models, so it cannot expose a *modelling* error — only an
implementation one. The ground-truth vehicle is deliberately written out separately rather than
calling the filter's own transition function, so a change to the process model surfaces as a
tracking error instead of cancelling. But validation against real simulated dynamics remains
outstanding and is the first thing to do once a Linux host is available.

---

## 4. Verification

| Check | Result |
|---|---|
| `ruff format --check .` | 112 files, clean |
| `ruff check .` | clean |
| `mypy --strict` | clean, 80 source files |
| `lint-imports` | **6** contracts kept, 0 broken |
| `pytest --cov=astra` | **1 775 passed**, **99.02%** coverage against a 95% gate |

Per-module coverage is 100% for every module except `filter.py` at 99% — the single uncovered line
is `_identity_observation`'s return, which is *supposed* to be unreachable: every real update
overrides `hx`, and the miss is evidence the docstring's claim holds.

Two new import contracts were added this phase: `contracts-independence`, and NumPy and FilterPy
were named explicitly in `kernel-independence`. Both exist because the numerical stack is now a
real project dependency, which makes a convenience `import numpy` into the kernel the realistic way
its offline-importability would be lost.

---

## 5. Defects found and fixed

Seven, all found by tests rather than by review. The first four are the ones that mattered.

**1. A NaN staleness budget silently disabled FR1.** The constructor guarded `budget < 0`, which is
`False` for NaN, and `staleness > nan` is also `False` — so a NaN budget reported *every* stream
healthy forever. Reproduced: a reading 1 000 s old classified as `HEALTHY`. This is precisely the
fail-*open* mode `NonFiniteValueError` exists for. The identical hole was present in
`kernel.time.is_stale`. Both now route through `require_non_negative`.

**2. A cross-layout measurement silently corrupted the state.** `DualRateUKF._step` read
`state_indices` and discarded `layout`. An extractor returning a slow-state measurement from
`extract_fast` was accepted without complaint, and one tick drove the speed estimate from
12.0 m/s to 1.099 m/s — with the innovation monitor reporting it as an ordinary sensor fault rather
than the wiring fault it was. Every gate above L2 would have read that state.

**3. The reverse direction escaped as a raw `IndexError`**, carrying no `SafetyDisposition`, so the
caller's single reviewable `except SafetyPathError` — the entire basis of "anything wrong here
becomes a VETO" — would not have fired. `IndexError` and `FloatingPointError` are now caught
alongside the numerical failures.

**4. `acquire()` read the clock outside the lock.** A sample published in the intervening window
carried `observed_at` after `fused_at` and was reported with *negative* staleness — manufacturing
the future-timestamp fault signal out of ordinary scheduling jitter.

**5. `replay/harness.py` imported `datetime` at runtime**, violating this project's own architecture
test that only `kernel/time.py` may. Fixed by exporting `UNIX_EPOCH` from `kernel.time`.

**6. `ReplayHarness.frames()` was single-use.** Its own docstring says the workflow is re-running
the same fifty ticks repeatedly; the clock never rewound, so the second pass raised. Each traversal
now rewinds first.

**7. The bus emitted samples in publish order.** Two runs over identical inputs produced frames
equal in content but not in structure, defeating frame-by-frame comparison between a run and its
replay. Samples are now emitted in `SensorModality` declaration order.

Every one of these is now pinned by a regression test, and the two architecture rules (clock
discipline, `print()` confinement) were verified by injecting a violation, confirming the test
fails, and reverting.

---

## 6. Configuration changes

`fast_process_noise` and `slow_process_noise` are now **required** configuration with no defaults,
following the same A-4 discipline as every other empirical parameter. `Q` governs how quickly the
filter trusts measurements over its own model, which means it sets the state estimate all three
gates read — a plausible guess there would put an unreviewed number under the whole safety
argument. `certification.toml` leaves both commented out, so loading it now names **16** missing
fields rather than 14.

---

## 7. What is not done, and why

**The CARLA adapter is deferred.** Not descoped — deferred, for a reason outside the code: CARLA
has no macOS build and no macOS wheel, so the adapter cannot be written, run or tested on the
available machine. Writing an untestable adapter into a safety-critical repository would violate
this project's own standards more seriously than leaving it absent.

Nothing else is blocked by this. L1, L2 and the replay spine are complete and tested against
in-process fakes, and the `MeasurementExtractor` seam is exactly where the adapter will attach.

**What is needed to finish it:** a Linux x86-64 host with an NVIDIA GPU, CARLA 0.9.16, and
`pip install carla==0.9.16`. The first task on that machine is to confirm the install and a
client-to-server connection actually work — A-8 is currently *evidenced* from published wheel
metadata, not *verified* by a run, and the distinction is real.

---

## 8. Technical debt

1. **The UKF has been validated only against synthetic dynamics** (§3). Real-simulator validation
   is outstanding.
2. **Process noise is provisional.** The values in `development.toml` and `simulation.toml` are
   labelled as starting points for tuning, not tuned values. Tuning against ground truth is the
   work that does not compress.
3. **FilterPy is an unmaintained dependency inside a safety path.** ISO 26262 8-12 asks for such a
   component to be qualified. `stubs/filterpy/` enumerates exactly the surface depended on, which
   is where that argument starts, but the argument itself is not written.
4. **`Measurement` restricts observation to selecting state dimensions.** Every measurement the
   architecture describes is of that form, but a future sensor needing a genuinely non-linear `h`
   will need the type extended.
5. Carried from Phase 1: SI-1/SI-2/SI-5 import contracts remain narrower than the invariants they
   claim; SI-9's checksum is stored but never verified; SI-8 has no timing test.

---

## 9. Readiness

**8 / 10.**

Earned: the highest-rated project risk is closed and closed cheaply; both layers are at 100%
coverage with the safety properties pinned by regression tests rather than asserted; the replay
spine works and is byte-exact; latency is measured with two orders of magnitude of headroom; and
seven real defects were found and fixed before any of this was built upon.

Withheld: the UKF has not met real simulated dynamics, the process noise is untuned, and the
adapter — one of the phase's five scope items — is unwritten for an environmental reason that will
not resolve itself on the current hardware.

**Ready for Phase 3**, which is the deterministic safety spine: `l7_shield`, `l8_failsafe` and the
one-way Core-A→Core-B channel. Phase 3 depends on the state estimate, which now exists and is
tested, and on nothing from the simulator — so it can proceed at full speed on this machine while
the Linux host is arranged in parallel.

---

## 10. What must not be claimed

- **ASTRA still governs nothing.** L1 and L2 exist; no gate, no proposer, no arbitrator does. There
  is no pipeline, and no false-positive, false-negative or veto figure exists.
- **The latency figures in §3 are software measurements of two layers**, on one machine, excluding
  the simulator, the audit sink and every layer not yet built. They are a floor on the eventual
  end-to-end figure, not an estimate of it — and they are not the 1.25 µs analytical hardware bound.
- **The tracking accuracy in §3 is against a synthetic vehicle**, not against CARLA and not against
  a real one.
- **The CARLA 0.9.16 finding rests on published wheel metadata**, not on an install anyone has run.
- **The shared L2 state estimate is now a live common-cause channel**, not a theoretical one. Every
  gate built from Phase 3 onward will read it. The innovation monitor mitigates that; it does not
  eliminate it.
