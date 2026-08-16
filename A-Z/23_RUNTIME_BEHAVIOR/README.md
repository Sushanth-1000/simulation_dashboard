# 23 · Runtime Behaviour

What actually happens when the thing is running: order, rates, timing,
synchronisation, feedback, and what happens when something fails mid-tick.

---

## 23.1 · The two timing domains

**[FACT** — SI-8, `TimingDomain`.**]**

| Domain | Rate | Contains | Blocking? |
|---|---|---|---|
| **Hot path** | **20 Hz** — every 50 ms | L1 … L9 | **Never.** Budget target 10 ms (A-2) |
| **Cold path** | Asynchronous, slower | RCM's knowledge-base search, profile evaluation | May take as long as it needs |

**Why the separation exists.** RCM must search a calibration knowledge base to
decide whether a better profile exists. That search is expensive and unbounded.
Putting it on the hot path would make the tick period depend on the size of the
knowledge base.

**And the enforcement is social as much as technical:** any component added later
**must declare which domain it runs in**, and *the declaration is what makes an
accidental blocking call on the hot path reviewable*.

**[INTERPRETATION]** A declaration is not a guarantee. A cold-path component that
blocks would still block. What the declaration buys is that the mistake is
**visible in review** rather than only in a latency histogram.

---

## 23.2 · Initialisation — t < 0

```
1  Load configuration        every A-4 threshold present, or STARTUP FAILS
2  Verify the config schema  version mismatch → refuse
3  Compute the config hash   stamped into every audit record
4  Load the twin checkpoint
5  Load the calibration corpus
6  Build the RunId           the ONE random value in the system (ADR-0009)
7  Open the audit sink       append-only JSONL
8  assemble_pipeline(...)    construct all nine layers
9  Seed the clock            ManualClock or a real source (ADR-0010)
```

**Three properties of startup worth knowing.**

**A missing safety threshold is a startup failure**, not a warning (A-4). So is a
**typo** in a threshold name — `extra="forbid"` means an unrecognised key is an
error rather than a silently ignored line.

**Exactly one random value exists in the whole system** — the `RunId` (ADR-0009).
Everything else is deterministic from seeds, which is what makes byte-comparable
replay possible (A-5).

**The clock is injected.** No component calls `time.now()`. A replay run supplies
a `ManualClock` and gets identical timestamps.

---

## 23.3 · One tick, with timings

**[FACT]** for the order; **[UNVERIFIED]** for the per-stage millisecond figures —
the project has a 10 ms *budget* (A-2) and the per-stage split has not been
measured. The relative ordering is what matters below.

```
t = 0 ms     ── TICK OPENS ────────────────────────────────────────────
             clock advances; TickId increments

t → L1       sensors publish; freshness judged per modality
             ┌── health map FORKS here ──► L8 (bypasses everything)
             │
t → L2       median-fuse 3 position channels          (ADR-0033)
             UKF predict:  11 sigma points → fx → +Q
             UKF update:   sigma points → hx → S, K
             produces: mean, covariance, innovation

t → L3       classify context; compute Trust Index

═══════════  SI-5 boundary — nothing crosses back ══════════════════════

t → L4       proposer reads state + trust ONLY
             produces: ProposedCommand

t → L5       twin predicts, using this context's output head

t → gates    L6, L7a, L7b judge in parallel on the same inputs
             merge fail-closed

t → L8       OOD counter, integrity counter, ceiling, decay,
             capabilities withdrawn → posture

t → L9       apply speed cap through the projector
             construct IssuedCommand   ← the only place this is legal
             OR run the fallback controller if refused

t → audit    one DecisionRecord, hash-chained to the previous

t → FB1      issued command → L2, for the NEXT prediction

t = 50 ms    ── NEXT TICK ─────────────────────────────────────────────
```

### Which stages are on the critical path

Everything above is sequential **except the three gates**, which are independent
of one another and depend only on `(proposal, prediction, state)`.

**The slow filter does not run every tick.** At `slow_rate_hz` = 1.0 against
`fast_rate_hz` = 20.0, it runs **once every 20 ticks**.

---

## 23.4 · The feedback loops

Four were specified. **Two are wired; two were measured and refused.**

| Loop | Does | Status |
|---|---|---|
| **FB1** | Issued command → L2's *prediction* step | **Wired** |
| **FB2** | Twin adaptation | **REFUSED** — `E-39` |
| **FB3** | Requantilise the corpus online | **REFUSED** — `E-40` |
| **FB4** | Plant sync | Wired |

### FB1 — and the distinction that makes it safe

The issued command is a **prediction input**, not a state assignment.

> Writing the commanded value into `x` would make the estimate agree with the
> command **by construction**, which destroys the innovation the whole system
> uses to detect that the vehicle is not doing what it was told — **the filter
> would report perfect health precisely when the actuator had failed.**

As a control input, the covariance still grows around it and a measurement can
still overrule it.

**[INTERPRETATION]** This is the single clearest example in the codebase of a
one-word difference — *input* versus *assignment* — deciding whether a mechanism
is a safety feature or a blindfold.

### Why FB2 and FB3 were refused

**FB2** would train the twin on the proposer's own commands — the twin exists to
be *independent* of the proposer. Measured in shadow: the score fell **40%** in a
context where nothing changed.

**FB3** would requantilise on scores the system generates itself. Its veto rate
converges to `significance_epsilon` **exactly** — because ε of any distribution
lies above its own 1−ε quantile. **The gate stops being a detector and becomes a
fixed-rate sampler.**

**Neither was ever wired**, and both measurements are kept as the evidence *for*
not wiring them.

---

## 23.5 · Failure handling at runtime

| Failure | Response |
|---|---|
| Covariance loses positive-definiteness | `LinAlgError` → `SafetyPathError` → **VETO** |
| Extractor produces no measurement | Filter **predicts without correcting**; covariance grows; L6 becomes more permissive. *Correct behaviour* |
| A gate raises | Its verdict is absent; merge sees a short list — and an empty list merges to **VETO** |
| A proposal is refused | L9's fallback issues instead. **Caveat: it reads the same estimate** |
| A sensor goes quiet | `ABSENT` → integrity counter climbs → posture escalates, **with no gate involved** |
| A sensor lies fluently | `HEALTHY`. Caught only by redundancy, and only if it disagrees with the median |
| HALT is reached | **Terminal.** Only an explicit external `reset` leaves it |

**The governing rule:** an error becomes a **refusal**, never a repair.

---

## 23.6 · Escalation timing — worked

**[FACT** — `E-87`, `E-88`, 11 August 2026.**]** IMU dropout, thresholds 5 / 15 / 40:

```
tick +0    fault opens; stream goes ABSENT
tick +5    integrity counter = 5   → DEGRADED   (speed cap applies)
tick +15   integrity counter = 15  → LIMP       (tighter cap)
tick +40   integrity counter = 40  → HALT       (terminal)
tick +73   the vehicle would have left its corridor
```

**1.65 seconds of margin.** Deviation **4.199 m → 0.167 m**.

**[FACT** — re-measured 16 August 2026, `python -m benchmarks.fault_study`.**]**
The same fault, on the system as it stands today:

```
tick +0    fault opens; IMU stream goes DEGRADED
tick +5    integrity counter = 5   → DEGRADED
tick +15   integrity counter = 15  → LIMP       (deepest posture reached)
tick +40   integrity counter = 40  → LIMP       (ceiling holds it)
           ... the vehicle never leaves the corridor at all
```

Final deviation **0.062 m**; 195 of 400 ticks outside NOMINAL; peak counter **40**.

**Two changes, both from ADRs landed on 15 August, neither of which recorded that
it had moved this number.**

- **ADR-0033** made three-channel sensing the *driven* path, so one frozen channel
  is outvoted and the departure never develops.
- **ADR-0030**'s health-level ceiling maps `DEGRADED → LIMP`. The counter still
  reaches its HALT threshold; the ceiling refuses the escalation. **HALT is now
  unreachable for this fault.**

**[INTERPRETATION]** Read the second change carefully before calling it an
improvement. The vehicle is safer *because of redundancy*, and separately the
fail-safe's deepest response to a dark IMU has been **capped one posture short of
where it used to go**. That is defensible — a stream that is stale is not a stream
that is gone — but it is a weakening of the response, and it arrived as a side
effect of a different decision.

And recovery, from the other direction: the longest walk back to NOMINAL is **91
consecutive clean ticks — 4.6 s**. Automatic *and* bounded.

---

## 23.7 · Determinism and replay

Three properties make a run byte-reproducible:

1. **One random value** — the `RunId` (ADR-0009)
2. **The injected clock** (ADR-0010)
3. **Fixed summation order** in the cross-covariance loop — *"a matrix product
   sums in a different order and lands a nanosecond of state away"*

**Why it matters.** The evidence pack's claims must be re-derivable. And veto
counts are **threshold crossings**, which *"can flip on the last bit"* — so
bit-comparability is not fastidiousness, it is what makes a veto count a stable
number.

**[FACT** — a measured limit.**]** Bit-identity with FilterPy was **not**
achieved and is not claimed: SciPy factors covariance with an upper-triangular
Cholesky and NumPy with a lower-triangular one, and the two LAPACK paths round
differently. Over 2,000 steps the state agrees to **6e-10** and the covariance to
**1e-14**. What was checked instead is whether the difference **changes a
decision** — measured as no (`E-68`).

---

## 23.8 · Computational load

| Component | Cost | Note |
|---|---|---|
| UKF predict + update | `O(n³)`, n=5 | Two Choleskys per tick since ADR-0032 |
| Median fusion | `O(1)` | Three values |
| Twin forward pass | One small network | Per-context head |
| L6 | `O(log n)` | Quantile lookup on a sorted corpus |
| L7a / L7b | `O(1)` | Arithmetic bounds |
| L8 | `O(m)`, m = modalities | Two counters, a ceiling, a decay per modality |
| **Cold path** | **Unbounded** | Off the tick entirely |

**[UNVERIFIED]** No end-to-end latency measurement appears in the evidence pack.
A-2 asserts 10 ms at 20 Hz is *achievable in CPython*, and A-2 is an
**assumption**, not a measurement. **[OPEN]** — the real per-tick cost is unknown.

---

## 23.9 · You should know this before moving on

**The runtime shape**

- **20 Hz hot path**, cold path asynchronous, declared per component
- **Slow filter every 20th tick**
- **The health map forks before L2** — the only signal upstream of the common cause
- **FB1 wired as a prediction input**; **FB2 and FB3 measured and refused**
- Errors become **refusals**, never repairs
- **HALT is terminal**; recovery elsewhere is automatic and bounded at 4.6 s

**Questions you should be able to answer**

1. Why must RCM's knowledge-base search be off the hot path?
2. Why is FB1 a prediction input rather than a state assignment? What breaks
   otherwise?
3. Why does FB3's veto rate converge to exactly `significance_epsilon`?
4. Why is a tick that produces no measurement handled by *widening* the
   covariance rather than by refusing?
5. Why does bit-comparable replay matter for a *veto count* specifically?

**Misconception to avoid**

> *"The 10 ms budget has been verified."*
>
> It is **A-2 — an assumption**, listed as such. No end-to-end latency
> measurement appears in the evidence pack. The architecture is *shaped* for the
> budget; whether it meets it is **[OPEN]**.

---

**Next:** pass 5 — `11_UNCERTAINTY_AND_ERROR`, `12_SAFETY_AND_RELIABILITY`,
`13_TESTING_AND_VALIDATION`, `14_SIMULATION`.
