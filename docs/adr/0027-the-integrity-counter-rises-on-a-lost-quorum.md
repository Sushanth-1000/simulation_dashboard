# ADR-0027: The integrity counter rises on a lost quorum, not on any bad channel

- **Status:** Accepted
- **Date:** 2026-08-11
- **Successor to** [ADR-0024](0024-sensor-integrity-is-a-second-counter-not-a-fourth-gate.md), which named this decision and its trigger
- **Forced by** [ADR-0026](0026-faulted-gets-a-producer-and-the-counter-needs-a-quorum.md) and E-116
- **Evidence:** E-117 – E-119 in [`../EVIDENCE.md`](../EVIDENCE.md)

## Context

ADR-0024 gave L8 a sensor-integrity counter that rises when **any** modality is
worse than `HEALTHY`. That was right, and the record said why it would stop being
right:

> **Any modality, not a quorum.** A single unhealthy channel is enough, because
> the modalities are not redundant in this build — there is one publisher per
> modality and no cross-check to fall back on. When redundancy exists this is the
> line that should become a vote, **and it needs its own decision record when it
> does.**

Redundancy arrived with ADR-0026, and the prediction came true on the first run.
With three position channels fused by median and a drift injected into one, the
vehicle drives *well* — **0.042 m** deviation, two good channels, a median that
correctly excludes the liar — and the integrity counter climbs to 40 and **HALTs
it** (E-116). A recoverable single-channel fault converted into a stop.

## Decision

**The counter rises when the number of unhealthy modalities exceeds
`integrity_tolerated_faults`, a configured declaration of how many the
deployment can absorb.**

```python
unhealthy = sum(1 for _, health in frame_health if health is not StreamHealth.HEALTHY)
if unhealthy <= self._settings.integrity_tolerated_faults:
    return max(_COUNTER_FLOOR, self._integrity - 1)
return min(self._settings.integrity_threshold_halt, self._integrity + 1)
```

Measured across the two settings that matter:

| tolerance | channels faulted | posture after 60 ticks | φ |
|--:|--:|---|--:|
| 0 | 1 | **HALT** | 40 |
| 0 | 2 | HALT | 40 |
| **1** | **1** | **NOMINAL** | **0** |
| 1 | 2 | **HALT** | 40 |

**At zero this is bit-identical to ADR-0024**, because one unhealthy channel
already exceeds zero — and zero is what every shipped profile sets. All 2,915
tests pass unchanged.

### Why the threshold is configuration and not a constant

How many lying channels a vehicle can absorb is a property of **its sensor set**,
which is exactly the platform knowledge NFR5 keeps out of the layers. L8 counts
modalities; the deployment declares what it can survive. That keeps L8 neutral
and puts the claim in a file a safety engineer signs.

**It is a safety threshold and therefore has no default** (A-4). Raising it above
zero asserts two things, and *both* are required:

1. the sensor set carries enough independent measurements of each quantity to
   keep working with that many of them lying, **and**
2. something actually excludes the liar from the fusion.

Either alone is not redundancy. Three channels with a mean rather than a median
satisfies (1) and fails (2), and a liar corrupts the mean in exact proportion to
its lie.

## Alternatives considered

### 1. A constant in the layer

Rejected. It is platform knowledge and NFR5 forbids it there; it would also be
wrong for every deployment but one.

### 2. Have the monitor report `DEGRADED` rather than `FAULTED` while a quorum survives

Rejected, and it is the tempting one because it needs no L8 change at all. It
fails because L8 treats **anything** not `HEALTHY` as unhealthy, so a `DEGRADED`
channel escalates identically — the change would move the problem rather than fix
it. It also lies in the record: the channel *is* faulted, and downgrading its
reported health to obtain a downstream behaviour is the kind of inversion this
register has filed twice (OD-2, OD-7).

### 3. A frame-level "is this trustworthy" boolean from the monitor

The cleanest in the abstract, and rejected as premature. It moves the severity
decision into the adapter, where it is invisible to configuration review, and it
needs a second port method to carry information one integer already carries.

### 4. A second threshold: tolerated-but-degraded

Considered and deferred. It would report `DEGRADED` at one fault and `HALT` at
two, so the loss of fault tolerance changes the posture. Rejected *for now*
because it imposes a speed cap on a vehicle with no safety problem, and because
**the loss is already visible**: per-modality health is on every audit record, so
an auditor sees `FAULTED` on a channel beside a `NOMINAL` posture. The posture
answers *"is the vehicle in trouble?"* and the health map answers *"what is
broken?"*, and those are different questions.

## Consequences

### Positive

- **The vehicle keeps driving when it safely can.** One faulted channel of three,
  median working, deviation 0.042 m: NOMINAL, and correctly so.
- **It still stops when the quorum is lost.** Two faulted of three exceeds the
  declared tolerance and HALTs at φ 40, unchanged.
- **Zero regression.** Every shipped profile sets zero, and the whole suite
  passes unchanged — the claim checked rather than asserted.
- ADR-0024's named successor exists, which closes a loop that record deliberately
  left open.

### Negative / accepted trade-offs

- **Losing fault tolerance does not change the posture.** At tolerance 1, the
  first faulted channel leaves the vehicle one fault from a stop and the fail-safe
  machine reports NOMINAL. That is defensible — the vehicle is *fine* — and it
  is a real reduction in margin that only the health map records. An integrator
  who wants it escalated needs alternative 4, and it is written down above rather
  than left to be re-derived.
- **A wrong tolerance is a serious wrong number**, and nothing can check it. Set
  to 1 on a vehicle with one publisher per quantity, the system ignores its only
  sensor for that quantity — which is worse than the defect this fixes. The
  schema documents both halves of the claim; nothing enforces them, because
  nothing in software can count a vehicle's sensors.
- **It counts modalities, not quantities.** Five modalities with three measuring
  position and two measuring something else are treated as one pool. A
  deployment whose redundancy is uneven across quantities cannot express that in
  one integer, and will have to set the tolerance to its *weakest* quantity.
- **The denial-of-service surface shifts rather than closing.** At tolerance 1 an
  adversary needs two channels rather than one. Better, and not a fix.

## Implementation

`FailSafeSettings.integrity_tolerated_faults` (`config/schema.py`);
`_advanced_integrity` (`layers/l8_failsafe/machine.py`); the three environment
files, all at zero.

**Verified:** ruff clean, `mypy --strict` over 159 files, 12 import contracts,
**2,915 tests + 5 strict xfail passing unchanged at tolerance zero**.
