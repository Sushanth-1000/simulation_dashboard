# ADR-0017: A jerk veto yields the largest admissible step, not zero steering

- **Status:** Accepted
- **Date:** 2026-08-02
- **Phase:** Validation (post-Phase 4)
- **Finding:** F1a in [`../SOAK_REPORT.md`](../SOAK_REPORT.md); item P0.2 in [`../PENDING.md`](../PENDING.md)
- **Reads with:** [ADR-0016](0016-exploration-may-not-override-a-deterministic-veto.md), which closed the accidental escape this record replaces with a designed one.

## Context

The fallback controller commands zero on every channel but its own, by explicit
design and for a good reason: *"a vetoed tick is not evidence that the previous
steering command was good, and continuing to turn on the strength of a command
nobody validated is how a fallback becomes the fault."*

Under a sustained veto that produces a deadlock:

1. The fallback governs, so the vehicle's lateral acceleration is pinned at zero.
2. L7b's bound is `|a_proposed − a_current| / dt ≤ 8.0 m/s³`, and `a_current` is
   read from the state estimate — which now reflects the *fallback's* behaviour.
   At `dt = 0.05 s` the largest admissible lateral acceleration **from rest is
   0.4 m/s²**.
3. The vehicle is by now far off-lane, so every useful correction exceeds it.
4. Vetoed. The fallback governs again, re-establishing (1).

**The escape is closed by construction:** leaving requires ramping in ≤0.4 m/s²
steps, but a proposal only moves `a_current` if it is *executed*, and it is not
executed while vetoed. No proposer can climb a ramp it is never allowed to stand
on. Measured across three policies — one that stopped the vehicle, one that held
13 m/s and 0.03 m of lane error, and one trained with an explicit jerk penalty —
all reached the same terminal state: 100% veto, FSM in HALT, unbounded departure.

**The gate is not wrong.** With `a_current = 0` and a proposal demanding
2 m/s², the tyres genuinely cannot make that transition in one tick. What was
wrong was the substitute: of every command available, zero steering is the one
that most guarantees the *next* proposal is equally inadmissible. The fallback
was never required to make progress toward anything.

## Decision

**When the physical gate refuses a proposal solely because the demanded change in
lateral acceleration was too fast, L9 issues the largest step that bound permits,
in the direction asked for.**

`a_issued = a_current ± min(jerk_max · dt, |a_proposed − a_current|)`, projected
back onto the steering channel. This is a rate limiter — what every physical
actuator already is, and the standard engineering answer to "that transition is
too fast".

**The veto is not overridden.** The proposal is not issued; a different command
is, derived from the bound that refused it and therefore admissible under it by
construction. ADR-0016 stands untouched.

Three constraints make it safe, and all three are load-bearing:

- **Only rate reasons ratchet.** The reason codes eligible are supplied by the
  composition root (`frozenset({REASON_LATERAL_JERK})`), not imported by the
  arbitrator. A divergence veto or any deterministic bound is a statement about
  the *destination*; arriving there in small steps would defeat the gate while
  looking like compliance.
- **Any other blocking gate cancels it.** If anything besides a rate reason
  objects on the same tick, the fallback governs.
- **It fails to the fallback, never to a guess.** No projector, no eligible
  reason, missing evidence, non-finite values — every one yields the fallback,
  which is the answer that needs no argument.

### The seam

L9 needs one piece of platform knowledge: how much lateral acceleration a unit of
steering produces. That is `CommandProjector` in `astra.ports.pipeline`, supplied
by the adapter exactly as the actuation space is, so NFR5 survives.

It has **one method**, the inverse direction only. The forward projection already
exists in L7b, which computes the proposal's implied lateral acceleration to
evaluate its own bound and publishes it, the current value, the demanded jerk and
the limit as verdict evidence. L9 reads those four numbers rather than
recomputing them, so one projection exists in the system instead of two that
could disagree — and two that disagreed would mean the arbitrator was stepping
toward a target the gate would not recognise.

That makes the evidence keys an interface of bare strings between two layers.
Rename one and nothing raises: rate limiting silently stops, the latch returns,
and every unit test on both sides still passes because each builds its own
fixtures. `test_the_evidence_carries_every_key_rate_limiting_reads` is the only
thing that would notice, and it exists for that reason.

## Alternatives considered

### 1. Give the fallback lateral authority

**Blocked, not rejected.** A lateral controller must know where the lane is, and
`position_y` is never measured — the extractor publishes speed and lateral
acceleration only, so it is dead-reckoned from an unobserved heading and reached
2.9 × 10⁶ m of error over 100,000 ticks (finding F4). Heading is unobserved too.
There is currently nothing trustworthy for a lateral fallback to steer on; it
would steer on fiction, confidently. Revisit after P2.4.

### 2. Compare the proposal against the proposer's previous proposal

Rejected. L7b's bound means something physical — *"tyres and suspension transfer
force through deflection, which takes time"* — and that is a claim about the
transition from the vehicle's **actual** state. Comparing proposal-to-proposal
turns a deliverability check into a proposer-smoothness check and admits commands
the vehicle cannot execute.

### 3. A ratcheted exception that issues the vetoed proposal itself

Rejected, and precluded by ADR-0016, which was accepted specifically to establish
that no path overrides a veto. Note the difference from this record: ADR-0017
issues a *different, admissible* command. ADR-0016's rejected option issued the
refused one.

### 4. Tune the proposer instead

Measured and rejected. An explicit jerk term in the training objective collapses
training at weight 1.0 (return 63, collision rate 1.0) and makes the closed loop
*worse* at 0.1 (97% veto against 36% without). The existing action-rate proxy is
inert at the bound: 2×10⁻⁴ of reward against a centring reward of 1.0. The latch
is not a property of the proposer.

## Consequences

### Positive

- The deadlock has a designed exit. `a_current` advances by up to 0.4 m/s² per
  tick toward the request, so a correction inadmissible now becomes admissible
  after a few ticks, with no gate overridden on any of them.
- Every issued rate-limited command is admissible under the bound that produced
  it — not by assertion but by construction.
- The `CommandProjector` seam now exists, and is the same seam P2.1 needs for
  fail-safe speed-cap enforcement and the L7a scope question. One seam, three
  open items.
- It degrades to the previous behaviour exactly when it cannot be sure.

### Negative / accepted trade-offs

- **A broken or hostile proposer now gets what it asked for, just slower.** Under
  zero-steer it got nothing. What bounds it is L7a, which monitors the achieved
  state against friction and lateral-acceleration limits — so the ratchet
  controls *how fast* and L7a controls *how far*. That is a real weakening and it
  belongs in the safety case as an argued position.
- **The evidence record became a cross-layer interface.** It was previously
  write-only — emitted for humans and archives. One test guards it.
- **`CommandOrigin` gained a value**, within the audit schema version this change
  set already moved to 2.
- **It does not, on its own, stop the vehicle leaving the lane.** See below.

### What it did not fix, measured

A 20,000-tick soak with the limiter live: `RATE_LIMITED` on 347 ticks,
`PROPOSED` on 647, `FALLBACK_PID` on 19,006, and the departure unchanged.

The mechanism works — the unit tests demonstrate convergence, and those 347
firings are it working in the loop. It does not resolve the departure because
**a second latch exists, and this record does not address it**: from tick ~2,000
onward L6 and L7b veto on *every* tick simultaneously (2,000 and 2,000 in a
2,000-tick window), and any non-rate objection correctly cancels the ratchet.

Two things about that are worth recording rather than working around.

First, once the vehicle is outside the region the corpus covers, **L6 vetoes
every correction that would bring it back** — the same shape of latch, at a
different gate, and no bounded approach answers a statistical objection.

Second, the two gates are not firing independently. L6's score is
`dist(proposed, twin_predicted) / sigma`; L7b's divergence term is
`|implied − twin_implied|`. **Both are measuring proposal-against-twin.** They
co-fire because they share an input, which is the documented common-cause
weakness showing up in a measurement rather than in a caveat — and it bears
directly on the "three structurally independent gates" claim.

Widening the eligible reason set to ratchet through a statistical veto would make
the number better and would be ADR-0016 undone by the back door. It needs its own
decision.
