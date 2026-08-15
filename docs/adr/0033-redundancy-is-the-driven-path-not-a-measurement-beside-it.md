# ADR-0033: Redundancy is the driven path, not a measurement beside it

- **Status:** Accepted
- **Date:** 2026-08-15
- **Defect closed:** OD-15 in [`../CREDIBILITY_MATRIX.md`](../CREDIBILITY_MATRIX.md)
- **Evidence:** E-152 – E-155 in [`../EVIDENCE.md`](../EVIDENCE.md)
- **Completes** [ADR-0026](0026-faulted-gets-a-producer-and-the-counter-needs-a-quorum.md), which built the machinery, and [ADR-0027](0027-the-integrity-counter-rises-on-a-lost-quorum.md), which fixed the escalation policy

## Context

`_publish_state` computed one payload and published it **byte-identical to all
five modalities**, and the extractor read the IMU alone. Five modalities, one
sensor. Every cross-check that could catch a lying channel had nothing to check
against, and *"unmeasurable here"* was written into three separate refutations on
the strength of it (E-108).

[ADR-0026](0026-faulted-gets-a-producer-and-the-counter-needs-a-quorum.md) built
the machinery — a median-fusing extractor, a residual monitor, `FAULTED` produced
for the first time — and measured the slow drift falling from **2.025 m to
0.042 m**. But it ran *beside* the vehicle. The default remained one channel, so
the register's own words: *"redundancy is measured beside the vehicle rather than
by it. Wiring it is a further step and needs its own decision record."*

This is that record.

## Decision

**Redundancy is the default.** `drive_closed_loop` builds three independent
position channels unless a caller asks for one, and asking has to be explicit:

```python
if redundant is None and not single_channel:
    redundant = RedundantSensing.build(sigmas=DEFAULT_CHANNEL_SIGMAS, seed=seed)
```

`single_channel=True` is how the old behaviour is requested, **and it has to say
so**. A default that read `redundant=None` and silently meant *"one sensor"* is
how the defect survived as long as it did: nothing in the call site was false, it
simply never mentioned the thing that mattered.

### Three channels, and unequal noise

```python
DEFAULT_CHANNEL_SIGMAS = {IMU: 0.1, GPS: 0.2, LIDAR: 0.06}
```

**Three, not two.** A median needs three to have a middle. With two, a
disagreement establishes that *something* is wrong without saying which; with
three the largest residual names the liar, which is what produced `FAULTED` for
the first time in this project's life (E-114).

**Unequal, deliberately.** Identical sigmas model identical sensors, and
identical sensors share a failure mode — which is the assumption that makes a
redundancy argument worthless. A vehicle carrying three copies of one part has
one part.

The constants moved from `benchmarks/redundancy.py` into `training/closed_loop.py`.
Two definitions that must agree, in modules only one of which is on the driven
path, is how they stop agreeing — the same reasoning that moved the
`StreamHealth` ordering onto the enum in ADR-0031.

## What it bought

**The clean run got six times better (E-152):**

| | vetoes | final \|dev\| | speed |
|---|---|---|---|
| single channel | 5 | 0.1034 m | 10.85 m/s |
| **redundant** | **1** | **0.0168 m** | 12.09 m/s |

A median over three channels — one of them at σ = 0.06 — is a far better position
estimate than a single σ = 0.1 channel, and the proposer inherits it.

**That matters beyond its own merit.** [ADR-0032](0032-the-sigma-points-are-redrawn-after-the-process-noise-is-added.md)
had just cost control quality — a correct innovation covariance means a smaller
gain, and final deviation went 0.0122 m → 0.1218 m. This more than repays it.
**The honest fix for a filter that must trust each measurement less is to give it
better measurements**, which is a more satisfying answer than retuning the one it
had.

**And the drift is now arrested by the vehicle rather than beside it (E-153):**
with a 0.01 m/tick drift injected into the IMU, final deviation is **0.0490 m** —
inside a lane it used to leave at 2.025 m — and 66 ticks are vetoed on
`PROPOSAL_DIVERGES_FROM_TWIN`. A gate fires. Under the single-channel default no
gate ever did.

## Alternatives considered

**Keep the default and document it.** What the register did for four days, and
the reason OD-15 stayed open: a capability demonstrated in a benchmark is not a
capability the system has. Every claim of sensor diversity rested on a path
nothing drove.

**Make it configurable in the TOML profile.** Wrong layer. Which sensors a
vehicle carries is a property of the *plant*, and the plant here is the training
harness, not a deployment setting. `failsafe.integrity_tolerated_faults` is the
configuration that responds to redundancy and it already exists (ADR-0027).

**Publish three channels but keep fusing one.** Would have made the residual
monitor live while leaving the estimate single-sourced — the monitor could name a
liar the estimator was still listening to. Worse than either end.

**Five channels rather than three.** The bus carries five modalities and only
three are position sensors in any honest reading; a camera and a radar do not
measure lateral position the way an IMU, a GPS and a lidar do. Publishing five
would have inflated the quorum with channels that were duplicates again.

## Consequences

### Positive

- The vehicle is **driven** by redundant sensing, so every claim of sensor
  diversity now describes the path that runs.
- Control quality improved 6×, which pays back ADR-0032's cost with margin.
- `integrity_tolerated_faults = 1` becomes an honest setting for the first time:
  there are now three channels for a quorum to be a quorum of.
- The single-channel path is preserved and **named**, so the ablation and
  comparison arms can still isolate it.

### Negative / accepted trade-offs

- **Every number in the evidence pack moves**, and this is the second
  regeneration in one day. The pack was re-measured against a matched
  twin → corpus → policy set; anything quoted from before is on a different
  system.
- **The three channels share the plant.** Their *errors* are independent — the
  disjoint generator guarantees that — but all three observe the same simulated
  truth through the same model. **They cannot catch a plant-model error**, and no
  amount of channel count will. That is the boundary of what this buys, and it is
  the same boundary the whole `[M-syn]` column has.
- **This is the harness, not `src/`.** `FusedSensorFrame` already carried
  per-modality samples and `MeasurementExtractor` was already injectable, so
  nothing in the library changed — which is the good news architecturally and
  means the *deployment* still has to supply real redundancy. The prototype
  models it; it does not provide it.
- **A real vehicle's channels are not three noisy copies of one quantity.** GPS
  is absolute and drifts slowly, an IMU integrates and drifts quickly, a lidar is
  relative to landmarks. Modelling all three as unbiased Gaussians around truth
  is generous to the median, and a real fusion problem is harder than this one.
