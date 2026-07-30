# ADR-0007: SI units internally via `NewType`; conversion only at boundaries

- **Status:** Accepted
- **Date:** 2026-07-29
- **Phase:** 1 (Foundation)

## Context

The ASTRA source documents mix unit systems freely, and they do it inside the same subsystem.

The Hard Safety Shield is specified as `a_lat <= mu*g`, in metres per second squared. The
sensor-fault injection scenario uses `15 m/s²`. The Fail-Safe FSM is specified with a `20 km/h` LIMP
cap and a `60 km/h` nominal recovery target. Bounded safe exploration limits steering to
`±15 degrees`, while every kinematic equation in the mathematical model is written in radians.

None of that is an error in the documents. Humans specify speed limits in km/h and steering limits
in degrees because that is how humans think about them, and physicists write kinematics in radians
because that is how the maths works. The error would be carrying both conventions into the same
codebase and relying on variable names to keep them apart.

A safety-critical control system that silently mixes unit systems has a latent defect of exactly the
kind that destroyed the Mars Climate Orbiter — a spacecraft lost because one team's pound-seconds
met another team's newton-seconds in an interface nobody had typed. The consequence here is the same
shape: a shield that computes `a_lat <= mu*g` with a km/h speed produces a number, and the number is
wrong by a factor of 3.6, and nothing about it looks wrong.

## Decision

**Every quantity crossing an ASTRA interface is in strict SI base units. Conversion happens only in
an adapter or in the configuration schema, at the boundary, explicitly, once.**

The policy is expressed with `typing.NewType` aliases over `float`, in
`src/astra/kernel/units.py`:

```python
Seconds = NewType("Seconds", float)
Metres = NewType("Metres", float)
Kilograms = NewType("Kilograms", float)
MetresPerSecond = NewType("MetresPerSecond", float)
MetresPerSecondSquared = NewType("MetresPerSecondSquared", float)
Radians = NewType("Radians", float)
RadiansPerSecond = NewType("RadiansPerSecond", float)
Hertz = NewType("Hertz", float)
```

Non-SI types exist, and their purpose is the opposite of convenience:

```python
KilometresPerHour = NewType("KilometresPerHour", float)  # boundaries only
Degrees = NewType("Degrees", float)  # boundaries only
Milliseconds = NewType("Milliseconds", float)  # boundaries only
```

They exist so that a non-SI value is **visibly** non-SI in a signature. They appear in configuration
files (which humans author) and in adapter code, and nowhere else.

The configuration schema shows the intended shape. A human writes `legal_speed_limit_kmh = 50.0`;
the field is named for its unit; and the accessor converts once:

```python
legal_speed_limit_kmh: PositiveFloat  # what the human wrote


@property
def legal_speed_limit(self) -> MetresPerSecond:  # what the pipeline reads
    return kmh_to_mps(KilometresPerHour(self.legal_speed_limit_kmh))
```

The conversion happens there and never again. The same pattern applies to `staleness_budget_ms` →
`staleness_budget: Seconds`, `exploration_steering_limit_deg` → `exploration_steering_limit:
Radians`, and both FSM speed caps.

**Enforcement.** `tests/architecture/test_invariants.py::test_no_non_si_unit_type_appears_in_a_port_signature`
parses every module in `src/astra/ports/` and asserts that neither `KilometresPerHour` nor `Degrees`
appears anywhere in it. The rule is not "please use SI at the boundary"; it is a failing test.

## Alternatives considered

**A runtime units library — `pint`, `astropy.units`.** Rejected on cost. Every arithmetic operation
allocates a wrapper object and dispatches through a unit registry, which is a 50–100× penalty on
arithmetic. The software latency target is < 5 ms for the Core-B intercept path and < 10 ms
end-to-end at a 20 Hz tick. Paying that on the hot path to buy a check a type checker performs
statically, for free, is a bad trade — and it is a trade that gets worse as the pipeline fills in.

The honest counterpoint: `pint` would catch unit errors that `NewType` does not, including the
arithmetic-propagation gap described below. If ASTRA were an offline analysis tool rather than a
hard real-time one, `pint` would probably be the right answer.

**Plain `float` with a naming convention (`speed_mps`, `steering_rad`).** Rejected. A convention
that is not machine-checked is a comment, and comments do not fail builds. It also degrades exactly
when it matters — under time pressure, in a hurried refactor, at the interface between two people's
code.

**Dimensional-analysis dataclasses of our own** (a `Quantity` type with exponents). Rejected. It
reproduces `pint` badly, adds runtime cost, and puts a numerics library inside the kernel — which
ADR-0011 rules out for separate reasons.

**Allow non-SI internally and convert at the point of use.** Rejected. It means every consumer must
know which convention its supplier used, which is the Mars Climate Orbiter failure restated as a
policy.

## Consequences

### Positive

- Static unit safety at literally zero runtime cost. `MetresPerSecond(3.0)` **is** `3.0` — `NewType`
  is erased at runtime and costs one function call at construction only — while mypy treats the
  alias as a distinct type. Passing a `Radians` where a `MetresPerSecond` is expected is a build
  failure.
- The unit policy is enforced at the boundary that matters most: every signature in `astra.ports`,
  checked by an architecture test rather than by review.
- Configuration stays human-authorable. A safety engineer writes km/h and degrees, and the
  conversion is visible, single-sited and reviewable.
- Future state vectors become self-documenting. The fast UKF state annotates as
  `tuple[Metres, Metres, MetresPerSecond, Radians, MetresPerSecondSquared]`, which makes the
  *ordering* of that vector a type-level fact and mis-ordering a type error rather than a silent
  physical-nonsense result.
- No dependency added. The kernel stays importable by an offline tool with nothing installed.

### Negative / accepted trade-offs

- **`NewType` does not propagate through arithmetic.** `a + b` where both are `Metres` infers as
  `float`, not `Metres`. This is the decision's real weakness and it is not small: the moment a
  quantity is computed rather than passed, the type is gone, and re-wrapping (`Metres(a + b)`) is a
  manual step nothing enforces. It is tolerated because the alternative is runtime cost on a hard
  real-time path, and because the port signatures — the boundary where a mistake crosses between
  components — are fully protected.
- **`NewType` is not a runtime check.** `MetresPerSecond("fast")` type-checks as an error but
  executes fine, and a value loaded from JSON or TOML arrives as a bare `float` with no alias at
  all. The type is a static claim about provenance, not a runtime guarantee.
- **Re-wrapping is noise.** `Metres(float(x))` appears wherever a value re-enters the typed world,
  and it reads as ceremony to someone who has not read this ADR.
- **The boundary is enforced for `ports/` only.** The architecture test scans `src/astra/ports/`.
  Nothing stops `KilometresPerHour` appearing in a future layer's internals, and the convention
  there rests on review.
- **Two names for one quantity.** `legal_speed_limit_kmh` and `legal_speed_limit` are the same
  operating point in two units. A reader who grabs the wrong one gets a plausible number. The
  naming convention (`_kmh`, `_ms`, `_deg` suffix means non-SI) is the only thing distinguishing
  them, which is a convention — the very thing this ADR rejected elsewhere. It is accepted here
  because the two live adjacent in one small class, under review, rather than scattered.
- **Milliseconds sits awkwardly.** It is non-SI and therefore boundary-only, but "50 ms" is how
  FR1 states the staleness rule and how every engineer will discuss it. The conversion to `Seconds`
  is correct and will still surprise people reading a log line in seconds.
