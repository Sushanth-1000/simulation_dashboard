# E18-R1 - Recovering P3 Operational Calibration

# VERDICT: FAIL-P3   |   GATE: DO NOT PROCEED TO E19

| | |
|---|---|
| Question | Can run-local (windowed) calibration recover stable P3 run-level false-alarm behaviour? |
| Frozen criterion | >= 24/30 runs in band = PASS; 12-23 = CONDITIONAL; < 12 = FAIL |
| **P3 result** | **9/30 -> FAIL-P3** |
| P1 positive control | 3/30 (E18 matched-window: 4/30) - did not improve |
| Secondary finding | **A window-mismatch defect in E18 that revises its P1 verdict** |

## The two results

**1. Run-local calibration removed the mechanism and still failed.** P3's bimodality was caused by a
per-run baseline offset (corr = +0.909 between run mean and run FAR). Run-local thresholds removed
that dependence (corr -> -0.469) but cost more estimation variance than they removed bias:
per-run threshold SD (0.0135-0.0251) is comparable to the entire threshold headroom
(0.0170-0.0235). The monitor over-covers; median run FAR is 0.00-0.50 % against a 5 % nominal.

**2. E18 measured false-alarm rate and detection on different windows.** FAR over ticks 0-399,
detection over ticks 200-399. On the matched window P1 has 4/30 runs in band and a median run FAR of
0.00 %, not the 21/30 and 4.88 % E18 reported. **E18's "P1 VALID" does not survive.**

## Read in this order

1. `audit_of_E18.md` - the E18 audit, including the bimodality mechanism (section 10)
2. `hypothesis.md` - H1, H0, and the failure mode predicted in advance
3. `preregistration.md` - frozen criterion, window justification, integrity requirements
4. `implementation_plan.md`
5. `calibration_protocol.md` - the complete mathematical definition
6. `frozen_parameters.md` - calibration version 2
7. `integrity_checks.md`
8. `analysis.md`
9. `limitations.md`
10. `final_decision.md` - **the decision and the minimum required repair**

## Next step

**E18-R2 - matched-window pooled calibration.** Calibrate on ticks 200-399 of the existing clean
calibration runs, pooled as in E18. Takes the large sample from E18 and the window discipline from
R1; it is the only untested combination of the two, and costs about four minutes of compute.
