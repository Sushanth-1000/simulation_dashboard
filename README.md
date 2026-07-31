# ASTRA

**Autonomous Safety, Trust, and Runtime Architecture**
Runtime governance for AI-controlled cyber-physical systems.

> **Confidential — unpublished proprietary work.** An intended patent filing covers this
> architecture. Do not distribute, demonstrate externally, or publish any part of this
> repository until the filing status is confirmed. See [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).

---

## What ASTRA is

An AI controller in a safety-critical system can be structurally healthy — no bit flips, no
crashes, correct by every classical definition — and still issue a semantically wrong command
to a physical actuator, because the world it faces at runtime no longer matches the world it
was trained in.

Existing infrastructure does not catch this. Lockstep processors replicate the same wrong
answer on both cores. Hypervisors isolate execution domains without inspecting what crosses
them. Hardware security modules authenticate a command's origin, not whether it was a good
idea.

ASTRA governs the **actuation boundary**. It treats the AI controller as an *untrusted
proposer* and interposes an independent nine-layer pipeline between it and the actuators. Every
proposed command is validated three ways — statistically, physically, and against hard
deterministic bounds — by gates with structurally different failure modes, and the whole system
recalibrates itself from what actually happened.

```
                    L1  Shared Sensor Bus
                     │
                    L2  Dual-Rate UKF  ──────────────┐ state + covariance
                     │                               │
          ┌──────────┴──────────┐                    │
         L3 Conformal Trust    L4 Core-A (CMDP)      │
          │  Trust Index TI     │                    │
          │                     │ π_prop  (ONE-WAY)  │
          │                     ▼                    │
          │        ┌──────── CORE-B (safety island) ─┴──────┐
          │        │  L5 PINN twin  →  physical gate        │
          │        │  L6 MPC + ICP  →  statistical gate     │
          │        │  L7 Hard Shield → deterministic gate   │
          │        │  L8 Fail-Safe FSM                      │
          │        └────────────────┬───────────────────────┘
          │                         │ verdict + FSM state
          └────────────►  L9  RCM (sole actuator authority)
                                    │
                                 Actuators
                                    │
              FB1 · FB2 · FB3 · FB4 └── outcomes fed back upstream
```

Three gates, three unrelated ways to fail: the statistical gate fires on a statistical anomaly,
the physical gate on a violation of Newtonian admissibility, the deterministic gate on a hard
bound. The Hard Safety Shield's veto is unconditional and cannot be overridden by any other
component's PASS.

---

## Project status

| | |
|---|---|
| **Current phase** | **All ten layers built and composed. The pipeline runs end to end.** |
| Implemented | All of **L1–L9** · the tick loop composing them · trained digital twin · calibration corpus · replay spine · one-way Core-A→Core-B channel |
| Not yet implemented | Trained PPO policy, the four feedback loops, the CARLA adapter, the dashboard |
| Quality gate | Green — 2 459 tests, 98.2% coverage, `ruff` + `mypy --strict` + **12** `lint-imports` contracts clean |
| Invariants | 10 declared; **9 mechanically enforced** including SI-8 and SI-9, which were partial until now. SI-6 is review-only until a trained policy exists. |
| Measured | Full ten-layer tick p99 **1.98 ms** — 4% of a 50 ms tick. Software measurement. |
| Next | Linux + CARLA (needs hardware), then the PPO policy — see [`docs/PROJECT_STATE_AND_ROADMAP.md`](docs/PROJECT_STATE_AND_ROADMAP.md) |

> **R-6 resolved.** CARLA 0.9.16 publishes an official CPython 3.12 wheel, so the interpreter
> incompatibility that was this project's highest-rated technical risk no longer exists. CARLA has
> no macOS build, however, so simulator work needs a Linux x86-64 host — see
> [`docs/adr/0015-carla-interpreter-strategy.md`](docs/adr/0015-carla-interpreter-strategy.md).

Phase 1 deliberately contained **no layer logic** — only the vocabulary, contracts, interfaces,
invariants, configuration and evidence machinery every layer depends on. Phase 2 added the first
two layers and the replay spine on top of it. The reasoning is in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## Quick start

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/). No simulator and no GPU are needed:
everything through Phase 2 is developed and tested against in-process fakes.

```bash
git clone <repository-url> astra && cd astra
uv sync --all-groups --all-extras   # create .venv and install everything
uv run astra doctor           # verify the installation and print the environment report
uv run astra config show      # render the effective, fully-resolved configuration
uv run astra invariants list  # print the separation invariants and their enforcement
```

Run the full quality gate exactly as CI does:

```bash
make check     # format check + lint + type check + architecture contracts + tests
```

Or individually:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run lint-imports              # architecture fitness contracts
uv run pytest --cov=astra
```

See [`docs/INSTALL.md`](docs/INSTALL.md) for a full environment setup and
[`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) for the day-to-day workflow.

---

## Repository layout

```
astra/
├── src/astra/
│   ├── kernel/          Units, identifiers, time, errors, validation, enums, constants
│   ├── contracts/       The immutable records layers exchange
│   ├── ports/           Protocol interfaces for L1–L9 and infrastructure
│   ├── invariants/      Separation invariants SI-1 … SI-10, with enforcement
│   ├── config/          Layered, validated, startup-frozen settings
│   ├── observability/   Audit log, correlation context, structured logging
│   ├── layers/          The pipeline layers themselves
│   │   ├── l1_sensing/      Shared sensor bus: fusion and staleness
│   │   ├── l2_estimation/   Dual-rate UKF and the innovation monitor
│   │   ├── l7_shield/       Hard Safety Shield: three deterministic bounds
│   │   └── l8_failsafe/     Four-state fail-safe machine
│   ├── runtime/         Channels between layers; the one-way Core-A→Core-B pair
│   ├── replay/          Record a run's inputs; replay it byte-identically
│   └── bootstrap/       Composition root and CLI
├── config/              Default and per-environment configuration files
├── benchmarks/          Reproducible software latency measurement
├── stubs/               Local type stubs for untyped dependencies
├── docs/                Architecture, roadmap, conventions, assumptions, ADRs, spikes
└── tests/
    ├── unit/            Behaviour of individual modules
    ├── integration/     Layers wired together
    ├── property/        Hypothesis-driven invariants
    └── architecture/    Fitness tests over the codebase's own structure
```

Every directory's purpose, and why it exists rather than the obvious alternative, is documented
in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## Documentation

| Document | What it answers |
|---|---|
| [`docs/PROJECT_STATE_AND_ROADMAP.md`](docs/PROJECT_STATE_AND_ROADMAP.md) | **Start here.** Complete state: everything built, every file, every phase remaining to a working prototype |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | How the system is put together and why |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | What each future phase builds, and on what |
| [`docs/SEPARATION_INVARIANTS.md`](docs/SEPARATION_INVARIANTS.md) | The safety argument, invariant by invariant |
| [`docs/DOCUMENT_RECONCILIATION.md`](docs/DOCUMENT_RECONCILIATION.md) | Every contradiction found across the four source documents, and how it was resolved |
| [`docs/ASSUMPTIONS.md`](docs/ASSUMPTIONS.md) | What was assumed where the documents were silent |
| [`docs/CONVENTIONS.md`](docs/CONVENTIONS.md) | Coding standards this repository enforces |
| [`docs/INSTALL.md`](docs/INSTALL.md) | Environment setup |
| [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) | Workflow, quality gate, adding a layer |
| [`docs/adr/`](docs/adr/) | Architecture Decision Records — one per significant choice |
| [`docs/PHASE1_COMPLETION_REPORT.md`](docs/PHASE1_COMPLETION_REPORT.md) | What Phase 1 delivered, its risks and its debt |
| [`docs/PHASE2_COMPLETION_REPORT.md`](docs/PHASE2_COMPLETION_REPORT.md) | What Phase 2 delivered, the R-6 resolution, seven defects found |
| [`docs/PHASE3_COMPLETION_REPORT.md`](docs/PHASE3_COMPLETION_REPORT.md) | What Phase 3 delivered: the shield, the FSM, and the unsuppressable veto |
| [`docs/spikes/`](docs/spikes/) | Technical decision spikes, with sources |

---

## Honesty boundaries

Carried forward verbatim from the Prototype & Demo Plan, because they constrain what this
codebase may claim:

1. The **1.25 µs Core-B intercept latency is an analytical hardware bound**, not a measurement.
   The software prototype's real latency will be in the low milliseconds, and must be reported
   against the software target of < 5 ms, never against the hardware figure.
2. False positive/negative targets are **< 1%, not zero**. The argument is defence in depth
   through structurally independent gates, never "eliminates hallucination".
3. The **shared UKF state is an acknowledged residual common-cause channel** across all three
   gates — mitigated by the innovation monitor and FB1, not eliminated.
4. Conformal prediction's coverage guarantee **assumes exchangeability**, which adversarial
   perturbation violates by construction. That is why there is more than one gate.
5. The PINN twin will be trained on **simulated dynamics**, not real vehicle physics.
6. Core-B here is **Python processes, not fabricated hardware**. FPGA/ASIC is roadmap, not done.

Any metric this repository reports must come from code that ran. Nothing is hardcoded to look
good in a demo.
