# ADR-0002: Domain-independent platform core with adapters, not a CARLA-coupled prototype

- **Status:** Accepted
- **Date:** 2026-07-29
- **Phase:** 1 (Foundation)

## Context

The Prototype & Demo Plan proposes a flat module layout for the prototype — `core/`, `feedback/`,
`comms/` — with no packaging, no test tree and no configuration layer. It is a sensible shape for
something that has to work in four weeks and be demonstrated once.

Two things pull against it.

The first is NFR5, from the requirements authority: *"The architecture shall be domain-independent…
new operational contexts through the addition of certified profiles without modification to any
other component."* The papers make claims about applicability beyond automotive on that basis. A
prototype in which `tyre_friction`, `lane_change` and a CARLA vehicle handle are threaded through
the gate logic cannot support those claims, and extracting them afterwards is a migration, not a
refactor.

The second is reconciliation finding R-6, which is more immediate: the documents mandate Python
3.10+ *and* CARLA 0.9.14, whose official Python client ships for Python 2.7/3.6/3.7/3.8 only. Those
requirements are incompatible as stated. If the simulator client is imported anywhere in the core,
that incompatibility becomes an architectural constraint on the whole project — every module would
have to run on an interpreter the rest of the toolchain has abandoned.

So the question in Phase 1 was whether to build the Demo Plan's prototype layout or a packaged
platform core with the simulator held at arm's length. This was confirmed with the project owner
and recorded as reconciliation finding R-11.

## Decision

Build a **domain-independent platform core** under `src/astra/`, with a hexagonal (ports-and-
adapters) boundary. Every module the Demo Plan proposed maps to a new home; the architecture is
respected, only the packaging is upgraded.

Concretely:

- **Layer interfaces are structural `Protocol` classes** in `src/astra/ports/pipeline.py`
  (`SensorSource`, `StateEstimator`, `TrustEstimator`, `CommandProposer`, `DynamicsPredictor`,
  `StatisticalGate`, `PhysicalAdmissibilityChecker`, `DeterministicShield`, `SafetyStateMachine`,
  `CalibrationArbiter`) and infrastructure interfaces in `ports/infrastructure.py` (`EventSink`,
  `ProfileRepository`, `ActuationSink`, `FeedbackBus`).
- **Structural typing, not abstract base classes.** An adapter implementing `SensorSource` does not
  import an ASTRA base class, so the dependency arrow points inward: the CARLA adapter will know
  about ASTRA and ASTRA will never know about CARLA.
- **The actuation space is configured data, not fixed controls.** `ActuationChannel` and
  `ActuationSpace` in `src/astra/contracts/actuation.py` describe what a plant accepts; they do not
  hardcode throttle, brake and steering.
- **Sensor payloads are opaque behind a type parameter.** `SensorSample[PayloadT]` and
  `FusedSensorFrame[PayloadT]` mean the core moves and times sensor data without ever knowing what
  a LiDAR sweep looks like — which is simultaneously the enforcement mechanism for SI-1 (sensor
  opacity) and the reason a non-automotive sensor needs no core change.
- **`src/` layout with hatchling**, so tests always exercise the installed package.
- **The prohibition is mechanical.** `.importlinter` carries a `simulator-isolation` contract
  forbidding *any* module in `astra` from importing `carla`, and
  `tests/architecture/test_layering.py::test_no_module_in_the_core_imports_the_simulator_client`
  walks the AST as an independent second check.

## Alternatives considered

**The Demo Plan's flat prototype layout, coupled to CARLA.** Rejected. It fails NFR5 outright, and
it converts R-6 from a deployment question into an architectural one — the whole project would be
pinned to whatever interpreter the simulator client supports. The Demo Plan is the implementation
authority on *what to build in what order*, and that guidance is retained in full; it is not the
authority on packaging, and its own §9 layout carries no tests, no configuration and no
architectural enforcement.

**Abstract base classes instead of protocols.** Rejected. An ABC forces the adapter to inherit
from an ASTRA class, which means the adapter imports the core. That is the correct direction for a
plugin system and the wrong one for a safety island: it makes the core a dependency of every
integration, and it means an adapter's mistake can reach the core through inheritance. Structural
protocols cost nothing at runtime and keep the arrow pointing the right way. `JsonlAuditSink`
demonstrates the pattern — it satisfies `EventSink` without inheriting from it, and says so in its
docstring.

**Write the core generically but let the simulator be imported "just in the sensor layer".**
Rejected. A single permitted import is not a boundary; it is a boundary that has already been
crossed once. The contract is written against the whole `astra` package precisely so that there is
no argument about where the exception starts. The eventual adapter will be added to the contract's
exclusions explicitly, as a reviewed change.

**Defer the decision — build coupled, extract later.** Rejected on the strength of the counter-check
in the handoff: introducing `tyre_friction` into the core and extracting it afterwards is a
migration, and it would land in the phase with the least slack. Phase 1 costs days; that discovery
costs weeks.

## Consequences

### Positive

- R-6 is now a deployment detail. Whichever of the three routes resolves the CARLA interpreter
  problem — newer CARLA, a community wheel, or a Python 3.8 sidecar bridged to the 3.12 core — the
  core is unaffected. That is what makes assumption A-8's "without changing the core" clause
  credible rather than hopeful.
- The pipeline can be assembled from fakes before any layer exists. A five-line test double
  satisfies a structural protocol with no inheritance and no registration, which is what makes
  "validate layer X in isolation before wiring it" achievable.
- SI-1 is enforced by the type system rather than by review: a layer that cannot name the payload
  type cannot read it.
- The dependency-free kernel plus the isolation contract means an offline evidence-analysis tool, a
  certification script or the dashboard process can import ASTRA's vocabulary without installing a
  simulator or a numerical stack.
- The 1:1 mapping from the Demo Plan's proposed modules to their new homes is recorded, so the
  implementation guidance in that document is still directly usable.

### Negative / accepted trade-offs

- **More indirection than a four-week prototype needs.** Ten ports, seven contract modules and a
  composition root exist before a single layer does. Anyone joining to write L2 must first read
  interfaces they did not design. This is a genuine cost paid up front for a benefit that arrives
  in Phase 6.
- **Domain independence is claimed, not demonstrated.** No non-automotive profile exists. The core
  still contains automotive vocabulary that is defensible as *configured* domain rather than
  hardcoded — `road_friction_coefficient` and `tyre_wear_index` in `SLOW_STATE_FIELDS`,
  `legal_speed_limit_kmh` in `ShieldSettings` — but the argument rests on prose until a second
  profile exists. That is assumption A-1, and it stays HOLDING until Phase 6.
- **Structural typing checks less than nominal typing.** `runtime_checkable` protocols verify
  *method presence only*, never signatures. An adapter with the right method names and the wrong
  parameter types passes the composition root's `isinstance` sanity check and fails at the call
  site. mypy catches this statically; a dynamically loaded adapter is not covered.
- **The simulator isolation contract will need an exception**, and the moment it gets one, the
  guarantee weakens from "nothing imports carla" to "one reviewed module imports carla". That is
  the intended design, but it is worth naming: the contract's strength today is partly an artefact
  of the adapter not existing yet.
- **Generic payloads propagate.** `SensorSample[PayloadT]` means the type parameter threads through
  `FusedSensorFrame`, `SensorSource` and everything downstream that touches a frame. It is more
  type machinery than a concrete payload type would need, and PEP 695 syntax is part of why the
  Python floor is 3.12 (ADR-0003).
