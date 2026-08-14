# ADR-0029: Capability withdrawal is a second axis, not a third counter

- **Status:** Accepted
- **Date:** 2026-08-15
- **Gap closed:** OD-19 in [`../CREDIBILITY_MATRIX.md`](../CREDIBILITY_MATRIX.md)
- **Evidence:** E-129 – E-133 in [`../EVIDENCE.md`](../EVIDENCE.md)
- **Fourth change to the same mechanism**, after [ADR-0024](0024-sensor-integrity-is-a-second-counter-not-a-fourth-gate.md), [ADR-0027](0027-the-integrity-counter-rises-on-a-lost-quorum.md) and [ADR-0028](0028-the-deployment-declares-which-sensors-are-critical.md) — and the first that does not touch the counter at all

## Context

ADR-0028 let a deployment name which modalities may move the posture. It closed
a real defect: a camera failure no longer has to stop the vehicle exactly as an
IMU failure does. But it left the system with exactly **two** responses to a
sensor failure, selected by one boolean:

| the sensor is… | what happens |
|---|---|
| **critical** | the whole ladder — DEGRADED → LIMP → HALT, identical for every critical sensor |
| **non-critical** | nothing at all |

`critical_modalities` is a *switch*, not a dial. It can say *"this sensor does
not matter."* It cannot say *"this sensor matters, but only this much"*, and it
cannot say the thing a vehicle engineer actually wants: **lose the camera, stop
offering lane changes, keep driving.**

Every effect the machine has — speed cap, lane-change permission, handover
request — reads `self._state`, and the state comes from one integer banded into
four levels. The most natural per-sensor response in the whole system was
therefore unrepresentable:

| lose | the sensible response | expressible before this record |
|---|---|---|
| camera | no automated lane changes, keep lane-keeping | **no** |
| GPS | no route following, keep local control | **no** |
| radar | reduce speed, increase following distance | **no** |
| IMU | stop and hand over | yes — the only one the ladder fits |

### The diagnosis

One integer was being asked two questions:

- *how bad is this getting?* — answered by a severity level, and **already correct**
- *what is broken?* — answered by a set of lost functions, and **missing**

The ladder was designed for the first and was being asked to carry the second.
No refinement of a single counter can hold both, which is why every option that
tried to is rejected below.

Found the same way OD-16, OD-17 and OD-18 were: by a question a customer would
ask — *"can the car take a response based on the sensor that degraded?"* — rather
than by a test. That is now four in a week, and none of the four by a test.

## Decision

The deployment declares what each autonomy function requires. A function is
**withdrawn** for as long as any modality it requires is worse than `HEALTHY`.

```toml
[failsafe.capabilities]
lane_change     = ["CAMERA", "RADAR"]
lane_keeping    = ["CAMERA"]
adaptive_cruise = ["RADAR", "IMU"]
route_following = ["GPS"]
```

The derivation is mechanical — no threshold, no counter, no policy:

```python
unhealthy = {m for m, h in frame_health if h is not StreamHealth.HEALTHY}
withdrawn = tuple(
    name for name, required in self._settings.capabilities if unhealthy.intersection(required)
)
```

The two axes compose by **intersection**: a function is offered where the
posture allows it *and* its sensors support it.

### Four properties that make it safe

**It can only subtract.** A capability set able to *grant* something the posture
forbids would be a fourth gate with veto-override authority, which SI-3 forbids.
Intersection makes that unrepresentable rather than merely untested.

**It ignores `critical_modalities` entirely, deliberately.** The critical set
decides whether a modality moves the *posture*; this decides which *functions* it
carries. Filtering here would re-couple the axes and reproduce OD-18 one level
down. A camera that is no reason to slow down is still the only thing a lane
change depends on.

**No counter and no hysteresis, unlike both existing counters.** A counter
exists to distinguish a glitch from a fault, because escalating the *posture* on
one bad frame would spend the vehicle's life in DEGRADED. Withdrawing a function
has no comparable cost — the vehicle keeps driving and declines one thing — so
paying a detection delay to avoid it is the wrong trade, and would mean granting
a lane change during the ticks the camera had already gone dark.

**`reset` does not clear it.** A reset clears what the *machine* decided; it
cannot clear what the *sensors* reported. The counters are accumulated state and
zeroing them is the machine forgetting its own history. The withdrawn set is a
pure function of the last frame, and emptying it would assert every sensor
healthy — which a reset has no way to know and no authority to say.

### It is published beside `lane_change_permitted`, not folded into it

L8 would have to know that the string `"lane_change"` names the capability
behind that field, and a layer that knows what a lane is has lost NFR5.
Composition belongs to the domain adapter that reads the names. `capabilities`
keys are **opaque to L8** throughout: the layer knows that capabilities exist
and get withdrawn, never what any of them means.

This also converges with **OD-11 wall 4**. `lane_change_permitted` is automotive
vocabulary sitting in a domain-independent contract *today*; under this design
it stops being a hardcoded field and becomes one capability among many. The two
merge when wall 4 is taken.

## Alternatives considered

**Per-modality severity ceiling** — *losing the camera may reach at most
DEGRADED.* One line, reuses the ladder, and wrong: a ceiling says *how far*,
never *what*. It makes camera loss cap the **speed**, when losing a camera has
nothing to do with speed, and two sensors sharing a ceiling behave identically
again — OD-18 reproduced one level down.

**Weighted counter** — each modality contributes a weight. Rejected in ADR-0028
and still rejected. Nobody can defend *"the camera is worth 0.4 of an IMU"* to an
assessor, and an unfalsifiable number in a safety argument is worse than a
missing one.

**One state machine per modality.** Fully expressive. But the vehicle has one
throttle, so five postures must be combined anyway — the combination rule *is*
the design question, and this option skips it while paying 5× the state. It also
muddies SI-7's sole actuation authority, which is the invariant with the least
slack in the architecture.

**Leave it, and document the limitation.** Defensible for a prototype, and it
was my first recommendation — on the grounds that four of five modalities feed
nothing (OD-15), so a dependency map would be fiction. That reasoning was wrong
and is worth recording as wrong: the map states **what the vehicle may do when a
sensor is unhealthy**, not what the estimator reads. Camera health is real today
— L1 computes it from freshness, per stream, whether or not anyone consumes the
payload, which is exactly how a dark camera drove the counter to HALT in E-126.
OD-15 blocks the *estimation* benefit; it does not touch the *capability*
benefit. Merging the two delayed a change that had no reason to wait.

## Consequences

### Positive

- The response is now per-sensor rather than per-severity. Measured on a profile
  that narrows the critical set: three of five modalities keep the vehicle
  **NOMINAL** and withdraw only what they carry (E-131).
- The degradation table is **derived from the running machine**
  (`benchmarks/degradation.py`), not maintained by hand beside it. A safety
  case's degradation concept and the system it describes cannot drift apart,
  because the document is a measurement of the system.
- A new commissioning check falls out free: a modality that is neither critical
  nor required by any capability is **inert** — losing it does nothing at all.
  That is the "we added a sensor and forgot to wire its failure response"
  integration bug, made visible (E-132).
- The driver-facing message becomes actionable: *"lane centering unavailable —
  camera fault"* instead of a vehicle that simply stops.
- Empty declaration reproduces the previous behaviour exactly, so the change is
  provably additive: all 2,958 pre-existing tests pass untouched.

### Negative / accepted trade-offs

- **Restoration is symmetric and probably should not be.** A modality flapping
  between healthy and stale flaps its capabilities with it. The fix is a restore
  debounce — withdraw at once, restore after N clean ticks, because the two
  errors do not cost the same — but N is an operating point and no flap rate has
  been measured on this platform. Inventing one would be the same unfalsifiable
  number that got weighted counters rejected above. The field is not added until
  a measurement asks for it.
- **Nothing enforces a withdrawal yet.** The set is derived, recorded and
  reported; it does not bind an actuator. Neither does `lane_change_permitted`,
  which is also record-only today, so nothing regressed — but a reader who
  assumed "withdrawn" meant "prevented" would be wrong. The binding seam is the
  `CommandProjector`, the same one ADR-0023 used to make the exploration speed
  cap real, and taking it is a separate decision.
- **The shipped profiles declare no non-critical modality**, so no shipped
  profile exercises the graceful path. The behaviour is proved by tests and by
  `benchmarks/degradation.py` against a narrowed profile, not by the default
  configuration. Same reasoning as ADR-0028: narrowing the critical set here
  would be true only because of OD-15.
- **An empty `withdrawn_capabilities` is ambiguous** — it means either that
  nothing was withdrawn or that the profile declared no capabilities. The
  contract says so and the run manifest records the profile, but a reader with
  only one row cannot tell.
- **The field defaults to empty, which A-4 would normally forbid.** Accepted,
  and the asymmetry is the argument: an empty `critical_modalities` disables a
  counter that already escalates, so it is a fail-open *claim* and is refused.
  An empty `capabilities` withdraws nothing, which is the absence of a claim and
  precisely the behaviour shipped before the field existed.
- **A fourth change to one mechanism in five days.** The counter was written when
  there was one sensor, and every assumption that quietly rested on that has had
  to be found and stated one at a time. This record does not touch the counter,
  which is some evidence the decomposition has finally reached the right shape —
  but that is a hope, not a measurement.
