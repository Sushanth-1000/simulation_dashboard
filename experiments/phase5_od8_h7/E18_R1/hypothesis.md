# E18-R1 — Hypothesis

**Fixed before any R1 result was computed.**

## Research question

Can a pre-registered windowed (run-local) calibration procedure recover sufficiently stable
run-level false-alarm behaviour for P3 to satisfy the predefined operational criterion?

## H1 (primary)

A temporally localized, run-local calibration procedure will improve the run-level stability of
OD-8's P3 false-alarm behaviour sufficiently to satisfy the predefined operational calibration
criterion of **>= 24/30 runs in band**.

**Mechanistic basis** (from `audit_of_E18.md` section 10): P3's false-alarm rate is driven by a
per-run baseline offset (corr = +0.909) whose spread (0.0277) exceeds the pooled threshold headroom
(0.0170). A threshold estimated from each run's own baseline removes that offset by construction.

## H0 (null)

Run-local calibration does not provide sufficient P3 run-level calibration stability to meet the
predefined criterion.

**H0 is a live possibility, and the reason is stated in advance:** run-local calibration trades
between-run bias for estimation variance. Each threshold is estimated from 200 ticks instead of
12,000, and those 200 ticks are autocorrelated. If the quantile estimate is too noisy, per-run FAR
will scatter around the nominal rate rather than concentrate on it, and the criterion will fail.

**The experiment can therefore produce either result**, and the failure mode is specified before the
run rather than explained afterwards.

## Secondary question

Does the recovered monitor, if any, remain operational — i.e. does detection performance survive the
change in calibration? Reported, not optimised.

## What this experiment is not

It is not a search for a window size. It is not an attempt to rescue P2. It is not a re-opening of
the E19 predictor question.
