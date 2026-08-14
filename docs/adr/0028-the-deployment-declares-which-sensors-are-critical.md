# ADR-0028: The deployment declares which sensors are safety-critical

- **Status:** Accepted
- **Date:** 2026-08-11
- **Defect closed:** OD-18 in [`../CREDIBILITY_MATRIX.md`](../CREDIBILITY_MATRIX.md)
- **Evidence:** E-126 – E-128 in [`../EVIDENCE.md`](../EVIDENCE.md)
- **Third correction to one line**, after [ADR-0024](0024-sensor-integrity-is-a-second-counter-not-a-fourth-gate.md) and [ADR-0027](0027-the-integrity-counter-rises-on-a-lost-quorum.md)

## Context

ADR-0024 gave L8 a sensor-integrity counter that rises when a modality is
unhealthy. ADR-0027 made it rise only when *more* modalities are unhealthy than
the deployment declared it could absorb. Neither asked **which** modality.

Measured, driving the machine directly with one channel absent for two seconds:

| sensor that fails | what it feeds | posture after 2 s |
|---|---|---|
| **IMU** | position, speed, lateral acceleration | **HALT** |
| **CAMERA** | nothing the estimator reads | **HALT** |
| **RADAR** | nothing the estimator reads | **HALT** |

The extractor calls `frame.sample_for(SensorModality.IMU)` and nothing else, so
in the shipped configuration the camera and radar contribute **nothing** to the
state estimate that all three gates read — and losing either stops the vehicle in
two seconds. **A nuisance stop caused by a component that was not contributing.**

Found by a question a customer would ask — *"does it act differently depending on
which sensor degraded?"* — rather than by any test. The third defect this week
found that way, after OD-16 and OD-17.

### Why ADR-0024 missed it

That record justified counting rather than quorum on the grounds that *"there is
one publisher per modality and no cross-check to fall back on."* That is an
argument about **redundancy**. It is silent on **criticality**, and the two are
different questions: *how many can fail* is not *which ones matter*. ADR-0027
answered the first and inherited the gap on the second.

## Decision

**`FailSafeSettings.critical_modalities` — the deployment names the modalities
whose health may change the vehicle's posture.**

```python
critical = self._settings.critical_modalities
unhealthy = sum(
    1
    for modality, health in frame_health
    if health is not StreamHealth.HEALTHY and modality in critical
)
```

**A modality outside the set is still recorded** in every frame-health map and
every audit record. It simply stops being a reason to slow down or stop. *Not
counted* is not *not seen*: the health map is evidence, the counter is a
decision, and suppressing the first to change the second would hide a real
failure from a technician reading the log.

### Why it is configuration and not code

*"The IMU feeds the state estimate; the radar feeds nothing"* is **platform
knowledge**, and NFR5 keeps platform knowledge out of the layers. L8 counting is
architecturally correct — what was missing is that nothing *supplied* the
criticality. Same shape as `integrity_tolerated_faults`: **L8 counts, the
deployment declares.**

**No default** (A-4). Naming a modality non-critical asserts that nothing the
safety argument depends on reads it; get it wrong and the vehicle drives on a
dead sensor it needed. An **empty** set is refused by a validator, because it
would silently disable the counter entirely — a fail-open mode reachable by
deleting one line from a TOML file.

### Why the prototype does not use its own escape hatch

**Every shipped profile lists all five modalities**, which is exactly the
behaviour before this field existed, and all 2,953 tests pass unchanged.

It would be *true of this build* to declare only the IMU critical — the extractor
reads nothing else. But that is true **only because of OD-15**, five modalities
carrying one measurement, which is a defect to fix rather than a property to
write into a safety file. Encoding a known defect as a deliberate safety claim
would make the configuration a record of what is broken rather than of what is
intended.

The mechanism is proved by tests instead, which is where a capability nobody
should yet rely on belongs.

## Alternatives considered

### 1. Weight modalities rather than filter them

Rejected. A weighted counter needs a weight per modality *and* a re-derived set
of thresholds, and the extra expressiveness buys nothing: no deployment has been
able to say what "the camera is worth 0.4 of an IMU" would mean. A set is a claim
someone can check.

### 2. Derive criticality from what the extractor reads

Superficially attractive — the adapter *knows* which modalities it consumes, so
the system could infer the set. Rejected on two counts. It makes a **safety
declaration** an emergent property of an implementation detail, so a refactor of
the extractor silently changes what stops the vehicle. And it is wrong in the
direction that matters: a modality the *current* estimator ignores may still be
one the vehicle must not drive without.

### 3. Leave it, and accept nuisance stops

Rejected, and worth stating because it is the cheapest option. A fail-safe that
stops the vehicle for a non-contributing component teaches its operators that its
stops are noise — and an alarm people learn to ignore is worse than no alarm.

## Consequences

### Positive

- **The nuisance stop is gone where it is declared gone.** With only the IMU
  critical, a camera failure holds NOMINAL with the counter at 0; an IMU failure
  still HALTs.
- **Bit-identical by default.** All five declared, 2,953 tests unchanged.
- The claim is in a file a safety engineer signs, not in code review.

### Negative / accepted trade-offs

- **A wrong declaration is a serious wrong answer and nothing can check it.**
  Declare the IMU non-critical and the vehicle drives on a dead estimator
  in silence. The schema says so; nothing enforces it, because nothing in
  software knows what a vehicle's sensors are for.
- **It is per-modality, not per-quantity.** A modality that feeds one critical
  signal and three cosmetic ones must be declared critical whole.
- **Third change to one line in one day.** ADR-0024 introduced it, ADR-0027
  changed how many failures matter, and this changes which failures count. That
  is a lot of churn in an escalation policy, and the reason is worth naming: the
  first version was written when there was **one sensor**, and every assumption
  that quietly rested on that has had to be found and stated one at a time.

## Implementation

`FailSafeSettings.critical_modalities` and its non-empty validator
(`config/schema.py`); `_advanced_integrity` (`layers/l8_failsafe/machine.py`);
the three environment files, all listing five.

Tests: five in `tests/unit/test_sensor_integrity.py` — the defect, its control,
the compatibility claim, the *still recorded* property, and the empty-set
refusal.

**Verified:** ruff clean, `mypy --strict` over 161 files, 12 import contracts,
**2,953 tests + 5 strict xfail passing unchanged**.
