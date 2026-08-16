# 29 · Remaining work

**Engineering** — known how, not yet done. Research questions with no known answer
live in section 27; this section is work you could schedule.

Ordered by what unblocks what, not by size.

---

## 29.1 · Immediate — the CARLA sequence

The whole plan exists to answer one question: **what happens when the plant is
something this project did not write?** Everything in 29.1 is in service of that.

### The order is not negotiable, and each step has a gate

| # | Step | Gate before proceeding |
|---|---|---|
| **0** | **Commit `partition.json`** — the seed and the routes | It is **in git, before a single frame is rendered** |
| **0b** | **Decide `RAIN_NIGHT`** — fix the classifier input or drop the phase, ADR either way | Decided, **not deferred** |
| 1 | Generate TRAIN | The **run guard**: the vehicle actually drove |
| 2 | Fit the twin on TRAIN **only** | — |
| 3 | Generate the corpus from CALIBRATE, twin from step 2, FB1 on | Corpus SHA-256 recorded |
| 4 | **Per-class sufficiency check** | **Abort if any reachable class is short** |
| 5 | Run TEST **once** | Steps 0–4 recorded and unchanged |

**Why step 0 comes before everything.** A split chosen after seeing results is not
a split. Committing it to git first makes the choice **dated and public**, so it
cannot be quietly adjusted when a number disappoints.

**Why step 0b is a blocker rather than a nice-to-have.** `RAIN_NIGHT` is
undecidable from the fast state vector, and the demo has a rain/night phase. A
wet-night tick would classify as `HIGHWAY_CLEAR` and be judged against a
population that does not match it — silently.

**Why "any change to step 2 invalidates step 3" is in bold.** This project has
paid for that lesson **four times**. Most recently on 15 August, when the corrected
innovation covariance put **400 of 400 ticks** into a veto until the corpus was
regenerated — and `make artifacts-check` is what caught it.

### What has to be built

| | Component | Note |
|---|---|---|
| §2.1 | **The adapter**, `src/astra/adapters/carla/` | The first real work item. `carla` must appear nowhere outside `adapters/`, and `lint-imports` enforces it |
| §2.2 | **The driver**, `training/carla_loop.py` | — |
| §2.3 | **A CARLA profile** | No defaults, per A-4 — every threshold chosen deliberately |
| §2.4 | **The run guard** — *"and this one is not optional"* | The same shape as `StationaryVehicleError`: refuse to report from a run where the vehicle did not drive |
| §3.5 | **TEST-once, mechanically** | The manifest digest stamped into an append-only `test-runs.log`; a second evidence run against the same digest **refuses** |

**[INTERPRETATION]** §3.5 is the most interesting item on this list. In a fixed
dataset, re-running TEST leaves a trace; in a simulator it leaves none, which makes
*"we only looked once"* something a reviewer must simply believe. Making the tool
refuse turns re-running TEST into **a deliberate act someone has to perform on
purpose**, rather than a thing that happens because a number looked disappointing
on a Friday.

It is not tamper-proof — anyone can delete the log — and that is explicitly not the
point. It is the same standard `extra="forbid"` sets for configuration and strict
`xfail` sets for known-false claims: **the discipline lives in the tooling rather
than in somebody remembering it.**

### The six predictions, written down first

Falsifiable and dated **before** the measurement, so they cannot be rationalised
after.

| | Prediction | If wrong, that is a finding |
|---|---|---|
| **P1** | OD-8 gets **worse** | Exchangeability is more robust than measured |
| **P2** | The twin is badly wrong — CARLA has suspension, tyre slip, drivetrain lag | The bicycle model is a better approximation than assumed |
| **P3** | **L7a finally fires** — the corridor bound is reachable in real driving | L7a's thresholds are wrong, not its traffic |
| **P4** | **The gate census inverts** — L6 stops being silent and vetoes constantly | The gate is insensitive rather than mis-calibrated |
| **P5** | Wall 3 does not bite — CARLA drives a car | A road vehicle needs more than a bicycle model, which is a real finding |
| **P6** | The fail-safe halts more often — `integrity_tolerated_faults = 0` everywhere | The integrity thresholds transfer, which would be a genuine result |

**P3 and P4 are the ones that matter.** Today two of three gates judge every tick
and never object. If CARLA makes them object, the three-gate independence claim
gets its **first real support**. If it does not, the paper's contribution 2 needs
rewriting further than it already says.

### The exit criteria

1. The adapter satisfies its ports **with no change to `src/astra/`** beyond what
   ADR-0034 made injectable — *and if the core has to change, NFR5 was weaker than
   believed, and that is the finding*
2. `lint-imports` still passes
3. `partition.json` committed before the first frame; TRAIN/CALIBRATE/TEST disjoint
   by route; exactly one TEST entry in the log
4. The seven-phase drive completes without the vehicle stopping — **or it stops and
   the reason is in the audit log, named, with the posture**

**[INTERPRETATION]** Criterion 4 is the right shape for an exit criterion on a
governance system. It does not require success; it requires that failure be
**legible**. A stop with a named reason and a posture is a passing result.

---

## 29.2 · Should have been done already

### Measure latency

A-2 has been an **assumption** for the entire project: 10 ms per tick at 20 Hz in
CPython. No end-to-end figure appears in the evidence pack.

**Why it should have come first.** A timing budget you never measure is a claim you
discover is false at the worst possible moment — and CARLA adds a simulator round
trip to every tick, so the first real measurement will be taken under the worst
conditions the project has yet run.

**Cheap.** This is instrumentation, not research.

### Explain L7a's zero

The deterministic gate does not fire, and unlike L6's silence the cause is **not
understood**. It is either thresholds set too loose or traffic too easy, and those
have opposite fixes.

P3 tests it — but a synthetic answer is available now and would sharpen the
prediction.

### Record which scoring rule produced an archive row

L13: ADR-0032 changed the innovation covariance, which is a **code** change, so
neither the audit schema nor the config hash records it. A reader pooling a pre-
and post-15-August archive has nothing in the record to warn them.

**Small, and it grows expensive with every archive written.** It also becomes a
prerequisite the moment R2 changes the non-conformity denominator.

---

## 29.3 · After CARLA

### Close OD-8 properly

Not *"make the numbers agree"* — that is tuning. Either an adaptive conformal
method (R1), or an honest statement that the guarantee does not hold in a closed
loop and the gate is a heuristic. **Both are acceptable outcomes; pretending is
not.**

### Put uncertainty on the twin

R2. Becomes urgent the moment P2 comes true — and note the coupling: changing the
score's denominator makes **the corpus incomparable across the change**, which is
why the archive needs the scoring-rule field first.

### A second domain, for wall 4

Not a better car. A warehouse AGV, or something equally unlike one. This is what
tests ADR-0002's domain-independence claim, and CARLA cannot do it.

### The false-positive rate

**No false-positive or false-negative rate exists anywhere in this project**, and
none should be quoted until one is measured. This is the number a company will ask
for first, and it requires an external distribution of *normal* driving — which is
precisely what fault injection cannot manufacture.

---

## 29.4 · Not scheduled, and honestly so

| | Why |
|---|---|
| **Hardware** | Out of scope by design, permanently |
| **ISO 26262 artefacts** | Real, large, and premature before `[M-ext]` moves off zero |
| **Wall 3 / bicycle process model** | Deferred by explicit decision — R4, a research fork |
| **FB4** | Unbuilt; no case has been made for it |
| **Process isolation for T4** | A different system, not a change to this one |
| **The paper's six unapplied items** | The paper is not in this repository |

---

## 29.5 · If you could only do three things

**[INTERPRETATION]**

1. **`partition.json`, committed.** Ten minutes. It is the difference between a
   result and a result you can defend, and it **cannot be done later** — its whole
   value is that it precedes the data.
2. **The run guard and TEST-once refusal.** Before the adapter, not after. Every
   retraction this project has made came from a measurement taken in a
   configuration where it was meaningless, and both guards are that lesson applied
   in advance rather than after the third one.
3. **Latency.** The cheapest open question in the project, and the only assumption
   still unmeasured after nine months.

**Note what is not on that list: the adapter.** It is the biggest item and it is
not the most important — because a CARLA result generated without the guards is a
number nobody, including its author, should believe.

---

## 29.6 · You should know this before moving on

**Questions you should be able to answer**

1. Why must `partition.json` be committed before a single frame is rendered?
2. Why is `RAIN_NIGHT` a blocker rather than a limitation to note?
3. What would it mean if P3 turns out to be **wrong**?
4. Why does making TEST-once mechanical matter if the log can be deleted?
5. Why does putting uncertainty on the twin require an archive change first?

**Misconception to avoid**

> *"CARLA will validate the architecture."*
>
> It will produce `[M-ext]` rows against **one simulator, one town, one seed** —
> and the plan names this as its highest-rated risk, rhetorical rather than
> technical. The failure mode is presenting those numbers as validation. The
> mitigation is the discipline that has held all along: every row keeps its
> marker, and `[M-ext]` means *this simulator*.

---

**Next:** `30_MASTER_A_TO_Z_DOCUMENT/` — the through-line, written last.
