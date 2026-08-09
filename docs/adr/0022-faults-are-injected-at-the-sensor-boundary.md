# ADR-0022 — Faults are injected at the sensor boundary, never inside the core

**Status:** Accepted, implemented
**Date:** 9 August 2026
**Unblocks:** P3.5 and P4.2 in [`../PENDING.md`](../PENDING.md), and section D of
[`../CREDIBILITY_MATRIX.md`](../CREDIBILITY_MATRIX.md)
**Reads with:** [ADR-0021](0021-ablation-neutralises-a-gate-it-never-removes-one.md),
which takes the opposite placement for the opposite reason.

## Context

Five open items were the same missing piece. The ablation study measures nothing
on nominal driving where nothing goes wrong; the comparison harness needs two
instances driven from the same seed against the same *injected fault*; P4.2 is
fault injection; section D of the matrix is empty because nothing in the
synthetic plant is out-of-distribution in the sense L6 is calibrated for; and
P2.1 left open that the fail-safe speed cap has only ever been observed under a
deliberate provocation.

Everything measured up to this point shows the machinery **runs**. None of it
shows what any gate **catches**, which is the product claim.

## Decision

**Faults are injected at the sensor boundary — `training/faults.py`, applied in
`training.closed_loop._publish_state` before a reading reaches the bus. Nothing
in `src/astra/` changes, and nothing in `src/astra/` knows the injector exists.**

Two reasons, and the second is the stronger one.

**It keeps the machinery out of the safety package.** A component whose purpose
is to make sensors lie, shipped inside a package a certification argument is
being built for, is a question with no good answer. The twelve import contracts
and `make verify-install` already enforce the boundary; this decision is to stay
on the right side of it rather than to add a new guard.

**It is the honest place.** From the pipeline's side a corrupted reading is
indistinguishable from a genuinely faulty sensor, because it *is* the same
event: L1 receives a payload, and nothing downstream can tell how it was
produced. A fault injected anywhere further in would be a simulation of a fault.
This is a fault.

The corollary is a real limitation and is stated rather than buried: **this
injects sensor faults only.** An actuator fault, a compute fault, or a
proposer that has been compromised are all outside what this reaches, and the
first two are outside what the reference plant can represent at all.

## Options considered

| | Benefit | Drawback | |
|---|---|---|---|
| **A.** A fault component inside `src/astra/` | Reaches any layer | Ships fault-injection machinery in the safety package. Breaks the import contracts or forces them to be widened | rejected |
| **B.** Corrupt the plant's state directly | Trivial | Injects a fault into the *world*, not into the *sensing of it*. The estimator would then be right and the vehicle wrong, which is a different experiment and not the one any open item asked for | rejected |
| **C.** Corrupt the payload at `_publish_state` | Indistinguishable from a real sensor fault; core untouched; the adapter seam is what it is for | Sensor faults only | **chosen** |

## What makes the injector trustworthy

An injector nobody has verified would produce a table of *"faults the gates did
not catch"* that was really a table of faults never injected — failing by making
the evidence look **better**, which is the shape of OD-2, OD-5 and E-28 and
which testing cannot see by construction. Three properties, each pinned by a
test rather than asserted in prose:

- **A `FaultSpec` cannot be configured inert.** A zero-magnitude bias, an empty
  window, a magnitude on a fault with no use for one — each raises at
  construction. An injector that does nothing is a rejected one, not a quiet one.
- **A `FaultEpisode` reports the peak error measured *while injecting*.** Intent
  and achievement are separate fields, so they can disagree, and
  `test_every_kind_reports_the_error_it_actually_injected` fails on an injector
  that has silently become a no-op.
- **The injector draws no randomness when nothing is active**, from a stream
  seeded disjointly from the harness's measurement noise. So `fault=None` and an
  injector whose window has not opened are the same run to the byte — which is
  what makes the fault the *only* difference between two arms of a comparison.
  Without it the two arms would differ in the fault and in every sensor reading
  after it, and no outcome could be attributed to either.

## Consequences

- `drive_closed_loop` gains one optional parameter. `TickSample` gains
  `fault_active`, the **ground-truth label** a detection rate is taken over:
  every veto rate measured before it had no denominator, because nothing
  recorded whether anything was actually wrong.
- The first fault this injector ran found a defect on its first run. See
  **OD-9** in [`../CREDIBILITY_MATRIX.md`](../CREDIBILITY_MATRIX.md) and
  E-44 – E-47 in [`../EVIDENCE.md`](../EVIDENCE.md): ten seconds of frozen IMU
  puts the vehicle 4.199 m off a 1.75 m lane with a verdict trace **identical**
  to the clean run's.
- P3.5's comparison harness now has its missing half and is the next item.
