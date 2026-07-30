# ADR-0001: Adopt the consolidated L1–L9 layer numbering

- **Status:** Accepted
- **Date:** 2026-07-29
- **Phase:** 1 (Foundation)

## Context

ASTRA's four source documents do not agree on how many layers the pipeline has or what they are
called.

`ASTRA_paper 1.pdf`, the earlier draft, numbers Core-B's internal stages as layers 4–6 and places
RCM at layer 7 — a seven-layer pipeline. The other three documents — `ASTRA_shortened.pdf` (the
latest and most honest version of the paper), `ASTRA_mp1report.pdf` (the requirements authority)
and `ASTRA_Prototype_and_Demo_Plan.md` (the implementation authority) — all use a nine-layer
scheme, L1 through L9, in which the Core-B stages are L5–L8 and RCM is L9.

This is reconciliation finding R-1. It is not a cosmetic disagreement. Layer identity is the
primary dimension of the whole architecture: it appears in the separation invariants (*"no layer
above L2 reads a raw sensor payload"*), in the timing budget table, in the ASIL decomposition, in
every audit record's provenance, and in the names of the modules the later phases will create. Two
numbering schemes in circulation means an audit record saying "layer 6 vetoed" is ambiguous, and an
ambiguous evidence record is not evidence.

A decision had to be made in Phase 1, before any layer existed, because the numbering is baked into
the identifier type that every record carries.

## Decision

Adopt the consolidated **L1–L9** numbering, encoded once as
`LayerId` in `src/astra/kernel/enums.py`:

| | Layer | Execution domain |
|---|---|---|
| L1 | Shared Sensor Bus | `SHARED` |
| L2 | Dual-Rate UKF | `SHARED` |
| L3 | Conformal Trust Module | `SHARED` |
| L4 | Core-A (CMDP proposer) | `CORE_A` |
| L5 | PINN Twin | `CORE_B` |
| L6 | MPC scoring + ICP gate | `CORE_B` |
| L7 | Hard Safety Shield | `CORE_B` |
| L8 | Fail-Safe FSM | `CORE_B` |
| L9 | Runtime Calibration Management | `ARBITRATOR` |

`ASTRA_paper 1.pdf` is declared superseded on numbering. The enum's docstring says so explicitly
and points at the reconciliation record, so a reader who arrives via the older paper is told
immediately that they are holding the wrong map.

Two consequences of the choice are encoded alongside it. `LayerId.ordinal` derives the 1-based
number from the member name, so "layers above L2" is an expressible predicate rather than a
convention. `LayerId.execution_domain` maps each layer to one of four `ExecutionDomain` values, so
the process architecture — which layers share memory, which sit behind the one-way Core-A/Core-B
channel, which may issue an actuator command — is data rather than prose.

L7 carries a further split that the numbering alone does not express. Reconciliation finding R-3
found the Demo Plan asserting L7 has "no dependency on L5 or L6 outputs" while the papers describe
it as a combined shield *and physical recheck* that uses the PINN prediction. Both are made true by
distinguishing **L7a**, the Hard Safety Shield — deterministic, reads only UKF state, zero
dependency on L5/L6, which is what preserves its unconditional-veto independence — from **L7b**,
the physical checker, which is PINN-based and is formally assigned `GateId.PHYSICAL`. L7a and L7b
share a layer number because they share a position in the pipeline; they have separate ports
(`DeterministicShield`, `PhysicalAdmissibilityChecker`) because they have separate dependencies.

## Alternatives considered

**Adopt `paper 1`'s 7-layer numbering.** Rejected. It is the earlier draft and is superseded by
three later documents, including the requirements authority. It also collapses Core-B's four
stages into three numbers, which obscures the fact that the Fail-Safe FSM is a distinct stage with
its own state and its own failure mode.

**Support both, with a translation table.** Rejected, and it is worth saying why at length because
it is the superficially safe option. A translation table between numbering schemes is a permanent
tax on every reader and every tool: the audit log would need to declare its scheme, the dashboard
would need to convert, and the first record written under the wrong scheme would be undetectably
wrong. Compatibility with a superseded draft is not worth a lifelong ambiguity in the evidence
artefact.

**Introduce a third, "cleaner" numbering of our own.** Rejected under the project's standing rule
that the source documents are the authority and architecture is not invented. Three of four
documents already agree; inventing a fourth scheme would put the codebase at odds with every
document a reviewer will read.

**Name layers instead of numbering them** (`SENSOR_BUS`, `TRUST`, …). Rejected. The documents,
the FMEA table, the timing budget and the separation invariants all refer to layers by number.
Dropping the numbers would force a translation every time the code is read against the paper. The
enum member names carry both (`L3_CONFORMAL_TRUST`), which is the compromise actually taken.

## Consequences

### Positive

- One spelling of layer identity across the audit log, the configuration, the dashboard, the test
  suite and the documentation. A `DecisionRecord` naming `L6_MPC_ICP_GATE` means exactly one thing.
- `StrEnum` means `json.dumps` emits `"L6_MPC_ICP_GATE"` with no custom encoder, so the evidence
  file stays readable by a human assessor.
- "Layers above L2" becomes a computable predicate via `ordinal`, which is what allows SI-1 to be
  checked rather than asserted.
- The execution-domain mapping makes the Core-A/Core-B trust boundary queryable, and it is what the
  architecture tests use to assert that exactly one layer has actuation authority (SI-7).
- Future layer packages have their names decided: `astra.layers.l4_proposer`, `l5_twin`,
  `l6_statistical_gate`, `l7_shield`, `l8_failsafe`. The commented-out SI-5 contract in
  `.importlinter` already names them.

### Negative / accepted trade-offs

- **Anyone reading `ASTRA_paper 1.pdf` alongside this repository will be confused**, and will stay
  confused until they find the reconciliation note. This is a real, recurring cost: that draft
  contains prose on shadow execution and safe exploration that exists nowhere else, so people will
  keep reading it.
- **The L7a/L7b split is invisible in `LayerId`.** There is one `L7_HARD_SAFETY_SHIELD` member, and
  the distinction lives in the two ports and in `GateId`. A reader who looks only at the enum will
  not see it. The alternative — an `L7A`/`L7B` pair — was worse, because it would have made the
  pipeline ten layers and contradicted `ASTRA_LAYER_COUNT = 9` and every document.
- **Renumbering later would be extremely expensive.** Layer identifiers are written into every
  audit record. Changing the scheme after evidence exists means either an unreadable archive or a
  migration of it. This decision is close to irreversible from the moment the first run is
  recorded, which is a good reason to have made it in Phase 1 and a bad thing to discover in
  Phase 6.
- **A-9 could still disturb it.** If "MPC candidate scoring" turns out to need its own layer rather
  than a sub-stage behind `StatisticalGate`, the numbering changes. That assumption is unresolved
  and awaits clarification; the cost of being wrong grows sharply once L6 is implemented.
