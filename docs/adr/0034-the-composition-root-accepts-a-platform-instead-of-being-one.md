# ADR-0034: The composition root accepts a platform instead of being one

- **Status:** Accepted
- **Date:** 2026-08-15
- **Defect partly closed:** OD-11 walls 1 and 2, in [`../CREDIBILITY_MATRIX.md`](../CREDIBILITY_MATRIX.md)
- **Evidence:** E-156 – E-158 in [`../EVIDENCE.md`](../EVIDENCE.md)
- Walls 3 and 4 remain open and are still strict xfails

## Context

[ADR-0002](0002-domain-independent-platform-core.md) promised a
domain-independent core with adapters. `assemble_pipeline` called
`automotive_actuation_space()` directly and took no parameter for it, and built
`AutomotiveCommandProjector` the same way — **while the module docstring three
hundred lines above claimed an adapter could supply both.**

Two strict xfails had pinned this since the NFR5 audit. Strict is what made the
fix announce itself: both flipped to `XPASS(strict)` — reported as failures — the
moment the parameters existed.

## Decision

`space` and `projector` are keyword-only parameters, defaulted to the automotive
implementations.

**Defaulted rather than required**, and that is the whole of the judgement here.
This composition root *is* automotive until a second platform exists; making the
parameters mandatory would break every caller to prove a point no adapter is yet
making. What NFR5 asks is that a different platform **can** supply one — and the
difference between *can* and *does* is the difference between a wall and a
default.

### Supplying a space obliges you to supply the rest of the platform

```python
if space is not None and (projector is None or policy is None):
    raise ConfigurationError(...)
```

The projector inverts a lateral acceleration through `STEER_INDEX`; the
placeholder policy steers through it. **Both defaults assume the automotive
layout**, so a caller supplying a two-channel differential drive and defaulting
either used to get `steer_index 2 is outside a 2-channel actuation space` from
somewhere deep in construction. Refusing here says the same thing where it can be
acted on, and refusing beats defaulting: there is no sensible projector or
fallback controller for a platform this function has never heard of.

## What writing an honest test found

The original assertions were `any("space" in name for name in parameters)`. They
would have been satisfied by a parameter named `workspace`, and by a parameter
that was accepted and ignored.

Driving the root with a real two-channel space instead turned up **three further
couplings, none of which review had named:**

1. The **projector** default, which the xfail did describe.
2. The **placeholder policy**, which it did not. It takes `speed_index` and
   `steer_index` into the space and is constructed whenever no policy is
   supplied.
3. **`twin.control_effectiveness`**, whose length *is* the channel count. This
   one the configuration layer already caught, with a better message than any
   test could add: *"the row maps a command to the lateral acceleration it
   produces, so a length mismatch describes a different platform."*

**Making the space injectable is not the same as making the root
platform-neutral, and only driving it with a different space says which.** The
third item is not an NFR5 violation at all — a different platform needing a
different profile is correct — but it means an adapter supplies **four**
coordinated things, and nothing had said so.

## Alternatives considered

**Require the parameters.** Honest, and it breaks every caller today to serve an
adapter that does not exist. The refusal above gets the same protection at the
only point where the defaults are actually wrong.

**Default the projector from the supplied space.** Attractive and undecidable: a
projector needs to know *which channel steers and how much lateral acceleration
a unit of it produces*, and neither can be read off a list of channel names and
bounds. Guessing would produce a plausible projector that steers the wrong
channel.

**Move `STEER_INDEX` into configuration.** The right long-term shape, and a
larger change than this one: it is threaded through the placeholder policy, the
projector and the twin's effectiveness row, so moving it means moving all three
together. Recorded here as the successor rather than smuggled in.

**Leave both walls and fix wall 3 first.** Wall 3 — the bicycle process model —
is the one that *cannot* be fixed by moving a symbol, so it is the honest
priority. But it is also a research problem, and leaving two mechanical walls
standing next to it would have kept a false claim in a docstring for the sake of
tidiness.

## Consequences

### Positive

- The docstring's claim is now true, and a test drives it rather than inspecting
  a signature: a two-channel differential drive assembles, and
  `built.space is supplied`.
- The four things an adapter must bring are **named**, one of them for the first
  time.
- A mis-matched platform fails at the composition root with a message saying
  what is missing, instead of an index error deep inside construction.
- Two strict xfails removed rather than relaxed — the suite went 5 xfails to 3.

### Negative / accepted trade-offs

- **Walls 3 and 4 are still up**, and wall 3 is the one that matters: L2's
  process model derives yaw rate from `a_lat / v` and refuses below a minimum
  speed, so a platform that turns on the spot cannot be estimated at all. No
  amount of injection reaches it.
- **`STEER_INDEX` is still a module constant** in the composition root, read by
  three separate constructions. The refusal makes its wrongness *loud* on a
  foreign platform rather than *absent*.
- **No adapter exists.** The seam is proved by a test stub — a `_WheelProjector`
  with two wheels and no steering channel — not by a second real platform. The
  claim this record supports is *"a platform could be supplied"*, and it stops
  there.
- **The default path is unchanged and untested by this**, in the sense that
  every existing caller passes neither parameter and gets exactly what it got
  before. That is deliberate — it is why the change carries no regeneration —
  and it means the injected path has one test rather than a suite behind it.
