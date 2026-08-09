# ADR-0020 — FB2 estimates the control effectiveness, rather than regressing on commands

**Status:** Accepted, not yet implemented
**Date:** 9 August 2026
**Follows:** [ADR-0019](0019-one-twin-head-per-context.md), which fixed *where* FB2
writes. This fixes *what it learns from*.

## Context

ADR-0019 gave the twin one output head per context, which made catastrophic
forgetting structurally impossible. It did not touch the loss, and the loss is
where the remaining defect lives.

`_consolidate`'s data term is `MSE(predicted, applied)`, and `applied` is the
issued command — the proposer's on 99.9% of ticks. **FB2's only source of labels
is the component the twin exists to be independent of.**

`twin.py`'s module docstring already names the consequence:

> *If the twin were trained until it predicted Core-A's policy accurately, every
> non-conformity score would be small, the statistical gate would stop firing,
> and the system would look healthy while having disarmed one of its three
> gates.*

Measured rather than assumed (E-39). Over 100,000 ticks in a context where
nothing changed, with FB2 running against a twin nothing reads: the score against
the live twin stayed flat to four decimal places, 1.1564 → 1.1560, while the
score against the adapted twin fell **40%**, 1.1534 → 0.6962, monotonically and
still falling at the end.

Offline training does not have this problem. `train_twin.py` labels each state
with `steer = lateral / gain` — the inverse of `B·π = a_lat`, physics, with the
proposer playing no part. Only the *online* loop regresses on commands.

## Decision

**FB2 estimates the platform's control effectiveness `B` from measured response,
and stops fitting a network to commands.**

What "the vehicle's response has changed" *means* — tyre wear, load shift, a wet
road — is that the true `B` has moved. That is directly observable from the pairs
FB2 already receives: command a steering value `s`, observe the lateral
acceleration `a` it produced, and `a / s` is the effective `B`.

The estimate feeds the physics residual the whole twin is anchored on. The twin's
weights stop moving online altogether.

**It lives in the adapter, not in L5.** `B` is a platform fact — it is
`control_effectiveness` in configuration precisely because NFR5 keeps vehicle
knowledge out of the layers — so the thing that estimates it belongs on the same
side of that boundary. L5 consumes the estimate through the existing settings
seam rather than computing it.

### The requirement that makes it work, and it is not optional

**Saturated samples must be excluded.** Measured on the synthetic plant, whose
configured `B` is 140.0 and which clamps lateral acceleration at 3.0 m/s², so it
saturates beyond `|steer| = 0.0214`:

| samples used | recovered `B` | error |
|---|---|---|
| linear region only (`\|steer\| ≤ 0.02`) | **140.000**, σ = 0.0000 | **0.000 %** |
| wide steer, saturated excluded | **140.000**, σ = 0.0000 | **0.000 %** |
| wide steer, saturated **admitted** | 116.0, σ = 30.5 | **17.1 %** low |

Exact when the condition holds; 17 % low when it does not, and *biased in the
dangerous direction* — an underestimated `B` makes the twin expect more steering
than the vehicle needs, which shrinks the departure the score is computed from.

Saturation is detectable without extra instrumentation: `|a_lat|` sits at the
configured limit. A sample at the limit carries no information about `B` and must
be dropped rather than averaged in.

The first probe of this ADR got 17 % because it drove ±0.05 steer into a plant
that saturates at 0.0214, and read the bias as a property of the estimator rather
than of the probe. It is recorded because the same mistake in production would be
silent.

## Options considered

| Option | Benefit | Drawback | |
|---|---|---|---|
| **A. Estimate `B` from measured response** | The target is measured physics, so drifting toward the proposer is **impossible rather than penalised** — the same move as ADR-0019, one level up. Recovers `B` exactly. Forgetting is moot: a scalar per context, not a network. Removes online weight updates from a safety reference entirely | Tracks a *gain* change, not a *shape* change. Needs saturated samples excluded. `B` is platform configuration, so placement needs care | **chosen** |
| B. Label FB2 from physics, keep the network | Looks like the minimal change | Does not work. The physically-consistent command satisfies `B·π = a_lat` with `B` **configured**, so labelling from a fixed `B` reproduces `train_twin.py`'s corpus exactly and FB2 learns nothing it did not ship with |
| C. Raise `physics_weight` on the online path so the residual dominates | Cheap | A tuning answer to a structural problem. This phase has already shown twice where those end up — `ewc_lambda` at a value that did nothing, and a penalty that could not be selective at any value | rejected |
| D. Do not wire FB2 at all | Correct today, and costs nothing | Gives up a quarter of the stated architecture permanently, on the grounds that one implementation of it was wrong | rejected |

**On A's drawback.** Losing shape adaptation is accepted deliberately.
Expressiveness is what let FB2 learn the policy in the first place; a reference
the proposer cannot move is worth more than a reference that fits well. If shape
adaptation is ever needed, it belongs offline, where the labels come from a
corpus rather than from the thing being judged.

## Consequences

Good:

- The twin's weights stop changing during a run. `twin_weights_digest` becomes
  constant by construction rather than by FB2 being switched off, which makes the
  soak criterion *"the twin is the one the run started with"* meaningful instead
  of vacuous.
- `B` is one number per context with a physical meaning and a configured
  starting value, so a wrong estimate is legible in a way a wrong network is not.
- The estimator can be checked against its own configuration: a live estimate far
  from the configured `B` is either a genuine platform change or a fault, and
  either is worth an event.

Costs and open questions, none of them resolved here:

- **Sample starvation.** With steer drawn from ±0.2, only 387 of 4,000 samples
  survived the saturation filter. A vehicle that corners hard spends much of its
  time saturated, and that is exactly when someone would want the estimate. The
  update rate must be measured, not assumed.
- **Noise on a real platform.** The synthetic plant is noise-free in this
  relation, which is why σ came out at exactly zero. On a real vehicle `a / s` is
  a ratio of two noisy quantities and will need a recursive filter rather than a
  median.
- **Where the boundary lands.** L5 currently reads `control_effectiveness` from
  settings once at construction. Making it read a live estimate is a port change,
  and the port must not let a layer reach into the adapter.

**Measured in shadow before it is wired**, like FB2 and FB3 before it. That is
now the standing rule for feedback loops in this project, and it has caught two
defects that no test would have.

## Compliance

- **NFR5**: strengthened. The estimator sits with the other platform knowledge
  rather than inside a layer.
- **SI-3, SI-7**: untouched. Nothing here changes which component may veto or
  issue.
- **A-4**: `control_effectiveness` remains a configured value with no default. The
  estimate refines it at runtime; it does not replace the requirement to state it.
- **RK-5** (catastrophic forgetting): retired for FB2. There is no longer an
  online network update to forget anything.
