# ADR-0011: Packed lower-triangular `SymmetricMatrix`; no NumPy in the kernel

- **Status:** Accepted
- **Date:** 2026-07-29
- **Phase:** 1 (Foundation)

## Context

Covariance matrices are load-bearing in three places in ASTRA.

`P_f`, the fast UKF covariance, supplies `σ(x) = sqrt(P_f[control dim])` — the locally adaptive
normalisation in the ICP non-conformity score. This is the mechanism by which the statistical gate
widens its acceptance band when state estimation is less certain, and it is one of the paper's
headline contributions. `S_t`, the innovation covariance, drives the Mahalanobis sensor-fault
monitor. And each calibration profile in the Knowledge Base stores a certified covariance alongside
its RCS centroid, used for RCM's Mahalanobis distance in the cold-path search.

All three are symmetric by definition. The question is how to represent them.

The obvious answer — a NumPy array — collides with two of Phase 1's foundational decisions.
Contract records are frozen and slotted (ADR-0008), and a NumPy array is mutable and unhashable, so
a record containing one would be frozen in name only: `record.covariance[0, 0] = 999` succeeds on a
frozen dataclass, because freezing prevents attribute rebinding, not mutation of what the attribute
points at. And the kernel is the module every other module imports; ADR-0002 and the
`kernel-independence` contract keep its dependency set empty so an offline evidence-analysis tool, a
certification script or the dashboard process can import ASTRA's vocabulary without the numerical
stack.

NumPy will certainly be a dependency of this project from Phase 2 onward — FilterPy and PyTorch both
require it. The question is not whether NumPy is used, but whether it is used *in the kernel*.

## Decision

**Store the lower triangle, not the full matrix.**

```python
@dataclass(frozen=True, slots=True)
class SymmetricMatrix:
    dimension: int
    lower_triangle: tuple[float, ...]  # (a00, a10, a11, a20, a21, a22, ...)
```

`n(n+1)/2` entries in row-major lower-triangular order rather than `n²`. For the 5×5 fast covariance
that is 15 stored numbers rather than 25.

The argument is not compression. It is that **storing all `n²` entries makes it *possible* to
represent an asymmetric matrix**, which then has to be checked for, reported on and repaired at
every boundary it crosses. Storing the lower triangle makes asymmetry *unrepresentable* — the
illegal state simply has no encoding. This is the same principle as `SafetyVerdict` having no trust
field (SI-4) and `Instant` carrying its timeline: prefer the representation in which the defect
cannot be expressed.

**No NumPy in the kernel.** `SymmetricMatrix` is pure Python, with a hand-written Cholesky
factorisation. A 5×5 Cholesky is roughly 40 floating-point operations — the interpreter overhead of
calling into NumPy is comparable to just doing the arithmetic at that size.

**`to_rows()` is the interoperability seam.** Phase 2's UKF converts to and from NumPy at its own
boundary, where the mutation is contained. The kernel never sees an array.

Validation runs once, in `__post_init__`: the dimension must be a positive `int` (and explicitly not
a `bool`), the packed length must match `n(n+1)/2`, and every element must be finite — because a NaN
in a covariance defeats every comparison downstream rather than failing one, which is the fail-open
mode `NonFiniteValueError` exists to catch.

## Alternatives considered

**NumPy arrays inside contract records.** Rejected on two counts, both fatal on their own. A NumPy
array is mutable, so a "frozen" record containing one is frozen in name only, and the immutability
argument that underpins gate independence (ADR-0008) collapses. And it is unhashable, so records
containing one cannot be dictionary keys or set members — which the audit correlation structures
use. Adding NumPy to the kernel would also break the offline-importability property that
`kernel-independence` enforces, and that property is why a certification script can read an
evidence archive on a machine with nothing installed.

**Full `n²` storage with a symmetry check at construction.** Rejected. It converts "asymmetry is
impossible" into "asymmetry is detected", which is strictly weaker: the check must be run at every
boundary, it needs a tolerance (`1e-9` here, in the `from_rows` path), and a tolerance is a
judgement call that someone will eventually get wrong. It also stores 40% more numbers for a 5×5.

**A `frozen`-wrapping NumPy subclass**, or `array.setflags(write=False)`. Rejected. Read-only
NumPy views can be defeated (`arr.base`, `arr.view()`), the read-only flag is not preserved by every
operation, and it still puts NumPy in the kernel.

**`tuple[tuple[float, ...], ...]` — immutable nested tuples, full matrix.** Rejected. Immutable and
hashable, so it fixes the freezing problem, but it keeps asymmetry representable and adds a second
level of indirection on every element access.

**Defer the matrix type to Phase 2, when NumPy arrives.** Rejected under the same reasoning that put
units and identifiers in Phase 1: the contracts that carry covariances are being written *now*, and
a contract whose covariance field changes type in Phase 2 is a contract change, which means an audit
schema change, which means an evidence archive migration.

## Consequences

### Positive

- Asymmetry is unrepresentable rather than merely checkable. There is no code path that produces an
  asymmetric `SymmetricMatrix`, so there is no code path that needs to check for one.
- Contract records containing a covariance are genuinely frozen and genuinely hashable.
- The kernel's dependency set stays empty, enforced by `kernel-independence` with
  `allow_indirect_imports = False`. An offline tool imports ASTRA's vocabulary with `pip install
  astra` and nothing else.
- 40% less storage for the 5×5 fast covariance, which at 20 Hz with a per-tick record is not nothing.
- Constructor validation catches NaN at the boundary, where a NaN in a covariance would otherwise
  propagate into `σ(x)` and turn a VETO into a PASS.
- Property-based tests (`tests/property/test_matrix_props.py`) exercise symmetry and Cholesky over
  generated inputs, which is where hand-written examples systematically miss edge cases. The module
  is at 100% coverage.

### Negative / accepted trade-offs

- **A hand-written Cholesky is code this project now owns and must get right.** It is a
  well-understood algorithm and it is property-tested, but it is still numerical code in a safety
  path that a NumPy dependency would have provided from a far more heavily exercised implementation.
  This is the most honest objection to the decision, and the counterweight is that a 5×5 factorisation
  is small enough to test exhaustively in a way a general LAPACK path is not.
- **Pure Python arithmetic does not scale.** At 5×5 the interpreter overhead is comparable to the
  arithmetic. At 50×50 it would be a serious cost, and if a later phase needs larger covariances the
  representation will need to move — with the conversion pushed to the `to_rows()` seam rather than
  into the kernel.
- **`to_rows()` is an allocation.** Every NumPy interop hop materialises the full `n²` matrix. On
  the Phase 2 UKF path that happens at least once per filter step, which partly gives back the
  storage saving.
- **Packed indexing is easy to get wrong.** `row * (row + 1) // 2 + column` is correct and it is not
  obvious. Anyone touching the storage layout must think carefully, and the failure mode is silently
  reading the wrong element — which produces a plausible number, not an exception.
- **The 40-flop figure is an operation count, not a measurement.** No Cholesky timing has been
  taken. It is an argument that the size is small, not a benchmark, and it must not be quoted as
  performance evidence.
- **The kernel's purity is enforced against pydantic and `carla` by name.** `kernel-independence`
  lists specific forbidden modules; it does not forbid third-party imports in general. Adding `numpy`
  to the kernel would break the *intent* immediately and the *contract* only if someone remembers to
  add it to the list.
