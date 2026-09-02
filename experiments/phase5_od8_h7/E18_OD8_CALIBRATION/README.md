# E18 - OD-8 Calibration

**Status: PARTIAL** -- a valid monitor is established for P1 and P3; P2 fails the drift criterion.

| | |
|---|---|
| Question | Can L6 be calibrated to a controlled clean false-alarm rate across policies? |
| Verdict | **PARTIAL** (C1 pass, C2 pass, C3 fail on P2) |
| Frozen thresholds | P1 **3.7095** / P2 **5.9024** / P3 **3.4000** at eps = 0.05 |
| Gate consequence | E19 may proceed **on P1 and P3 only** |

## Read in this order

1. `hypothesis.md` -- question, H, H0, falsification criteria
2. `protocol.md` -- the full pre-registration, written before any value was computed
3. `configuration.md` -- **the frozen thresholds**, and why global calibration was rejected
4. `integrity_checks.md` -- seven checks and their outcomes
5. `analysis.md` -- observed / inferred / hypothesised, kept separate
6. `limitations.md`
7. `final_decision.md`

## Headline

OD-8 was a **calibration-set provenance** failure, not a bad threshold value. A single global
threshold reproduces the original defect exactly (0 % false alarms on P1/P3, 11 % on P2).
Policy-conditional calibration puts all three policies inside the target band and restores
exchangeability. P2 then fails a separate criterion: its score drifts within a run by more than its
between-run spread.
