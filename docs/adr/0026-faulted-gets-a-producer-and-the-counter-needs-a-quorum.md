# ADR-0026: `FAULTED` gets a producer, and the counter now needs a quorum

- **Status:** Accepted, with a named successor decision
- **Date:** 2026-08-11
- **Defect narrowed:** OD-9's drift arm; **OD-15** partly
- **Evidence:** E-113 – E-116 in [`../EVIDENCE.md`](../EVIDENCE.md)
- **Completes a seam** reserved by `SensorReading.health_at`. **Triggers** the successor [ADR-0024](0024-sensor-integrity-is-a-second-counter-not-a-fourth-gate.md) named.

## Context

Four candidates were built and measured against a slow position drift and all
four are silent (E-53, E-94, E-105, E-106), for one shared reason: **a
self-consistent lie slower than the sensor noise cannot be distinguished from
truth by any function of a single sensor chain.**

The prototype had a single chain and did not look like it. `_publish_state`
computed one payload and published it byte-identical to five modalities;
`_Extractor` read the IMU and discarded the rest. **Five modalities, one sensor**
— OD-15, and about thirty lines of test harness rather than anything
architectural.

### The seam was reserved before anything could fill it

`SensorReading.health_at` has always said:

> *Only `HEALTHY` and `DEGRADED` can be decided here. `FAULTED` requires ... a
> monitor which knows what the reading should have been; a stale stream and a
> lying stream are different faults and are deliberately not collapsed.*

It named the UKF's innovation gate as that monitor. **Measured, that gate cannot
be**: at the shipped γ of 7.5 it fires on tick 0 of every arm *including the
control* and on no injected fault but a 25σ noise burst (E-105). `FAULTED` has
been an unreachable enum member for the project's whole life.

## Decision

**Three dissimilar channels, fused by median, cross-checked by residual — and
the residual monitor is the producer of `FAULTED`.**

`IntegrityMonitor` is a new port beside `MeasurementExtractor`, in the same
module and supplied by the same adapter, because deciding that two readings
*should* agree needs to know what each modality measures and NFR5 keeps that out
of the layers.

The pipeline merges its verdict with L1's staleness health by taking the **worse
of the two per modality**. Neither can mask the other: a stale channel is stale
whatever its values say, and a lying channel is lying however punctually it
arrives. **A modality the monitor omits keeps L1's verdict** rather than being
cleared — a monitor that can only judge position must not clear a camera.

### Three channels, and unequal sigmas

Three is the smallest number that permits a **median**, and the median is what
makes a liar *identifiable* rather than merely detectable: with two, a
disagreement says something is wrong and cannot say which. The fused measurement
being the median also means a single faulted channel is excluded from the
estimate **by construction** rather than by a decision.

The sigmas are deliberately unequal — IMU 0.1, GPS 0.2, LIDAR 0.06. Identical
sigmas model identical sensors, and identical sensors share a failure mode: two
devices from one batch drift the same way at the same temperature. Modelling
that away would make the result look better than it is.

### Bit-identity is preserved

The redundant channels draw from a generator seeded `seed ^ 0x2ED0`, so adding
them consumes no draw the IMU would have taken and a run with redundancy off is
**identical to one before this existed**. Same reasoning as the fault injector's
offset seed: an instrument that perturbs the thing it measures is not an
instrument.

## Consequences

### Positive

- **The drift is caught, and the estimate is protected, and these are two
  separate wins.** The median rejects the outlier from the first tick, so the
  deviation stays at **0.042 m** against the 2.025 m the same drift caused
  before (E-113). Independently, the monitor **identifies** the faulted channel
  at **+84 ticks** (E-114).
- **Zero false alarms.** The clean redundant arm holds the integrity counter at
  **0** across 400 ticks and never leaves NOMINAL.
- `FAULTED` has a producer for the first time, and the value stops being a
  documented aspiration.
- **Nothing in the layers changed** — a port, a merge at the composition root,
  and an adapter.

### Negative / accepted trade-offs

- **The escalation is now wrong, and this is the finding that matters.** With one
  of three channels faulted the vehicle is driving *well* — 0.042 m, two good
  channels, a median that works — and the integrity counter escalates it to
  **HALT**. ADR-0024's counter asks *"is any modality unhealthy?"*, which was
  right when there was no redundancy to fall back on and is wrong now.

  **ADR-0024 predicted this exactly** and named the trigger: *"any modality, not
  a quorum ... when redundancy exists this is the line that should become a vote,
  and it needs its own decision record when it does."* The condition has
  arrived. The successor decision is **loss of voting capability**, not channel
  count: with three channels, one faulted leaves a working pair and should
  degrade rather than stop; two faulted leaves nothing to vote with.

  It is left as a named successor rather than folded in here, because a
  fail-safe escalation policy is exactly the kind of thing that should not be
  changed in the same commit that gives it a new input.
- **Redundancy costs accuracy.** The clean redundant arm sits at **0.050 m**
  against the single-channel 0.009 m, because the fused sigma is the *worst*
  channel's — deliberately conservative, since claiming the median is better than
  its worst input would tell the filter to trust the fusion more than any single
  reading justifies.
- **The channels differ by noise draw and sigma, not by physics.** This shows
  the *information exists*; it does not show a real sensor suite behaves this
  way. Dissimilar redundancy in the field fails through correlated modes this
  plant cannot express — which is what CARLA is for, and the honest limit of
  every number here.
- **A new denial-of-service surface**, larger than ADR-0024's. An adversary who
  can bias one channel now stops the vehicle, and does not even need to silence
  it. The quorum successor reduces this; it does not remove it.

## Implementation

`IntegrityMonitor` (`layers/l2_estimation/measurement.py`);
`GovernancePipeline._frame_health` and the `integrity` parameter
(`runtime/pipeline.py`); `assemble_pipeline` (`runtime/assembly.py`);
`RedundantSensing` and the publish path (`training/closed_loop.py`);
`RedundantExtractor` and `ResidualMonitor` (`training/redundant.py`).

**Verified:** ruff clean, `mypy --strict` over 159 files, **12 import contracts
kept**, and the integration suite passes unchanged — which is the bit-identity
claim, checked rather than asserted.
