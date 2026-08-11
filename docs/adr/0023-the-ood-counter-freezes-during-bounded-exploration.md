# ADR-0023: The OOD counter freezes during bounded exploration, and the envelope's speed cap goes through the projector

- **Status:** Accepted
- **Date:** 2026-08-11
- **Defects closed:** OD-12, OD-13 in [`../CREDIBILITY_MATRIX.md`](../CREDIBILITY_MATRIX.md)
- **Evidence:** E-83 – E-86 in [`../EVIDENCE.md`](../EVIDENCE.md)
- **Extends** [ADR-0016](0016-exploration-may-not-override-a-deterministic-veto.md). **Supersedes nothing.**

## Context

The architecture's distinguishing sentence, from `exploration.py`'s own
docstring, is that outside its certified envelope it does not stop:

> *Those degrade to a halt when they leave their certified envelope. ASTRA is
> built not to: with no admissible profile, RCM engages bounded safe exploration
> … and the vehicle continues.*

Two promises in one sentence — **it continues**, and it continues **inside a
bound**. Neither held. They were found by the cheapest test available: change the
**plant** and leave everything else alone. The twin, the calibration corpus and
the policy are all fitted to `EnvironmentSpec()`'s defaults, so a vehicle with
weaker brakes or less steering bite is, to this pipeline, a platform nothing was
certified for — which is precisely the condition exploration exists to handle.

Measured over 600 ticks at seed 20260810
(`uv run python -m benchmarks.platform_transfer`), with the three source files
at their pre-fix revision:

| platform | exploring | vetoed | max m/s | final m/s | fail-safe |
|---|--:|--:|--:|--:|---|
| calibrated | 80 | 2 | 14.27 | 12.53 | NOMINAL |
| **weak acceleration** | 520 | 352 | 14.22 | **0.00** | **HALT at t398** |
| **weak brakes** | 580 | 315 | **23.43** | **0.00** | **HALT at t404** |
| worn tyres | 80 | 3 | 14.27 | 12.49 | NOMINAL |
| sharp steer | 80 | 3 | 14.27 | 12.45 | NOMINAL |

### OD-12 — it did not continue

On a platform the twin was never fitted to the twin mispredicts, so L6 (which
scores proposal against twin) and L7b (which checks the same prediction against
physics) veto. L9 finds no certified profile matching the resulting context and
declares `SAFE_EXPLORATION`. **L8 counts those same vetoes**, escalates
NOMINAL → DEGRADED → LIMP → HALT, and HALT is terminal.

Two layers answering *"are we outside our envelope?"* and acting in
contradiction. The vetoes L8 counted were **the definition of the condition L9
had already detected, declared, and responded to** — one event escalated twice,
and the terminal answer won. The vehicle was stopped by the fail-safe machine
underneath an arbitrator still reporting, on the same tick, that it was safely
exploring.

This is the same shape as ADR-0016 and it is worth naming: **one condition with
two owners.** There, L6's veto and L9's envelope both answered "no profile covers
this context", and the conflict was resolved by L9 ignoring L6. Here the same
condition is owned by L9 and L8, and the conflict was resolved by L8 winning
silently. ADR-0016 fixed the ordering; it did not look one layer further.

### OD-13 — it was not bounded

Fixing OD-12 alone would have been worse than leaving it. The second defect is
visible in the control arm above: **the weak-braking platform reached 23.43 m/s**
— against the calibrated platform's 14.27 — before it halted, with **zero ticks
marked `SPEED_CAPPED`**. Freezing the counter would have removed the only thing
stopping it.

`exploration_envelope` computes `speed_cap = nearest_certified_max * 0.5` and
`restricted_space` turns the envelope into **narrowed channel bounds**. Channel
bounds limit how much throttle may be commanded on one tick. They bound the
resulting *speed* not at all: given enough ticks at reduced throttle, a vehicle
accelerates to whatever its drag allows. The envelope computed a number and
enforced it against nothing.

The seam that fixes it already existed. P2.1 built exactly this for the fail-safe
cap — L9 holds a projector, and a cap that alters a command is stamped
`CommandOrigin.SPEED_CAPPED` so an auditor can tell a cap that bound from a cap
that was merely computed.

## Decision

**Two changes, and neither works without the other.**

### 1 · `FailSafeStateMachine.observe` takes `exploring`, and freezes the counter

```python
def observe(self, *, tick, verdict, exploring: bool = False) -> FailSafeSnapshot: ...


def _advanced_counter(self, *, blocking: bool, exploring: bool = False) -> int:
    if exploring:
        return self._counter
    ...
```

`RuntimeGovernancePipeline` supplies it from the arbitration outcome it already
holds — `outcome is ArbitrationOutcome.SAFE_EXPLORATION` — so L8 acquires no
knowledge of L9 and no import runs upward. The pipeline is the composition root;
it is the only place that legitimately sees both.

### 2 · `engage_exploration` carries the cap, and the cap goes through the projector

```python
def engage_exploration(self, restricted_space, *, speed_cap: float | None = None) -> None:
```

`_speed_capped` now takes the **minimum** of the fail-safe cap and the
exploration cap, and applies it through the same projector as before. Exiting
exploration clears it. The command is stamped `SPEED_CAPPED` exactly as a
fail-safe cap is, so the two are indistinguishable to an auditor *in mechanism*
and distinguishable *in cause* by the arbitration outcome on the same record.

### Why it conditions on posture, not on which gate vetoed

The obvious alternative is to have L8 ignore vetoes from L6 and L7b while
exploring, since those are the gates the platform mismatch fires. `machine.py`'s
own docstring forbids it, and the reasoning is SI-3's:

> *which gate vetoed is evidence for the log, not an input to the escalation
> policy … which SI-3 forbids.*

An escalation policy that weights gates differently is an escalation policy that
can be tuned to ignore the gate that keeps firing. Conditioning on **posture** —
a single boolean the arbitrator already publishes on every record — keeps every
gate's contribution identical and puts the exception somewhere an auditor can
see it on the tick it applied.

### Why SI-3 is untouched

This is the part to read carefully, because the change *looks* like it weakens a
gate and does not.

SI-3 governs **verdict aggregation**: a blocking verdict from any gate blocks. It
is about whether a command reaches an actuator. What freezes here is the
**escalation counter** — a second, slower mechanism that converts a *sustained*
pattern of vetoes into a change of operating posture.

Concretely, during exploration:

- Every gate still runs, still scores, still returns its own verdict.
- `Verdict.merge` still applies the fail-closed rule, unchanged.
- A blocking verdict still stops the proposed command reaching an actuator; L9
  still falls back rather than issuing it (ADR-0016).
- Every veto is still written to the audit record with its reason code.

What does *not* happen is that a veto during exploration advances a counter
toward a terminal state. `test_exploration_does_not_alter_the_verdict_itself`
pins this: the verdict object is blocking before `observe` and blocking after.

The honest statement of the trade-off is this: **the fail-safe machine's
authority to escalate is suspended for as long as another layer has taken
ownership of the same condition.** That is an argued position and it belongs in a
safety case as one, not as a footnote. See the accepted risk below.

### Why frozen and not reset

A vehicle that was already DEGRADED must not emerge from a tunnel pretending it
was not. Freezing preserves whatever posture was reached before exploration
began; resetting would launder it. The freeze is symmetric — a clean tick does
not decay the counter either — for the same reason: a decaying counter lets a
vehicle launder a bad posture by entering a tunnel, which is resetting, more
slowly. Both directions are pinned by tests.

## Alternatives considered

### 1. Exempt L6 and L7b vetoes from the counter

Rejected. Directly forbidden by SI-3 as `machine.py` states it, and it puts a
per-gate weighting into an escalation policy — the thing that, once present, is
tuned rather than reasoned about.

### 2. Raise `ood_threshold_halt` when exploring

Rejected. It converts a structural contradiction into a tuning parameter, and the
parameter has no defensible value: it must be larger than the longest tunnel,
which is not a quantity anyone knows.

### 3. Make HALT recoverable

Rejected, and it is worth saying why, because it is the tempting one. HALT being
terminal is not an accident — it is what makes "the vehicle has stopped and a
human is needed" a statement with content. A recoverable HALT is a LIMP with a
frightening name. The right fix is to not reach HALT for a condition another
layer already owns, which is this record.

### 4. Enforce the speed cap in the shield rather than the projector

Rejected. L7a is a **veto** gate; expressing the exploration cap there would make
the envelope produce vetoes instead of commands, so every tick above the cap
would fall back rather than be clamped — replacing an unbounded vehicle with a
stopped one, which is OD-12 by another route. The projector *alters* a command;
that is what the envelope means.

### 5. Fix only OD-12, file OD-13, ship

Rejected on the measurement. The control arm shows 23.43 m/s reached *before* the
halt; removing the halt removes the only thing that stopped it. Shipping the
counter freeze alone would have converted "stops unnecessarily" into "accelerates
without bound", which is strictly worse and would have been reported as a fix.

## Consequences

### Positive

- **Measured: every platform now finishes NOMINAL and moving.** Weak
  acceleration 520 exploring ticks, 306 vetoes, final 4.36 m/s. Weak brakes 600
  exploring ticks, final 16.58 m/s, `|dev|` 0.237 m (E-83).
- **The cap binds, and the record says so.** The weak-braking platform is held at
  **16.72 m/s across 105 `SPEED_CAPPED` ticks** — half the highway profile's
  33.34 maximum, plus one tick of plant integration. Before the fix: 23.43 m/s
  and zero capped ticks (E-84).
- **The distinguishing sentence is now true on a measurement rather than in a
  docstring.** Until 11 August, on every platform where bounded safe exploration
  actually engaged for a sustained period, the system halted — the behaviour the
  architecture exists to differ from.
- `benchmarks/platform_transfer.py` exits non-zero if any platform HALTs or
  stops, so the regression is a build failure rather than a re-reading.

### Negative / accepted trade-offs

- **A sustained fault that arises *during* exploration will not escalate the
  posture.** This is the real cost and it is not small. If a sensor fails while
  the vehicle is in a tunnel, the vetoes it produces do not move the counter, and
  the vehicle continues under the exploration envelope rather than pulling over.
  It is mitigated by the envelope itself — half speed, a ±15° cone, no lane
  changes — and it is **not** mitigated by anything that detects the fault, which
  is OD-9's territory. The two defects compose: OD-9 says a sensor fault does not
  produce vetoes anyway, so today the exposure is smaller than the argument
  suggests and it will grow when OD-9 is closed. **Whoever closes OD-9 must
  revisit this record.**
- **`FailSafeSnapshot` now depends on a state the fail-safe machine cannot
  observe for itself.** `exploring` is supplied by the caller and the machine
  takes it on trust. A pipeline that passed `exploring=True` unconditionally
  would disable escalation entirely and no test in `test_l8_failsafe.py` would
  notice — the control test in `test_exploration_bounds.py` is what covers it, and
  it is there for exactly that reason.
- **The parameter defaults to `False`.** That is deliberate — every existing
  caller keeps its behaviour — but a default is a place a caller can forget. The
  pipeline is the only production caller and it always passes explicitly.
- **The exploration cap and the fail-safe cap are indistinguishable in
  `CommandOrigin`.** Both render `SPEED_CAPPED`. Adding a third origin was
  considered and rejected: the cause is already on the same record in
  `arbitration.outcome`, and an enum that grows a member per cause stops being a
  classification.

## Implementation

`FailSafeStateMachine.observe` / `_advanced_counter`
(`layers/l8_failsafe/machine.py`); `RuntimeGovernancePipeline._is_exploring` and
the `_follow` call site (`runtime/pipeline.py`);
`RuntimeCalibrationManager.engage_exploration` / `exit_exploration` /
`_speed_capped` and the `_exploration_speed_cap` slot (`layers/l9_rcm/arbiter.py`).

Tests: `tests/unit/test_exploration_bounds.py`, ten of them — six for the counter
freeze including the control arm that fails if escalation is disabled outright,
and four for the cap.

**Verified:** ruff clean, `mypy --strict` clean over 154 files, and the platform
study reproduces from a clean checkout with one command.
