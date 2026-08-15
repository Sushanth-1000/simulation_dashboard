# ADR-0031: Decay measures the duty cycle the counter cancels out

- **Status:** Accepted
- **Date:** 2026-08-15
- **Defect closed:** OD-21 in [`../CREDIBILITY_MATRIX.md`](../CREDIBILITY_MATRIX.md)
- **Evidence:** E-135, E-137, E-138 in [`../EVIDENCE.md`](../EVIDENCE.md)

## Context

The sensor-integrity counter moves **+1** on an unhealthy frame and **−1** on a
healthy one. That symmetry is what makes recovery automatic and bounded, and it
has an arithmetic consequence nobody had written down: **any duty cycle at or
below 50% nets to zero and never escalates, however long it runs.**

Measured over a full minute at 20 Hz on the shipped profile (E-135):

| pattern | ticks dark | % dark | peak φ | worst posture |
|---|---|---|---|---|
| 1 dark / 1 clean | 600 / 1200 | 50 | **1** | **NOMINAL** |
| 3 dark / 3 clean | 600 / 1200 | 50 | 3 | NOMINAL |
| 3 dark / 10 clean | 279 / 1200 | 23 | 3 | NOMINAL |
| 20 dark / 20 clean | 600 / 1200 | 50 | 20 | LIMP |
| continuously dark | 1200 / 1200 | 100 | 40 | HALT |

**A camera dark half the time for a full minute reported perfect health.** A
camera dropping a quarter of its frames reported perfect health. Both are
failing hardware, and the only thing that separated the visible row from the
invisible ones was the *period* of the fault, not its severity.

It is a duty-cycle detector with a 50% threshold, and it had been described as a
health detector.

### The counter is not wrong

It answers *"am I in trouble now?"*, and the honest answer is no — the estimator
had a fresh reading a tick ago. It is memoryless **by design**, and that is the
same property that makes recovery automatic and gives it the bounded 91-tick
worst case the module docstring advertises. Changing it would cost more than it
bought.

So the defect is not in the counter. It is that no quantity in the system
answered the *other* question — *is this sensor dying?* — and that question is
the one a fleet operator asks.

## Decision

A **per-modality exponential average of the unhealth indicator**, which
converges to exactly the duty cycle the counter cancels out.

```python
alpha = 2 / (decay_window_ticks + 1)
decay[m] += alpha * (unhealthy - decay[m])
```

Measured after (E-137): the 50% patterns report **0.497**, **0.492** and
**0.475**; the 23% pattern reports **0.240**. The counter still peaks at 1 on
the first, correctly.

### Why this is not the weighted counter this project keeps refusing

[ADR-0028](0028-the-deployment-declares-which-sensors-are-critical.md) and
[ADR-0029](0029-capability-withdrawal-is-a-second-axis-not-a-third-counter.md)
both rejected weighting because *"the camera is worth 0.4 of an IMU"* is
unfalsifiable, and an unfalsifiable number in a safety argument is worse than a
missing one.

This number is not of that kind. It is **a fraction of recent frames**, it has
units, and it is checkable against the hardware: *this stream missed 23% of its
frames* is either true of the sensor or it is not. Nobody has to accept a
judgement to accept the measurement.

### It drives nothing, and that is the decision as much as the formula

No posture, no veto, no command, no gate. A decaying sensor is a **service**
condition, and a vehicle that stopped for maintenance would be the nuisance stop
OD-18 removed arriving through a different door. It reports; the fleet decides.

This is the project's standing rule — *no mechanism gets authority until it has
run with none* — and here it also settles the threshold question. What fraction
of dropped frames means *service this* is a property of a particular sensor on a
particular vehicle, and no such number has been measured. `decay_service_threshold`
is therefore unset in every shipped profile: declared, it names the sensors that
crossed it; undeclared, the decay is measured and reported and flags nothing.

### Two things it deliberately does not do

**It is not cleared by `reset`.** Otherwise halt → reset → halt → reset would
launder a failing sensor clean, and the record would show a healthy fleet
forever. A reset clears what the machine decided; it does not make the camera
younger.

**A modality missing from the frame is not decayed toward health.** No
observation is not evidence of health, and decaying an unreported stream toward
zero would let one that stopped being *reported* look like one that recovered —
the inversion this register has already filed twice.

## Alternatives considered

**Make the counter asymmetric** — rise by 1, fall by 0.5. Cheapest change, and
it destroys the property being relied on: recovery stops being bounded by
`θ_halt − θ_degraded + hysteresis`, and the module docstring's 91-tick guarantee
becomes false. It also still cannot attribute, because the counter is aggregate.

**A second, slower counter per modality.** Workable, and it would have to invent
its own thresholds and decay rate — two more numbers with no measurement behind
them. The fraction needs none: 0.23 means 23%.

**Count total unhealthy ticks per modality, monotonically.** Honest and useless
after an hour: a sensor that glitched once at start-up is indistinguishable from
one failing now, because nothing ever comes back down.

**Detect it in L1 instead.** Arguably the right long-term home — the bus sees
the stream — and rejected for now because L1 would need per-modality history it
does not currently keep, and because the quantity is wanted in the *fail-safe
snapshot*, which is what the audit record and the explainer already read.

**Leave it to the fleet's telemetry.** The data would have to be exported first,
and it was not in the archive at all: this is the fifth time a quantity the
pipeline could compute was missing from the evidence, after schema 3, 5, 7 and 8.

## Consequences

### Positive

- The blind spot is closed and its shape is now stated: a duty-cycle detector
  with a 50% threshold, documented in the module that implements it.
- **Predictive maintenance falls out of the safety monitor at no extra sensor
  cost.** The same health map that protects the vehicle now says which sensor to
  service, per modality, in every audit row — which is a fleet-operator feature
  derived from a safety mechanism rather than bolted beside it.
- Non-critical modalities are tracked too. Criticality governs the posture; it
  says nothing about what is worth knowing, and an operator servicing a camera
  cares whether it is dying regardless of what it is allowed to stop.
- The archive can be mined retrospectively. A fleet's schema-10 logs carry per-
  sensor wear whether or not anyone was looking for it at the time.

### Negative / accepted trade-offs

- **It is a lagging indicator by construction.** A 200-tick window needs several
  seconds to move, so a sensor that fails abruptly is caught by the counter and
  not by this. The two are complementary and neither covers the other.
- **`decay_window_ticks` has a default where A-4 values do not.** It is a filter
  constant rather than a threshold — it changes how quickly a number converges,
  not whether anything happens — but it is a number in a safety file with no
  measurement behind it, and 200 was chosen for being 10 s at 20 Hz.
- **No shipped profile arms the service signal**, so the threshold path is
  proved by tests and by a benchmark, not by the default configuration. Same
  position as ADR-0029's graceful path.
- **It still cannot see a sensor that lies fluently.** `StreamHealth` is
  computed from staleness, so a stream publishing fresh, well-formed, slowly
  wrong values reads `HEALTHY` for ever and its decay stays at zero. That is
  OD-9's remaining two-thirds and needs redundancy (OD-15), not this.
- **Sixth change to this machine in five days**, and the second today. The
  pattern is now clear enough to name: L1 has been computing a rich health
  signal since Phase 1, and L8 was built to read one bit of it because when it
  was written there was one sensor and one bit was all there was.
