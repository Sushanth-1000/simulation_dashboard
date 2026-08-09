# ADR-0021 — An ablation neutralises a gate; it never removes one

**Status:** Accepted, not yet implemented
**Date:** 9 August 2026
**Unblocks:** P3.4 in [`../PENDING.md`](../PENDING.md), and deliverable D2 in
[`../ENGAGEMENT_DELIVERABLES.md`](../ENGAGEMENT_DELIVERABLES.md)
**Supersedes nothing.** Answers the question P3.4 left open and the 9 August
handover explicitly declined to answer alone.

## Context

The ablation study needs to switch off six mechanisms in turn and re-measure.
Checked against the code, **one of the six has a disable path**:

| Ablation | Disable path today |
|---|---|
| FB1 off | `control_effectiveness: Sequence[float] \| None` — the only one |
| L6 off | `statistical_gate: IcpStatisticalGate` — a **required** parameter |
| L7a off | `shield: HardSafetyShield` — a **required** parameter |
| L9 exploration off | An `ArbitrationOutcome`, not a switch |
| FB2 off | Vacuous — never wired; "off" *is* the shipped configuration |
| FB3 off | Vacuous, for the same reason |

FB2 and FB3 need no ablation and should not get one. Both were measured **in
shadow** — adapting real state, read by nothing — which is a stronger comparison
than an ablation because it changed no verdict: FB2 on would collapse the
non-conformity score 40 % in a context where nothing changed (E-39), and FB3 on
would pin the veto rate to ε by construction (E-40). Those are measured rows,
not ablations to be re-derived by switching off something that was never on.

That leaves three, and all three are the same question: **may a required safety
parameter become optional so that a study can leave it out?**

The requirement is load-bearing. A pipeline that could be constructed without a
statistical gate is the single most dangerous defect this codebase could carry,
because it fails silently and in the flattering direction — every audit row
would still be written, every verdict would still say `ACCEPT`, and nothing
would record that the gate which accepted was absent. That is precisely the
shape of OD-2 (a speed cap recorded on every tick and applied to no actuator)
and of OD-7, and this project has now been bitten twice by mechanisms that make
the evidence look better rather than worse.

## Decision

**The parameters stay required. An ablation supplies a gate that cannot
block, rather than no gate at all.**

Three pieces:

1. **Transparent gates.** `TransparentStatisticalGate(IcpStatisticalGate)` and
   `TransparentShield(HardSafetyShield)` in `astra/runtime/ablation.py`. Each
   overrides `evaluate` to return an `ACCEPT` `GateVerdict` carrying a reason
   code that names the ablation. They are subtypes, so the constructor's
   declared type is satisfied without being widened: **there is no `| None`
   anywhere, and a pipeline with no gate remains unconstructible.**
2. **A profile, stamped into the evidence.** A frozen `AblationProfile` value
   object names which layers are neutralised. `assemble_pipeline` takes it,
   defaulting to `AblationProfile.NONE`, and every `DecisionRecord` carries it.
   **A run measured under an ablation is self-identifying in its own audit log,
   permanently and per tick** — it cannot later be mistaken for a governed run,
   which is the failure mode that would turn a certification artefact into a
   description of a system that was not running.
3. **A refusal outside `development`.** Any profile other than `NONE` raises at
   assembly. Defence in depth, and deliberately the *weakest* of the three: it
   is a runtime check on a construction-time property, and this project's
   standing preference is the type system where the type system will do.

## Options considered

| | Benefit | Drawback | |
|---|---|---|---|
| **A.** `statistical_gate: … \| None` | Two characters | A pipeline can be constructed ungated, and nothing in the resulting evidence would say so. Every guard against it becomes a runtime check | rejected |
| **B.** `AblationProfile` gating optional parameters, refused outside `development` | Explicit; the profile reaches the evidence | Still relaxes the parameter. One configuration mistake, or one caller that resolves a different environment, and it degenerates to A. Protects a construction-time property with a runtime check | rejected |
| **C.** Gate stays required; ablation supplies a transparent instance, profile stamped into every record | The dangerous state is **unconstructible**, not merely guarded. Same move as SI-5, where the one-way core channel is a type error rather than a convention. The layer still runs, still emits a verdict, still appears in the audit log — so the ablation measures the gate's *authority* rather than its presence | Measures the safety contribution, not the compute contribution — see below | **chosen** |
| **D.** Drop P3.4 | — | D2 is an offered deliverable, and the ablation table is the artefact most often reported as surprising by its recipient | rejected |

## The drawback, and why it is not one

C leaves a transparent gate running, so total tick latency barely moves and the
ablation cannot report what each layer costs. D2 promises the table in FP rate
**and in compute**.

Compute comes from `benchmarks/latency.py` instead, which already times each
stage individually against its own budget (E-10). That is the better instrument
regardless: subtracting two whole-pipeline latencies to infer one stage's cost
is a difference of two noisy numbers, while the benchmark measures the stage
directly. The ablation answers *what does this gate catch*; the latency
benchmark answers *what does it cost*. Neither was ever the right tool for the
other's question.

## Consequences

- `GovernancePipeline.__init__` is unchanged. No signature in the safety spine
  is widened by this decision, which is the whole point of it.
- `DecisionRecord` gains one field with a default, so existing readers are
  unaffected and existing audit logs remain parseable.
- The ablation table lands with **two rows already measured** — FB2 and FB3,
  from the shadow runs — and four to build.
- An architecture test must pin the property that makes this safe: that no
  `DecisionRecord` can be produced without the profile field. Without it the
  guarantee is a convention again, and convention 13 of
  [`../CONVENTIONS.md`](../CONVENTIONS.md) is the rule this project keeps
  learning the hard way.
- The transparent gates ship inside `src/astra/`, which is a cost and is
  accepted knowingly. Ablation is a statement about *how the core is composed*
  and cannot be expressed at an adapter boundary the way fault injection can —
  see [ADR-0022](0022-faults-are-injected-at-the-sensor-boundary.md), which
  takes the opposite placement for the opposite reason.
