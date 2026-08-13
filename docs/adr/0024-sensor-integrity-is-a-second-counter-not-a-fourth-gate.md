# ADR-0024: Sensor integrity is a second counter, not a fourth gate

- **Status:** Accepted
- **Date:** 2026-08-11
- **Defect closed:** OD-9 (partly — the dropout arm) in [`../CREDIBILITY_MATRIX.md`](../CREDIBILITY_MATRIX.md)
- **Evidence:** E-87 – E-91 in [`../EVIDENCE.md`](../EVIDENCE.md)
- **Implements** P2.7 option A. **Revisits** [ADR-0023](0023-the-ood-counter-freezes-during-bounded-exploration.md)'s accepted risk, as that record required.

## Context

OD-9 is the worst defect this project has found, and it was found by the first
fault the injector ever ran.

Every Core-B gate reads L2's fast estimate. The proposer closes its loop on that
same estimate. So a corrupted sensor reading is not merely *undetected* — it is
**actively driven toward the value the gates consider safe**. Measured over
400 ticks with a 200-tick IMU dropout, against a bit-identical control:

| | control | dropout |
|---|--:|--:|
| final \|deviation\| | 0.009 m | **4.199 m** |
| ticks outside the ±1.75 m corridor | 0 | **73** |
| corridor bound's own reading at the worst point | — | **0.023 m** |
| vetoes, and their reason codes | 3, jerk | **3, jerk — identical** |
| fail-safe posture | NOMINAL | **NOMINAL, all 400 ticks** |

`shield.py` predicted it in its own docstring — *"this bound is only as good as
the position estimate, and that is not a quibble"* — where it was written as a
caveat. It is now a measurement.

### The sentence that decides the design

**A veto could not have fixed this.** L9's fallback controller reads the same
corrupted estimate, so refusing the proposal substitutes one command computed
from a lie for another. Adding a fourth gate, tightening a bound, or lowering a
threshold are all the same move and all of them fail for the same reason:

> **You cannot veto your way out of a lying sensor.**

Everything downstream of L2 is compromised together. A remedy has to read
something that is not.

### What P2.7 measured before anything was built

The standing convention — *no mechanism gets authority until it has run with
none* — put three candidates through the shadow harness first. Latency from the
fault opening; **zero false alarms on the control for all three** (E-51):

| scenario | departure | health (A) | innovation (B) | trust |
|---|--:|---|---|---|
| `imu_dropout` | 4.199 m | **+5 ticks** | silent | +5 ticks |
| `position_drift` | 2.025 m | silent | silent | silent |
| `position_bias` | 0.931 m | silent | silent | silent |
| `lateral_noise` | 0.140 m | silent | +84 ticks | +10 ticks |
| `speed_stuck` / `speed_bias` | — | silent | silent | silent |

**Option A fires at +5 against a departure that begins at +73** — 3.4 seconds of
margin, from a signal L1 already computes, already records, and no gate reads.

**Option B, the principled candidate, is refuted by measurement.** The innovation
sequence is the one recorded quantity that can *disagree* with the estimate, and
it is silent on the slow drift: ramping 2 m over 200 ticks is 1 cm per tick
against a declared sigma of 0.1 m, so every step sits inside what the filter
expects. It is silent on exactly the fault it was most wanted for (E-53).

## Decision

**L8 gains a second counter, driven by `StreamHealth`, driving the same four
states. It is not a gate and it changes no verdict.**

```python
def observe(self, *, tick, verdict, frame_health=(), exploring=False) -> FailSafeSnapshot:
    self._counter = self._advanced_counter(blocking=verdict.is_blocking, exploring=exploring)
    self._integrity = self._advanced_integrity(frame_health=frame_health)
    self._state = self._next_state()
```

Four parts, and each is a separate decision:

1. **The input is `StreamHealth`**, which L1 computes at the sensor boundary
   from *staleness*, before the filter touches anything. It is the only input
   this machine has that sits upstream of OD-9's common cause. Everything else
   on the record — the estimate, the innovation, the Trust Index, every gate
   verdict — is downstream of L2 and therefore compromised by the same fault.

2. **It is a counter, not a gate.** The four-state machine already owns the job
   of converting *sustained* evidence into a graduated posture, and the
   graduated posture is the correct response here: a speed cap, then a lower
   one, then a controlled stop with `human_intervention_requested`. Making it a
   fourth gate would have meant `CORE_B_GATE_COUNT` rising from 3, the
   nine-layer count being argued about, and a veto that — see above — does not
   help.

3. **Two counters, reported separately.** `FailSafeSnapshot` carries both. *"The
   gates refused forty commands"* and *"a sensor was dark for forty ticks"* need
   different responses from whoever reads the log, and one integer cannot say
   which happened. Audit schema **5 → 6**.

4. **The state is the worse of the two.** Neither counter can be overruled by
   the other's good news. A clean verdict stream says nothing about whether the
   sensors are honest; a healthy frame says nothing about whether the commands
   are admissible. Taking a sum or an average would make a moderate amount of
   each look like a lot of one.

### Its own thresholds, and why they are tighter

`integrity_threshold_degraded / limp / halt` — 5 / 15 / 40 at the simulation
profile, i.e. 0.25 s, 0.75 s and 2.0 s at 20 Hz, against the OOD counter's
10 / 30 / 100.

The two triples answer different questions and the answers have different
floors. `ood_threshold_*` is bounded from *below* by a legitimate recovery — a
vehicle 1 m off centre needs ~21 vetoed ticks to correct, so a threshold under
that turns a correction into a pull-over, which is how `ood_threshold_halt = 20`
once meant *"declare a terminal pull-over after one second"*. **There is no
legitimate reason for a modality to stop publishing**, so the integrity triple
has no such floor and is bounded from the other side instead: by the hazard.
The measured departure takes 73 ticks, so every threshold must land inside it.
φ₃ = 40 leaves 33 ticks — 1.65 s — between a commanded stop and the corridor.

They are **absent from `certification.toml`** for the same reason the OOD
thresholds are (A-4). The right value depends on how fast a particular vehicle
departs when a particular channel dies, which is the integrator's measurement to
make, not this repository's to assume.

### It does not freeze during exploration, and that is the point

ADR-0023 froze the OOD counter while L9 owns the out-of-envelope condition, and
recorded as an accepted risk:

> *A sustained fault that arises during exploration will not escalate the
> posture … Whoever closes OD-9 must revisit this record.*

This is that revisit, and **the risk is materially reduced rather than merely
noted.** The integrity counter does not freeze. L9 narrowing its envelope is a
response to *the world being unfamiliar*; it says nothing whatever about whether
the sensors are still telling the truth. A vehicle exploring a tunnel with a
dead IMU is in more trouble than one doing either alone, not less.

What remains accepted from ADR-0023 is narrower and can now be stated precisely:
during exploration, a fault that the *gates* can see still does not escalate the
posture. A fault that kills a channel now does.

## Alternatives considered

### 1. A fourth Core-B gate that vetoes on stream health

Rejected on the mechanism, not on the cost. The fallback controller reads the
same corrupted estimate, so a veto exchanges one command computed from a lie for
another; measured, the vehicle would still have left the corridor. It also
raises `CORE_B_GATE_COUNT` — a constant three architecture tests assert — and
puts a fourth box into every diagram of a three-gate architecture, for a
mechanism that is not doing a gate's job.

### 2. Feed stream health into the existing OOD counter

The cheapest option, and rejected for three reasons. It conflates two conditions
in one integer, so an auditor reading `counter = 40` cannot tell which happened.
It inherits the OOD counter's thresholds, which are too slow — HALT at 100
against a departure at 73. And **it would freeze during exploration**, which is
precisely the risk ADR-0023 named and this record exists to reduce.

### 3. Gate on the innovation sequence (P2.7 option B)

The principled candidate, and **refuted by its own measurement** rather than by
argument. Silent on the slow drift, which is the fault it was most wanted for.
Recorded here rather than merely dropped, because it is the answer a reviewer
will propose and the refutation is more interesting than the choice.

### 4. Gate on estimate uncertainty, `trace(P_f)` (P2.7 option C)

Rejected before it was built, and written down so nobody tries it twice: a
frozen or biased reading is maximally *self-consistent*, so the filter grows
**more** confident, not less. `P_f` shrinks under exactly the faults that matter.

### 5. Reduce the Trust Index instead

L3 already responds — trust fired at +5 on the dropout, the same latency as
health (E-51) — and it changed nothing, because nothing acts on trust alone.
Wiring it further has a worse problem: the Trust Index is a *conformal* quantity
calibrated against a corpus, and injecting a health term into it would make it no
longer that, invalidating E-12's coverage arithmetic. Trust feeds L6, which reads
the estimate; the remedy would re-enter through the compromised channel.

### 6. Escalate only on a modality that has published at least once

Considered because of what this change broke: an integration rig that published
the IMU alone went DEGRADED, since the other four modalities read `ABSENT`.
Rejected — it silently tolerates a sensor that is **dead at boot**, which is the
worst of the three failures to tolerate. The rig was fixed instead, to publish
every modality as `training/closed_loop.py` and a real vehicle do, and the old
behaviour is pinned by
`test_a_vehicle_publishing_one_modality_does_not_stay_nominal`.

### 7. Sensor redundancy and a cross-check (P2.7 option D)

**Not rejected — deferred, and it is the only general answer.** It is what a real
vehicle does and the only candidate that addresses `BIAS`, `DRIFT` and
`STUCK_AT`. It cannot be measured here: the reference plant publishes one ground
truth to all five modalities, so it is structurally incapable of expressing
redundancy. Recorded as an integrator precondition and as Phase 7 work.

## Consequences

### Positive

- **Measured: the IMU dropout's final deviation falls from 4.199 m to 0.167 m**,
  inside the lane it used to leave by two and a half lane widths (E-88).
- **The response beats the hazard, and the margin is a number.** DEGRADED at
  +5 ticks, LIMP at +15, HALT at +40, against a departure that begins at +73 —
  1.65 s of margin at 20 Hz (E-87).
- **Zero false alarms.** The control run holds the integrity counter at 0 across
  all 400 ticks and never leaves NOMINAL (E-89).
- **Nothing else moved.** The other five fault scenarios, the ablation study and
  the platform-transfer study all reproduce their previous figures exactly. The
  mechanism is additive, not a re-tune (E-90).
- **It is invisible to ablation**, which is a structural-independence argument
  rather than an argued one: disarming any of the three gates leaves the
  dropout's 0.167 m unchanged, because the response does not come from a gate.
- **ADR-0023's accepted risk shrinks**, as that record required.
- The end-user behaviour is a sentence a manufacturer can act on: *a channel goes
  quiet, and within a quarter of a second the vehicle is slowing; within two
  seconds it is stopping and asking for a human.* The signal costs no new
  hardware — it was already being computed and thrown away.

### Negative / accepted trade-offs

- **This closes one third of OD-9 and the row stays open.** `StreamHealth` is
  computed from *staleness*, so a modality publishing a **fresh, well-formed,
  wrong** value stays `HEALTHY` for ever. `BIAS`, `DRIFT` and `STUCK_AT` are
  exactly that, and are exactly why those faults were chosen. The slow drift
  still ends **2.025 m** out with the integrity counter at **0**, and
  `test_a_fresh_well_formed_wrong_reading_is_invisible_to_this_counter` asserts
  that silence so that nobody can describe this mechanism as *"detects sensor
  faults"* without a test turning red.
- **Core-B is still blind.** No gate sees the fault; the verdict trace under the
  dropout is still identical to the control's, and D-3 is no less contradicted
  than it was. The response now comes from outside the three-gate argument
  rather than from within it, and a safety case must say so in those words.
- **Any modality, not a quorum.** One unhealthy channel is enough, because in
  this build the modalities are not redundant. On a platform whose sensor set
  differs from `SensorModality`, this over-fires; that platform needs a declared
  *required* set, which is deployment configuration this repository does not yet
  have and is named in the integration assessment.
- **A new way to induce a stop.** An adversary who can silence one channel can
  now drive the vehicle to a controlled halt in two seconds. That is a
  denial-of-service trade against a loss-of-lane-position hazard, and it is the
  right trade — but it is a trade, and `THREAT_MODEL.md` §5.1 gains it rather
  than losing the entry it already has.
- **Two counters is more machinery than one**, and `_next_state` now resolves
  two bands and takes the worse. The alternative was one integer answering two
  questions, which is how an evidence log becomes ambiguous.
- **Audit schema 5 → 6, and this boundary is asymmetric.** A version-5 reader
  loses attribution. More importantly, every pre-version-6 record was written by
  a machine that *could not* escalate on sensor health, so a v5 archive showing
  NOMINAL through a sensor fault is correct about the machine that produced it
  and must not be compared with a v6 archive as the same system. That archive is
  the OD-9 evidence.

## Implementation

`FailSafeSettings.integrity_threshold_*` and its ordering validator
(`config/schema.py`); the three environment files; `FailSafeSnapshot.integrity_counter`
(`contracts/assurance.py`); `AUDIT_SCHEMA_VERSION` 5 → 6 (`kernel/constants.py`);
`FailSafeStateMachine.observe` / `_advanced_integrity` / `_next_state` /
`_escalated_state` / `_de_escalated_state` / `reset` and the module-level
`_band` and `_worse` (`layers/l8_failsafe/machine.py`); the `observe` call site
(`runtime/pipeline.py`); the escalation table in `benchmarks/fault_study.py`.

Tests: `tests/unit/test_sensor_integrity.py`, 18 of them — six for the defect,
five for the control, three for counter independence, two for the exploration
asymmetry including its control, and two that pin what this **cannot** see.
`tests/integration/test_closed_loop_faults.py` gained
`test_the_posture_escalates_on_sensor_health_rather_than_on_a_verdict` and had
two tests rewritten, one of which had said in its own comment: *"pinned so that
a future change which fixes it fails here and has to say so."* It fired.

**Verified:** ruff clean, `mypy --strict` clean over 156 files, 12 import
contracts kept, **2,881 tests + 5 strict xfail**. The fault study, the ablation
study and the platform-transfer study all re-run from a clean checkout.
