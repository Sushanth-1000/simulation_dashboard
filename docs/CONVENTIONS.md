# Conventions

The coding standards this repository holds to, why each exists, and how each is enforced. These
are the conventions from the engineering handoff's "conventions that must not drift" list, with the
reasoning that produced them.

The organising principle: **a convention that is not machine-checked is a comment, and comments do
not fail builds.** Where a rule can be made mechanical it has been. Where it cannot, this document
says so plainly rather than implying an enforcement that does not exist.

For how to run the checks, see [`DEVELOPMENT.md`](DEVELOPMENT.md).

---

## Summary

| # | Convention | Enforced by |
|---|---|---|
| 1 | Absolute imports only | ruff `TID252` (`ban-relative-imports = "all"`) + architecture test |
| 2 | No package facade re-exports | Review |
| 3 | Docstring on every public symbol, Google convention | ruff `D` |
| 4 | Full type annotations | ruff `ANN` + `mypy --strict` |
| 5 | No magic numbers | Review, with the constant/configuration test |
| 6 | SI units internally; non-SI only at boundaries | Architecture test over `ports/` + `NewType` aliases |
| 7 | Never `assert` for a safety check | Review (`S101` is on in `src/`, off in `tests/`) |
| 8 | Never a bare `except` | ruff `BLE` |
| 9 | Never `time.time()` — use the injected `Clock` | Review + composition-root discipline |
| 10 | Never `print()` outside `bootstrap/cli.py` | ruff `T20` + architecture test |
| 11 | No f-strings in logging calls | ruff `G` |
| 12 | Fail closed | Runtime guards + architecture tests |
| 13 | Every claim traceable | Review — the honesty rule |
| 14 | Frozen slotted dataclasses on the hot path | Review + ADR-0008 |
| 15 | pydantic only at boundaries | import-linter `kernel-independence` + review |

---

## 1. Absolute imports only

```python
from astra.kernel.units import Metres  # yes
from .units import Metres  # no
from ..kernel import units  # no
```

**Rationale.** A relative import is resolved against the *file's* position, so moving a module
silently re-points its imports at whatever now occupies the old location. An absolute import fails
loudly instead — and loudly is the correct behaviour in a codebase whose module layering is a
safety property. Absolute imports also make the dependency graph readable without knowing where the
file sits, which is what lets import-linter's contracts be reviewed as prose.

**Enforced by.** ruff rule `TID252`, configured project-wide:

```toml
[tool.ruff.lint.flake8-tidy-imports]
ban-relative-imports = "all"
```

plus `tests/architecture/test_layering.py::test_no_kernel_module_uses_a_relative_import`, which
walks the kernel's AST directly.

---

## 2. No package facade re-exports

Import a symbol from the module that defines it. Do not add convenience re-exports to
`__init__.py`.

```python
from astra.kernel.errors import ConfigurationError  # yes
from astra.kernel import ConfigurationError  # no — not provided, and must not be
```

**Rationale.** Three costs, all paid later.

- A facade hides the real dependency. `from astra.kernel import X` tells a reviewer nothing about
  which module the importing code actually depends on, and import-linter's contracts become harder
  to reason about at exactly the point where reasoning matters.
- Facades create import cycles. A package `__init__.py` that re-exports from every submodule must
  import every submodule, so importing any one of them imports all of them — and a genuinely
  layered package cannot survive that.
- It doubles the public surface. Every symbol then has two valid import paths, both of which
  appear in the codebase, and renaming means changing both.

`src/astra/kernel/__init__.py`, `contracts/__init__.py`, `ports/__init__.py` and
`observability/__init__.py` are documentation-only: a module docstring and no re-exports. Coverage
confirms it — those files report zero statements.

**Enforced by.** Review. A re-export in `__init__.py` is valid Python and valid to every tool in
the gate; nothing will stop you. This is the convention most likely to erode, so it is the one to
watch for in review.

---

## 3. Docstring on every public symbol

Google convention, with `Args:` / `Returns:` / `Raises:` sections wherever they apply. A
`Raises:` section is not optional when the function raises: it is part of the contract, because in
this codebase an exception carries a `SafetyDisposition` and therefore states what the runtime may
do next.

Verbatim from `src/astra/kernel/validation.py`:

```python
def require_probability(value: float, *, name: str, layer: LayerId | None = None) -> Probability:
    """Require a value in the closed unit interval.

    Used for the Trust Index, conformal coverage levels, the Calibration
    Divergence Index, per-profile validation fractions and every normalised
    component of the Runtime Context Signature.

    Args:
        value: The value to check.
        name: Field name for diagnostics.
        layer: The layer performing the check, when known.

    Returns:
        The value as a :data:`~astra.kernel.units.Probability`.

    Raises:
        NonFiniteValueError: If the value is NaN or infinite.
        RangeViolationError: If the value lies outside ``[0, 1]``.
    """
```

**Rationale.** The audit log has a human safety assessor among its consumers, and so does the
source. A docstring on a contract record is the only place the *meaning* of a field lives — that
`FAST_STATE_FIELDS` ordering is architectural, that `friction_margin` below 1.0 is a safety margin,
that `coverage_level` has no default on purpose. A type signature cannot carry any of that.

Module docstrings in this codebase go further than describing the module: they record why it exists
and which alternatives were rejected. `kernel/units.py`, `kernel/errors.py`, `kernel/matrix.py`,
`kernel/time.py` and `kernel/identifiers.py` each contain the reasoning that also appears in an ADR.
That duplication is deliberate — the reader who opens the source should not have to find the ADR.

**Enforced by.** ruff `D` rules with `convention = "google"`. `D203` and `D213` are disabled because
they conflict with `D211` and `D212` respectively; the project takes no blank line before a class
docstring, and the summary on the first line. `tests/**` is exempt from `D100`–`D104`: a test's name
is its documentation, and `test_an_empty_verdict_set_is_a_veto_because_an_uninspected_command_is_not_a_cleared_one`
says more than a docstring would.

---

## 4. Full type annotations

Every parameter, every return, every attribute. `mypy --strict` is a gate, not advice.

```toml
[tool.mypy]
python_version = "3.12"
files = ["src", "tests"]
strict = true
warn_unreachable = true
enable_error_code = [
    "redundant-expr", "possibly-undefined", "truthy-bool",
    "ignore-without-code", "explicit-override",
]
disallow_any_unimported = true
```

**Rationale.** Retrofitting strict typing onto an existing codebase costs roughly an order of
magnitude more than starting with it, and `astra.contracts` is precisely where a silent type error
becomes a safety defect: a `Radians` passed where a `MetresPerSecond` is expected is not a style
issue, it is a physically meaningless command. Non-strict mypy was rejected as theatre — it reports
what it can prove without `Any`, which in an untyped codebase is very little.

Four of the extra error codes earn their place specifically here:

- **`explicit-override`** pairs with `typing.override` so "this was meant to override something"
  is a checked claim rather than a comment.
- **`ignore-without-code`** forbids blanket `# type: ignore`. Every suppression names its rule, so
  a reviewer can see which check was waived. The kernel uses exactly this: `# type: ignore[redundant-expr]`
  on the deliberate `isinstance` guards in `Instant` and `SymmetricMatrix`, each with a comment
  explaining that the values arrive from adapters and persisted records where the annotation is a
  claim, not a guarantee.
- **`possibly-undefined`** catches the branch that forgot to assign.
- **`disallow_any_unimported`** stops an untyped third-party package from silently turning a whole
  signature into `Any`.

Tests are type-checked too. The one relaxation is `disallow_untyped_defs = false` for `tests.*`,
which keeps test bodies readable while still checking every call they make.

**Enforced by.** ruff `ANN` (annotation presence) and mypy (annotation correctness). The two are
complementary: `ANN` catches the missing annotation, mypy catches the wrong one.

---

## 5. No magic numbers

A number in the source is one of exactly two things:

- an **architectural constant** — it lives in `src/astra/kernel/constants.py`, under review, with a
  git history; or
- **configuration** — it lives in `config/`, and a safety engineer may change it without a code
  review.

There is no third category.

**The test:** *if this value changed, would the change be reviewed by a software engineer or by a
safety engineer?* Software engineer means constant. Safety engineer means configuration.

Applied: `RCS_DIMENSION = 5` is a constant, because changing it invalidates every certified
profile's centroid and covariance in the Calibration Knowledge Base and forces re-certification —
that is an architecture change wearing a number's clothing. `innovation_gate_gamma` is
configuration, because it is an operating point that differs between the development, simulation
and certification environments and is determined empirically.

`CORE_B_GATE_COUNT = 3` deserves its own note. Three is load-bearing: the independence argument
requires each gate to have a distinct failure mode, so a fourth gate sharing a failure mode with an
existing one would weaken the argument while appearing to strengthen it. The constant is asserted
against the `GateId` enumeration by the architecture tests, so adding a gate without updating the
architecture documentation fails the build.

**Rationale.** A literal buried in an expression is invisible to review and unattributable in
evidence. Worse, in this system the two categories have different *authorities*: a safety threshold
in source is a threshold a safety engineer cannot change without a developer, and a structural
constant in configuration is a structural change nobody reviewed.

**Enforced by.** Review. No linter can distinguish 9 (the layer count) from 9.0 (a Mahalanobis
gate). `PLR2004` (magic value in comparison) is active in `src/` and off in `tests/**`, which helps
but does not decide the question.

Related and mechanical: **no safety threshold has a default.** `θ1/θ2/θ3`, `ε`, `γ`, `τ`, `δ_CDI`
and the shield bounds are required fields in `astra.config.schema`, and
`config/environments/certification.toml` ships with every one of them commented out. Loading it
raises `ConfigurationError [ASTRA-CFG-001]`. See [`ASSUMPTIONS.md`](ASSUMPTIONS.md) A-4.

---

## 6. SI units internally; non-SI only at boundaries

Every quantity crossing an ASTRA interface is in strict SI base units. Conversion happens only in
an adapter or in the configuration schema, explicitly, once.

```python
Seconds = NewType("Seconds", float)
Metres = NewType("Metres", float)
MetresPerSecond = NewType("MetresPerSecond", float)
Radians = NewType("Radians", float)

# Permitted at boundaries only — they exist so that a non-SI value is *visibly*
# non-SI in a signature.
KilometresPerHour = NewType("KilometresPerHour", float)
Degrees = NewType("Degrees", float)
```

**Rationale.** The source documents mix unit systems freely: the Hard Safety Shield is specified in
m/s², the Fail-Safe FSM in km/h speed caps, safe exploration in ±15 degrees, and every kinematic
equation in radians. A safety-critical control system that silently mixes those has a latent defect
of exactly the kind that destroyed the Mars Climate Orbiter.

`NewType` was chosen over a runtime units library (`pint`, `astropy.units`) and over a naming
convention (`speed_mps`). A units library allocates a wrapper and dispatches through a registry on
every arithmetic operation — a 50–100× penalty on a path with a < 5 ms Core-B intercept target and
a < 10 ms end-to-end budget at 20 Hz, paid to buy a check a type checker performs statically. A
naming convention is not machine-checked, so it is a comment.

**Trade-off, stated honestly:** `NewType` does not propagate through arithmetic. `a + b` where both
are `Metres` infers as `float`, not `Metres`. That is a real weakness. It is accepted because the
alternative is runtime cost on a hard real-time path, and because the boundary that matters most —
every signature in `astra.ports` — is fully protected.

**Enforced by.** mypy, for the aliases themselves; and
`tests/architecture/test_invariants.py::test_no_non_si_unit_type_appears_in_a_port_signature`, which
parses every module in `src/astra/ports/` and asserts that neither `KilometresPerHour` nor `Degrees`
appears. The configuration schema shows the intended pattern: the field is
`legal_speed_limit_kmh` (a human wrote it, in km/h), and the accessor
`ShieldSettings.legal_speed_limit` returns `MetresPerSecond`. The conversion happens there and
never again.

See [ADR-0007](adr/0007-si-units-via-newtype.md).

---

## 7. Never `assert` for a safety check

```python
assert value >= 0.0, "must be non-negative"  # NO — deleted by python -O

if value < 0.0:  # yes
    raise RangeViolationError(...)
```

**Rationale.** `python -O` removes every `assert` statement. A safety check written as an assertion
is a check that disappears in exactly the deployment configuration where it matters most — an
optimised production interpreter. This is not a hypothetical: `-O` is a normal thing to set on an
embedded or containerised deployment for the bytecode-size saving.

The whole of `src/astra/kernel/validation.py` exists because of this rule. `require_finite`,
`require_range`, `require_probability`, `require_non_negative`, `require_positive`,
`require_dimension` and `require_non_decreasing` are ordinary `if` statements that raise typed
`ContractViolationError` subclasses, so the behaviour is identical in every interpreter mode.

`require_finite` deserves the specific note its docstring gives it: NaN is checked more often than
anything else because it is the only value that *defeats* a comparison rather than failing it.
`nan > threshold` is `False`, so a NaN non-conformity score turns a VETO into a PASS. That is a
fail-open mode, and it is why the check has its own error class.

**Where guards run.** At boundaries — a value entering from a sensor, a configuration file, a
calibration profile, an adapter. Not between internal layers on the hot path. Re-validating a value
that a frozen record already validated at construction buys nothing and spends the tick budget; the
type carries the guarantee from there.

**Enforced by.** Review. ruff `S101` is enabled in `src/` and disabled for `tests/**`, where
`assert` is the point of the file — so the rule helps but does not decide. A safety-path assert in
`src/` reads identically to any other.

---

## 8. Never a bare `except`

```python
except AstraError:              # yes
except ConfigurationError:      # better
except Exception:               # no
except:                         # no
```

**Rationale.** `AstraError` is the base of every failure ASTRA models and understands. Catching it
catches exactly those, and leaves genuine programming errors — `TypeError`, `AttributeError`,
`KeyError` — to propagate, where they belong. A bare `except Exception` in a safety path erases
that distinction: a `NameError` from a typo in a rarely-taken branch becomes indistinguishable from
a modelled sensor timeout, and the system continues in a state nobody reasoned about.

`from error` on every re-raise. The chained cause is part of the diagnostic record; dropping it
turns a five-minute fix into an afternoon.

**Enforced by.** ruff `BLE` (blind-except), project-wide, with no per-file exemptions. This rule is
called out explicitly in `pyproject.toml`'s comment: *a bare `except` in a safety path hides
faults.*

---

## 9. Never `time.time()`

Every component that needs the time receives a `Clock` through its constructor. No component reads
a global clock.

**Rationale.** Three separate requirements, any one of which would be sufficient.

1. **Correctness.** The sensor bus must flag a stream whose staleness exceeds 50 ms. Staleness is a
   *duration*, and durations must be measured on a monotonic timeline. The wall clock is not
   monotonic: an NTP correction, a leap-second smear or a VM migration can move it backwards, and a
   negative staleness silently reads as "perfectly fresh". That is a fail-open mode.
2. **Replay.** The prototype plan requires tooling that can freeze and replay a tick range, and
   states that building it during closed-loop integration rather than before is the difference
   between debugging in hours and in days. Replay is impossible if components read a global clock;
   the recorded timeline has to be substitutable for the live one.
3. **Simulation.** CARLA in synchronous mode advances simulated time in fixed steps that do not
   track wall-clock time. A pipeline measuring its own latency against the wall clock while the
   simulator advances on its own timeline is comparing two different things.

`Instant` carries integer nanoseconds and its `Timeline` (`SYSTEM_MONOTONIC`, `SIMULATED`,
`MANUAL`). Subtracting instants from different timelines raises rather than returning a number,
because "simulated tick time minus wall-clock arrival time" is a perfectly valid float expression
and a meaningless quantity.

**Enforced by.** Review, plus composition-root discipline: `bootstrap/composition.py` is the only
module permitted to construct a concrete `SystemClock`, so a layer that wanted the wall clock would
have to import `time` itself — visible in review. No blanket lint ban is possible, because
`astra.kernel.time` imports `time` legitimately.

> **Known gap.** The `Clock` protocol's docstring claims the architecture suite forbids `time` and
> `datetime` imports outside that module. No such test exists in `tests/architecture/`. The property
> does hold today — `src/astra/kernel/time.py` is the only module in `src/astra/` importing either —
> but by discipline, not enforcement. Write the test or fix the docstring.

See [ADR-0010](adr/0010-injected-clock.md).

---

## 10. Never `print()` outside `bootstrap/cli.py`

**Rationale.** Diagnostic output for a human at a terminal is not logging, and routing it through
the logging pipeline would subject it to level filtering and JSON formatting — wrong for both. So
the CLI prints, and nothing else does.

Everywhere else, a `print()` is one of three things: debugging left behind, a log line that escaped
the logging system (and therefore carries no correlation context and reaches no audit file), or
unbounded synchronous I/O on the hot path. All three are defects.

**Enforced by.** ruff `T20`, with exactly one exemption:

```toml
"src/astra/bootstrap/cli.py" = ["T20"]  # the CLI is the one place print() is correct
```

plus two architecture tests — one asserting `print` appears nowhere else, and one asserting the
exempted module actually exists, so the exemption cannot outlive the file it exempts.

---

## 11. No f-strings in logging calls

```python
logger.info("tick %s exceeded budget by %s ms", tick, overrun)  # yes
logger.info(f"tick {tick} exceeded budget by {overrun} ms")  # no
```

**Rationale.** The lazy form pays the formatting cost only if a handler actually emits the record.
The f-string pays it always — including when the level is filtered out, including on the hot path,
including in production where `DEBUG` is off. At 20 Hz with dozens of records per tick, formatting
strings that are immediately discarded is measurable work spent on nothing.

Two secondary benefits. The message template stays constant, so records are groupable by template
across a run — the f-string produces a unique string per call and defeats that. And a structured
JSON formatter can carry the arguments as fields rather than embedding them in prose, which is what
lets diagnostic logs be joined to audit records on run and tick without a parsing regex.

**Enforced by.** ruff `G` (flake8-logging-format), project-wide.

---

## 12. Fail closed

The absence of a verdict is a VETO. An empty verdict set is a VETO. No PASS from any component can
suppress a VETO.

**Rationale.** This is SI-3, the unconditional-veto invariant, and it mirrors the hardware FMEA
mitigation for a silent Core-B crash: the crossbar defaults to VETO on a missed heartbeat. A
command that was never inspected is not a cleared command. Any aggregation rule that treats
"nothing said no" as "yes" converts a crash into a permission.

The same reasoning shapes the exception hierarchy. Every `AstraError` carries a
`SafetyDisposition`:

| Disposition | Meaning |
|---|---|
| `FAIL_FAST` | Cannot start or continue defensibly. Configuration and invariant violations. Refusing to start is safe; starting under an unverified configuration is not |
| `FAIL_CLOSED` | The pipeline could not complete its judgement. The command under inspection is treated as VETOed and the fail-safe FSM sees a VETO event |
| `FAIL_OPERATIONAL` | The failure is outside the safety argument — a dashboard socket dropping, an evidence file failing to write. Only failures that provably cannot influence a command carry this |

An exception in a safety path is not merely a bug report; it is a statement about what the system
is now permitted to do. Attaching the disposition to the *type* turns "handle errors carefully"
from a review-time hope into a property of the class.

**Enforced by.** `Verdict.merge`, `SafetyVerdict.aggregate` and the runtime guard
`guard_verdict_aggregation`, backed by architecture tests including
`test_an_empty_verdict_set_is_a_veto_because_an_uninspected_command_is_not_a_cleared_one` and
`test_a_single_veto_survives_any_number_of_passes`. For *new* aggregation code, only by review —
which is why new aggregation code should be rare.

---

## 13. Every claim traceable

A number that appears in a report, a dashboard, a paper or a demo must come from a record that a
run produced. Nothing is hardcoded to look good.

**Rationale.** This is the project's honesty rule, and it is the one that matters most, because it
is the only one whose violation damages credibility rather than code. The source corpus already
contains a cautionary example: an earlier draft of the paper reported a "21-minute run" and "≈47
evidence tuples" as achieved results, and the current paper states plainly that the prototype and
all its metrics are planned, not executed. Reconciliation finding R-2 resolves this as: nothing is
a result until code produces it.

Three specific standing obligations:

- **The 1.25 µs Core-B intercept figure is an analytical hardware WCET bound** (AbsInt aiT,
  500 MHz, 627 cycles). It is not measurable by a Python prototype and must never be reported as a
  measurement. Software latency is reported against the software target of < 5 ms.
- **False positive/negative targets are < 1%, not zero.** The argument is defence in depth through
  structurally independent gates, never "eliminates hallucination".
- **The shared L2 state estimate is an acknowledged residual common-cause channel** across all
  three gates — mitigated by the innovation monitor and FB1, not eliminated. State it every time,
  do not hide it.

The mechanism that makes traceability possible: every `DecisionRecord` carries the hash of the
resolved configuration it ran under, so two runs producing different verdicts from identical code
are distinguishable by evidence rather than by memory. `development.toml` and `simulation.toml`
both carry a banner saying their thresholds are provisional and nothing produced under them may be
reported as a result.

A related and equally important honesty rule lives in `EnforcementKind`: an invariant marked
`REVIEW` in `src/astra/invariants/catalogue.py` is one the codebase does *not* mechanically
enforce, and it says so. `astra invariants list` reports SI-6 as review-only today. Upgrading that
marker before the enforcement exists would be the same defect as reporting an unmeasured latency.

**Enforced by.** Nothing. No tool checks it. This is the convention that depends entirely on the
people writing the code.

---

## 14. Frozen, slotted dataclasses on the hot path

Every record that layers exchange:

```python
@dataclass(frozen=True, slots=True)
class Instant:
    nanoseconds: int
    timeline: Timeline = Timeline.SYSTEM_MONOTONIC

    def __post_init__(self) -> None: ...  # validate here, once
```

**Rationale.** Three properties, each load-bearing.

- **`frozen=True` — immutability.** A downstream layer cannot mutate a record an upstream layer
  already consumed. In a pipeline where L5, L6 and L7 all read the same state estimate, a mutable
  record means the third gate may be judging a different value than the first — which would silently
  destroy the gate-independence argument that is the system's central claim.
- **`slots=True` — no per-instance `__dict__`.** Smaller and faster attribute access, measurable at
  20 Hz with dozens of records per tick. It also makes a typo'd attribute assignment an
  `AttributeError` rather than a new field nobody reads.
- **Validate once at construction, then trust.** `__post_init__` runs the boundary guards; every
  subsequent hop reads plain attributes. This is what makes the hot path allocation-light: the
  alternative — validating on every hop — spends the tick budget re-proving something already
  proven.

Frozen and slotted together also give hashability and safe use as dictionary keys, which matters
for the correlation structures the audit path builds.

**Enforced by.** Review, and by the pattern being universal in `src/astra/contracts/` and
`src/astra/kernel/`. mypy will catch an attempted mutation of a frozen instance.

See [ADR-0008](adr/0008-frozen-dataclasses-pydantic-at-boundaries.md).

---

## 15. pydantic only at boundaries

pydantic appears in exactly one package: `src/astra/config/`. It is not permitted in `kernel`, and
it does not appear in `contracts`, `ports` or `invariants`.

**Rationale.** Configuration and calibration profiles are parsed **once**, at startup, from text a
human wrote. That is exactly the boundary pydantic is for: rich validation with error messages that
name the file, the field and the constraint. `extra="forbid"` turns a typo in a TOML key into a
startup error instead of a silently ignored line — and a misspelled safety threshold that is quietly
dropped leaves the system running on a different value than the file appears to specify, which is
the worst failure mode a configuration file has.

Inside the pipeline, the same machinery is the wrong trade. pydantic validates on every construction;
the hot path constructs many records per tick and needs the guarantee to have been established once.
So: pydantic at the boundary, frozen dataclasses within. The settings objects are frozen after load
and read as plain attributes thereafter, which is O(1) and allocation-free.

**Enforced by.** The `kernel-independence` contract in `.importlinter`, which forbids `astra.kernel`
from importing `pydantic` or `pydantic_settings` with `allow_indirect_imports = False` — so a
transitive path counts too. Beyond the kernel, review; the layering contract keeps `config` above
`contracts` and `ports`, which prevents the dependency from flowing the wrong way.

---

## Also mechanically enforced, without further comment

These need no essay. They are on because the rule is right and the cost is zero.

| Rule | Effect |
|---|---|
| `DTZ` | No naive datetimes. A timestamp without a timezone is a defect here |
| `ERA` | No commented-out code. Git remembers it; the file should not |
| `PTH` | `pathlib` over `os.path` |
| `SLF` | No private-member access across objects (relaxed in `tests/**`) |
| `S` | bandit security rules |
| `T10` | No debugger imports left behind |
| `EM`, `TRY` | Exception messages as named variables, not inline literals; no exception anti-patterns |
| `RUF`, `B`, `PERF`, `FURB`, `SIM`, `C4` | Correctness and clarity |
| `filterwarnings = ["error"]` | A warning in a safety codebase is a defect, not noise |

`PLR0913` (too many arguments) is deliberately ignored: safety records legitimately carry many
fields, and splitting `DecisionRecord` to satisfy an argument count would make the evidence harder
to read, not easier.
