# Executive Overview

Fifteen minutes. The shape of the whole thing, so that everything after it has
somewhere to attach.

---

## 1 · The one-sentence version

> An AI controller is treated as an **untrusted proposer**. An independent
> pipeline sits between it and the actuators, judges every command it proposes,
> and owns the actuation boundary.
>
> — `docs/ARCHITECTURE.md` §1 **[FACT]**

Everything else is consequence.

---

## 2 · The problem, in one paragraph

A learned controller can be **structurally perfect and semantically wrong**. No
crash, no bit flip, no memory corruption — correct by every classical definition
— and still emit a command that is a bad idea, because the world it faces at
runtime no longer resembles the world it was trained in.

**Nothing in the existing safety stack addresses that.** `docs/ARCHITECTURE.md`
§1 names three defences and why each misses **[FACT]**:

| Defence | What it does | Why it misses |
|---|---|---|
| **Lockstep processors** | Run the same computation on two cores and compare | They agree. Both cores produce the *same wrong answer* |
| **Hypervisors** | Isolate execution domains | They police *who may run*, not *what crosses the boundary* |
| **Hardware security modules** | Authenticate a command's origin | They prove *who sent it*, not *whether it was a good idea* |

Every one of them answers *"did the computation execute correctly?"* The failure
mode here is a computation that executes perfectly and produces a wrong answer.

---

## 3 · The shape of the answer

Nine layers, `L1`–`L9`, split across a trust boundary **[FACT** — `LayerId` in
`src/astra/kernel/enums.py`**]**:

```
                    ┌─────────── CORE-A · untrusted ───────────┐
                    │                                          │
   sensors ──► L1 ──► L2 ──► L3 ──►  L4  ── proposes a command ─┐
               bus    UKF   trust   CMDP                        │
                       │                                        │
                    ┌──┴─────────── CORE-B · trusted ───────────▼──┐
                    │                                              │
                    │   L5 twin ──► L6 statistical gate ──┐        │
                    │                                     │        │
                    │              L7a hard shield ───────┼─► merge│
                    │                                     │        │
                    │              L7b physical gate ─────┘        │
                    │                       │                      │
                    │                       ▼                      │
                    │                  L8 fail-safe ──► L9 RCM ────┼──► actuators
                    └──────────────────────────────────────────────┘
```

| Layer | Name | One-line job |
|---|---|---|
| **L1** | Shared sensor bus | Receive per-modality readings, stamp freshness |
| **L2** | Dual-rate UKF | Fuse them into a state estimate, with uncertainty |
| **L3** | Conformal Trust Module | Say how much the current situation resembles anything calibrated |
| **L4** | CMDP proposer | **The untrusted AI.** Propose a command |
| **L5** | PINN digital twin | Predict what the command will actually do |
| **L6** | Statistical gate | Is the proposal conformant with the calibrated population? |
| **L7a** | Hard safety shield | Are the hard physical bounds respected? |
| **L7b** | Physical admissibility | Is the *change* physically admissible — jerk, divergence? |
| **L8** | Fail-safe FSM | How much trouble are we in, and what posture does that imply? |
| **L9** | Runtime Calibration Manager | **The only thing allowed to touch an actuator** |

---

## 4 · The three rules that generate the rest

Three consequences follow from *"the AI is untrusted"*, and between them they
explain most of the codebase **[FACT** — `ARCHITECTURE.md` §1**]**:

### 4.1 · The proposer must not see its judge — **SI-5**

Anything an optimiser can observe, it can learn to exploit. So `CommandProposer.propose`
accepts state and trust and **nothing else** — no verdict, no fail-safe state, no
calibration table. It is enforced as a **type error**, not a convention: the
write side of the channel exposes no read method.

### 4.2 · One component owns the actuation boundary — **SI-7**

Or it is not a boundary. `IssuedCommand` **refuses construction** by any
component whose layer is not `L9_RCM`.

### 4.3 · A veto is unconditional — **SI-3**

Or the strongest claim in the safety argument is advisory. `Verdict.merge` is a
**fail-closed fold** — not a vote, not a weighted score, not a majority. An
**empty** verdict set merges to `VETO`.

**There are ten such invariants, SI-1 … SI-10, and all ten are mechanically
enforced** — by the type system, by runtime checks, by tests, or by import
contracts **[FACT** — `SEPARATION_INVARIANTS.md`**]**. None is left to code
review. That is the difference between a safety argument and a safety intention.

---

## 5 · The thing that makes this project unusual

It is not the architecture. Similar shapes exist in the literature.

**It is that the project systematically tries to prove itself wrong, and keeps
the results when it succeeds.**

Concretely, as of 15 August 2026 **[FACT** — `CREDIBILITY_MATRIX.md`**]**:

- **21 defects, all self-found.** 16 closed and re-measured, 1 reclassified,
  1 partly closed, 3 open.
- **Not one was reported by the test suite**, `mypy --strict`, or the twelve
  import contracts. Every one came from running the system and reading the
  numbers, or from asking it a question a customer would ask.
- **Four feedback loops were specified. Two were measured and refused** — FB2
  and FB3 would each have disarmed the gate they fed, and the measurements that
  proved it are kept in the tree as evidence.
- **Claims get retracted in public.** On one day, three numbers were withdrawn
  because the observations behind them turned out to be inadequate.

And the number that governs how everything above should be read:

> **Rows at [M-ext]: 0 of 30.** **[FACT** — `CREDIBILITY_MATRIX.md`**]**

Every measurement so far is on a plant this project also wrote. The twin, the
calibration corpus and the trained policy all descend from **the same kinematic
bicycle model**, so the generator and the judge agree by construction. That is
stated at the top of the credibility matrix by the project itself, and it is the
single largest thing a reviewer can hold against the work.

**This is why CARLA is next.** It is the only item on the backlog that can move a
row off `[M-syn]`.

---

## 6 · Four findings worth knowing on day one

These are the ones that most shape how the system looks today.

### OD-9 — you cannot veto your way out of a lying sensor

Every Core-B gate reads L2's estimate, and the proposer closes its loop on the
*same* estimate. So a corrupted sensor reading is **actively driven toward the
value the gates consider safe**. Measured: an IMU dropout put the vehicle
**4.199 m off a 1.75 m lane** while the corridor bound read **0.023 m**, with a
verdict trace *identical to the clean run's* **[FACT** — `E-46`, `E-48`**]**.

A veto could not have helped: the fallback controller reads the same corrupted
estimate. The fix had to come from **upstream of the common cause** — sensor
freshness, computed at the boundary before the filter touches anything.

### OD-8 — the conformal guarantee does not currently hold

The statistical gate's guarantee rests on one assumption: that live scores and
calibration scores are *exchangeable*. Measured 15 August: **999 live samples
against 1,000 calibration samples, zero overlap** **[FACT** — `E-159`**]**. The
gate still emits verdicts; they do not mean what the theory says.

### Two of three gates never object

Census over 2,800 ticks of a fault suite *built to break them*: `STATISTICAL`
VETO 0, `DETERMINISTIC` VETO 0, `PHYSICAL` VETO 149 — all on one reason code.
And `ABSTAIN` is zero for all three, so the silent two are **judging every tick
and finding nothing**, not declining to judge **[FACT** — `E-162`, `E-163`**]**.

### The proposer is trained on truth and deployed against an estimate

`train_policy` fits against the bare plant — no pipeline, no filter, no sensor
bus **[FACT** — `E-155`**]**. **[OPEN]** what that skew costs has not been
measured.

---

## 7 · What state the project is in

**[FACT]** as of 15 August 2026:

- 3,065 tests, 3 strict `xfail`, `mypy --strict` over 169 files, 12 import
  contracts, 97.47% coverage with a per-file floor
- 34 architecture decision records
- 164 evidence rows
- Nine layers built; the full pipeline runs closed-loop against a synthetic plant
- Everything before CARLA is done, bar two deliberate deferrals

**What has not happened:** the system has never run against a simulator this
project did not write.

---

## 8 · You should know this before moving on

**Terminology to hold onto**

| Term | Meaning |
|---|---|
| **Core-A / Core-B** | Untrusted proposer side / trusted governance side |
| **Proposer** | The AI. Proposes; never issues |
| **Gate** | A component that returns PASS, VETO or ABSTAIN on a proposal |
| **Veto** | Unconditional refusal. Nothing overrides it |
| **Posture** | The fail-safe machine's state: NOMINAL, DEGRADED, LIMP, HALT |
| **`[M-syn]` / `[M-ext]`** | Measured on our own plant / measured against something we did not write |
| **SI-n** | Separation invariant. Ten of them, all mechanically enforced |
| **A-n** | Assumption. Ten of them, in `ASSUMPTIONS.md` |
| **OD-n** | Open defect in the register |
| **E-n** | An evidence row — one measurement with its reproduction command |

**Questions you should be able to answer**

1. Why doesn't lockstep redundancy solve this problem?
2. Why must the proposer be unable to see the verdict?
3. What does it mean that an *empty* verdict set merges to VETO?
4. Why is `[M-ext]: 0 of 30` the most important number in the project?
5. Why couldn't a veto have fixed OD-9?

**A misconception to avoid now**

> *"The gates make the AI safe."*

They do not, and the project does not claim it. What is claimed is **defence in
depth through gates with structurally different failure modes** — and OD-9 is the
measurement showing that even that is qualified, because all three gates read one
estimate. The honest claim is narrower than the architecture diagram suggests,
and knowing exactly how much narrower is most of what this folder is for.

---

**Next:** [`Learning_Path.md`](Learning_Path.md).
