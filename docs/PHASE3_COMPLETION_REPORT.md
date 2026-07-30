# Phase 3 — Engineering Completion Report

**Phase:** 3, Deterministic Safety Spine
**Status:** Complete. All four exit criteria met.
**Date:** 29 July 2026
**Scope delivered:** L7a Hard Safety Shield, L8 fail-safe state machine, and the one-way
Core-A → Core-B channel.

---

## 1. What this phase is for

Phase 3 builds the part of the safety argument that is least algorithmically uncertain and most
load-bearing. The shield's three bounds involve no learning, no statistics and no model: they are
arithmetic over the state estimate, and their authority comes precisely from that. The roadmap
puts them this early because every later phase needs a working veto path to be integrated
against — a statistical gate built before any veto exists has nothing to be wired to.

---

## 2. What was built

| Module | Responsibility |
|---|---|
| `layers/l7_shield/shield.py` | Three O(1) deterministic bounds; unconditional veto authority |
| `layers/l8_failsafe/machine.py` | Four-state FSM, OOD counter, hysteresis, latched HALT |
| `runtime/channels.py` | The one-way channel as a capability pair, plus two runtime guards |

### The shield's three bounds

| Bound | Form | Fails when |
|---|---|---|
| Tyre friction | `\|a_lat\| ≤ margin · μ_road · g` | the commanded lateral acceleration exceeds available grip |
| Stopping distance | `d_min + v²/(2·margin·μ·g) ≤ d_avail` | the vehicle cannot stop inside the distance its ODD assures |
| Legal speed | `v ≤ v_legal` | a legal limit is exceeded |

Using the **estimated** `μ_road` from the slow filter rather than a constant is what makes the
first two adaptive, and it is demonstrable: an identical state estimate and an identical proposal
PASS on dry tarmac and VETO on ice. A shield with a hard-coded friction figure passes both.

The three are separate because they fail for unrelated reasons. The stopping-distance bound is not
a restatement of the speed limit: on a wet road the legal speed can be perfectly lawful and still
leave the vehicle unable to stop.

### Why the FSM is a counter

One integer that increments on VETO and decrements on PASS gives three properties that would
otherwise need separate machinery: it distinguishes a glitch from a fault, recovery is the same
mechanism run backwards, and the whole history is reconstructible from one field per snapshot.

**HALT is deliberately asymmetric.** Every other transition is reversible on the counter; HALT is
not. A controlled pull-over is not something to reverse because a few ticks happened to pass, and
resuming automatically because a briefly-failed sensor started reporting plausible data again is
exactly what makes a fail-safe untrustworthy. Leaving HALT requires an explicit `reset()`.

### Why the channel is two types, not one queue

The obvious implementation is a shared queue with a comment saying Core-A must only call `put`.
A comment does not fail a build.

Instead the channel is a pair of endpoints with disjoint methods. Core-A holds a `ProposalWriter`
whose entire public surface is `send` and `pending` — **there is no method through which a verdict
could return.** Core-A cannot read a Core-B artefact through this channel not because it has been
told not to, but because the object it holds has no such method. That is the same technique
`IssuedCommand` uses for SI-7: make the illegal operation unrepresentable rather than forbidden.

---

## 3. Exit criteria

| Criterion | Result |
|---|---|
| No PASS from any component can suppress a shield VETO (SI-3) | **Met**, against a real shield verdict |
| The FSM walks NOMINAL → DEGRADED → LIMP → HALT and back without a restart | **Met** |
| Both layers' latency measured | **Met** |
| The one-way channel is a real topology, not a convention | **Met** |

**SI-3.** A shield VETO combined with PASSes from the statistical and physical gates aggregates to
VETO, in any order, and `vetoing_gates` names only `DETERMINISTIC`. Adding further PASSes cannot
change it. An empty verdict set aggregates to VETO — a command no gate inspected has not been
cleared, it has been missed.

**The FSM round trip**, driven only by verdicts with no `reset()` call:

```
NOMINAL --3 vetoes--> DEGRADED --3 more--> LIMP --8 passes--> NOMINAL
```

and separately, `NOMINAL --10 vetoes--> HALT`, which **200 subsequent clean ticks do not leave**.
Only `reset()` does.

**Latency**, macOS 15.7.3 / arm64, CPython 3.12.3, 2 000 samples after 200 warm-up ticks, via
[`benchmarks/latency.py`](../benchmarks/latency.py):

| Stage | p50 | p95 | p99 | max | budget |
|---|---|---|---|---|---|
| L1 acquire (fusion) | 0.003 | 0.003 | 0.004 | 0.047 | 1.0 |
| L2 `update_fast` (UKF) | 0.119 | 0.138 | 0.213 | 0.417 | 1.0 |
| **L7a shield (3 bounds)** | **0.003** | **0.003** | **0.003** | 0.035 | 1.0 |
| **L8 fail-safe FSM** | **0.002** | **0.003** | **0.004** | 0.084 | 1.0 |
| Hot path so far | 0.128 | 0.148 | 0.221 | 0.425 | 10.0 |

All figures in milliseconds, and all **software measurements** — not the 1.25 µs analytical
hardware WCET bound, which a Python prototype cannot measure.

The shield is the cheapest component in Core-B and the one with the strongest authority. That is
the correct relationship between the two, and it is worth noting that it arises from the design
rather than from optimisation: three comparisons and two multiplications, no allocation on the
nominal path beyond the verdict record, no iteration, no I/O.

---

## 4. Verification

| Check | Result |
|---|---|
| `ruff format --check .` | clean |
| `ruff check .` | clean |
| `mypy --strict` | clean |
| `lint-imports` | **8** contracts kept, 0 broken (up from 6) |
| `pytest --cov=astra` | **1 953 passed**, **99.10%** coverage against a 95% gate |

Two contracts became enforceable this phase and were added:

- **`si-3-shield-independence`** — the shield imports no other gate and no FSM. Its authority rests
  entirely on its bounds failing for a reason no other gate shares; a shield that imported the twin
  or the statistical gate would inherit their failure modes and the independence claim would be
  false. The FSM is named too: a shield that could read the posture could make its verdict depend
  on the posture its own verdict produces.
- **`l8-judges-verdicts-only`** — the machine imports no gate implementation, so it cannot weight
  one gate's veto above another's. That would give one gate more authority than the others and
  contradict SI-3's symmetry.

The invariant catalogue's enforcement claims were updated to match what is now genuinely enforced,
rather than what was planned. SI-5's mechanism now names the capability pair and the two runtime
guards; SI-3's names the two new import contracts.

---

## 5. Honest limitations

**`d_avail` is a certified ODD parameter, not a perceived distance.** The stopping-distance bound
compares against the clear distance the operational design domain assures, because the fast state
vector carries no distance-to-obstacle and SI-1 and SI-2 forbid the shield from re-reading the
sensors to find one. This is a weaker check than a perception-sourced one: it catches "too fast for
these conditions" but not "too fast for *that specific obstacle*". Sourcing `d_avail` from
perception requires extending the state vector, which is a visible architectural change and is
recorded here as debt rather than quietly approximated.

**SI-5's import contract is still inactive.** The capability pair and the runtime guards are real
and tested, but the `.importlinter` contract naming `astra.layers.l4_proposer` cannot be activated
until that module exists in Phase 4. The catalogue says so rather than implying otherwise.

**The shield's bounds are provisional.** `development.toml` and `simulation.toml` carry values
labelled as such. `certification.toml` refuses to load without them, which is the mechanism
designed to catch a permissive bring-up value that was never revisited.

---

## 6. Technical debt

1. `d_avail` from perception requires a state-vector extension (§5).
2. SI-5's import contract activates in Phase 4.
3. The hysteresis margin is a module constant rather than configuration. It is a property of the
   mechanism rather than an operating point, but if oscillation is ever observed in a long run
   that judgement should be revisited.
4. Carried forward: the UKF has met only synthetic dynamics; process noise is untuned; SI-9's
   checksum is stored but never verified; SI-8 has no timing test; FilterPy is unqualified.

---

## 7. Readiness

**8.5 / 10.**

Earned: every exit criterion met and demonstrated rather than asserted; the veto path now exists
end to end, so Phase 4 has something concrete to integrate against; two more invariants moved from
prose to build failures; the adaptive-friction property — the thing that makes this shield better
than a table of constants — is shown working through the real L1→L2→L7a path rather than on
hand-built records.

Withheld for the same reasons as Phase 2, plus the `d_avail` limitation: the state estimate the
shield judges has been validated only against synthetic dynamics, so the shield has been shown
correct against a world the filter modelled rather than one it observed.

**Ready for Phase 4** — the CMDP proposer and the PINN twin. That phase reaches Checkpoint 1: one
real scenario end to end with no feedback loops, proving independent gates, a deterministic veto
and the FSM. It is also where the SI-5 import contract activates and where SI-6 (veto-rate
exclusion) stops being review-only.

**Note on Phase 4's dependencies.** It needs PyTorch and Stable-Baselines3, and assumption A-6
flags their Python 3.12 support as a live risk that should be spiked early. GPU training time is
wall-clock bound and does not compress.

---

## 8. What must not be claimed

- **ASTRA still governs nothing end to end.** L1, L2, L7a and L8 exist. There is no proposer, no
  twin, no statistical gate and no arbitrator, so there is no pipeline and no false-positive or
  false-negative figure.
- **The latency figures are software measurements of four layers** on one machine, excluding the
  simulator, the audit sink, and L3, L4, L5, L6 and L9. They are a floor, not an estimate — and
  they are not the 1.25 µs hardware bound.
- **Gate independence is currently a claim about one gate.** With only the deterministic gate
  built, "three structurally independent gates" is architecture, not evidence. The evidence is the
  Phase 9 scenarios designed so that exactly one gate fires, and those cannot run yet.
- **The shield has been validated against a synthetic vehicle**, through a filter validated against
  the same synthetic vehicle.
