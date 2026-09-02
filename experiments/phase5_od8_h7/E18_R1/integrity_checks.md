# E18-R1 - Integrity Checks

Standing rule: a result cannot be trusted unless the faulted arm differs from the clean arm **at the
delivered signal**.

## Injection integrity

**Not applicable to the primary experiment.** R1's primary criterion uses clean runs only. The
faulted evaluation was deliberately not run (`final_decision.md` section 7), so no injection claim is
made and none is needed.

## Calibration integrity

| check | method | result |
|---|---|---|
| Calibration contains only clean data | window is ticks 1-200; injection begins at tick 200 | **PASS** by construction |
| No fault-test contamination | primary experiment runs no faulted trials | **PASS** by construction |
| No future-data leakage | calibration window strictly precedes evaluation window | **PASS** |
| No cross-run leakage | each threshold uses only its own run's prefix | **PASS** |
| Threshold frozen before evaluation | `q_r` computed from `W_r`, then applied to `E_r` | **PASS** |
| No outcome-driven parameter choice | one window definition, fixed in advance, no search | **PASS** |

## Run integrity

| check | result |
|---|---|
| Expected run count | **PASS** - 30 per policy, 60 total |
| Seed identity preserved | **PASS** - `20261001 + i`, recorded per row in `run_manifest.csv` |
| Policy identity preserved | **PASS** |
| No duplicate runs | **PASS** - seed x policy unique |
| No missing runs | **PASS** |
| No stale or non-finite samples | **PASS** - all runs report finite calibration and evaluation samples |

## Statistical integrity

| check | result |
|---|---|
| Run-level FAR computed per run | **PASS** - `alarm_count / evaluation_n`, one value per run |
| Pooled tick-level FAR supplementary only | **PASS** - the criterion is evaluated at the run level |
| Confidence intervals at the correct unit | **PASS** - run-level counts, n = 30 |
| No pseudo-replication | **PASS** - 400 autocorrelated ticks are never treated as 400 samples |

## Defect found in E18 by this audit

**E18 computed false-alarm rate over ticks 0-399 and detection over ticks 200-399.** Both quantities
were correct on their own terms; neither was comparable to the other. `E18/protocol.md` section J did
not name a tick range, so nothing forced them to agree.

This is not an R1 integrity failure - it is an E18 defect that R1's window discipline exposed. It is
recorded in `final_decision.md` section 1 and revises E18's P1 verdict.

**Corrective rule for future experiments:** a false-alarm rate and a detection rate quoted together
must be computed over the same tick range, and the range must be named in the pre-registration.
