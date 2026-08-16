# 19 · Trade-offs

Every design choice bought something and paid for it. This section names the
price, because a benefit with no stated cost is marketing.

---

## 19.1 · The eleven trades that define the system

### T1 · Governance layers vs. latency

**Bought:** every proposal is judged by three gates before it reaches an actuator.

**Paid:** nine layers of work inside a 50 ms tick. Two Cholesky decompositions, a
twin forward pass, three gate evaluations, and a record written — every tick.

**Why the cost exists:** you cannot judge a command without computing what it
would do, and you cannot compute that without a model.

**Measured, 16 August 2026** — and this corrects an earlier draft of this section
that called the cost unmeasured. Six runs of 2,000 assembled ticks each, against
A-2's 10 ms budget:

| | p50 | p99 | max | over budget |
|---|---|---|---|---|
| best run | 2.246 ms | 2.768 ms | 7.676 ms | **0** / 2000 |
| worst run | 2.173 ms | **10.460 ms** | 46.958 ms | **31** / 2000 |

**The median is stable across every run at about 2.2 ms — a fifth of the budget.
The tail is not stable at all.** p99 ranged 2.768–10.460 ms, and the worst run's
p99 was *itself over budget*. Three of six runs produced a maximum above 44 ms.

**Why the cost exists:** you cannot judge a command without computing what it
would do, and you cannot compute that without a model. **Why the *tail* exists is
a different question** — CPython offers no timing guarantee, and a pause of that
shape is a runtime artefact rather than a slow layer.

**[OPEN]** The outlier is not diagnosed, and there is **no deadline monitor**, so
a 10 ms budget is met at the median and violated somewhere between 0 and 31 times
per 2,000 ticks with nothing recording that it happened.

---

### T2 · Availability vs. caution

**Bought:** the vehicle keeps driving outside its certified envelope, under a
narrowed one, instead of halting. *"Others degrade to a halt … ASTRA is built not
to."*

**Paid:** the system continues operating in a state nobody certified.

**Why the cost exists:** halting is itself a hazard. A stopped vehicle in traffic
is not safe, and a defence that fires too often gets disabled by operators.

**Measured on both sides:** OD-12 caught the counter halting a vehicle L9 was
correctly exploring with; ADR-0017 caught a jerk veto latching a correction that
could never complete.

---

### T3 · The correct filter vs. control quality

**Bought:** `S` now carries `H·Q·Hᵀ`, so `fast_innovation` **is** a Mahalanobis
distance and may be compared across a change to `Q`.

**Paid, measured:** final lane deviation **0.0122 m → 0.1218 m**.

**Why the cost exists:** a correctly larger `S` means a smaller Kalman gain, so
the filter trusts each measurement **less** and converges more slowly. The old
behaviour was not better — it was **over-confident**.

**[INTERPRETATION]** A rare, clean example of correctness costing performance.
And ADR-0033 then repaid it with margin — *the honest fix for a filter that must
trust each measurement less is better measurements.*

---

### T4 · Redundancy vs. a new attack surface

**Bought:** a 1 m bias in one channel **never reaches the estimator**
(0.8387 m → 0.0168 m), and the clean run improved six-fold.

**Paid:** threat **T1′** — with `n = 3`, two coordinated liars are tolerated
**zero** times, and it **inverts**: the median becomes the lie, so the monitor
flags the *honest* channel by name.

Plus availability: `tolerated_faults = 0` everywhere, so silencing **one** channel
is a two-second denial of service that did not exist before.

**Why the cost exists:** `n ≥ 3f+1` for Byzantine faults. Three channels buy one
crash fault and **zero** coordinated ones. *The defence created the surface.*

---

### T5 · Mechanical enforcement vs. flexibility

**Bought:** SI-5 and SI-7 violations do not compile or do not construct. Not
conventions anyone can forget.

**Paid:** the architecture is **rigid**. A legitimate future need for the
proposer to see *some* Core-B signal would require an ADR, a type change, and an
amendment to an invariant.

**Why the cost exists:** that rigidity **is** the guarantee. A boundary that can
be crossed when convenient is not a boundary.

---

### T6 · No defaults vs. usability

**Bought:** A-4 — a threshold nobody chose cannot be silently in force. A missing
one is a startup failure; a **typo** in one is too (`extra="forbid"`).

**Paid:** the system will not start without a complete profile, and
`certification.toml` ships with every value **commented out**.

**Why the cost exists:** a default is an unreviewed claim wearing the appearance
of a decision.

---

### T7 · Reproducing a library exactly vs. improving it

**Bought:** the FilterPy removal is a defensible **like-for-like** swap. Any
difference in results is attributable to one change.

**Paid:** `inv(S)` where `solve` would be better conditioned; a summation order
chosen for bit-comparability rather than speed; an associativity kept for its
rounding.

**Why the cost exists:** *"replacing a library and improving its numerics in the
same change makes any difference unattributable to either"* — and veto counts are
threshold crossings that **can flip on the last bit**.

---

### T8 · Evidence completeness vs. volume

**Bought:** every tick produces a record carrying frame health, estimate, trust,
proposal, prediction, **every** gate verdict, posture, arbitration, issued
command and config hash — hash-chained.

**Paid:** volume, and a schema that has changed **ten times**, each change forced
to be a decision by a test that has fired seven times.

**[OPEN]** A-3 assumes JSONL is adequate prototype evidence. Not stress-tested at
certification volumes.

---

### T9 · Synthetic simulation vs. external validity

**Bought:** ground truth to four decimals, faults injectable on purpose, and
runs reproducible from one command — **none of which a real vehicle gives you**.

**Paid:** `[M-ext]: 0 of 30`. The plant, L2's process model, the twin and the
corpus are **the same bicycle model**.

**Why the cost exists:** you cannot inject a sensor fault into a real vehicle at
speed, and you cannot know the truth to four decimals in the field.

---

### T10 · A learned proposer vs. explainability

**Bought:** the thing being governed is genuinely untrusted — a real adversary for
the governance rather than a straw one.

**Paid:** *"why did it propose that?"* is unanswerable in model terms.

**Why the cost exists, and how it was scoped:** A-10 — explainability means
**decision provenance**, not model-internal attribution. The question answered is
*"why did the vehicle do that, on what evidence, under which calibration"*.

**[INTERPRETATION]** Good scoping. Model-internal attribution is contested and
hard to defend to an assessor; a provenance log is a document you can argue about.

---

### T11 · Three gates vs. concentration

**Bought:** three structurally different failure modes.

**Paid, measured:** on the current baseline **one gate does all the work** —
`PHYSICAL` 149 vetoes, the other two **zero**, all 149 on a single reason code.

**Why the cost exists:** partly by design (a bound *should* rarely fire), partly
by defect (L6 cannot fire because of OD-8). For an attacker, *there is one gate to
neutralise, not three.*

---

## 19.2 · The trades that were refused

Worth as much as the ones taken.

| Refused | Would have bought | Rejected because |
|---|---|---|
| **Self-calibration (FB3)** | A corpus that never goes stale | The veto rate converges to ε **regardless of whether anything is wrong** |
| **Twin adaptation (FB2)** | A twin that tracks the platform | Trains the judge on the thing it judges; score fell 40% in an unchanging context |
| **A per-gate override list in config** | Operational flexibility | *"Turns 'which gate may be overruled' into a value a deployment can edit"* |
| **Weighting modalities** | Finer escalation | Nobody can defend *"the camera is worth 0.4 of an IMU"* to an assessor |
| **Deleting bounded exploration** | Strictly safer | Kept on record as the honest fallback — it would delete the distinguishing behaviour |

**[INTERPRETATION]** The pattern: every refusal was of a mechanism that would have
made the system *more adaptive* at the cost of making a guarantee unfalsifiable.

---

## 19.3 · The meta-trade

**Bought:** a project that knows what it does not know. 21 self-found defects, a
column for what each claim does *not* license, retractions in public.

**Paid:** it reads as a project with many problems, because it lists them. A
comparable project with a green suite and no register has the same defects and no
list — and looks better.

**[INTERPRETATION]** This is the trade the whole project's credibility rests on,
and it is the one most likely to be misread by a casual reviewer.

---

## 19.4 · You should know this before moving on

**The four trades with measured costs:** T3 (correctness vs control quality),
T4 (redundancy vs T1′), T7 (fidelity vs numerics), T11 (three gates vs
concentration).

**Questions you should be able to answer**

1. Why did fixing the innovation covariance make lane-keeping *worse*, and why is
   that acceptable?
2. In what sense did adding redundancy make the system *less* safe?
3. Why does `certification.toml` ship with every value commented out?
4. Why is `inv(S)` deliberately kept when `solve` is better?
5. Which refused trade would have made the statistical gate useless, and how?

**Misconception to avoid**

> *"The trade-offs show where the design is weak."*
>
> They show where it is **decided**. A design with no stated trade-offs has not
> been examined — the project's own decision log says an entry with an empty
> *"Gave up"* column is *"a decision that has not been thought about hard
> enough."*

---

**Next:** `20_ALTERNATIVES/`.
