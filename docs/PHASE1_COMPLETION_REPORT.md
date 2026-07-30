# Phase 1 — Engineering Completion Report

**Phase:** 1, Foundation
**Status:** Complete
**Date:** 29 July 2026
**Scope delivered:** the vocabulary, contracts, interfaces, invariants, configuration and
evidence machinery every later phase depends on. **No layer logic.**

---

## 1. What Phase 1 was for

The purpose of this phase was not to build any part of the governance pipeline. It was to make
the pipeline *buildable* — to fix, before any layer exists, the decisions that are cheap now and
a rewrite later: how state is represented, how time is read, how records are identified, what a
verdict means, what "fail closed" is in code rather than in prose, and how evidence is produced.

Six arguments for starting here are set out in [`ENGINEERING_HANDOFF.md`](ENGINEERING_HANDOFF.md)
§7. The one that governed most decisions: **replay tooling cannot be retrofitted.** It requires
deterministic identifiers, an injected clock, immutable records and a schema-versioned event log.
Every one of those is a foundation decision, and the roadmap names closed-loop integration as the
highest-risk stage *and* the one that does not compress. Arriving there without replay is the
difference the plan describes between debugging in hours and in days.

---

## 2. Files created

33 source modules, 30 test modules, 24 documents.

| Package | Modules | Responsibility |
|---|---|---|
| `astra.kernel` | `units`, `enums`, `constants`, `errors`, `identifiers`, `time`, `validation`, `matrix` | Dependency-free primitives. Imports nothing from `astra`, nothing third-party. |
| `astra.contracts` | `sensing`, `estimation`, `actuation`, `assurance`, `governance`, `audit` | The immutable records layers exchange. Validate once at construction, then trusted. |
| `astra.ports` | `pipeline`, `infrastructure` | Ten layer protocols and four infrastructure ports. Structural, so no adapter imports a base class. |
| `astra.invariants` | `catalogue` | SI-1 … SI-10 as data, with runtime guards for SI-3 and SI-7. |
| `astra.config` | `schema`, `loader` | Layered, validated, startup-frozen settings and the configuration hash. |
| `astra.observability` | `context`, `logging`, `audit` | Correlation context, non-blocking logging, the JSONL evidence sink. |
| `astra.bootstrap` | `composition`, `cli` | The composition root and the `astra` command-line interface. |

Supporting artefacts: `.importlinter`, `Makefile`, `.github/workflows/ci.yml`,
`.pre-commit-config.yaml`, `.editorconfig`, `.env.example`, `CHANGELOG.md`, four configuration
files, and `docs/` including fourteen ADRs.

---

## 3. Architecture established

**A strictly acyclic, strictly downward module graph**, machine-checked:

```
bootstrap  >  {config, observability, invariants}  >  ports  >  contracts  >  kernel
```

The bottom layer having no dependencies is not tidiness. It is what lets an offline
evidence-analysis tool, a certification script or the dashboard process import ASTRA's vocabulary
and contracts without installing NumPy, PyTorch or a simulator.

**Illegal states made unrepresentable**, rather than checked for:

| Illegal state | Why it cannot be represented |
|---|---|
| An asymmetric covariance | `SymmetricMatrix` stores only the lower triangle |
| A command issued by something other than L9 | `IssuedCommand.__post_init__` refuses a non-L9 issuer (SI-7) |
| A safety verdict influenced by the Trust Index | `SafetyVerdict` has no field for one, and no gate port accepts a `TrustAssessment` (SI-4) |
| A PASS that overrides a VETO | The aggregate is only ever `Verdict.merge`, which is fail-closed (SI-3) |
| A non-monotonic quantile table in a profile | `CalibrationProfile` applies `require_non_decreasing` (SI-9) |
| A duration computed across two timelines | `Instant.elapsed_since` raises rather than returning a number |
| A run under an unset safety threshold | The field has no default; startup fails (A-4) |

**Nine of ten separation invariants are mechanically enforced.** SI-6 is `REVIEW` until Phase 4,
and the catalogue, the CLI and the documentation all say so rather than implying otherwise.

---

## 4. Engineering decisions

Fourteen decisions are recorded as ADRs in [`adr/`](adr/). The four with the widest blast radius:

**ADR-0007 — SI units via `NewType`, converted only at boundaries.** The source documents mix
m/s², km/h, degrees and radians freely. This is a Mars-Climate-Orbiter-shaped risk, and a units
library would cost 50–100× on arithmetic on a path with a millisecond budget. `NewType` is erased
at runtime and distinct to the type checker. Accepted trade-off: it does not survive arithmetic.

**ADR-0010 — an injected `Clock`; no component reads time directly.** The wall clock is not
monotonic, and a negative staleness reads as "perfectly fresh". Replay and simulator-synchronous
mode both need a substitutable timeline. This is now enforced by an architecture test, not only
documented.

**ADR-0006 — a typed exception hierarchy carrying a `SafetyDisposition`.** An exception in a
safety path is a statement about what the system may now do, not just a bug report.
`FAIL_FAST` / `FAIL_CLOSED` / `FAIL_OPERATIONAL` attaches that statement to the type.

**ADR-0012 — separation invariants as executable contracts.** The implementation plan is explicit
that these must be verified "with a code-level check, not just a comment". They are data, they are
verified at startup, they are printed by the CLI, and five import-linter contracts plus the
architecture test suite enforce what is expressible statically.

---

## 5. Verification

The quality gate, run exactly as CI runs it:

| Check | Result |
|---|---|
| `ruff format --check .` | 89 files, clean |
| `ruff check .` | clean (34 rule families, including `D`, `ANN`, `S`, `BLE`, `T20`, `G`, `TID`) |
| `mypy --strict` | clean, 62 source files |
| `lint-imports` | 5 contracts kept, 0 broken |
| `pytest --cov=astra` | **1 418 passed**, **99.10%** coverage against a 95% gate |
| `astra doctor` | reports a healthy runtime, exit 0 |

Every number above came from a run performed for this report. None is projected.

**Properties demonstrated, not merely asserted:**

- A PASS added to a verdict set containing a shield VETO cannot change the aggregate; an empty
  verdict set aggregates to VETO.
- `IssuedCommand` refuses every non-L9 issuer (parametrised over all nine layers) and refuses an
  out-of-bounds command.
- `DecisionRecord.to_json()` round-trips byte-identically through `json.loads`/`json.dumps`.
- Loading `certification.toml` as shipped fails, naming all fourteen missing safety thresholds.
- The clock and `print()` rules were verified by injecting a violation and confirming the
  architecture tests fail, then reverting.

---

## 6. Risks

| ID | Risk | Severity | Position at end of Phase 1 |
|---|---|---|---|
| RK-1 | CARLA 0.9.14 requires Python ≤ 3.8; this project targets 3.12 (finding R-6) | **High** | **Unresolved, and the most consequential open item.** Contained: the simulator is behind a port and `.importlinter` forbids importing `carla` anywhere in the core. Must be decided in Phase 2 *before* any adapter code is written. |
| RK-2 | Hand-rolled EnbPI subtly wrong; the coverage guarantee silently invalid | **High** | Not yet started. Phase 5 must unit-test it in isolation on synthetic series before integration. |
| RK-3 | Closed-loop emergent dynamics | **High** | Mitigation is on schedule: the replay spine is Phase 2 work, not Phase 7 work, and the foundation it needs (deterministic identifiers, injected clock, immutable records) is delivered. |
| RK-8 | Overclaiming — the 1.25 µs figure, "eliminates hallucination", zero-failure | **High** | Actively managed. The honesty boundaries are in `README.md`; the 1.25 µs figure is labelled an analytical hardware WCET bound everywhere it appears; `EnforcementKind.REVIEW` exists so an unenforced invariant is visible rather than implied. |

---

## 7. Technical debt

Carried knowingly, each with the phase that clears it.

1. **SI-1, SI-2 and SI-5's import contracts are narrower than the invariants they claim to
   enforce.** SI-5's contract is commented out in `.importlinter` because it names layer modules
   that do not exist yet; SI-1's active contract covers only `kernel` and `invariants`. The
   catalogue's `mechanism` strings are therefore optimistic in the direction that matters least
   (the type-level enforcement is real) but they should be tightened as each layer lands.
   *Clears: Phases 3–4.*
2. **SI-9's checksum is stored and required non-empty, never verified.** Only the monotonicity
   half of "signed checksum plus quantile monotonicity" is enforced. *Clears: Phase 6.*
3. **SI-8 is classified `TEST` but no timing test exists.** What exists proves `emit` returns on a
   full queue, not that a tick meets a budget. *Clears: Phase 6.*
4. **`kernel-independence` forbids only `pydantic`.** NumPy arrives in Phase 2 and is the
   realistic future offender. *Clears: Phase 2.*
5. **`LayerId` has no `L7A`/`L7B`.** Finding R-3's split lives in the ports and in `GateId`, not
   in the layer enum; a reader following R-3's text will look for it there. Documented, not
   changed — adding two members would misrepresent L7 as two layers in every audit record.
6. **`ENGINEERING_HANDOFF.md`'s header and §9 status tables are a stale snapshot** ("~40%
   complete"). Everything in its §10 is now delivered. The document remains authoritative for
   architecture, reconciliation and roadmap; its status tables are not.

---

## 8. Readiness

**8.5 / 10.**

Earned: the module graph is enforced rather than described; the safety-critical properties are
structural rather than reviewed; coverage is 99% with the invariant tests verified to fail on
injected violations; the configuration cannot silently invent a safety threshold; the evidence
path is non-blocking and complete from tick zero.

Withheld: RK-1 is unresolved and is a Phase 2 gating decision, not a Phase 2 task. Three
invariants are enforced more narrowly than their statements claim (§7.1–7.3). And the foundation
has been exercised only by its own tests — no layer has yet used it in anger, which is the only
way some of these decisions will be properly tested.

**Ready for Phase 2.** The dependencies Phase 2 needs are all in place: a unit-typed
dimension-checked state estimate with covariance, an injected substitutable clock, deterministic
identifiers, an append-only evidence sink and an architecture harness that will fail the build if
L1 or L2 is wired in a way that breaks the layering.

**The first Phase 2 action is the R-6 spike** — resolve the CARLA/interpreter incompatibility
before writing adapter code. It is the one decision that could still change the shape of what
comes after, and the core is deliberately insulated from all three of its possible answers.

---

## 9. What must not be claimed

Carried forward because this report will be read alongside the papers:

- ASTRA has **run nothing**. There is no pipeline yet. No latency, coverage, false-positive or
  false-negative figure in any ASTRA document is a measurement, and none may be presented as one.
- The **1.25 µs Core-B intercept is an analytical hardware WCET bound** (AbsInt aiT, 500 MHz,
  627 cycles). The software prototype's real latency will be in the low milliseconds and must be
  reported against the < 5 ms software target.
- The **shared L2 state estimate is a genuine common-cause channel** across all three gates. It is
  mitigated by the innovation monitor and FB1. It is not eliminated, and saying otherwise would
  misrepresent the safety argument.
- The only measured numbers this report contains are the quality-gate results in §5, and they
  measure the foundation's own tests — not the governance of anything.
