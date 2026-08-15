# ADR-0032: The sigma points are redrawn after the process noise is added

- **Status:** Accepted
- **Date:** 2026-08-15
- **Defect closed:** OD-10 in [`../CREDIBILITY_MATRIX.md`](../CREDIBILITY_MATRIX.md)
- **Evidence:** E-147 – E-151 in [`../EVIDENCE.md`](../EVIDENCE.md)
- **The first deliberate departure from FilterPy**, which
  [`unscented.py`](../../src/astra/layers/l2_estimation/unscented.py)'s docstring
  reserves for changes made alone and measured

## Context

`predict()` drew sigma points from `P`, pushed them through `fx`, and set
`x, P = unscented_transform(propagated, ..., Q)` — so `P` carried the process
noise but `_sigmas_f` did not. `update()` then observed that stale set, making

```
S = H (P - Q) Hᵀ + R
```

short by exactly `H·Q·Hᵀ`. Every Mahalanobis distance the filter ever reported
was inflated by the shortfall.

**Inherited, not introduced.** This is FilterPy's behaviour, reproducing it was
deliberate, and a unit test pinned it *"so that changing the formulation has to
be a decision rather than a drift"*. It became a decision; the test fired and
was rewritten to assert the opposite.

## Decision

Redraw the sigma points from the `Q`-inflated covariance at the end of
`predict()`:

```python
self.x, self.P = unscented_transform(propagated, wm, wc, self.Q)
self._sigmas_f = self._points.sigma_points(self.x, self.P)
```

**A UKF has no `H` to add `H·Q·Hᵀ` with** — not having one is the entire point of
the sigma-point formulation — so the term cannot be bolted on. Redrawing is how
the textbook formulation carries it: the process noise goes into the measurement
sigma set, where the unscented transform can find it.

**It also changes the gain, and that is correct rather than incidental.** The
cross-covariance is accumulated from the same points, so it becomes `P·Hᵀ`
against the predicted covariance rather than the pre-noise one — which is what
the Kalman gain is defined against. A fix that corrected `S` and left the
cross-covariance on the old sigma set would have made the two inconsistent.

## What it moved

**The statistic, measured over 400 closed-loop ticks (E-147):**

| | before | after | ratio |
|---|---|---|---|
| p25 | 0.1938 | 0.1390 | 1.39× |
| median | 0.2817 | 0.2096 | **1.34×** |
| p95 | 0.5658 | 0.5282 | 1.07× |
| max | 22.9606 | 22.4129 | **1.02×** |

E-71 predicted "1.53× on the smallest half, 1.23× on the tail, 1.024× on the
largest single distance" from a different measurement. The largest-distance
figure lands on 1.02×. **The correction is largest where innovations are small
and nearly absent in the tail**, which is where vetoes are decided — which is
why OD-10 was correctly downgraded from the 22.4× algebraic bound it was filed
under.

**Control quality got worse, and that is the honest cost (E-149).** A correctly
larger `S` means a smaller gain, so the filter trusts each measurement less and
converges more slowly. Final lane deviation went from 0.0122 m to **0.1218 m**.
The old test bounds were set against an over-confident filter; they have been
re-derived from the corrected one with the old numbers recorded beside them, and
the vehicle remains far inside both the policy's own 0.875 m budget and the
1.75 m corridor.

## What it forced, and what that revealed

**The corpus had to be regenerated before anything would drive.** With the
corrected filter and the old corpus, **400 of 400 ticks were vetoed** on
`SCORE_EXCEEDS_CONFORMAL_QUANTILE`: the corpus had been calibrated on the old
statistic. `make artifacts-check`, added hours earlier, failed immediately with
*"the vehicle never drove"* — its first real regression, and the reason it
exists (E-148).

Two integration tests then failed in ways that were **not** threshold drift, and
both sharpen OD-9 rather than weakening it (E-150):

**The faulted run now has strictly fewer vetoes than the clean one.** The test
asserted the two verdict traces were *identical*. Measured: clean has 5 vetoes,
3 of them after the fault opens; the frozen-IMU run has 2, **none** after. A
frozen IMU stops the estimate moving, so the commands get smoother and the jerk
bound is never reached. **The fault makes the system look healthier to the gates
than the healthy run does.**

**The faulted run also ends closer to the lane centre, with a smaller estimator
error** — 0.0973 m against 0.1034 m, and 0.0974 m against 0.1547 m. A dropout
stops the extractor producing a measurement, so the filter coasts, and on this
seed coasting lands nearer the truth than tracking a noisy channel. An assertion
that the faulted run is *worse* by trajectory was reading a coincidence and has
been deleted.

**The only thing that separates the two runs is the integrity counter, 40
against 0** — exactly the claim ADR-0024 exists to support, and now the only
surviving discriminator rather than one of several.

## Alternatives considered

**Add `H·Q·Hᵀ` analytically.** Requires an `H`. A UKF does not have one, and
constructing a Jacobian to patch a sigma-point filter would reintroduce the
linearisation the formulation was chosen to avoid.

**Propagate `Q` into the points before `fx` instead.** Inflates the *prior*
rather than the prediction, so `fx` is evaluated at points the process model was
never meant to see, and the propagated mean shifts. Wrong quantity, and it
changes `x` as well as `S`.

**Leave it and correct the distance downstream.** The correction is
state-dependent — 1.39× at p25 and 1.02× at the maximum — so no scalar exists,
and computing one per tick means computing `S` correctly anyway.

**Leave it, and rename the field.** Defensible, and what the register already
did: OD-10's row says the archived `fast_innovation` is not a Mahalanobis
distance and may not be compared across a change to `Q`. That is a caveat where
a fix was available, and it leaves a quantity three gates read carrying a name
that is false.

## Consequences

### Positive

- `S` is the textbook innovation covariance, so `fast_innovation` **is** a
  Mahalanobis distance and may now be compared against a chi-squared
  expectation, against a distance computed elsewhere, and across a change to
  `Q` — the one the register warned would bite silently.
- The gain is consistent with the covariance it is derived from.
- Both directions asserted in the unit test: `S` equals the with-`Q` identity
  and **is not** the without-`Q` one, so a regression cannot pass as a deletion.
- The regeneration is now a documented, checked command rather than folklore.

### Negative / accepted trade-offs

- **Control quality is measurably worse** — final deviation 0.0122 m → 0.1218 m.
  The correct filter is less aggressive, and this is a real cost paid for a
  correct statistic.
- **Every recorded `fast_innovation` before this change is on the old scale**,
  and a mixed archive cannot be pooled. The audit schema does not record which
  formulation produced a row; the run's config hash does not either, because
  this is a code change rather than a configuration one. **A reader comparing a
  pre- and post-15-August archive has nothing in the record to warn them**, and
  that is the sharpest cost here.
- **A second Cholesky factorisation per tick.** Immaterial on a 5×5 at 20 Hz,
  and it is still work added to the hot path.
- **Two test bounds were loosened.** Justified by a understood cause and
  recorded with the old values, and loosening a safety-adjacent bound is exactly
  the move that needs to stay visible.
- **The corpus regenerated here was produced by the corrected filter against a
  twin that predates it.** A full twin → corpus → policy regeneration in that
  order ran later the same day under
  [ADR-0033](0033-redundancy-is-the-driven-path-not-a-measurement-beside-it.md).
- **Correction, same day.** This record originally said the policy was retrained
  to match the corrected filter. It was retrained and it **changed nothing**:
  `training/train_policy.py` trains against `SyntheticDrivingEnv` directly — the
  bare plant, with no pipeline, no UKF and no sensor bus — so the proposer never
  observes the filter and cannot be mismatched to it. Retraining produced a
  **bit-identical checkpoint**, `sha256:ac5b91bc…`, before and after.
  That is worth knowing for a larger reason than bookkeeping: **the policy is
  trained on ground truth and deployed against an estimate.** Nothing in this
  register covers that skew yet.
