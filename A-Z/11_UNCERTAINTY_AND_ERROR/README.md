# 11 · Uncertainty and Error Propagation

Where uncertainty comes from, how it is represented, how it moves, how it changes
decisions — and how false positives and false negatives actually arise.

---

## 11.1 · The four sources

| # | Source | Represented as | Where it enters |
|---|---|---|---|
| 1 | **Sensor noise** | σ per channel — IMU 0.10, GPS 0.20, LIDAR 0.06 m | `R` in the update |
| 2 | **Model error** | `Q`, the process noise | Added in every predict |
| 3 | **Twin error** | Not represented as a distribution at all | Enters as *departure* in L6's score |
| 4 | **Calibration error** | The corpus's finite sample | The quantile |

**Source 3 is worth pausing on.** The twin produces a **point prediction** with no
uncertainty attached. So when L6 computes `departure = |proposal − prediction|`,
a large departure may mean *the proposal is unusual* **or** *the twin is wrong* —
and the score cannot distinguish them.

**[INTERPRETATION]** This is a real structural limitation and it is under-stated
in the project's own documents. It matters most against CARLA, where prediction
P2 says the twin will be badly wrong: every twin error will present as a
proposer anomaly.

---

## 11.2 · How uncertainty moves through a tick

```
        sensor σ           ──►  R
                                 │
   ┌─────────────────────────────▼──────────────────────────┐
   │  PREDICT   P ← F P Fᵀ + Q          uncertainty GROWS   │
   │  UPDATE    P ← (I − K H) P         uncertainty SHRINKS │
   └───────────────────────┬────────────────────────────────┘
                           │  P[a_lat]
                           ▼
                    sigma = √P[a_lat]
                           │
                           ▼
                score = departure / sigma      ← the decision
```

**The chain to remember:** *sensor noise → covariance → σ → the denominator of
the gate's score → whether a command is vetoed.*

Uncertainty is not decoration here. **It is a term in the decision.**

---

## 11.3 · Three regimes, and what each does to the gate

| Regime | `P` | `σ` | Score | Gate behaviour |
|---|---|---|---|---|
| **Measurements arriving, consistent** | Shrinks | Small | Large | **Strict** |
| **No measurement this tick** | Grows unopposed | Large | Small | **Permissive** |
| **A self-consistent lie** | **Shrinks** | Small | Large | **Strict — about a wrong estimate** |

### Regime 2 is correct behaviour, deliberately

A tick where every sensor was absent widens `P`, which makes L6 more permissive.
That is the right response: *the statistical gate automatically becomes more
permissive precisely when the state is less certain*, and the project notes this
is *"the mechanism the paper describes, arising here rather than being
special-cased."*

### Regime 3 is OD-9, expressed as uncertainty

A frozen reading is **maximally self-consistent**. The innovation is small, so
the filter treats the reading as informative and `P` **shrinks**.

> **Confidence rises while correctness falls.** The two move in opposite
> directions, and nothing in the pipeline can see it, because every quantity
> downstream is computed from the same measurement.

Measured: the error is pushed into an unobserved state — true heading
**0.0686 rad**, estimate **0.0017 rad** (`E-58`).

---

## 11.4 · How a false negative happens — mechanically

A **false negative** is a bad command that is issued. Here is the actual causal
chain, from `E-46`/`E-48`:

```
1  IMU freezes; readings stay fresh and well-formed
2  L1 judges freshness only        → HEALTHY.        No signal.
3  L2 fuses a self-consistent reading → P SHRINKS.   Confidence rises.
4  Error is pushed into heading, which nothing observes.
5  L3 sees a small innovation and tight P → HIGH TRUST.
6  L4 reads "we are centred" and proposes to stay there
      → it is correcting toward a lie, so each command makes it worse
7  L5 predicts from the same estimate → the twin AGREES
8  L6  departure small, sigma small → PASS
   L7a corridor bound 0.023 m       → PASS
   L7b jerk fine, twin agrees       → PASS
9  merge → PASS → issued
```

**Nine steps, no bug.** Every component behaved correctly given its inputs. The
false negative arises from a **structural** property — a shared input — not from
any component being wrong.

**And step 8 is the load-bearing one:** three gates, one estimate. That is why
`E-107`'s conclusion is *architectural* rather than about detector quality.

---

## 11.5 · How a false positive happens

Two mechanisms, both measured.

### Mechanism 1 — the reference is wrong

If the corpus does not describe the running system, the threshold is a number
computed from the wrong sample.

**Measured:** closing FB1 changed the estimate, which changed the score, and a
corpus built before it drove the veto rate **59.8% → 99.8%** with no policy
change. Almost every one of those vetoes was a false positive.

### Mechanism 2 — a bound that latches

**Measured (ADR-0017):** a vehicle 1 m off centre needs ~21 ticks to correct, and
every one of them was vetoed on jerk. The gate was correct on each individual
tick and **collectively made the vehicle undriveable** — a false positive not
about any single command but about the *sequence*.

**[INTERPRETATION]** Mechanism 2 is the more interesting one, because no
per-tick check can detect it. It is only visible over a window, which is why the
project's long soaks find things unit tests cannot.

---

## 11.6 · The current calibration state — and why it matters here

**[FACT** — `E-159`.**]**

```
URBAN_CLEAR   corpus 3.8758 – 5.4312     live 3.3648 – 3.4083     ZERO OVERLAP
```

**What this does to the error rates:**

- **False positives: ~zero.** Live scores are entirely *below* the threshold, so
  the gate essentially never fires.
- **False negatives: unbounded.** A gate that cannot fire cannot catch anything.
- **And it looks healthy.** The veto rate is near zero, which reads as *"the
  proposals are good"*.

> The veto rate is **measuring the mismatch, not the discrimination.** That is
> how OD-8 survived from 6 to 15 August unnoticed.

**[FACT** — `E-162`, `E-164`**]** The gate census confirms it from the other
side: `STATISTICAL` **VETO 0** across 2,800 ticks of a suite built to break it,
with **ABSTAIN 0** — it is judging every tick and finding nothing.

---

## 11.7 · Uncertainty the system does **not** represent

Worth listing, because absence is easy to miss:

| Not represented | Consequence |
|---|---|
| **Twin prediction uncertainty** | A twin error is indistinguishable from a proposer anomaly |
| **Corpus finite-sample uncertainty** | The quantile is treated as exact. Partly mitigated: `⌈(n+1)(1−ε)⌉` and the infinite-threshold rule |
| **Context-classification uncertainty** | A class is assigned, never a distribution over classes. A wet-night tick is confidently `HIGHWAY_CLEAR` |
| **Correlation between sensor failures** | The redundancy argument assumes independence; `T1'` is what happens when that is false |
| **Model-form uncertainty** | *"Is the bicycle model right for this platform?"* has no runtime representation. OD-11 wall 3 |

**[OPEN]** None of these has been quantified. They are named here because a
reader should know what the covariance matrix does **not** cover.

---

## 11.8 · You should know this before moving on

**The chain**

`sensor σ → P → √P → the denominator of the score → veto or not`

**The three regimes**

| | `P` | Gate |
|---|---|---|
| Consistent measurements | shrinks | strict |
| No measurement | grows | permissive — **correct** |
| Self-consistent lie | shrinks | strict about a **wrong estimate** |

**Questions you should be able to answer**

1. Walk the nine steps of the OD-9 false negative. At which step could it first
   have been caught, and by what?
2. Why is a *widening* covariance the right response to a missing measurement?
3. Give two distinct mechanisms for a false positive — one per-tick, one only
   visible over a window.
4. Why does the current zero veto rate tell you nothing good?
5. Name three kinds of uncertainty the system does not represent at all.

**Misconception to avoid**

> *"A confident estimate is a good estimate."*
>
> In this system confidence is computed from *self-consistency*, and a frozen
> sensor is perfectly self-consistent. The most dangerous state the filter can be
> in is **confidently wrong**, and by construction it cannot report it.

---

**Next:** `12_SAFETY_AND_RELIABILITY/`.
