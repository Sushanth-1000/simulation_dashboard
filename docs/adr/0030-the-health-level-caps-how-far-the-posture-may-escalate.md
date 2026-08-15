# ADR-0030: The health level caps how far the posture may escalate

- **Status:** Accepted
- **Date:** 2026-08-15
- **Defect closed:** OD-20 in [`../CREDIBILITY_MATRIX.md`](../CREDIBILITY_MATRIX.md)
- **Evidence:** E-134, E-136 in [`../EVIDENCE.md`](../EVIDENCE.md)

## Context

`StreamHealth` has four values. L1 computes them, the pipeline merges two health
reports by taking the worse of them, and the Runtime Context Signature weights
them 1.0 / 0.5 / 0.1 / 0.0. The fail-safe machine read **one bit** of them —
`health is not HEALTHY` — in both places it consulted them.

Measured on the shipped profile, holding a camera at each level for three
seconds (E-134):

| camera health | posture | φ |
|---|---|---|
| `DEGRADED` | HALT | 40 |
| `FAULTED` | HALT | 40 |
| `ABSENT` | HALT | 40 |

A camera arriving **late** stopped the vehicle exactly as a camera that was
**gone**. This is OD-18's shape one level in: one response for situations the
system had already gone to the trouble of telling apart, and had been telling
apart since Phase 1.

`StreamHealth`'s own docstring says the distinction is deliberate — *"a stale
stream and a lying stream demand different responses, and collapsing them loses
that distinction"* — and the fail-safe machine collapsed it anyway.

## Decision

The deployment declares, per health level, the worst posture that level may
justify. The integrity counter's band is capped there.

```toml
[failsafe.integrity_ceiling]
DEGRADED = "LIMP"
FAULTED  = "HALT"
ABSENT   = "HALT"
```

After (E-136): a stale camera settles at **LIMP** — the vehicle slows to the
limp cap and keeps driving — while a dark one still HALTs. The counter is
untouched at 40 in both cases; only the posture is capped, so the log still
shows how long the fault ran.

### Why a ceiling is right here, having been rejected one record ago

[ADR-0029](0029-capability-withdrawal-is-a-second-axis-not-a-third-counter.md)
rejected a per-**modality** severity ceiling, and the two are not in tension.

A ceiling answers *how far*. **Modality identity is not a question about how
far** — asking how severe a camera is compared to an IMU has no defensible
answer, which is why that option collapsed into the weighted counter this
project keeps refusing. **`StreamHealth` is a severity**: it is literally how
far past the staleness budget a stream has fallen, and the ordering already
exists and is already relied on elsewhere. Mapping one severity onto another
invents no number. It has to defend exactly one claim — *a late reading is less
bad than no reading* — which a safety engineer can accept or reject on sight.

### Three properties

**It is a high-water mark, not an instantaneous read.** The ceiling caps a
counter that persists across ticks, so recomputing it from the current frame
alone would let a modality that *recovered* lift the cap while the counter was
still high — **halting the vehicle at the moment the sensor came back**. So it
only rises while a fault persists and resets when the counter reaches its floor,
where it stops mattering anyway. That failure is pinned by a test named after
it.

**A level the deployment did not name is uncapped.** Silence in a safety file is
not permission to be lenient: a profile naming `DEGRADED` and forgetting
`ABSENT` is far more likely to be incomplete than to intend that a vanished
sensor never escalates.

**Applied in one place, because the counter reaches a posture from three.**
Escalation, de-escalation, and the HALT check that short-circuits both. A cap
applied at two of them would be a fail-safe that escalated past its own ceiling
on one path — so the band and the cap live in a single method that all three
call.

## Alternatives considered

**Per-level counter increments** — `DEGRADED` +1, `ABSENT` +3. The weighted
counter again, wearing a different hat, and with the same fatal property: no one
can defend the ratio.

**A configured cut-off — which level starts counting.** Simple, and still
binary: it moves the line rather than removing it, so two of the three levels
still behave identically.

**Make the monitor report a milder health while a quorum survives.** Rejected
for the third time, and it is worth naming as a recurring temptation: changing a
component's *reported health* to obtain a downstream behaviour is the inversion
this register has filed twice (OD-2, OD-7). The health map is evidence.

**Leave it.** The measurement is what refuses this. Three rows reading HALT
identically is not a limitation to document; it is the same defect OD-18 closed,
in the adjacent field.

## Consequences

### Positive

- A stale sensor now slows the vehicle instead of stopping it, which is the
  proportionate response and the one a passenger would expect.
- The four levels L1 computes finally reach a decision. Before this, three of
  them were recorded and none was acted on differently.
- Undeclared reproduces the previous behaviour exactly, so the change is
  additive: it caps nothing until a profile says so.
- The monotonicity validator catches the likeliest typo — two adjacent lines of
  the same table transposed — which would otherwise assert that no reading is
  safer than a late one.

### Negative / accepted trade-offs

- **A wrong ceiling is a serious wrong number and nothing can check it.**
  Capping `ABSENT` at DEGRADED leaves a vehicle driving on a sensor that is
  gone. The validator enforces internal coherence, not correctness; only a
  safety engineer can supply that.
- **The cap hides how bad it got, in the posture.** A vehicle held at LIMP by a
  ceiling looks, in the state field alone, like one whose counter reached the
  LIMP band. The counter is in the record and disambiguates it, but a reader of
  the state column alone will be misled.
- **The high-water mark is per-machine, not per-modality.** Two modalities
  failing at different levels take the worse ceiling, and it stays until the
  shared counter clears. That is conservative and it is also imprecise.
- **`FAULTED` below `ABSENT` is asserted, not measured.** A lying stream tells
  the estimator something it can partly bound; a missing one tells it nothing.
  Defensible, consistent with the RCS weighting, and no measurement in this
  repository supports it.
- **Fifth change to this machine in five days.** The counter was written when
  there was one sensor. Everything that quietly rested on that has had to be
  found and stated one at a time, and this is the fifth.
