# 4 · Original goals, assumptions, constraints, and what success means

---

## 4.1 · The goal, stated as narrowly as the project states it

Not *"make AI safe"*. The scope is deliberately much smaller **[FACT** —
`docs/ARCHITECTURE.md` §1**]**:

> **The AI controller is an untrusted proposer. An independent governance
> pipeline sits between it and the actuators, and governs the actuation
> boundary.**

Three things follow that are worth stating as goals in their own right, because
each one is testable:

1. **A wrong proposal must not reach an actuator unexamined.**
2. **The examination must not be something the proposer can learn to pass.**
3. **The examination must produce evidence a human can audit afterwards.**

And one **non**-goal, stated explicitly: making the learned controller provably
safe. That is left as an open problem.

---

## 4.2 · The ten assumptions the system makes

**[FACT** — `docs/ASSUMPTIONS.md`, verified against the file's own headings.**]**

This is the list to know. Each assumption is stated so that *"what breaks if this
is wrong"* is answerable — which is the point of writing them down.

| # | Assumption | If it is wrong |
|---|---|---|
| **A-1** | Domain independence comes from ports plus a configured `ActuationSpace` | A second platform costs a rewrite, not an adapter. **Partly measured false** — see `OD-11` |
| **A-2** | A 10 ms end-to-end budget at 20 Hz is achievable in CPython | The prototype's timing does not transfer to a real controller |
| **A-3** | Append-only JSONL, one file per run, is adequate prototype evidence | The evidence pack does not scale to certification volumes |
| **A-4** | **Safety thresholds have no defensible default** | A run proceeds under a threshold nobody chose or reviewed |
| **A-5** | A single random `RunId` is sufficient for byte-comparable replay | Runs cannot be reproduced exactly |
| **A-6** | Python 3.12 is supported by the ML stack at Phase 4 | The interpreter floor and the ML dependencies conflict |
| **A-7** | The repository stays private until the patent filing is confirmed | Disclosure risk |
| **A-8** | The CARLA/interpreter incompatibility is resolvable without changing the core | The simulator drives the architecture rather than the reverse |
| **A-9** | MPC candidate scoring fits behind the `StatisticalGate` port | A planned capability needs a new interface |
| **A-10** | **Explainability means decision provenance, not model-internal attribution** | The explainability claim is about the wrong thing |

### The two to memorise

**A-4 — no safety threshold has a default.** This shapes the whole configuration
system. The source documents never assign numbers to the key thresholds, and the
project's position is that this is not an oversight: those values can only be
fixed empirically, and *shipping a plausible-looking default would let a run
proceed under a threshold nobody chose*. A missing safety threshold is a
**startup failure**, not a warning.

> **Why this matters more than it sounds.** A default is an unreviewed claim
> wearing the appearance of a decision. The project has a matching rule for
> configuration keys: `extra="forbid"`, so a *typo* in a threshold name is a
> startup error rather than a silently ignored line.

**A-10 — explainability is decision provenance.** ASTRA does not try to explain
what the neural network was "thinking". It records, per tick: what the sensors
said, what the filter concluded, what the proposer asked for, what the twin
predicted, what each gate decided and why, what posture resulted, and what was
actually issued. The question it answers is *"why did the vehicle do that, on
what evidence, under which calibration"* — **without any model-internal
attribution**.

**[INTERPRETATION]** This is a genuinely good scoping decision. Model-internal
attribution (saliency maps and their relatives) is contested and hard to defend
to an assessor. Decision provenance is a log, and a log can be argued about.

---

## 4.3 · Constraints that were fixed before the design

**[FACT** — traced to the ADRs named.**]**

| Constraint | Source | Consequence |
|---|---|---|
| **Python 3.12 floor** | ADR-0003 | Collided head-on with CARLA, whose then-current client shipped wheels for CPython 2.7/3.7/3.8 only. This was the project's highest-rated technical risk, **RK-1** |
| **The simulator sits behind a port** | ADR-0003, ADR-0002 | `carla` may not be imported anywhere in `astra` — enforced by an import contract since Phase 1 |
| **No NumPy in the kernel** | ADR-0011 | The innermost layer has no third-party dependency at all |
| **20 Hz control tick** | design | Everything on the hot path has ~50 ms, and the budget target is 10 ms (A-2) |
| **SI units internally** | ADR-0007 | Non-SI values converted once, at the configuration boundary, and never again |
| **Proprietary licence while the filing is pending** | ADR-0014 | The repository is private (A-7) |

### How the CARLA collision was resolved

Worth knowing because it is a good example of the project's habit of
**re-examining a premise rather than working around it** **[FACT** — ADR-0015**]**.

The source documents mandated CARLA 0.9.14, which had no Python 3.12 client.
Three workarounds were on the table — a sidecar process, an unofficial wheel, or
lowering the interpreter floor — and none had been evaluated.

The resolution was that **the premise expired**: CARLA 0.9.16 ships an official
`cp312` wheel. No workaround was needed. A new constraint replaced it — CARLA has
no macOS build — and that one is real and stands.

---

## 4.4 · What success looks like

**[FACT** — `docs/CREDIBILITY_MATRIX.md` defines the marker system; the
interpretation of "success" below is this folder's reading of it.**]**

The project measures its own credibility with five markers, and the honest
summary of where it stands is one line:

> **Rows at [M-ext]: 0 of 30.**

| Marker | Meaning | Supports an accuracy claim? |
|---|---|---|
| **[M-ext]** | Measured against external data this project did not author | **Yes — the only one that does** |
| **[M-syn]** | Measured, but on a plant this project also wrote | No. Shows a mechanism runs |
| **[M-code]** | A measured property of the source itself | Provenance-neutral; true whatever the plant |
| **[E]** | Engineering estimate. Not measured | No |
| **[NOT DONE]** | Outstanding, named so it cannot be mistaken for complete | No |

So success is layered:

**Success level 1 — structural (largely achieved).** The invariants hold
mechanically, the contracts are enforced, the types are strict. These are
`[M-code]` and they are true regardless of which plant the system faces. This is
the strongest column today.

**Success level 2 — the machinery runs (achieved).** Nine layers, closed loop,
faults injected at the sensor boundary, evidence produced per tick. All `[M-syn]`.

**Success level 3 — it works against something we did not write (not started).**
This is what CARLA is for. **Zero rows today.**

**Success level 4 — it works on a real vehicle.** Out of scope.

### The distinction that governs everything

> The digital twin, the calibration corpus, and the trained policy **all descend
> from the same kinematic bicycle model**. The generator and the judge agree by
> construction. **[FACT** — `CREDIBILITY_MATRIX.md`**]**

Every `[M-syn]` row therefore demonstrates *that machinery runs* — **not that it
is correct**. The project states this at the top of its own credibility document,
which is unusual and is the main reason its numbers can be trusted as far as they
go.

---

## 4.5 · What "done" would mean for the safety argument

**[INTERPRETATION]**, built from `SEPARATION_INVARIANTS.md` and
`CREDIBILITY_MATRIX.md`.

A safety argument needs three things, and the project has them in very different
states:

| Element | State |
|---|---|
| **Hazards identified** | Done — the threat model has adversary models T0–T4 plus T1′, and the register holds 21 measured defects |
| **Mechanisms addressing them** | Done — ten invariants, three gates, two counters, a fail-safe posture ladder |
| **Evidence the mechanisms work** | **This is the gap.** `[M-code]` for structure; `[M-syn]` for behaviour; **nothing at `[M-ext]`** |

**[OPEN]** The gates' *efficacy* is the weakest column in the matrix, and the
project says so: five of the ten gate-efficacy rows are `[NOT DONE]`. No
false-positive or false-negative rate appears anywhere in the project's
documents, "because none has been measured and none can be until a row reaches
`[M-ext]`".

---

## 4.6 · You should know this before moving on

**Assumptions to remember by number**

- **A-4** — no safety threshold has a default; a missing one is a startup failure
- **A-10** — explainability is decision provenance, not model attribution
- **A-1** — domain independence via ports; **partly measured false** (`OD-11`)

**The marker system** — you will meet `[M-syn]`, `[M-ext]`, `[M-code]`, `[E]` and
`[NOT DONE]` constantly. Learn them now.

**Questions you should be able to answer**

1. Why does a safety threshold having a default count as a defect rather than a
   convenience?
2. What does A-10 deliberately *not* attempt, and why is that a good scoping
   decision?
3. What is the difference between `[M-syn]` and `[M-ext]`, and why is *0 of 30*
   the number that governs how everything else should be read?
4. Why does "the generator and the judge agree by construction" limit what any
   current measurement can show?
5. What was RK-1, and how was it resolved? *(Careful: it was not worked around.)*

**Misconception to avoid**

> *"The system has been validated."*
>
> It has been **measured**, extensively, against a plant the project wrote. Those
> are different claims and the project's own documents are careful to keep them
> apart. Nothing here has been validated against an external reference, and the
> credibility matrix leads with that fact rather than burying it.

---

**End of section 01.** Next: `02_PROJECT_HISTORY/` — how this went from an idea
to nine layers, and what broke on the way.
