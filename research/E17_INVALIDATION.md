# E17 — Invalidation of the Position-Fault Result

**1 September 2026.** Written on audit of the 30-seed sweep, hours after reporting it.

# The headline result of the 30-seed sweep is an artefact. `D_L2a = 0.500` for the two position faults is 0.5 **by construction**, not by measurement.

This is the **third** defect of the same shape in this project. It was found by auditing the result
*because* it looked too clean, not by an independent check.

---

## 1 · What triggered the audit

`D_L2a = 0.500` on 90 of 90 runs, to three decimals, with zero variance. The AUC is folded to
`[0.5, 1.0]`, so 0.5 is the floor. Hitting the floor *exactly* 90 times out of 90 is not what a noisy
statistic does — it is what a **degenerate** one does. That is the same signature as the L1
health-count defect corrected on 31 August.

## 2 · What the audit found

Dumping the per-tick stage values for both arms of one `position_bias` run:

| stage | clean | faulted | identical? |
|---|---|---|:--:|
| L1 (measured y) | mean 0.1579 | mean **1.1579** | no — fault present |
| **L2a (innovation)** | min 0.0189664, max 0.371807 | min 0.0189664, max 0.371807 | **byte-identical** |
| **L2b (estimated y)** | min 0.0472758, max 0.277947 | min 0.0472758, max 0.277947 | **byte-identical** |
| **L3, L6** | — | — | **byte-identical** |

Not "overlapping distributions". **The same 200 values.**

A per-tick probe across the injection boundary:

```
 tick |   measured_y  clean/faulted |  estimated_y  clean/faulted | innovation clean/faulted
  199 |     0.07975       0.07975   |    0.20864       0.20864    |   0.16925      0.16925
  200 |     0.15025       1.15025   |    0.22744       0.22744    |   0.15467      0.15467
  258 |     0.05944       1.05944   |    0.10894       0.10894    |   0.07496      0.07496
```

A **+1.0 m** measurement bias, sustained for 58+ ticks, moves the estimate and the innovation by
**less than 1e-5**.

## 3 · The mechanism

`training/closed_loop.py:742` — `drive_closed_loop` resolves sensing through `_resolved_sensing`,
which returns `RedundantSensing.build(...)` **by default**. Redundancy has been the driven path since
**ADR-0033, 15 August 2026**.

`training/closed_loop.py:365-374` — in `_publish_state`, for every modality in `redundant.sigmas`:

```python
published = {
    **payload,
    "y": float(state[1]) + redundant.draw(modality) + redundant.offset(modality, tick),
}
```

**`y` is rebuilt from `state[1]` — the plant's ground truth — discarding the fault-corrupted value.**
Only `y`. `v` and `a` pass through from `**payload` intact.

`RedundantExtractor.extract_fast` then takes `statistics.median(positions(frame).values())` across
IMU, GPS and LIDAR — all three of which were regenerated from truth. The median is clean.

**The position fault is erased before any consumer sees it.**

Confirmed directly: patching `_Extractor.extract_fast` showed it is called **0 times in 215 ticks** —
the pipeline runs `RedundantExtractor`, not `_Extractor`.

## 4 · Why L1 still showed the fault

`_publish_state` **returns** `payload` — the corrupted dict — while **publishing** the
ground-truth-derived one. My `measured_position_m` instrumentation reads the return value.

**L1 was measuring a corruption that was computed and never delivered to anything.** The
instrumentation I added on 31 August to fix the *first* L1 defect reads the wrong side of the publish
boundary, and reads it only for position.

## 5 · Scope — which results survive

The mechanism predicts exactly the pattern observed across all six faults, which is why I am
confident in it:

| fault | channel | overwritten? | sweep result | status |
|---|---|:--:|---|---|
| `position_bias` | POSITION_Y | **yes** | `D_L2a` 0.500 on 90/90 | **INVALID** |
| `position_drift` | POSITION_Y | **yes** | `D_L2a` 0.500 on 90/90 | **INVALID** |
| `speed_bias` | SPEED | no | `L2a` 0.513, **`L6` 0.963** | **valid** |
| `speed_stuck` | SPEED | no | `L2a` 0.559, `L6` 0.630 | **valid** |
| `lateral_noise` | LATERAL_ACCELERATION | no | `L2a` 0.980 | **valid** |
| `imu_dropout` | frame-level | n/a — publish skipped | non-monotonic | **valid** |

**Only the two POSITION_Y faults are affected — and they are the two the entire C1 claim rested on.**

## 6 · The wider consequence

**`FaultChannel.POSITION_Y` is inert against the driven sensing path, and has been since ADR-0033
(15 August 2026).** `FaultInjector` corrupts the shared pre-publish payload; the redundant path then
regenerates `y` for every channel from ground truth. Nothing lies, so nothing is out-voted.

This is a **fault-injection harness defect, not an ASTRA defect.** Real redundancy would have IMU
lying while GPS and LIDAR stay honest, and the median would correctly out-vote the liar — which is
what ADR-0033 is *for*. The harness cannot construct that situation through `FaultInjector`, because
it injects upstream of the per-channel regeneration. The correct injection point for a position fault
post-ADR-0033 is `redundant.offset(modality, tick)`, which exists and is per-channel.

**Any result depending on a POSITION_Y fault and dated after 15 August 2026 should be treated as
suspect until re-run.** That includes rows in `E17_CORRECTED_DECISION.md` and
`E17_SECOND_POLICY_DECISION.md`, whose "policy-independent to three decimals" finding is now
explained: the values were identical across policies because **no policy ever saw the fault.**

## 7 · Corrected status of C1

# C1: NOT ESTABLISHED

The two faults that supported it never reached the estimator. The four that did reach it do **not**
show clean absorption:

- `speed_bias` — absorbed at L2a, then **recovered at L6 to 0.963–0.994**
- `speed_stuck` — partly recovered at L6; unstable on P2
- `imu_dropout` — non-monotonic, no well-posed `A(f)` on any policy
- `lateral_noise` — persistent, never absorbed

**No fault that actually propagates shows a clean, stable absorption point.** The pre-registered
falsification checks did not fire because they were evaluated on the two faults whose values were
fixed by construction — the checks were sound, the data underneath them was not.

## 8 · What still stands

- **The L6 detection-without-response gap** (`speed_bias`: L2a 0.513 → L6 0.963 → L7 0.500 → L8 0.500).
  On a channel that genuinely propagates. **This is now the strongest finding in the sweep.**
- **The regime Simpson's paradox** — computed on speed faults, unaffected.
- **Fault-propagation heterogeneity** — four valid faults, four distinct behaviours.
- The pre-registration, the 0-failure execution, the seed-level analysis and the statistics code are
  all sound. **The defect is upstream of all of it**, in what the harness delivers to the pipeline.

## 9 · Why the pre-registration did not catch it

It fixed *analysis* choices — stage, faults, cut points, tests, falsification criteria. It contained
**no measurement-validity check**: nothing required the faulted and clean arms to actually differ at
the stage under test before the result was believed.

**Corrective rule for any future sweep:** assert that the faulted arm differs from the clean arm at
the injection point *as delivered to the pipeline*, not as computed by the injector — and fail the
run if it does not. A degenerate cell must be an error, never a result.

## 10 · Next actions

1. **Do not use the position-fault numbers.** They are in `results/E17_30SEED/` and are retained for
   provenance, not for citation.
2. **Fix the L1 statistic** to read the published frame rather than the injector's return value, so
   L1 can never again show a fault the pipeline did not receive.
3. **Re-implement position-fault injection** through `redundant.offset`, which is the per-channel
   path ADR-0033 intends. This makes the interesting experiment possible for the first time: one
   channel lying while two stay honest.
4. **Re-run the sweep** for the position faults only. The four valid faults do not need re-running.
5. Nothing goes into v18 from the position rows.
