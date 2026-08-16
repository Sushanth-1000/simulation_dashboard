# 05 · The Current Architecture

You have read the history. Everything here should now arrive as an *answer* to a
question you have watched being asked.

---

## 5.1 · The one structural fact

Everything is organised around a single line:

```
        CORE-A  (untrusted)    │    CORE-B  (trusted)
        proposes               │    judges, and owns the actuators
```

**Core-A** may look at anything about the *world*. It may not look at anything
about its own *judgement*. **Core-B** judges Core-A's output and is the only
thing permitted to touch an actuator.

That line is enforced three ways, all mechanical **[FACT** — `ARCHITECTURE.md`
§1, `SEPARATION_INVARIANTS.md`**]**:

| Invariant | Enforced as | Violation is |
|---|---|---|
| **SI-5** — the proposer cannot read a verdict | The write channel exposes no read method | A **type error** — it does not compile |
| **SI-7** — only L9 may issue | `IssuedCommand` refuses construction from any other layer | A **runtime refusal** |
| **SI-3** — a veto is unconditional | `Verdict.merge` is a fail-closed fold | Structurally unrepresentable |

---

## 5.2 · The full picture

```
                     ┌───────────────── CORE-A ─────────────────┐
                     │                                          │
 ┌────────┐   ┌──────▼─┐   ┌──────┐   ┌───────┐   ┌──────────┐  │
 │sensors ├──►│ L1 bus ├──►│L2 UKF├──►│L3 trust├──►│L4 propose│  │
 └────────┘   └──┬─────┘   └───┬──┘   └───┬───┘   └─────┬────┘  │
                 │             │          │             │        │
                 │ StreamHealth│ estimate │ trust       │proposal│
                 │             │          │             │        │
 ═══════════════ │ ══════════  │ ════════ │ ═══════════ │ ══════ │ ═══ SI-5 ═══
                 │             │          │             ▼        │
                 │             │          │      ┌──────────┐    │
                 │             └──────────┼─────►│ L5 twin  │    │
                 │                        │      └─────┬────┘    │
                 │                        │            │prediction│
                 │                        ▼            ▼          │
                 │                   ┌─────────────────────────┐  │
                 │                   │ L6 statistical  (ICP)   │  │
                 │                   │ L7a hard shield         │──┼──► verdicts
                 │                   │ L7b physical admissible │  │
                 │                   └───────────┬─────────────┘  │
                 │                               │ merge fail-closed
                 ▼                               ▼                │
            ┌─────────────────────────────────────────┐           │
            │        L8 fail-safe machine             │           │
            │   OOD counter  ·  integrity counter     │           │
            └──────────────────┬──────────────────────┘           │
                               │ posture + capabilities            │
                               ▼                                   │
                        ┌─────────────┐                            │
                        │  L9 RCM     │────────────────────────────┴──► ACTUATORS
                        └─────────────┘
```

**The two arrows worth staring at:**

1. **`StreamHealth` bypasses L2 entirely.** It goes from L1 straight to L8. That
   arrow is ADR-0024, and it exists because everything routed through L2 shares a
   common cause (OD-9).
2. **Nothing flows right-to-left across the SI-5 line.** No verdict, no posture,
   no calibration reaches L4. That is what makes "untrusted" structural.

---

## 5.3 · The nine layers, one line each

**[FACT** — `LayerId` in `src/astra/kernel/enums.py`.**]**

| Layer | Name | Question it answers |
|---|---|---|
| **L1** | Shared sensor bus | *What did each sensor say, and how fresh is it?* |
| **L2** | Dual-rate UKF | *Given all of that, where are we — and how sure?* |
| **L3** | Conformal Trust Module | *How familiar is this situation?* |
| **L4** | CMDP proposer | *What should we do?* ← **the untrusted AI** |
| **L5** | PINN digital twin | *What would that command actually do?* |
| **L6** | Statistical gate | *Is this proposal conformant with the calibrated population?* |
| **L7a** | Hard safety shield | *Does it violate a hard physical bound?* |
| **L7b** | Physical admissibility | *Is the change admissible — jerk, divergence from the twin?* |
| **L8** | Fail-safe FSM | *How much trouble are we in, and what functions are lost?* |
| **L9** | Runtime Calibration Manager | *What actually gets issued?* ← **sole actuation authority** |

---

## 5.4 · The three gates and why there are exactly three

Core-B's judgement is three gates whose **failure modes are meant to be
unrelated** **[FACT** — reason-code vocabularies read from source**]**:

| Gate | Judges against | Reason codes |
|---|---|---|
| **L6 STATISTICAL** | A *calibrated population* — is this score unusual? | `SCORE_EXCEEDS_CONFORMAL_QUANTILE` |
| **L7a DETERMINISTIC** | *Hard physical/legal bounds* | `LATERAL_ACCELERATION_EXCEEDS_FRICTION`, `LATERAL_OFFSET_EXCEEDS_CORRIDOR`, `STOPPING_DISTANCE_EXCEEDS_ASSURED_CLEAR`, `SPEED_EXCEEDS_LEGAL_LIMIT`, `STATE_NOT_FINITE` |
| **L7b PHYSICAL** | *The change*, and the twin's prediction | `LATERAL_JERK_EXCEEDS_LIMIT`, `PROPOSAL_DIVERGES_FROM_TWIN`, `INPUT_NOT_FINITE` |

**Three is load-bearing, not incidental** **[FACT** — `CORE_B_GATE_COUNT` in
`constants.py`**]**:

> Three is a load-bearing number, not an implementation detail. The independence
> argument requires that each gate has a distinct failure mode; adding a fourth
> gate that shares a failure mode with an existing one would **weaken the
> argument while appearing to strengthen it**.

### How the verdicts combine — and the two properties that matter

`Verdict.merge` is a **fail-closed fold**, not a vote **[FACT** — SI-3**]**:

- **Any VETO ⇒ VETO.** No number of PASSes can outvote one refusal.
- **An empty verdict set ⇒ VETO.** If no gate reported, the answer is refusal.
  Absence of judgement is not permission.
- **ABSTAIN is dropped before the fold** (ADR-0016). A gate that *cannot* judge
  is not counted as either approval or refusal.

### The measured caveat you must carry

**[FACT** — `E-162`, `E-163`**]** Across 2,800 ticks of a fault suite built to
break them:

| gate | PASS | VETO | ABSTAIN |
|---|--:|--:|--:|
| STATISTICAL | 2800 | **0** | 0 |
| PHYSICAL | 2651 | **149** | 0 |
| DETERMINISTIC | 2800 | **0** | 0 |

All 149 on **one** reason code. And ABSTAIN is zero everywhere, so the two silent
gates are **judging every tick and finding nothing** — not declining to judge.

L6's zero has a known cause: its scores sit entirely below the corpus quantile
(OD-8), so it *cannot* veto. **A zero veto rate is not evidence the proposals
were sound.**

---

## 5.5 · The fail-safe posture — two counters, one ladder

L8 walks four states, and the posture is **the worse of two independent
counters** **[FACT** — `machine.py`**]**:

```
NOMINAL ──► DEGRADED ──► LIMP ──► HALT
   ▲            │           │        ╳ terminal — only reset() leaves it
   └────────────┴───────────┘
        automatic recovery, with hysteresis
```

| Counter | Question | Rises on | Falls on |
|---|---|---|---|
| **OOD** | *Is the command being refused?* | A blocking verdict | A clean verdict |
| **Integrity** | *Can I believe what I am told?* | Unhealthy critical modalities beyond tolerance | A clean frame |

**Why two and not one.** *"The gates refused forty commands"* and *"a sensor was
dark for forty ticks"* need different responses from whoever reads the log, and
**one integer cannot say which happened**. They are reported separately in every
snapshot.

**Neither can be overruled by the other's good news** — the machine escalates on
whichever is more severe and de-escalates only when both agree.

### And a second axis entirely — capabilities

**[FACT** — ADR-0029**]** The posture says *how bad*. A separate mechanism says
*what is broken*: `failsafe.capabilities` declares what each autonomy function
requires, and a function is **withdrawn** while any modality it needs is
unhealthy.

The two compose by **intersection** — a function is offered where the posture
allows it **and** its sensors support it. Withdrawal can only *subtract*; a set
able to *grant* what the posture forbids would be a fourth gate with
veto-override authority.

---

## 5.6 · L9 and the actuation boundary

L9 is the only thing that may construct an `IssuedCommand`. It also:

- applies the posture's **speed cap** through a `CommandProjector`, so the cap
  binds on an actuator rather than merely being recorded (that was OD-2)
- runs the **fallback controller** when a proposal is refused
- arbitrates calibration profiles, with five outcomes: `CONTINUE`,
  `SHADOW_EXECUTION`, `SWITCH_COMMITTED`, `ROLLBACK`, `SAFE_EXPLORATION`
- declares **bounded safe exploration** when no certified profile matches the
  context — the mechanism behind *"others degrade to a halt when they leave their
  certified envelope; ASTRA is built not to"*

---

## 5.7 · Two timing domains

**[FACT** — SI-8, `TimingDomain` in `enums.py`.**]**

| Domain | Rate | Contains |
|---|---|---|
| **Hot path** | 20 Hz — every tick | L1…L9. Budget target 10 ms (A-2) |
| **Cold path** | Slower, asynchronous | RCM's knowledge-base search, profile evaluation |

Separating them is what lets RCM run an expensive search **without ever blocking
the tick in flight**. Any component added later must declare which domain it runs
in — the declaration is what makes an accidental blocking call reviewable.

The estimator is itself **dual-rate**: a fast filter at 20 Hz over
`[position_x, position_y, speed, heading, lateral_acceleration]`, and a slow
filter tracking degradation processes.

---

## 5.8 · The evidence spine

Every tick produces a `DecisionRecord` carrying frame health, the state estimate,
the Trust Index, the proposal, the twin's prediction, **every gate verdict**, the
fail-safe snapshot, the arbitration decision, the issued command, and the
configuration hash **[FACT** — `contracts/audit.py`**]**.

Written as append-only JSONL, one file per run, **hash-chained** — each record
carries the previous record's digest, making the log tamper-*evident* rather than
merely integrity-checked.

**The schema is versioned and pinned by a test** that has fired **seven times**,
each time forcing a schema change to be a decision someone made deliberately.
Current version: **10**.

---

## 5.9 · You should know this before moving on

**The five structural facts**

1. Core-A / Core-B, with SI-5 as a **type error**
2. `StreamHealth` **bypasses L2** — the one signal upstream of the common cause
3. Verdicts merge **fail-closed**; empty ⇒ VETO
4. **Two counters**, one ladder, plus a **separate capability axis**
5. **Only L9** may issue

**Questions you should be able to answer**

1. Why does `StreamHealth` go straight from L1 to L8 instead of through L2?
2. Why would adding a fourth gate *weaken* the independence argument?
3. What does an *empty* verdict set merge to, and why is that the right answer?
4. Why are there two counters rather than one with two thresholds?
5. Why is a zero veto rate from L6 currently **not** evidence of anything good?

**Misconception to avoid**

> *"Three gates means three independent chances to catch a problem."*
>
> Structurally yes; **measurably, not yet**. All three read L2's estimate (OD-9),
> and on the current baseline two of them never object at all (`E-162`). The
> architecture is *shaped* for independence; the evidence that it *delivers*
> independence is the weakest column in the credibility matrix, and the project
> says so.

---

**Next:** `06_COMPONENTS/` — each layer in full.
