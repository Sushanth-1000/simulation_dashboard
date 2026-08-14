# ADR-0025: The vehicle proposes calibration *work*, never a calibration

- **Status:** Accepted
- **Date:** 2026-08-11
- **Defect closed:** OD-14 in [`../CREDIBILITY_MATRIX.md`](../CREDIBILITY_MATRIX.md)
- **Evidence:** E-101 – E-104 in [`../EVIDENCE.md`](../EVIDENCE.md)
- **Constrained by** [ADR-0020](0020-fb2-estimates-control-effectiveness.md) and the FB3 refutation. **Supersedes nothing.**

## Context

The commissioning certificate (E-97) says which contexts a platform is fit for.
On the calibrated platform, **four of five come back `BOUNDED`** — no profile
matched, the vehicle drove anyway inside the narrowed envelope, and nothing was
learned from it.

That is the architecture working. It is also waste. The vehicle has just spent
hundreds of ticks accumulating evidence about a context nobody calibrated for,
and discarded all of it. A fleet doing this for a year discards the most
valuable dataset anybody could have about where its calibration coverage is
missing.

The machinery to do better already exists and was built for something else:
`SHADOW_EXECUTION`, the divergence index, staged promotion, and a hash-chained
evidence log. What was missing is the thing that notices.

### What blocked it, and it was a defect

**The arbitration record did not carry the signature RCM decided on.**
`arbitrate()` received a `RuntimeContextSignature`, searched the knowledge base
with it, decided on it, and returned an `ArbitrationDecision` that did not
include it. So a record could say `SAFE_EXPLORATION, trust 0.62` and could
**not** say what context that was about.

The one question a reader of an arbitration record most wants to ask — *why did
RCM decide that?* — was unanswerable from the archive. That contradicts A-10,
which defines explainability for this project as **decision provenance**, and it
is the third instance of one shape: `fast_innovation` at audit schema 3 and
`previous_digest` at 5 were both quantities the pipeline had and the evidence did
not. Filed as **OD-14** and closed here; audit schema **6 → 7**.

## Decision

**A vehicle proposes a calibration *request*. It never proposes a calibration
*profile*, and the difference is the entire safety argument.**

A profile carries a **conformal quantile table**. A quantile table fitted to the
vehicle's own exploration episode is **FB3 wearing a new hat**: requantilising on
self-generated scores drives the veto rate to `significance_epsilon` *by
construction*, because ε of any distribution lies above its own 1−ε quantile
(E-40). The gate stops being a detector and becomes a fixed-rate sampler, and
nothing about the change looks like an error.

So a request carries only what the vehicle can honestly claim to know:

- the **centroid and spread** of the signature it kept meeting,
- its **safety record** while there — veto rate, escalation, availability,
- the **nearest certified profile**,
- and the tick range in the evidence log that backs all of it.

It carries **no quantile table, no coverage level, no certification dates**.
Turning a request into a profile requires an offline calibration run against
held-out data and a human signature. That is not a limitation to be engineered
away later — it *is* the mechanism.

### It is offline, and reads records

`benchmarks/envelope.py` is a pure function of an audit log. It never runs inside
a tick. Three things follow at once:

**It cannot influence anything.** The standing convention — *no mechanism gets
authority until it has run with none* — is satisfied **structurally** rather than
by discipline. There is no wire to cut, because none was laid.

**It is how a fleet actually works.** Vehicles upload evidence; a backend
aggregates and proposes. Putting this in the tick loop would model a fleet of
one, and would put a learning mechanism on the hot path for no benefit.

**It inherits the log's integrity.** The log is a hash chain (E-66), so a
proposal derived from it is derived from evidence whose alteration is detectable.

### Three filters, and the third is the one that is easy to forget

**Sustained** — below `_MINIMUM_TICKS` (200, ten seconds at 20 Hz) a stretch
outside every profile is a *transition*: entering a tunnel, a sensor recovering,
a manoeuvre. Set an order of magnitude above the arbitration period so an episode
must survive several independent re-evaluations.

**Safe** — a heavily vetoed, escalated, or non-driving episode is evidence
*against* operating in that context. Proposing it would ask an engineer to
certify a context the vehicle handled badly.

**Coherent** — the signature must have stayed in one place. A vehicle that drives
from a tunnel into daylight without any profile matching produces one long
episode whose **mean visibility is about 0.5**: a context that never existed and
that nobody should be asked to calibrate for. `_COHERENCE_LIMIT` bounds the
per-component spread, and an incoherent episode is **reported as such** rather
than silently averaged.

**A rejected episode is still reported, with its reason.** A proposer that
silently dropped what it rejected would give an engineer no way to discover its
filters were wrong.

## Alternatives considered

### 1. Propose a full profile, quantile table included

Rejected, and it is the reason this record exists. It is FB3 by another name —
see above. The failure is invisible: every metric continues to look healthy while
the gate degenerates.

### 2. Propose a profile that inherits the nearest certified profile's quantile table

Rejected. It makes a **statistical claim on no evidence**: that a context nothing
has been calibrated for has the same non-conformity distribution as its nearest
neighbour. That is exactly the assumption OD-8 found already violated on
synthetic data, where live scores sit *below the corpus minimum*. Cheaper than
option 1 and wrong in the same direction.

### 3. Auto-approve after enough evidence

Rejected, and it must stay rejected. It is the obvious next request from anyone
who likes this feature, and it converts a human gate into a threshold. The moment
a proposal can activate itself, the system certifies itself from its own data —
and a system that certifies itself from its own data will certify anything.

### 4. Run it in the tick loop, inside L9

Rejected on three counts: it would put a learning mechanism on the hot path
against SI-8's timing separation; it would model a fleet of one; and it would
give the mechanism runtime standing that the shadow convention says it has not
earned. Offline gives the same result with none of that.

### 5. Cluster episodes across runs before proposing

Deferred, not rejected. Clustering is what a real fleet backend would do, and it
is unmeasurable here — one vehicle, one plant, one seed. Recorded as the natural
extension rather than built on a dataset that cannot show whether it works.

## Consequences

### Positive

- **Measured, on a 600-tick tunnel run**: one episode, proposable, centroid
  `visibility 0.050 ±0.000, ego_speed 0.254 ±0.054, traffic 0.700 ±0.000,
  sensor_reliability 0.950 ±0.000, road_complexity 0.950 ±0.000`, nearest profile
  `highway_clear@v1`, 0.3% vetoed, NOMINAL throughout (E-102).
- **OD-14 closed as a by-product**, and it needed closing regardless: the
  evidence log can now answer *why did RCM decide that?*
- The commercial story is one an OEM acts on: ship one calibration, let the fleet
  find where the coverage is missing, and every expansion arrives with a signed
  audit trail and a human decision.
- It composes with the commissioning certificate: `BOUNDED` is precisely the
  state that generates requests.

### Negative / accepted trade-offs

- **It proposes work, not capability.** Nothing gets better until a human runs a
  calibration. Anyone measuring this by "contexts certified per week" will find
  it does nothing on its own, and that is the design.
- **The three filters are thresholds, and thresholds are arguable.** 200 ticks,
  0.15 spread, 10% veto rate. Each is justified in its docstring and none is
  tuned against a dataset, because there is no population to tune against —
  which is honest and is also why they should be revisited on real fleet data.
- **Coherence is checked per component, not jointly.** An episode that drifts
  along a diagonal in signature space — two components each moving inside the
  limit, together describing two contexts — would pass. A joint test needs a
  covariance and a distance, which is the clustering work deferred above.
- **Unmeasurable at fleet scale here.** One vehicle, one plant. Everything about
  aggregation, deduplication and cross-vehicle agreement is untested.
- **Audit schema 6 → 7**, and the module refuses a version-6 archive rather than
  guessing the missing field. That is deliberate and it means old evidence
  cannot be mined retrospectively.
- **A new surface for a bad actor with log-write access**: a forged episode is a
  forged calibration request. The hash chain detects alteration but not a
  fabricated log presented whole (E-67), which is the same residual
  `THREAT_MODEL.md` already records.

## Implementation

`ArbitrationDecision.signature` (`contracts/governance.py`); `_render_arbitration`
(`contracts/audit.py`); `AUDIT_SCHEMA_VERSION` 6 → 7 (`kernel/constants.py`);
the five decision paths and `_staged` (`layers/l9_rcm/arbiter.py`);
`benchmarks/envelope.py`.

Tests: `tests/unit/test_envelope_requests.py`, 14 of them — two asserting the
request/profile boundary **structurally**, because a proposer that grew a
quantile table would still pass every behavioural test in the file.

**Verified:** ruff clean, `mypy --strict` over 157 files, 12 import contracts.
