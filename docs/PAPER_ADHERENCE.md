# The paper against the implementation

**Checked** 10 August 2026, against `survey paper/astra survey (2).pdf`
**Method** Every structural and quantitative claim in the paper's abstract,
contributions list, Figure 1 and §4 traced to the code that implements it, or to
the record of why it does not exist.

**Why this document.** A survey paper and its prototype drift apart silently, and
the direction of the drift is always the same: the paper keeps the claim the
implementation dropped. Two of the divergences below are in the abstract's
numbered contributions, and one of them has a configuration slot in the shipped
schema that nothing reads — which is precisely how a reviewer finds it.

---

## Summary

| | Claim | Status |
|:--:|---|---|
| **1** | Nine-layer closed-loop governance pipeline | **Holds** |
| **2** | Dual-rate UKF feeding a Conformal Trust Module | **Holds** |
| **3** | Trust Index `TI ∈ [0,1]`, graduated rather than binary | **Holds**, and measured |
| **4** | **EnbPI** (Ensemble Batch Prediction Intervals) | **NOT IMPLEMENTED** |
| **5** | Mondrian conditioning | **Holds** |
| **6** | Three independent safety gates | **Structurally holds; independence is measurably false** |
| **7** | Four closed feedback loops FB1–FB4 | **Half holds** — two wired, two measured and refused |
| **8** | EWC-anchored PINN adaptation | **Deleted by ADR-0019** |
| **9** | MPC candidate scoring (paper's Layer 5) | **NOT IMPLEMENTED** |
| **10** | 1.25 µs Core-B intercept at 500 MHz | **Not measured, and cannot be** |
| **11** | ASIL-D(D) for Core-B | **A design target, not an outcome** |
| **12** | CARLA validation drive | **Not run** (P5, hardware-gated) |

Nine of twelve hold or partly hold. The three that do not are **4, 9 and 12**,
and only 4 is stated as a headline contribution.

---

## 1 · What holds

### Nine layers

The paper says nine; `ASTRA_LAYER_COUNT = 9` is asserted against the `LayerId`
enumeration by an architecture test, so the count cannot drift without the build
failing.

### Dual-rate UKF → Conformal Trust Module → Trust Index

Implemented as described. The Trust Index is genuinely graded rather than a
dressed-up flag, which the paper's contribution 1 specifically claims against
prior work: measured at **90 distinct values across 8,001 ticks**, mean 0.960,
p05 0.902, p95 1.000 (E-23). Two earlier iterations produced 2 and 5 distinct
values, and both were defects that were found and fixed — so this claim is one
the project can defend with the history as well as the number.

### Mondrian class-conditional conditioning

Implemented. Per-class calibration windows, class-conditional quantiles, and
`math.inf` returned honestly for a class with too few samples to certify —
which is a VETO rather than an error.

### The one-way channel

The paper's AXI4-Lite bridge argument — *"a compromised Core-A spitting out
adversarial commands"* cannot reach back — is implemented as SI-5 and enforced
as a **type error** rather than a convention.

### CMDP proposer, OOD counter, RCM arbitration, safe exploration

All present: PPO under a PID-Lagrangian constraint; a counter that increments on
VETO and decrements on PASS against θ₁/θ₂/θ₃; RCM as final arbitrator with the
five outcomes including `SAFE_EXPLORATION`.

---

## 2 · The divergences that matter

### 2.1 · EnbPI is in the abstract and not in the code

**The paper's contribution 1** reads: *"a Conformal Trust Module that produces a
continuous Trust Index TI ∈ [0,1] via **Ensemble Batch Prediction Intervals**
and Mondrian conditioning."* §3 cites EnbPI [35] for sequential data, correctly
noting it relaxes the exchangeability assumption standard inductive conformal
prediction depends on.

**There is no EnbPI anywhere in `src/`.** No ensemble, no bootstrap residuals,
no leave-one-out aggregation. The Trust Index is computed from the UKF's
innovation magnitude against Mondrian calibration windows — Mondrian conformal
prediction, which is the second half of the claim without the first.

**And the schema knows.** `astra/config/schema.py` declares:

```python
ensemble_size: PositiveInt = 10
"""Number of bootstrap models in the EnbPI ensemble."""
```

It is set in the test configuration and **read by nothing**. A configuration
slot for a mechanism that was never built is the same defect class as OD-2 and
OD-7 — a declaration no code honours — and it is the one a reviewer will find
first, because it is greppable.

**This is not cosmetic.** EnbPI is cited precisely because the pipeline's data
is sequential and therefore *not exchangeable*, and E-41 measured that
non-exchangeability directly: live non-conformity scores sit at **1.156, below
the corpus minimum of 1.158**. The paper names the right method for a real
problem the implementation has, and then does not use it. **OD-8 is the
measured consequence of the gap contribution 1 claims to have closed.**

**Options, and none is "leave it".**

| | | |
|---|---|---|
| **A** | Implement EnbPI | Honest, and the largest of the three. It is also the one that would close OD-8 |
| **B** | Amend the paper to claim Mondrian ICP, which is what is built | Cheapest and immediately truthful. Weakens contribution 1's novelty |
| **C** | Claim EnbPI as designed-not-implemented, explicitly | Acceptable only if the paper says so in the contributions list, not in a limitations paragraph |

**Delete `ensemble_size` from the schema either way.** A field nothing reads is
a false claim in shipped configuration, and it costs nothing to remove.

### 2.2 · Three gates, and the independence claim

**The paper's contribution 2** is three *independent* gates: statistical,
physical, deterministic. Structurally that holds — three gate objects, three
reason-code vocabularies, three failure modes on paper.

**Independence is measurably false**, and the project found it:

- **OD-9** — every Core-B gate reads L2's fast estimate, and the proposer closes
  its loop on the same estimate. A sensor fault blinds all three simultaneously:
  the vehicle went **4.199 m off a 1.75 m lane** with the corridor bound reading
  **0.023 m** and a verdict trace identical to the clean run's (E-46, E-48).
- **D-10** — disarming L7b takes the veto count to **zero on six of seven
  scenarios**. L6 contributes one veto in 2,800 ticks; L7a contributes none
  (E-59).

The paper should not claim independence as established. It can claim the gates
are *structurally* independent and that a common input has been identified and
measured — which is a stronger and more defensible sentence than the one
currently there.

### 2.3 · FB2 and FB3 are described as running; both are refused

The paper describes four loops carrying real outcomes back, and §4.7 narrates
FB2 (*"EWC kicks in: the output layer…"*) and FB3 (*"each executed outcome
updates…"*) as live mechanisms.

Measured in shadow, both break the gate they feed:

- **FB2** — its only labels are the proposer's own commands. Run against a twin
  nothing reads, the non-conformity score fell **40%** in a context where
  nothing changed, monotonically, still falling (E-39). `twin.py`'s own module
  docstring names this as the way to disarm the statistical gate.
- **FB3** — requantilising on self-generated scores drives the veto rate to
  **5.02%**, which is ε exactly, because ε of any distribution lies above its
  own 1−ε quantile. It fires at ε whether or not anything is wrong (E-40).

**Neither is wired, and that is correct.** But the paper claims four working
loops and the implementation has two, with the other two documented as
architecturally unsafe *as specified in the paper*. That is a finding the paper
should carry — it is more interesting than the original claim.

### 2.4 · EWC was deleted

Figure 1 labels Layer 4 *"PINN Digital Twin + EWC adapter"*, and §4.7 describes
Fisher-anchored weights.

**ADR-0019 removed it.** Measured: EWC was not selective at all — across λ from
0 to 10⁵ the ratio of forgetting to learning was **constant to three significant
figures** (E-32). It could not have been otherwise: FB2 adapts a single 16→2
readout that both contexts use in full, so there is no disjoint subspace for a
Fisher-weighted penalty to protect. It was a speed dial, not a consolidator.

Replaced by **one output head per context**, which makes forgetting structurally
impossible — the test asserts `==`, not a tolerance (E-33).

The residue is real: `ewc_lambda` and `adaptation_buffer` still appear in
comments and configuration. Same class of problem as `ensemble_size`.

### 2.5 · MPC candidate scoring does not exist

Figure 1 shows *"Layer 5: MPC candidate scoring"*. There is no MPC anywhere in
`src/`. The repository records it as assumption **A-9** — *"MPC candidate
scoring fits behind the `StatisticalGate` port"* — i.e. a deferred design
intent, not a built layer.

**Figure 1 shows a layer that has never existed.**

### 2.6 · The numbers the paper puts in a comparison table

The prior-art table lists ASTRA at **1.25 µs WCRT, ASIL D(D)** beside other
systems' figures. §5 says the table includes *"only the ones that reported actual
quantitative latency or overhead numbers on named hardware or RTOS platforms."*

- **1.25 µs** is `N-3`: an analytical AbsInt aiT bound for RTL **that does not
  exist**. Not measurable by a Python prototype and, in the repository's own
  words, *"must never be quoted as measured."*
- **ASIL D(D)** is `N-4`: a design target. An ASIL is the outcome of an assessed
  safety case.

Placing an analytical target in a column of measured numbers, under a heading
that says the column is measured, is the single most likely thing in the paper
to be challenged in review. **Mark both rows explicitly as analytical/target.**

### 2.7 · Layer numbering is internally inconsistent in the paper

Figure 1 labels **three different components "Layer 6"** — Hard Safety Shield,
ICP gate, Physical checker — and places RCM at Layer 7. The body text calls the
PINN twin Layer 4 (§4.5.1), the ICP gate Layer 5 (§4.5.2) and the Hard Safety
Shield Layer 6 (§4.5.3).

The implementation is consistent and is the numbering to adopt:

| | |
|---|---|
| L1 | Shared sensor bus |
| L2 | Dual-rate UKF |
| L3 | Conformal Trust Module |
| L4 | Core-A CMDP proposer |
| L5 | PINN digital twin |
| L6 | ICP statistical gate |
| L7a | Hard Safety Shield · L7b | Physical admissibility |
| L8 | Fail-safe state machine |
| L9 | Runtime Calibration Manager |

---

## 3 · What the implementation has that the paper does not

Worth adding, because these are the strongest results the project owns and none
is in the paper:

- **A fault injector with recorded ground truth**, and the finding that two of
  six injected faults leave the corridor with a verdict trace identical to the
  clean run's (E-46, E-47).
- **The shadow-harness method** — running a mechanism with no authority and
  diffing it against the live system. It caught FB2 and FB3 before either was
  wired, and it is more transferable than any single result.
- **An ablation that does not make a gate optional** (ADR-0021): required
  parameters stay required, an ablation supplies a transparent subtype, and the
  profile is stamped into every decision record.
- **A tamper-evident evidence log** (hash-chained), a threat model, and a
  measured test of NFR5 against a warehouse AGV that found four walls.
- **Thirteen defects, all self-found**, seven of them closed and re-measured.
  The last two — OD-12 and OD-13 — falsified the architecture's own
  distinguishing sentence: bounded safe exploration *halted* on two platforms
  out of five, having first accelerated past the calibrated platform's top
  speed, and both are now closed with the control arm reproducible from one
  command (ADR-0023, E-83 – E-86).

---

## 4 · Recommended edits, in priority order

1. **Fix contribution 1.** Either implement EnbPI or claim Mondrian ICP. Do not
   leave the abstract claiming a method the code does not contain.
2. **Delete `ensemble_size`** from the configuration schema, and the residual
   `ewc_lambda` / `adaptation_buffer` references.
3. **Mark 1.25 µs and ASIL-D(D)** as analytical bound and design target, in the
   table itself.
4. **Remove MPC candidate scoring from Figure 1**, or label it as future work.
5. **Rewrite the independence claim** to "structurally independent, with a
   measured common input (OD-9)".
6. **Correct Figure 1's layer numbering** to L1–L9 as built.
7. **Relabel FB2/FB3** as specified-and-refused, with the measurements.

Items 2, 3, 4 and 6 are corrections. Items 1, 5 and 7 are the paper becoming
more interesting rather than less: a survey whose prototype refuted two of its
own proposed feedback loops, and measured a common-cause failure in its own
three-gate argument, is a better paper than one that claims everything worked.
