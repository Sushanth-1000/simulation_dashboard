# ADR-0016: A gate that cannot judge abstains; no path overrides a veto

- **Status:** Accepted
- **Date:** 2026-08-02
- **Phase:** Validation (post-Phase 4)
- **Finding:** F6b in [`../SOAK_REPORT.md`](../SOAK_REPORT.md); item P0.1 in [`../PENDING.md`](../PENDING.md)
- **Supersedes nothing.** Extends SI-3 and reworks SI-4's wording.

## Context

`RuntimeCalibrationManager.issue` tested the bounded-safe-exploration envelope
*before* it tested Core-B's verdict, so in exploration the proposal was issued —
clamped to the narrowed space — regardless of what the gates decided.

Measured over two 100,000-tick soak runs with the cold path engaged:

| | |
|---|---|
| Arbitration outcome | `SAFE_EXPLORATION`, 100,000 of 100,000 |
| Commands issued as `EXPLORATION_BOUNDED` | 99,999 of 100,000 |
| **Issued while the aggregate verdict was blocking** | **99,808 — 99.8% of the run** |

Not an edge case. In the configuration this repository ships, it was what the
system did almost all of the time — because at the shipped operating point no
calibration profile is reachable for most of a drive, so exploration is engaged
almost always.

Three statements in the source contradicted that behaviour: `exploration.py`'s
*"The answer here is not to relax the gates. It is to shrink the envelope"*;
`GateId.DETERMINISTIC`'s *"Unconditional veto authority"*; and the README's
*"Every proposed command is validated three ways."*

**SI-3 was not literally violated** — it governs verdict *aggregation*, and the
aggregate remained a VETO. It was *issuance* that ignored the result. The
invariant was silent on issuance because, until bounded safe exploration existed,
no path issued a command the verdict had refused.

### Why the obvious fix was not enough

Simply reordering the two branches makes a veto binding again — and kills bounded
safe exploration. In a context no profile covers, L6 holds no finite conformal
threshold, so it vetoes `CONTEXT_NOT_CALIBRATED` on every tick; every tick then
falls to the fallback, the narrowed envelope applies to commands that are never
issued, and the mechanism the architecture is most distinctive for becomes code
that runs and changes nothing.

That is the real problem, and it is upstream of the ordering: **one condition had
two owners.** "No certified profile covers this context" produced two independent
responses — L6 vetoes (fail-closed, correct in isolation) and L9 narrows the
envelope and explores (also correct in isolation) — and the system resolved the
conflict by having L9 ignore L6.

The code already contained the argument. Above L6's uncalibrated branch:

> *"No finite threshold exists for this class. A gate that cannot make a
> statistical claim must not report that the proposal satisfied one."*

Exactly so — and it must not report that the proposal *violated* one either.
Both are claims about a distribution the gate holds no sample of. With only
`PASS` and `VETO` available, the author had to choose between two lies and chose
the safer one. The reasoning wanted a third value.

## Decision

**A gate that has no basis to judge returns `Verdict.ABSTAIN`, and no path
anywhere overrides a veto.**

Three parts, and they only work together:

1. **`Verdict` gains `ABSTAIN`.** An abstention is *not* a PASS: it removes the
   gate from the aggregation for that tick rather than clearing anything.
2. **`Verdict.merge` drops abstentions before applying the fail-closed rule.** A
   verdict set that is empty **or entirely abstentions** yields `VETO`, for the
   same reason: nothing judged the command, so the command was not cleared.
   Returning PASS there would let a gate clear a command by declining to look at
   it — the fail-open mode SI-3 exists to prevent, reached by a new route.
3. **`issue()` tests the verdict first.** The exploration branch moves below it,
   so exploration governs a tick no gate blocked and never one that was blocked.

L6 returns `ABSTAIN` for exactly one checkable condition: it holds no finite
conformal threshold for the context class it was handed. The calibration sample
count is already in that verdict's evidence, so the abstention is auditable after
the fact rather than taken on trust.

### Why abstention has to be local to L6

L6 keys on `math.isinf(quantile)` — its own calibration, for the class its own
classifier returned. It never asks L9 anything. Had L6 needed to know whether
exploration was engaged, that would be an upward dependency into the arbitrator
and the import contracts would rightly forbid it. The two conditions coincide
because they share an upstream input, not because one layer commands the other.

## Alternatives considered

### 1. Keep the ordering and document it honestly

Rejected. It makes the deterministic gate's authority conditional on a state the
gate cannot observe, and "unconditional veto authority" is the strongest claim in
this project's safety story. With exploration permanently engaged, *no* gate had
authority over the actuators.

### 2. Swap the branches; no abstention

Rejected. Preserves the unconditional veto perfectly and deletes bounded safe
exploration, for the reason given above. It is the honest fallback if abstention
is ever judged too subtle to defend — strictly safer, and it removes a feature
rather than pretending to have one.

### 3. Override only the `STATISTICAL` veto, at issue time

The first draft of this record, and rejected on reflection. It buys the same
behaviour for a fifth of the effort and pays with a permanent exception to the
unconditional veto plus an evidence log full of vetoes that did not bind. Cheaper
fix, worse architecture: the exception would have to be argued in the safety case
for the life of the project, and every future reader would have to be told that a
VETO sometimes is not one.

### 4. A per-gate override list in configuration

Rejected without much consideration. Which gate may be overridden is tied to
*why* each gate exists; in a TOML file it becomes a safety threshold a deployment
can change.

## Consequences

### Positive

- **Measured: commands issued under a blocking verdict went from 99,808 per
  100,000 ticks to zero.** A 5,000-tick run after the change issues
  `FALLBACK_PID` on 87.4% of ticks and `EXPLORATION_BOUNDED` on 12.6%, and never
  issues a proposal the gates refused.
- SI-3 holds without an exception. `issue()` *lost* a branch rather than gaining
  one.
- The evidence log distinguishes "judged and cleared" from "had no basis to
  judge" — the same distinction `TrustAssessment.is_calibrated` was added to
  preserve one layer up.
- A gate that abstains no longer drives the OOD counter toward HALT. Previously a
  long exploration episode pushed the vehicle to a pull-over on the strength of a
  gate that was not judging.
- Bounded safe exploration survives, and now means what its docstring says: the
  envelope shrinks what may be issued; it does not excuse it from inspection.

### Negative / accepted trade-offs

- **A command an uncalibrated L6 blocked before will now be issued when L7a and
  L7b pass.** This reduces what is blocked. It is the point of the change, and it
  belongs in the safety case as an argued position rather than a footnote.
- **The verdict is no longer binary**, and two invariant texts said it was. SI-4's
  statement lost the word, SI-3's grew "or in which every gate abstained", and
  `Verdict`'s docstring was rewritten. Amending an invariant statement is a
  deliberate, reviewable act — which is what the catalogue is for — but it is a
  change to a contract and is recorded as one.
- **`AUDIT_SCHEMA_VERSION` moved 1 → 2.** No field changed shape, so a version-1
  reader will parse a version-2 record structurally and mis-classify an
  abstention. That is the failure the version field exists to make loud.
- **Abstention is a licence that must not spread.** It is defensible here because
  the condition is objective and recorded in the same verdict's evidence. A gate
  abstaining because it was "uncertain" would be a fail-open mode wearing this
  record as cover. Any second use needs its own ADR.
- **It does not break the veto latch (F1a), and removes the accident that was
  hiding it.** Exploration was the one path by which a vetoed proposal reached
  the actuators, and in the cold-path runs that was holding the vehicle in its
  lane. With it gone, the departure reasserts — 123 m by tick 5,000. That is
  P0.2's problem, it always was, and this record makes it visible rather than
  causing it. Read the two together, in this order.
- **This change did not, in the measured run, cause any abstention.** The
  classifier lands in a seeded class, so L6 held a finite threshold and genuinely
  vetoed on score. Abstention is what makes the reordering *safe* — without it,
  reordering would have deleted exploration — but the behaviour change came from
  the ordering. Stated plainly because the opposite is the easy thing to imply.

## Implementation

`Verdict` (`kernel/enums.py`), `Verdict.merge`, `Verdict.participates`; L6's
uncalibrated branch (`l6_statistical_gate/gate.py`); `issue()`
(`l9_rcm/arbiter.py`); SI-3 and SI-4 statements (`invariants/catalogue.py`);
`AUDIT_SCHEMA_VERSION` (`kernel/constants.py`).

`guard_verdict_aggregation` needed no change: it is defined in terms of
`Verdict.merge` and inherited the new semantics.

The architecture property tests previously enumerated `(PASS, VETO)` explicitly
and would have stayed green while covering none of this. They now derive their
alphabet from `tuple(Verdict)`, so the next value added is covered on the day it
is added or the tests fail and say so.

**Verified:** `mypy --strict` clean across 140 files; **12 import contracts kept,
0 broken**; 2,596 tests passing at 97.97% coverage.
