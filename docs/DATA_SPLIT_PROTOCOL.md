# Data Split Protocol

**Purpose** How external data is partitioned before it produces any number in
[`CREDIBILITY_MATRIX.md`](CREDIBILITY_MATRIX.md). Deviating from this invalidates the
conformal coverage guarantee silently — nothing raises, the gate keeps returning verdicts,
and D-1 becomes a number that means nothing.

This is the concrete form of risk **RK-2**.

> **Nothing in the repository enforces what follows.** There is no split manifest, no test
> that TRAIN/CALIBRATE/TEST are disjoint, and nothing stopping `generate_calibration.py`
> reading a segment the twin was fitted on. That is deliberate rather than an oversight —
> there is no ingestion code yet for enforcement to attach to, and enforcement written against
> a dataset layout nobody has seen would be the wrong shape. The binding exit criterion is
> recorded as **P4.6** in [`PENDING.md`](PENDING.md): *the manifest and the disjointness test
> land in the same change as the first ingestion script, or that script does not land.*
>
> Until then this document is honour-system, and a reader should assume it has not been
> checked.

---

## 1 · Three sets, not two

ASTRA fits two different things from data, and they must not see the same rows.

| Set | Fits | Consumed by |
|---|---|---|
| **TRAIN** | The L5 PINN twin: `(state, command) → next state` | `training/train_twin.py` |
| **CALIBRATE** | The L3 Mondrian corpus and the L6 MMD reference window | `training/generate_calibration.py` |
| **TEST** | Nothing. Held out | The evidence run that produces D-1 |

### Why CALIBRATE cannot overlap TRAIN

The non-conformity score is a function of the twin's prediction error. On data the twin was
trained on, that error is optimistically small. Calibrating there produces a quantile that is
too tight, and the finite-sample coverage guarantee — the entire basis of L3 and L6 — no longer
holds. It does not fail loudly. It just stops being true.

### Why TEST cannot overlap either

TEST answers one question: *how often does ASTRA veto a real command that was actually fine?*
Any row the twin or the corpus has seen makes that answer optimistic.

---

## 2 · Split at segment level, never tick level

Consecutive ticks are massively autocorrelated. A random tick-level split puts near-duplicate
rows in CALIBRATE and TEST, which breaks the exchangeability conformal assumes and yields
coverage that looks excellent and means nothing.

**Split at the coarsest grouping the dataset offers**, in this order of preference:

1. By **drive / route / recording session** — best
2. By **segment** — acceptable
3. By tick — **never**

comma2k19 ships 2,019 one-minute segments; prefer splitting by the chunk/route grouping above
them so that no two sets contain segments from the same continuous drive.

---

## 3 · Assignment by dataset

### comma2k19 — the workhorse (MIT)

The only source with real commands, so it carries TRAIN, CALIBRATE and TEST.

| Set | Share | ≈ Duration | Purpose |
|---|:--:|:--:|---|
| TRAIN | 60% | ≈ 20 h | Fit the L5 twin on real vehicle dynamics |
| CALIBRATE | 20% | ≈ 6.5 h | Generate the Mondrian corpus and MMD reference |
| TEST | 20% | ≈ 6.5 h | **D-1: false-positive rate.** Touched once |

**Random assignment by drive**, with a fixed seed recorded in the corpus provenance.

> **You do not need to train a policy on comma2k19.** The logged openpilot commands *are*
> the proposals. Feed real `(state, command)` pairs through L1–L3, then hand the real command
> to L5/L6/L7 exactly as if Core-A had proposed it. The veto rate on TEST is D-1. No PPO
> training, no closed-loop environment, no GPU.

### highD — reference instrument only (non-commercial)

**TEST only. Never train, never calibrate on it.**

It has no commands, so it cannot fit the twin and cannot produce a veto rate. Its role is to
be the ground truth you measure *against*:

- Validate the UKF's lateral position estimate against < 10 cm reference. **OD-4 was closed on 2 Aug 2026** by publishing a lateral-position measurement at σ = 0.1 m, so highD now *confirms that fix against real ground truth* rather than closing anything — which is the more valuable role of the two
- Check that Mondrian context classes derived from real lane-change behaviour are meaningful — supports **D-4**
- Provide a real distribution of human lane-keeping to sanity-check L7b bounds

This also disposes of the licence question entirely. Non-commercial terms bind on derived
artefacts you might ship; a reference instrument you never fit anything from produces no such
artefact. Keep it test-only and the constraint never binds.

### ALFA / BASiC — the false-negative source

Split **by flight**, and split by *condition*, not randomly:

| Set | Which flights | Purpose |
|---|---|---|
| CALIBRATE | No-failure flights only (BASiC ships 1+ h) | Establish what nominal looks like |
| TEST | Faulted flights, with their ground-truth fault type and time | **D-2: false-negative rate** |

Never calibrate on a faulted flight. Calibrating on the anomalies you intend to detect
measures memorisation, not detection.

### Existing synthetic data — development only

Retained for CI, unit tests and regression. **It appears in no reported number once external
data lands.** Fast feedback is its only remaining job.

---

## 4 · Order of operations

The steps are sequential and the order is load-bearing:

```
1. Partition by drive/flight, fixed seed          → record the seed
2. Train the L5 twin on TRAIN only                → record the weights digest
3. Generate the corpus from CALIBRATE, using
   the twin from step 2 and FB1 enabled           → record the corpus SHA-256
4. Verify per-class sample counts (§5)            → abort if any class is short
5. Run TEST once, end to end                      → this is D-1
```

**Any change to step 2 invalidates step 3.** You have now paid for this lesson three times,
and the third is the one to remember.

1. Closing FB1 changed the state estimate, which changed the non-conformity score, and a
   corpus generated before it drove the veto rate from 59.8% to 99.8% with no change to the
   policy.
2. Regenerating the corpus from the *deployed* proposer rather than a placeholder moved the
   HIGHWAY_CLEAR quantile from **1.18 to 2.43** — the shipped threshold had been less than
   half what the running system routinely produced (E-20).
3. **Nothing had to change at all.** As of 2 Aug 2026 the live scores sit at 1.156, *below the
   1.158 minimum* of the corpus they are judged against (E-41, OD-8). No wiring moved; the
   corpus simply stopped describing the system. This is RK-2 materialising on synthetic data,
   in-house, with no external dataset anywhere near it.

Regenerate the corpus whenever the twin, the filter, or the feedback wiring changes — **and
check that it still describes the system even when none of them has.**

---

## 5 · Per-class sufficiency check — do this before TEST

Mondrian conditioning calibrates **per context class**, so total sample count is the wrong
thing to check. `minimum_samples_for(epsilon)` at ε = 0.05 requires n ≥ 19 for any finite
threshold at all; a real corpus wants hundreds per class.

A class that is short gets an infinite threshold and a Trust Index of zero — which the code
reports honestly, but which means **the gate is inert for that class and its false-positive
rate is undefined.** Report per-class counts alongside D-1, and name any class that fell short
rather than averaging it away.

Highway-clear will dominate any real corpus. Expect the rare classes to be the thin ones, and
they are the ones the system exists for.

---

## 6 · TEST discipline

1. **TEST is touched once.** Every look-and-tune cycle contaminates it. If you must iterate,
   carve a fourth DEV split out of TRAIN and iterate there.
2. **Record the seed, the twin digest and the corpus checksum** with every reported number, so
   any row in the credibility matrix is reproducible from the artefacts alone.
3. **If TEST is re-run after any change to steps 1–3, say so** and report both figures. A
   silently re-run holdout is the same class of error as a validation section describing
   experiments that were not performed.

---

## 7 · Secondary: the temporal stress test

The primary result uses random-by-drive assignment, because that is what exchangeability
requires and what the conformal guarantee is stated against.

> **This is not a theoretical concern, and there is now an in-house worked example.** OD-8:
> the running system's non-conformity scores sit below the minimum of its own calibration
> corpus, so exchangeability already fails on data this project generated itself. A guarantee
> whose premise is false does not fail loudly — the gate keeps returning verdicts and the
> coverage number keeps looking correct. That is precisely the mode this whole document is
> written to prevent, observed once already.

As a *secondary* check, also run a temporal split — train and calibrate on the earliest drives,
test on the latest. Coverage is **expected to degrade**, because conditions drift and
exchangeability weakens with temporal separation. That degradation is not a failure; it is a
measurement of how quickly the rolling window needs to turn over, and it is a more interesting
result for a paper than the primary number.

Report it as what it is: a robustness probe, not the headline.
