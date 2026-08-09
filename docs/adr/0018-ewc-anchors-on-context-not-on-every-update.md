# ADR-0018 — The EWC anchor moves on a context change, not on every update

**Status:** Accepted
**Date:** 6 August 2026
**Supersedes:** nothing. Amends the anchoring rule described in
`PhysicsInformedTwin._consolidate`.

## Context

`PENDING.md` P3.1 recorded a known issue before FB2 was wired into the tick loop:

> *EWC is inert at the configured λ.* `development.toml` sets 100 and
> `simulation.toml` sets 150; the penalty only measurably resists movement
> around λ≈10¹².

It proposed two answers: tune λ empirically, or rescale the penalty. The
catastrophic-forgetting test the same entry demanded — write it *first*, because
without it you cannot tell adaptation from destruction — was written first, and
it says the diagnosis was right about the symptom and wrong about the cause.

### What was measured

The experiment: train a twin offline on a "highway" context (Adam over both
layers, as `training/train_twin.py` does), then hand it to FB2 and feed it 4,000
samples of a "rain" context needing 2.5× the steering and less throttle. Measure
highway error before and after. Run the identical experiment at λ=0 and at the
configured value, from one shared checkpoint, so the penalty is the only
difference.

**λ=150 is not merely weak. It is bit-for-bit inert.**

| λ | highway before | highway after | forgetting |
|---|---|---|---|
| 0 | 0.000247 | 0.039219 | 0.038972 |
| 150 | 0.000247 | 0.039198 | 0.038951 |

Identical to four decimal places. And the threshold P3.1 guessed at — λ≈10¹² —
was not where the penalty began to work. Sweeping ten orders of magnitude found
a *single decade* that helped, with a cliff immediately above it:

| λ | forgetting, relative to λ=0 |
|---|---|
| 10² | 1.00 |
| 10⁴ | 0.97 |
| 10⁶ | **0.08** |
| 3×10⁶ | 2.33 — worse than no penalty |
| 10⁸ | 6.94 |

A parameter whose useful range is one decade wide, with a cliff at 3× and a
plateau of nothing below, is not a mistuned parameter. It is a mechanism doing
something other than what its name says.

### The cause

`_consolidate` re-anchored after **every** consolidation — every
`adaptation_buffer` samples, twenty in the experiment and fifty in production.

The anchor is what the penalty holds the parameters *near*. Moving it every fifty
samples means the term resists the last fifty samples' movement and permits
unlimited total drift. After two hundred consolidations of rain the anchor is
pure rain, and the highway it was supposed to consolidate is long gone. It was
a step-size limiter wearing elastic weight consolidation's name.

The cliff above 10⁶ has the same root. Gradients are clipped to norm 1, so a very
large λ does not freeze the weights — it makes the clipped gradient point almost
entirely along the penalty, and with the anchor following the parameters there is
no equilibrium to be pulled toward. The twin then takes maximum-size steps in an
arbitrary direction forever, which is why it ends up worse at *both* contexts.

The existing docstring defends anchoring on the previous consolidation rather
than the current parameters, and that argument is correct as far as it goes:
`(θ − θ)²` has zero value and zero gradient. It does not address how often the
previous consolidation happens.

## Decision

**The anchor is re-taken when the operational context changes, and held constant
within one.** `adapt()` accepts the `ContextClass` the outcome was observed in;
on a change it re-anchors from parameters that still describe the *outgoing*
context, and discards the partial buffer so no single update mixes two contexts.
Absent a context, the anchor is taken once and never moved.

EWC's task boundary becomes the system's own notion of a task. That is not a
convenience: `ContextClass` is already the Mondrian conditioning class of L3 and
the seed-profile key of L9, so the twin now consolidates against the same
partition the trust module and the knowledge base reason about.

**λ = 10⁴**, in both `simulation.toml` and `development.toml`.

## Options considered

| Option | Benefit | Drawback | |
|---|---|---|---|
| **A. Anchor on context change** | Restores the mechanism EWC actually is. The response becomes monotone from 10² to 10⁸ with no cliff, so λ can be set by intent instead of by knife-edge search. Uses a partition the architecture already has | `adapt()` grows a parameter, and a caller that does not supply it gets the conservative always-anchored behaviour | **chosen** |
| B. Tune λ to 10⁶ and leave the anchoring alone | One config value, no code change; 12× less forgetting | Ships a value where 3× higher is *worse than zero*. The next platform, Fisher scale or buffer size moves the optimum and nothing says so. This is the fragility class that produced the original defect | rejected |
| C. Normalise the Fisher by its mean, then tune λ | Would make λ scale-free if it worked | Measured, not assumed: it shifts the window to 10⁴ without widening it — still one decade, still a cliff at 10× — and the best protection available drops from 0.084 to 0.309 of unregularised. Strictly worse than B | rejected |
| D. Delete `ewc_lambda` and document that EWC is not active | Honest about the status quo | Gives up the only mechanism standing between FB2 and a twin that adapts by destruction. A twin that has forgotten does not fail loudly: it predicts confidently, and two gates then reason carefully about a non-conformity score computed against a wrong reference | rejected |

### Why 10⁴ rather than the value with the least forgetting

With the anchor fixed, more λ is monotonically more retention, so "best" has no
maximum — 10⁸ forgets least. 10⁴ is chosen for **robustness, not optimality**: it
sits in the middle of the working range, so being wrong by an order of magnitude
in either direction still leaves a penalty that functions. That is precisely the
property the old value lacked, and the reason this ADR exists.

## Consequences

Good:

- The configuration stops lying. A reader who sees `ewc_lambda = 10000` and
  concludes the twin is protected against forgetting is now right.
- Forgetting at the shipped value is 0.0032 against 0.0390 unregularised — the
  highway error after a full rain excursion stays under 0.004, so the twin is
  still a usable reference for an ICP score.
- The anchoring rule is now stated in terms of something meaningful (a context)
  rather than something incidental (a buffer size).

Accepted costs, both recorded rather than smoothed over:

- **The penalty is a brake, not a consolidator — P3.1a, open.** Across λ from 0
  to 10⁵ the ratio of forgetting to adaptation is constant to three significant
  figures (0.00184, 0.00184, 0.00186, 0.00186, 0.00194). EWC buys nothing here
  that a smaller learning rate would not buy equally. This is structural: FB2
  adapts a 16→2 linear readout and both contexts use all of it, so there is no
  disjoint parameter subspace for a Fisher-weighted penalty to exploit. RK-5
  anticipated exactly this. `test_the_penalty_protects_the_old_context_more_than_it_blocks_the_new`
  is a **strict xfail** — an executable statement of the defect that will fail
  the suite the day it is fixed. The candidate answer is a per-`ContextClass`
  output head, which makes forgetting structurally impossible instead of merely
  expensive.
- **FB2 is slow.** Unregularised, 4,000 samples — 200 seconds of driving at
  20 Hz — closed 21% of a large context change; at λ=10⁴, 1.7%. SGD at 10⁻³ with
  gradients clipped to norm 1 moves the parameters by at most 10⁻³ per step, and
  there are ten steps per fifty samples. Whether that is too slow is a question
  about what FB2 is *for*, and it should be answered before the loop is wired
  into the tick loop rather than discovered afterwards.

## Compliance

- **SI-3** untouched: the twin's prediction is an input to two gates and neither
  gains nor loses authority here.
- **NFR5** untouched: `ContextClass` is a core enumeration, not a platform fact.
- **A-5** (byte-reproducible runs): anchoring is now driven by an input carried
  in the evidence log rather than by a buffer count, so a replayed run
  re-anchors at the same ticks.
