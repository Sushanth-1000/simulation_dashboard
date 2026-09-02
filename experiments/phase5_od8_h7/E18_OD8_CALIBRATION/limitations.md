# E18 - Limitations

## Scope

- **One plant model.** The synthetic driving environment. `[M-syn]` throughout; `[M-ext]` remains
  **0 of 30**.
- **Three policies is not a sample of policies.** Nothing here generalises across policy space. The
  finding that calibration must be policy-conditional is itself evidence that policy-to-policy
  variation is large.
- **One context class in practice.** 99.75 % of ticks are `URBAN_CLEAR`, so the Mondrian structure is
  effectively unexercised. The calibration is conditional on a context that never varies, which means
  context-conditioning is untested rather than validated.

## Method

- **epsilon = 0.05 is a convention**, not a requirement derived from a hazard analysis. A real
  deployment would set it from an allowable nuisance-alarm budget.
- **Per-tick alarms are not per-event alarms.** This experiment models neither alarm persistence nor
  debouncing. A 5 % per-tick rate over 400 ticks makes an alarm somewhere in a run near-certain;
  whether that counts as a false alarm depends on a policy this experiment does not define.
- **Calibrating on clean data establishes validity, not usefulness.** A gate can have perfect
  false-alarm control and detect nothing. That is E19's question, and the threshold is frozen so it
  cannot be adjusted to improve the answer.
- **The finite-sample conformal guarantee assumes exchangeable draws.** Ticks within a run are
  autocorrelated, so pooling 400 ticks per run overstates the effective sample size. The quantile
  remains a valid empirical order statistic, but its nominal coverage guarantee is weaker than
  n = 12,000 would suggest. Not corrected; recorded.

## Specific to the P2 failure

- **The drift is measured, not explained.** E18 shows P2's score rises within a run by more than its
  between-run spread. It does not establish why. Candidate causes -- twin behaviour under a
  heavily-vetoed trajectory, accumulating state error, trajectory-dependent context drift -- are
  untested.
- **First-half versus second-half is a coarse drift statistic.** It detects monotone drift well and
  would miss oscillation or a step change. A per-tick regression was not pre-registered and is not
  substituted after the fact.

## Consequence

E18's conclusions apply to P1 and P3. **P2 is excluded from any claim requiring a valid operational
monitor** until its non-stationarity is understood.
