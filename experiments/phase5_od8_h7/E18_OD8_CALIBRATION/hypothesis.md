# E18 - Hypothesis

**Fixed 1 September 2026, before any calibration value was computed.**

## Research question

Can the L6 statistical gate be calibrated so that it operates as a valid conformal monitor -- a
controlled false-alarm rate on clean data -- across the three tested policies?

The objective is **not** to maximise fault detection. A gate tuned to catch faults is not a conformal
gate. Validity first; usefulness is E19's question.

## H-E18

The OD-8 failure is a **calibration-set provenance** problem, not a threshold-value problem.
Recalibrating from clean runs generated under the same conditions as live operation will produce a
threshold whose empirical clean false-alarm rate matches its nominal epsilon within sampling error.

## H0-E18

Clean scores are not exchangeable even within a single policy under identical conditions -- for
instance because they drift within a run -- so no fixed quantile achieves nominal coverage.

## Falsification criteria

E18 FAILS if, after recalibration:

1. empirical clean false-alarm rate falls outside `[eps/2, 2*eps]` for any policy under the selected
   scheme;
2. calibration and clean-test scores remain distinguishable at AUC > 0.70;
3. within-run drift exceeds between-run spread.

## Outcome

**PARTIAL.** Criteria 1 and 2 passed for all three policies. Criterion 3 failed for P2 only
(drift/SD = 1.28). H-E18 is supported for P1 and P3; H0-E18 holds for P2.
