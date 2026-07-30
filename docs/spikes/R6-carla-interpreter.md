# Spike R-6 — CARLA versus the Python 3.12 floor

- **Finding:** [R-6](../DOCUMENT_RECONCILIATION.md#r-6--carla-versus-the-python-floor)
- **Risk:** RK-1 (High) · **Assumption:** [A-8](../ASSUMPTIONS.md#a-8--the-carlainterpreter-incompatibility-is-resolvable-without-changing-the-core)
- **Phase:** 2 (Sensing & State Estimation) — the gating decision of the phase
- **Date of investigation:** 2026-07-29. Every source below was fetched on that date.
- **Outcome:** [ADR-0015](../adr/0015-carla-interpreter-strategy.md)

## The question, and why it gates Phase 2

The source documents mandate CARLA 0.9.14. CARLA 0.9.14's official Python client ships wheels for
CPython 2.7, 3.7 and 3.8 only. [ADR-0003](../adr/0003-python-312-floor-simulator-behind-a-port.md)
floors the project at Python 3.12 for PEP 695 generics and `typing.override`. No interpreter
satisfies both, which is finding R-6 — recorded as the single most consequential unresolved
technical risk in the project.

*A small correction in passing:* R-6 and ADR-0003 both describe 0.9.14's client as
"2.7/3.6/3.7/3.8". The PyPI distribution list for 0.9.14 has no `cp36` wheel (see F1). This changes
nothing — 3.6 is further from 3.12 than 3.8 is — but the record should be accurate.

It gates Phase 2 because Phase 2 owns `adapters/carla`, and because the Demo Plan's exit criterion
for the phase is that the dual-rate UKF is **validated against CARLA ground truth before anything
downstream is wired**. If the answer to R-6 were the sidecar, every simulator-sourced sensor frame
would cross a process boundary and the cost would be charged against assumption A-2's 10 ms
end-to-end budget at 20 Hz. The routes are not equivalent, and the difference between them is a
non-functional property of the delivered system — the only finding in the reconciliation with that
character.

Three routes were named in R-6 and none had been evaluated:

- **(a)** upgrade to a newer CARLA with modern interpreter support
- **(b)** use a community-built egg or wheel for Python 3.10+
- **(c)** run the CARLA client as a Python 3.8 sidecar, bridged over IPC to the 3.12 core

## Findings

### F1 — CARLA 0.9.16 ships an official CPython 3.12 wheel

This is the finding that decides the spike. The PyPI JSON API for the `carla` project, queried
2026-07-29, lists release 0.9.16 with six distributions uploaded 2025-09-14:

```
carla-0.9.16-cp310-cp310-manylinux_2_31_x86_64.whl   carla-0.9.16-cp310-cp310-win_amd64.whl
carla-0.9.16-cp311-cp311-manylinux_2_31_x86_64.whl   carla-0.9.16-cp311-cp311-win_amd64.whl
carla-0.9.16-cp312-cp312-manylinux_2_31_x86_64.whl   carla-0.9.16-cp312-cp312-win_amd64.whl
```

Source: <https://pypi.org/pypi/carla/json> and <https://pypi.org/project/carla/> (checked
2026-07-29).

The release announcement states: "Python versions 3.10, 3.11 and 3.12 are now supported" and
"Python eggs are now deprecated (only wheels are now provided)". Source:
<https://carla.org/2025/09/16/release-0.9.16/> (checked 2026-07-29).

`carla` on PyPI is an official artefact, not a fork: the maintainer list includes the verified
`carla-simulator` account and the project homepage is `https://github.com/carla-simulator/carla`.
Source: <https://pypi.org/pypi/carla/json> (checked 2026-07-29).

**R-6's premise was true of 0.9.14 and is false of the current release.** For completeness, the
same API confirms the premise for the older versions the documents named:

| CARLA version | PyPI upload date | CPython wheel tags |
|---|---|---|
| 0.9.14 | 2022-12-24 | cp27, cp37, cp38 |
| 0.9.15 | 2023-11-14 | cp27, cp37, cp38, cp39, cp310 |
| 0.9.16 | 2025-09-14 | cp310, cp311, cp312 |

Source: <https://pypi.org/pypi/carla/json> (checked 2026-07-29). Note that 3.10 support first
appeared in 0.9.15, and that the 0.9.15 changelog contains "Fixed segfaults in Python API due to
incorrect GIL locking under Python 3.10" — evidence that 3.10 support in 0.9.15 was new and
initially defective, and a reason to prefer 0.9.16 over 0.9.15 even though both nominally clear the
documents' 3.10 floor. Source:
<https://github.com/carla-simulator/carla/releases/tag/0.9.15> (checked 2026-07-29).

### F2 — 0.9.16 is the current release; 0.10.x is a parallel line, not a successor

The GitHub releases API, queried 2026-07-29, gives the publication order:

| Tag | Published |
|---|---|
| 0.9.16 | 2025-09-16 |
| 0.10.0 | 2024-12-19 |
| 0.9.15 | 2023-11-11 |
| 0.9.14 | 2022-12-24 |

Source: `https://api.github.com/repos/carla-simulator/carla/releases` (checked 2026-07-29); same
data rendered at <https://github.com/carla-simulator/carla/releases>.

**0.9.16 is the newest release, and there is no 0.9.17 or 0.10.1 as of 2026-07-29.** The official
downloads page states "The latest release of CARLA is 0.9.16". Source:
<https://carla.readthedocs.io/en/latest/download/> (checked 2026-07-29). The repository's default
branch is `ue5-dev` and was last pushed 2026-07-26, so the UE5 line is under active development,
but nothing newer has been tagged. Source:
`https://api.github.com/repos/carla-simulator/carla` (checked 2026-07-29).

The 0.10.0 announcement states that "the UE 4.26 and UE 5.5 versions of CARLA will coexist for the
foreseeable future". Source: <https://carla.org/2024/12/19/release-0.10.0/> (checked 2026-07-29).
That, plus 0.9.16 shipping twenty-one months after 0.10.0, is the basis for treating 0.9.x as the
maintained stable line rather than a legacy one.

### F3 — CARLA 0.10.0 clears the interpreter bar but is not usable for Phase 2

The 0.10.0 release notes state: "Python API now supports Python 3.8, 3.9, 3.10, 3.11 and 3.12" and
"Python API support dropped for Python versions 3.7 and lower". Source:
<https://github.com/carla-simulator/carla/releases/tag/0.10.0> (checked 2026-07-29). On the
interpreter question alone, 0.10.0 would serve.

Its published limitations are what disqualify it. From the release announcement
(<https://carla.org/2024/12/19/release-0.10.0/>, checked 2026-07-29):

- **Maps.** "Town 10 has been upgraded." Towns 1–9, 11, 12, 13 and 15 are not included.
- **Weather.** "Weather is fixed to daylight setting. Clouds, rain, fog and sun position cannot be
  modified."
- **Performance.** "Current peak frame rates recorded in internal tests are around 24/25 FPS."
- **Hardware.** "We recommend a minimum of 16 Gb of VRAM for version 0.10.0"; GPUs with less than
  12 GB "may not be capable of loading the default map."
- **Not migrated.** Map layers API, large maps, OpenDRIVE import, digital twins pipeline, asset
  import pipeline, V2X, Gbuffers. "The LightManager and related classes have been removed."

The release notes additionally record "RSS functionality removed from docs" and physics migrated
from PhysX to Chaos.

The weather limitation is decisive for this project rather than merely inconvenient. ASTRA's L6
covariate-shift detector is specified to notice a distribution change between operating conditions,
and the Phase 7 work requires demonstrating adaptation to rain without catastrophic forgetting of
highway behaviour. A build that cannot render rain cannot exercise the feature it would be bought
for. Separately, **0.10.0 has no PyPI distribution at all** — the `carla` project's release list
jumps from 0.9.16 with no 0.10.0 entry (source: <https://pypi.org/pypi/carla/json>, checked
2026-07-29) — so its client must be installed from the wheels bundled in the package, which is a
strictly worse dependency-management story than `pip install carla==0.9.16`.

### F4 — Route (b) is unnecessary, and the artefact it referred to is dead

The best-known community client package on PyPI is `carla-client-unofficial`. Its full release
history, queried 2026-07-29:

| Version | Uploaded | Wheel tags |
|---|---|---|
| 0.9.10 | 2021-03-08 | cp38 |
| 0.9.10.1 | 2021-03-08 | cp36, cp37, cp38 |
| 0.9.11 | 2021-03-09 | cp36, cp37, cp38 |

Source: <https://pypi.org/pypi/carla-client-unofficial/json> (checked 2026-07-29).

It has not been touched in five years, tops out at CARLA 0.9.11, and **its newest interpreter is
CPython 3.8** — it does not solve the problem it would have been reached for. No maintained
third-party wheel targeting CPython 3.10+ was found. That is unsurprising: since 0.9.15 and
decisively since 0.9.16, upstream publishes the wheels itself, which removes the demand that
produced such builds.

The supply-chain point should be stated even though the route is moot. An unofficial binary
rebuild of a native extension module, unsigned and of unrecorded provenance, sitting inside the
toolchain of a system that produces certification evidence, is a liability that has to be justified
to an assessor. The justification would have to be "upstream does not provide it", and upstream
does.

### F5 — CARLA does not run on macOS, and neither does its client

This is the finding with the longest life, and it is independent of the interpreter question.

- **No macOS package is built.** The 0.9.16 quickstart states: "CARLA is built for Windows **10**
  and **11** and Ubuntu **20.04** and **22.04**." Source:
  <https://raw.githubusercontent.com/carla-simulator/carla/0.9.16/Docs/start_quickstart.md>
  (checked 2026-07-29); rendered at <https://carla.readthedocs.io/en/latest/start_quickstart/>.
- **No macOS package is offered for download.** The downloads page lists Linux and Windows
  packages only. Source: <https://carla.readthedocs.io/en/latest/download/> (checked 2026-07-29).
- **The Docker images are x86-64 Linux only.** Every tag of `carlasim/carla`, including 0.9.16 and
  0.10.0, publishes a single `linux/amd64` image with no `arm64` variant. Source:
  `https://hub.docker.com/v2/repositories/carlasim/carla/tags` (checked 2026-07-29).
- **Not even the client wheel installs.** The 0.9.16 wheel tags are `manylinux_2_31_x86_64` and
  `win_amd64`. There is no `macosx` tag and no `aarch64` tag, so `pip install carla` fails on
  Darwin arm64 regardless of interpreter version. Source: <https://pypi.org/pypi/carla/json>
  (checked 2026-07-29).
- **Apple Silicon support is a five-year-old unmerged pull request.** PR #5086, "Add early support
  for Apple Silicon (M1) build", was opened 2022-01-18, targets `master`, and remains **open and
  unmerged** as of its last update on 2025-07-10. Source:
  <https://github.com/carla-simulator/carla/pull/5086> (checked 2026-07-29).

**The plain implication:** the developer's Darwin arm64 machine cannot host CARLA under any of the
three routes. Simulator work requires a Linux x86-64 machine with a dedicated NVIDIA GPU — the
0.9.16 quickstart recommends "a dedicated GPU equivalent to an NVIDIA 2070 or better with at least
8Gb of VRAM" and about 20 GB of disk. A local VM is not a substitute (no GPU passthrough on macOS)
and Docker Desktop is not a substitute (`amd64` images under emulation, still no GPU). The options
are a Linux workstation, a remote box, or a cloud GPU instance.

`manylinux_2_31` also sets a floor on that host: glibc 2.31 or newer, which is Ubuntu 20.04 or
newer — consistent with CARLA's own stated support matrix.

### F6 — Sensor payloads are megabyte-scale, which is what makes an IPC hop expensive

Route (c)'s cost is dominated by payload size rather than by call overhead, so the payload sizes
are worth establishing before the transport is discussed. From the 0.9.16 sensor reference
(<https://carla.readthedocs.io/en/0.9.16/ref_sensors/>, checked 2026-07-29):

- **RGB camera.** Defaults `image_size_x` 800, `image_size_y` 600; output is an "array of BGRA
  32-bit pixels", i.e. 4 bytes per pixel.
- **LiDAR (`ray_cast`).** Defaults `points_per_second` 56000, `rotation_frequency` 10.0; output is
  an "array of 32-bits floats (XYZI of each point)", i.e. 16 bytes per point.

Arithmetic from those cited defaults, not a measurement: a default camera frame is
800 × 600 × 4 = **1.92 MB**; at 1920 × 1080 it is **8.29 MB**. A default LiDAR revolution is
56000 / 10 = 5600 points × 16 bytes = **90 KB**. At 20 Hz with a single default camera, a sidecar
would move roughly 38 MB/s across the boundary; with a 1080p camera, roughly 166 MB/s.

The consequence for transport choice is that any mechanism which *copies or serialises* the frame
pays a cost proportional to megabytes, while any mechanism which passes a *reference* into shared
memory pays a cost proportional to bytes. That distinction matters far more than the difference
between two socket types.

### F7 — Route (c)'s IPC cost: what the published figures say, and what they cannot say

**Nothing here is a measurement of ASTRA.** No benchmark was run on this project's hardware. Every
figure below is a third party's measurement, quoted with its stated conditions, and each is
attributed. Where a source does not document its hardware, that is recorded as a defect of the
source rather than passed over.

**Transport ranking is consistent across independent sources.** The best-documented comparison is
F. Werner (Max Planck Institute for Nuclear Physics), "Using gRPC for (local) inter-process
communication", September 2021 — AMD EPYC 7402P, CentOS 8, gRPC v1.40.0, **C++17**, 1,000,000 calls
per configuration, payload one fixed64 field. **Round-trip** unary latency:

| | median | p95 | p99 |
|---|---|---|---|
| Unix domain socket, same core | 4 µs | 5 µs | 6 µs |
| Unix domain socket, other core | 11 µs | 12 µs | 13 µs |
| gRPC, same core | 167 µs | 178 µs | 200 µs |
| gRPC, other core | 116 µs | 129 µs | 142 µs |

Source: <https://www.mpi-hd.mpg.de/personalhomes/fwerner/research/2021/09/grpc-for-ipc/> (checked
2026-07-29). The author's own summary is that "gRPC is about a factor of 10 slower than blocking
I/O over Unix domain sockets". **This is C++ gRPC; the Python implementation would be slower**, and
gRPC's own performance guide states that "Streaming RPCs create extra threads for receiving and
possibly sending the messages, which makes streaming RPCs much slower than unary RPCs in gRPC
Python" (<https://grpc.io/docs/guides/performance/>, checked 2026-07-29).

A second source with documented hardware — `goldsborough/ipc-bench`, Intel Core i5-4590S @ 3.00 GHz,
Ubuntu 20.04.1, round-trip ping-pong throughput — gives the same ordering at 100-byte payloads:
memory-mapped files 5,338,860 msg/s, shared memory 4,702,557, pipes 162,441, domain sockets 130,372,
TCP 70,221, ZeroMQ over TCP 24,901. Source: <https://github.com/goldsborough/ipc-bench> (checked
2026-07-29). Inverting those rates gives roughly 213 ns, 7.7 µs and 14.2 µs per round trip for
shared memory, domain sockets and TCP respectively — an inversion performed by us, not published.

**Shared memory's advantage is the one figure with independent corroboration.** Three unrelated
ping-pong benchmarks put small-payload shared-memory round trips within about 40% of each other:
≈213 ns at 100 B (goldsborough, above), 270 ns at 32 B (V. Anderssén, "Linux IPC Shootout", 1 May
2026, <https://victoranderssen.com/blog/linux-ipc-benchmark/>), and ≈187 ns at 64 B
(<https://github.com/brylee10/unix-ipc-benchmarks>). **Neither of the latter two documents its
hardware**, which is why they are cited for corroboration of an order of magnitude rather than for
a number.

**At the payload sizes that matter here, the socket-versus-shared-memory gap widens.** La Corte,
Rashid and Dan (Hitachi Energy Research), "Performance Evaluation of Brokerless Messaging
Libraries", arXiv:2508.07934, 2025 — Intel Xeon w3-2435, 8 cores @ 3.1 GHz, 64 GB RAM, single
machine, ZeroMQ 4.3.4, 5,000 messages, **one-way** latency measured by embedding a timestamp in the
payload — reports ZeroMQ `ipc` (Unix domain socket) transport at roughly 200 µs for 128 KB and over
400 µs for 512 KB, against roughly 80 µs for 128 KB over `inproc`. Throughput: `inproc` 3–5 GB/s,
`ipc` 1–3 GB/s. Source: <https://arxiv.org/html/2508.07934v1> (checked 2026-07-29). **These values
were read off the paper's figures rather than a table and are approximate.**

**gRPC is disqualified for this payload profile on two independent grounds.** First, its default
maximum receive message size is 4 MB — below F6's 8.29 MB 1080p frame — so multi-megabyte frames
fail without explicit reconfiguration. Verified in two places: `defaultServerMaxReceiveMessageSize
= 1024 * 1024 * 4` in grpc-go's `server.go`
(<https://raw.githubusercontent.com/grpc/grpc-go/master/server.go>) and Microsoft's gRPC
configuration table, which lists a 4 MB default for both client and server
(<https://learn.microsoft.com/en-us/aspnet/core/grpc/configuration?view=aspnetcore-9.0>), both
checked 2026-07-29. Second, the only attributable localhost large-payload measurement found —
grpc-go issue #5676, 1 MB payload, gRPC-Go v1.48 — reports p50/p90/p99 of 1.972 / 2.313 / 2.685 ms
(<https://github.com/grpc/grpc-go/issues/5676>, checked 2026-07-29). **Its hardware is undocumented,
maintainers never confirmed it, and the issue went stale**, so it is a single unreviewed datapoint —
but roughly 2 ms per megabyte against a 10 ms total budget is the right order of magnitude to worry
about, and no better-sourced figure was found.

**The methodological warning is more important than any of the numbers above.** Essentially every
published IPC benchmark, including all of those cited here, measures messages sent *back to back*.
libzmq issue #4673 documents that inserting a **1 ms** idle gap between round trips raised ZeroMQ's
average latency from under 50 µs to **277.231 µs** — 100-byte payload, 10,000 round trips,
Ubuntu 23.10 / Debian Buster, reproduced independently in C++, Python and Rust
(<https://github.com/zeromq/libzmq/issues/4673>, checked 2026-07-29). ASTRA's loop idles roughly
50 ms of every 50 ms period. **Every figure in this section is therefore systematically optimistic
for this workload, by an unknown factor**, and none of them may be carried into a latency argument
without being re-measured at a 20 Hz duty cycle on the target hardware.

What follows from the mechanism rather than from any measurement: a sidecar adds, per frame, one
serialisation in the 3.8 process, one transfer, one deserialisation in the 3.12 process, and two
scheduler wakeups. Under a shared-memory design the transfer collapses to a pointer hand-off plus a
synchronisation primitive and the serialisation terms collapse to a buffer write and a
`memoryview`; under a socket or RPC design neither collapses, and both scale with F6's
megabyte-scale payloads. `multiprocessing.shared_memory` exists in both 3.8 and 3.12, so it is
available on both sides — at the price of hand-written framing, buffer lifetime management and a
synchronisation protocol, i.e. the transport becomes project code that has to be correct.

**Could not verify, and therefore not quoted:**

- **The official ZeroMQ wiki latency and throughput figures.** `wiki.zeromq.org` serves a
  certificate valid only for `*.wikidot.com` and `zeromq.wikidot.com` is in a redirect loop, so
  neither `area:results` nor `whitepapers:measuring-performance` is fetchable. The widely repeated
  "40 µs for 1-byte messages" and "~150 µs stabilised" figures trace to those pages and are
  **deliberately not cited here.**
- **Protobuf serialisation cost for large payloads.** No primary source found; searches returned
  only unattributed blog content with mutually inconsistent figures.
- **Memory-copy bandwidth, Python `pickle` overhead for large arrays, and
  `multiprocessing.shared_memory` benchmarks.** Not obtained. PEP 574's Performance section
  (<https://peps.python.org/pep-0574/>) is the right primary source for the pickle protocol 5
  zero-copy argument and was not read in time for this report.
- **lmbench's canonical IPC latency table.** Both the USENIX PDF and the FreeNIX results page
  return HTTP 403.

**One comparative caution:** ZeroMQ's own `perf` tools report **one-way** latency
(`latency = (double) elapsed / (roundtrip_count * 2);` in `perf/remote_lat.cpp`), while the Werner,
goldsborough and Anderssén figures are **round-trip**. Mixing the two silently doubles or halves a
budget. Any future comparison must normalise them.

### F8 — There is no prior art for a cross-interpreter CARLA bridge

No open-source project was found that runs the CARLA client on an older interpreter and bridges it
to a newer one. Searches for "carla python 3.12 bridge", "carla sidecar" and variants returned only
ROS-bridge forks and version-mismatch troubleshooting threads.

The loose architectural analogue is `carla-simulator/ros-bridge`
(<https://github.com/carla-simulator/ros-bridge>, checked 2026-07-29), which does run the CARLA
client in its own process with data crossing a boundary — but its interpreter is dictated by the
ROS distribution rather than chosen to escape a version conflict, and Python-version friction is a
longstanding open topic there (<https://github.com/carla-simulator/ros-bridge/issues/344>).

This matters for the rejection of route (c): it would have been **bespoke work with no design to
copy**, and the schedule cost of that is easy to underestimate.

## Comparison of the three routes

Scored H/M/L where the direction is stated in the column heading. **Route (a)** is split because
0.9.16 and 0.10.0 differ materially on everything except the interpreter.

| Criterion | (a1) CARLA 0.9.16 | (a2) CARLA 0.10.0 | (b) Community wheel | (c) 3.8 sidecar |
|---|---|---|---|---|
| **Interpreter compatibility (3.12)** | Official `cp312` wheel on PyPI (F1) | Officially supported 3.8–3.12; no PyPI dist (F3) | **None exists** for 3.10+; best-known artefact tops out at cp38 (F4) | Sidesteps the question by construction |
| **Latency impact** | **None.** In-process; A-2's budget untouched | None | None | **The only route with a per-frame cost.** Published localhost figures put UDS round trips in the µs range at small payloads and ZeroMQ over UDS in the hundreds of µs at 128–512 KB, but all are back-to-back measurements and optimistic for a 20 Hz duty cycle (F6, F7) |
| **Supply-chain / provenance risk** | **Low.** Official wheel, verified PyPI maintainer (F1) | Low, but installed from a bundled wheel rather than an index (F3) | **High.** Unsigned third-party binary, unmaintained since 2021 (F4) | Low for the client; the bridge itself becomes bespoke project code |
| **Maintenance burden** | **Low.** One pinned dependency | Low, but on a line still absorbing migration churn | High. Somebody must rebuild it per interpreter, forever | **High.** Two interpreters, two dependency sets, a wire format, a failure mode where the bridge dies silently — and no prior art to copy (F8) |
| **Feature completeness** | **Full 0.9 line.** All towns, full weather, TM, OpenDRIVE, V2X | **Reduced.** Town 10 only, daylight-only weather, no OpenDRIVE import, no large maps, LightManager removed (F3) | Full, but of CARLA 0.9.11 — five years stale | Full, whatever the sidecar's CARLA offers |
| **macOS / dev-machine practicality** | **None.** No macOS build, no arm64 wheel, amd64-only images (F5) | None (F5) | None (F5) | None. The sidecar still needs a CARLA server (F5) |
| **Reversibility** | **High.** One optional dependency behind `SensorSource`; no `src/astra/` change | High, same reason | High, same reason | **Low-ish.** Reverting is easy, but the bridge, its tests and its ops story are sunk work |

The macOS row is uniform, which is the point of including it: **no route makes the developer's
machine viable**, so it cannot discriminate between them and must instead be handled as a separate
constraint on the phase plan.

## Recommendation

**Adopt route (a1): target CARLA 0.9.16 and install its official `cp312` wheel into the project's
Python 3.12 interpreter. Reject the sidecar and the community wheel. Sequence Phase 2 so that L1
and L2 are built and validated against an in-process fake `SensorSource` now, and bind the CARLA
adapter when a Linux x86-64 host with an NVIDIA GPU is available.**

The reasoning is in four steps.

**R-6's premise expired.** The finding was written against CARLA 0.9.14, whose newest client wheel
is cp38. CARLA 0.9.16, released 2025-09-16 — after ADR-0003 was written — publishes an official
cp312 wheel to PyPI (F1). There is no longer an incompatibility to resolve, only a version number
in the source documents to supersede. This is the outcome A-8 hoped for and the one branch of it
that costs nothing at runtime: the adapter runs in-process, so A-2's 10 ms budget is untouched by
this decision and the timing argument stays simple.

**0.9.16 rather than 0.10.0.** Both clear the interpreter bar, so the choice turns on everything
else, and 0.10.0 loses on all of it for this project: one town, daylight-only weather, ~24/25 FPS,
16 GB VRAM recommended, and no OpenDRIVE import (F3). Daylight-only weather is not a minor gap for
a system whose covariate-shift detector and Phase 7 forgetting test are both specified in terms of
a rain/highway distribution change. 0.9.16 shipped after 0.10.0 and is named the latest release
(F2), so choosing it is not choosing a dead end. The UE5 migration is a future adapter rewrite, and
recording it as such is more honest than adopting a half-migrated build now.

**Fakes first, and this is forced rather than merely prudent.** CARLA has no macOS build, no arm64
wheel and no arm64 image (F5), so nobody on this project can currently run it at all. Every Phase 2
exit criterion — a UKF validated in isolation, byte-identical replay, fast-filter latency under
1 ms — is reachable against a synthetic `SensorSource` implementing the same `Protocol`. Building
against fakes now converts a hardware-procurement dependency at the front of the phase into an
integration task with a known answer at the end of it, which is the schedule de-risking the port
was built to permit. `carla` therefore ships as an optional extra, never a core dependency, so
`astra` stays installable and testable on machines that cannot host the simulator.

**The isolation contract is unaffected, which is the whole point.** `.importlinter`'s
`simulator-isolation` contract continues to forbid `carla` anywhere in `astra`, with
`astra.adapters.carla` added as the single named exclusion when that module is written. Nothing
under `src/astra/` changes as a result of this spike. ADR-0003 predicted that all three routes were
deployment choices; that prediction held, and the 0.9.14 → 0.9.16 upgrade touches no core file.

Recorded as [ADR-0015](../adr/0015-carla-interpreter-strategy.md).

## What would change the recommendation

Each of these is a re-check with a stated trigger, not a vague caveat.

1. **`pip install carla==0.9.16` fails on CPython 3.12, or the client segfaults against a 0.9.16
   server.** This is the one finding that would reopen the whole spike. The 0.9.15 changelog's
   "Fixed segfaults in Python API due to incorrect GIL locking under Python 3.10" shows that this
   failure mode is real for a newly-added interpreter. **Re-check:** on the Linux host, first. If
   3.12 is broken and 3.11 is not, the fallback is the 0.9.16 `cp311` wheel plus reverting to
   3.11 — which ADR-0003 costs as a bounded mechanical migration — before the sidecar is
   reconsidered.
2. **A 0.10.x release restores weather, the other towns and OpenDRIVE import.** That would make the
   UE5 line the better target and turn ADR-0015 into a superseded record. **Re-check:** at the start
   of Phase 4, and whenever a new CARLA release is announced.
3. **CARLA drops the 0.9/UE4 line.** The current statement is that the lines coexist "for the
   foreseeable future" (F2). An announced end-of-life for 0.9.x would force the 0.10.x migration on
   someone else's schedule. **Re-check:** annually, or on any CARLA release announcement.
4. **The project acquires a macOS-only constraint it cannot buy its way out of.** If no Linux GPU
   host is ever available, the CARLA adapter cannot be run by anyone, and the honest response is to
   scope the simulator out and state the fake as the only validation environment — not to pretend a
   sidecar helps, because it does not (F5).
5. **A future need arises to run the client in a different interpreter from the core** — for
   instance an ML dependency that pins an incompatible Python. Then route (c) returns on its own
   merits, and F7's instruction applies: measure the candidate transports at F6's payload sizes,
   on the target hardware, **at a 20 Hz duty cycle rather than back-to-back**, before choosing one.
   The published figures are a guide to which transports are worth benchmarking — shared memory
   and Unix domain sockets, not gRPC — and are not themselves a budget.

## Open questions

- **Everything in F1–F5 is verified on paper, not on metal.** No one has installed the 0.9.16
  cp312 wheel, launched a 0.9.16 server, or connected the two. A-8 should move to *evidenced* on
  this report and to *closed* only after that. This is the single largest gap in the spike.
- **Client and server must be version-matched.** CARLA emits "Version mismatch detected: You are
  trying to connect to a simulator that might be incompatible with this API" when they differ
  (source: <https://github.com/carla-simulator/carla/issues/2470>, checked 2026-07-29). So `pip
  install carla==0.9.16` is only correct if the server is also 0.9.16. Whether a 0.9.16 client is
  usable against a 0.9.15 server is **unverified** and should be assumed false.
- **The 0.9.14 → 0.9.16 API delta is enumerated but not assessed.** Two changes in the 0.9.16
  changelog are known to be breaking rather than additive: `Sensor.is_listening` was "defined twice
  (property and method), cleaned and clarified it as a method", and "carla.ad subpackages are now
  directly importable and are not directly importable anymore" (source:
  <https://github.com/carla-simulator/carla/releases/tag/0.9.16>, checked 2026-07-29). No scenario
  code exists yet, so nothing is broken today, but any script lifted from 0.9.14 material must be
  read rather than assumed.
- **Synchronous mode and the `Timeline.SIMULATED` clock are untested against 0.9.16.**
  `kernel/time.py` assumes CARLA's synchronous mode advances simulated time in fixed steps
  decoupled from wall clock. That is CARLA's documented behaviour for the 0.9 line, but the
  determinism of sensor callback delivery under 0.9.16 — which is what byte-identical replay
  depends on — is unverified.
- **The 0.9.16 documentation lags its own release.** The quickstart at the 0.9.16 tag still says
  "the latest release, which is currently 0.9.15", and still claims "CARLA supports Python 3.7 to
  3.12 on Ubuntu" although no cp37, cp38 or cp39 wheel is published for 0.9.16 (F1). Where the docs
  and the published wheel tags disagree, **the wheel tags were treated as authoritative** in this
  report. Anyone re-reading the docs should know they are stale.
- **No route (c) latency figure applies to this workload.** F7 quotes published figures with their
  sources, but every one of them measures back-to-back sending, and libzmq#4673 shows a 1 ms idle
  gap alone degraded ZeroMQ latency more than fivefold. The number ASTRA would actually need does
  not exist in the literature and would have to be measured. Several sub-questions were left
  unverified outright and are listed in F7.
- **GPU host not identified.** F5 establishes what is needed; procuring it is an action item this
  spike does not resolve.
