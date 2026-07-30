# ADR-0015: Target CARLA 0.9.16 on Linux; no sidecar, no unofficial wheel

- **Status:** Accepted
- **Date:** 2026-07-29
- **Phase:** 2 (Sensing & State Estimation)

## Context

Reconciliation finding R-6 records the project's highest-rated technical risk (RK-1) and assumption
A-8: the source documents mandate CARLA 0.9.14, whose official Python client ships wheels for
CPython 2.7/3.7/3.8 only, while ADR-0003 floors the project at Python 3.12. As stated the two
requirements admit no interpreter. Three routes were named and none had been evaluated: (a) a newer
CARLA, (b) a community-built wheel, (c) a Python 3.8 sidecar bridged to the 3.12 core over IPC.

The spike is recorded in full, with sources, in
[`../spikes/R6-carla-interpreter.md`](../spikes/R6-carla-interpreter.md). Three findings decide it.

**CARLA 0.9.16 publishes an official CPython 3.12 wheel.** The release landed on 2025-09-16, after
ADR-0003 was written, and the PyPI distribution carries `cp310`, `cp311` and `cp312` wheels for
`manylinux_2_31_x86_64` and `win_amd64`. The release announcement states plainly that "Python
versions 3.10, 3.11 and 3.12 are now supported" and that eggs are deprecated in favour of wheels.
The premise of R-6 — that no interpreter satisfies both requirements — is simply no longer true. It
was true of 0.9.14 and it is not true of the current release.

**0.9.16 is the current stable line, not a legacy one.** CARLA 0.10.0 (2024-12-19) migrated to
Unreal Engine 5.5 and also supports Python 3.8–3.12, so on the narrow interpreter question either
would serve. But 0.9.16 shipped twenty-one months *after* 0.10.0, the official downloads page names
0.9.16 as the latest release, and the 0.10.0 announcement says the UE4 and UE5 lines "will coexist
for the foreseeable future". 0.10.0 is a parallel rebuild in progress, not a successor.

**CARLA does not run on macOS, and this is the larger practical constraint.** The 0.9.16 quickstart
states CARLA "is built for Windows 10 and 11 and Ubuntu 20.04 and 22.04". No macOS package is
offered; the Docker images are `linux/amd64` only; the PyPI wheels carry no `macosx` or `aarch64`
tag, so on Darwin arm64 not even the *client* library installs. The developer's machine cannot host
the simulator under any of the three routes. That is independent of the interpreter question and it
outlives this decision.

## Decision

**Target CARLA 0.9.16 and install its official `cp312` wheel into the project interpreter.** Route
(a). The `SensorSource` adapter runs in the same Python 3.12 process as the core. There is no
sidecar, no IPC hop on the sensor path, and no unofficial binary in the toolchain. The documents'
"CARLA 0.9.14" is superseded by 0.9.16 within the same 0.9/UE4 line.

**The adapter's dependency is optional and the isolation contract is unchanged.** `carla` is
declared as an optional extra, never a core dependency, so `astra` remains installable and testable
on a machine that cannot host the simulator — which is every machine the project currently has. The
`simulator-isolation` contract in `.importlinter` continues to forbid `carla` everywhere in
`astra`, with `astra.adapters.carla` added as the single named exclusion when that module is
written. Nothing in `src/astra/` changes as a result of this ADR.

**L1 and L2 are built against an in-process fake first, and the CARLA binding is deferred.** This
is the operative half of the decision. Phase 2's exit criteria — a validated UKF, byte-identical
replay, measured fast-filter latency — are reachable against a synthetic `SensorSource` that
implements the same `Protocol`, and Phase 2 is not gated on procuring hardware the project does not
have. The CARLA adapter is written when a Linux x86_64 host with an NVIDIA GPU is available. The
port is what makes that ordering legal, and this is the first time it pays.

## Alternatives considered

**CARLA 0.10.0 (Unreal Engine 5.5).** Rejected. It resolves the interpreter question equally well
and is the better long-term bet, but its published limitations disqualify it for Phase 2 today:
only Town 10 is migrated, weather is fixed to daylight with clouds, rain, fog and sun position not
modifiable, internal peak frame rates are around 24/25 FPS, and 16 GB of VRAM is recommended.
OpenDRIVE import, large maps, the map-layers API, V2X and the Light Manager are not migrated. A
project whose L6 covariate-shift detector is meant to notice a distribution change between highway
and rain cannot use a build that cannot render rain. It is also absent from PyPI entirely, so the
convenient `pip install carla` path does not exist for it.

**A community-built wheel for a newer interpreter.** Rejected, and now pointless. The best-known
such artefact, `carla-client-unofficial` on PyPI, was last published in March 2021, tops out at
CARLA 0.9.11 and at CPython 3.8 — it does not even solve the problem it was reached for. More
generally, an unsigned third-party binary rebuild of the client for a safety-adjacent system is a
supply-chain liability that would have to be justified in front of an assessor, and no such
justification is available when the upstream project publishes the wheel itself.

**A Python 3.8 sidecar bridged to the 3.12 core.** Rejected, though it was the route the project
feared. It is now unnecessary, and it was always the most expensive answer: a second interpreter, a
second dependency set, a serialisation format, a failure mode where the bridge dies and the core
does not know, and an IPC hop charged against A-2's 10 ms budget on every tick that carries a
multi-megabyte camera frame — CARLA's default 800×600 BGRA frame is 1.92 MB and a 1080p frame is
8.29 MB. The spike also found no open-source prior art for running the CARLA client on one
interpreter and bridging it to another, so it would have been bespoke work with no design to copy.
It survives as the documented contingency should 0.9.16's 3.12 wheel prove defective in practice,
and it stays cheap to adopt for exactly the reason ADR-0003 gave: the adapter is the only thing
that would change. Were it ever revived, the spike's instruction stands — measure the candidate
transports at those payload sizes at a 20 Hz duty cycle, because the published localhost IPC
figures all measure back-to-back sending and are optimistic for a loop that idles between ticks.

**Staying on CARLA 0.9.14 and lowering the floor to 3.8.** Rejected in ADR-0003 and rejected again
here. CPython 3.8 reached end of life on 2024-10-07 (source: <https://endoflife.date/python>,
checked 2026-07-29), so the route now proposes an unsupported interpreter for a safety-adjacent
system in order to match a simulator version that upstream has itself moved past twice.

## Consequences

### Positive

- **R-6 is closed and RK-1 retires without a runtime cost.** The resolution is the one branch of
  A-8 that charges nothing against the latency budget: sensor frames stay in-process, so A-2's
  10 ms budget is unaffected by this decision and the timing argument stays simple.
- **The type story improves.** 0.9.16 added type hints to the Python API. Under mypy strict, an
  adapter against a typed client is a materially different exercise from one against an untyped
  extension module.
- **`pip install carla` works on the project's own interpreter.** No egg on `sys.path`, no
  hand-managed `dist/` directory, no build from source. Dependency resolution stays inside uv.
- **Phase 2 is decoupled from hardware procurement.** L1, L2, the innovation monitor and the replay
  harness proceed against fakes now. The simulator becomes an integration task with a known
  answer rather than a blocking unknown at the front of the phase.
- **The port earned its keep.** ADR-0003 isolated the simulator to make R-6 a deployment question.
  The upgrade path from 0.9.14 to 0.9.16 touches no file under `src/astra/`, which is the claim the
  isolation existed to make good on.

### Negative / accepted trade-offs

- **The documents said 0.9.14 and this says 0.9.16.** A second deliberate deviation from a stated
  requirement, on top of ADR-0003's interpreter floor, and a requirements audit will find it. The
  0.9.15 and 0.9.16 changelogs are largely additive within the 0.9 line, but they are not empty:
  `Sensor.is_listening` was cleaned up from a duplicate property/method into a method, and the
  `carla.ad` subpackages changed import form. Any scenario script written against 0.9.14 must be
  read, not assumed.
- **macOS remains impossible, and no decision here fixes it.** Simulator work needs a Linux
  x86_64 machine with an NVIDIA GPU — a workstation, a remote box or a cloud instance. Neither a
  local VM nor Docker Desktop on Apple Silicon substitutes, because the images are `amd64` and
  macOS offers no GPU passthrough. Until such a host exists, the CARLA adapter cannot be run or
  tested by anyone on this project, only written.
- **`manylinux_2_31` sets a floor on the host.** glibc 2.31, i.e. Ubuntu 20.04 or newer. Consistent
  with CARLA's own stated support, but it is a constraint on the eventual machine.
- **Deferring the adapter defers its discovery of surprises.** Synchronous-mode determinism, sensor
  callback threading and the fixed-delta-seconds clock that `Timeline.SIMULATED` assumes are all
  claims that only a running simulator can test. Choosing to build against fakes first buys
  schedule safety at the price of finding those late. The mitigation is that the fake must be
  written to the `SensorSource` contract rather than to what is convenient, or it will validate the
  UKF against a world that does not exist.
- **0.9.16 is verified on paper, not on metal.** Every claim above is sourced from CARLA's
  published artefacts. Nobody on this project has run `pip install carla==0.9.16` on 3.12 or
  connected a client to a server. Until someone does, A-8 moves from OPEN to *evidenced*, not to
  closed.
- **The UE5 migration is deferred, not avoided.** CARLA's own position is that the two lines
  coexist "for the foreseeable future", but 0.9.x is UE4.26 and will not be the end state. A move
  to the 0.10.x line is a future adapter rewrite that this decision schedules for someone else.
