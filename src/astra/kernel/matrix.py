"""An immutable symmetric matrix, used for every covariance in the system.

Where covariances appear in ASTRA
---------------------------------
* ``P_f`` -- the fast UKF covariance. Its diagonal supplies ``sigma(x) =
  sqrt(P_f[control dim])``, the locally adaptive normalisation in the ICP
  non-conformity score. This is the mechanism by which the statistical gate
  widens its acceptance band when state estimation is less certain, and it is
  one of the paper's headline contributions.
* ``S_t`` -- the innovation covariance, used by the Mahalanobis sensor-fault
  monitor.
* The certified covariance stored alongside each calibration profile's RCS
  centroid, used for RCM's Mahalanobis distance in the cold-path search.

Design decision: store the lower triangle, not the full matrix
--------------------------------------------------------------
A covariance matrix is symmetric by definition. Storing all ``n^2`` entries
makes it *possible* to represent an asymmetric matrix, which then has to be
checked for, reported on and repaired. Storing the ``n(n+1)/2`` lower-triangular
entries makes asymmetry unrepresentable -- the illegal state simply has no
encoding. For the 5x5 fast covariance that is 15 stored numbers rather than 25.

Design decision: no NumPy dependency in the kernel
--------------------------------------------------
NumPy will certainly be a dependency of this project from Phase 2 onward, since
FilterPy and PyTorch both require it. It is nonetheless kept out of the kernel
for two reasons. First, a NumPy array is mutable and unhashable, so embedding
one in a frozen record would make that record frozen in name only. Second, the
kernel is the module every other module imports; keeping its dependency set
empty means the contracts can be imported by an offline evidence-analysis tool,
a dashboard process or a certification script without pulling in the numerical
stack. :meth:`SymmetricMatrix.to_rows` is the interoperability seam: Phase 2's
UKF converts to and from NumPy at its own boundary, where the mutation is
contained.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Self

from astra.kernel.errors import ContractViolationError, DimensionMismatchError
from astra.kernel.validation import require_finite

__all__ = ["SymmetricMatrix"]

_DEFAULT_SYMMETRY_TOLERANCE = 1e-9


def _triangular_index(row: int, column: int) -> int:
    """Return the packed index of a lower-triangular element.

    Args:
        row: Row index, zero-based.
        column: Column index, zero-based, not greater than ``row``.

    Returns:
        The index of the element within the packed lower-triangular storage.
    """
    return row * (row + 1) // 2 + column


@dataclass(frozen=True, slots=True)
class SymmetricMatrix:
    """A symmetric matrix stored as a packed, immutable lower triangle.

    Attributes:
        dimension: The matrix order ``n``.
        lower_triangle: ``n(n+1)/2`` values in row-major lower-triangular order,
            that is ``(a00, a10, a11, a20, a21, a22, ...)``.
    """

    dimension: int
    lower_triangle: tuple[float, ...]

    def __post_init__(self) -> None:
        """Validate the packed representation.

        Raises:
            ContractViolationError: If the dimension is not a positive integer.
            DimensionMismatchError: If the packed length is inconsistent with
                the declared dimension.
            NonFiniteValueError: If any element is NaN or infinite.
        """
        # Deliberately checked despite the annotation: covariances are
        # reconstructed from persisted records and from the NumPy seam, where
        # the declared type is an expectation rather than a guarantee.
        if not isinstance(self.dimension, int) or isinstance(  # type: ignore[redundant-expr]
            self.dimension, bool
        ):
            message = f"matrix dimension must be an int, got {type(self.dimension).__name__}"
            raise ContractViolationError(message)
        if self.dimension < 1:
            message = f"matrix dimension must be >= 1, got {self.dimension}"
            raise ContractViolationError(message, context={"dimension": self.dimension})

        expected = self.dimension * (self.dimension + 1) // 2
        if len(self.lower_triangle) != expected:
            message = (
                f"a {self.dimension}x{self.dimension} symmetric matrix needs "
                f"{expected} packed elements, got {len(self.lower_triangle)}"
            )
            raise DimensionMismatchError(
                message,
                context={"dimension": self.dimension, "expected": expected},
            )
        for index, value in enumerate(self.lower_triangle):
            require_finite(value, name=f"covariance[{index}]")

    # ----------------------------------------------------------------- #
    # Construction
    # ----------------------------------------------------------------- #

    @classmethod
    def from_rows(
        cls,
        rows: Sequence[Sequence[float]],
        *,
        symmetry_tolerance: float = _DEFAULT_SYMMETRY_TOLERANCE,
    ) -> Self:
        """Build a matrix from a full square array, verifying symmetry.

        The tolerance exists because a covariance produced by floating-point
        arithmetic -- a UKF update, for instance -- is symmetric in exact
        arithmetic but typically differs in the last bits. Rejecting such a
        matrix outright would be pedantry; accepting an arbitrarily asymmetric
        one would be negligence. The lower triangle is the value retained.

        Args:
            rows: A square, nested sequence of numbers.
            symmetry_tolerance: Maximum permitted ``|a_ij - a_ji|``.

        Returns:
            The packed symmetric matrix.

        Raises:
            DimensionMismatchError: If the input is not square.
            ContractViolationError: If asymmetry exceeds the tolerance.
        """
        dimension = len(rows)
        for row_index, row in enumerate(rows):
            if len(row) != dimension:
                message = (
                    f"row {row_index} has {len(row)} elements, "
                    f"expected {dimension} for a square matrix"
                )
                raise DimensionMismatchError(
                    message, context={"row": row_index, "dimension": dimension}
                )

        for row_index in range(dimension):
            for column_index in range(row_index):
                upper = rows[column_index][row_index]
                lower = rows[row_index][column_index]
                if abs(upper - lower) > symmetry_tolerance:
                    message = (
                        f"matrix is not symmetric at ({row_index}, {column_index}): "
                        f"{lower!r} vs {upper!r}"
                    )
                    raise ContractViolationError(
                        message,
                        context={
                            "row": row_index,
                            "column": column_index,
                            "difference": abs(upper - lower),
                        },
                    )

        packed = tuple(
            rows[row_index][column_index]
            for row_index in range(dimension)
            for column_index in range(row_index + 1)
        )
        return cls(dimension=dimension, lower_triangle=packed)

    @classmethod
    def from_diagonal(cls, diagonal: Sequence[float]) -> Self:
        """Build a diagonal matrix.

        The common case for an initial filter covariance and for a profile
        whose certified dimensions are treated as independent.

        Args:
            diagonal: The diagonal entries.

        Returns:
            The corresponding symmetric matrix with zero off-diagonal entries.

        Raises:
            ContractViolationError: If the diagonal is empty.
        """
        dimension = len(diagonal)
        packed = tuple(
            diagonal[row_index] if row_index == column_index else 0.0
            for row_index in range(dimension)
            for column_index in range(row_index + 1)
        )
        return cls(dimension=dimension, lower_triangle=packed)

    # ----------------------------------------------------------------- #
    # Access
    # ----------------------------------------------------------------- #

    def at(self, row: int, column: int) -> float:
        """Return a single element, exploiting symmetry.

        Args:
            row: Zero-based row index.
            column: Zero-based column index.

        Returns:
            The element value.

        Raises:
            DimensionMismatchError: If either index is out of bounds.
        """
        if not (0 <= row < self.dimension and 0 <= column < self.dimension):
            message = (
                f"index ({row}, {column}) is outside a {self.dimension}x{self.dimension} matrix"
            )
            raise DimensionMismatchError(
                message, context={"row": row, "column": column, "dimension": self.dimension}
            )
        if column > row:
            row, column = column, row
        return self.lower_triangle[_triangular_index(row, column)]

    @property
    def diagonal(self) -> tuple[float, ...]:
        """Return the diagonal entries, i.e. the per-dimension variances.

        Returns:
            A tuple of ``dimension`` values.
        """
        return tuple(self.at(index, index) for index in range(self.dimension))

    def variance_of(self, index: int) -> float:
        """Return the variance of one state dimension.

        The accessor the ICP gate uses to obtain ``P_f[control dim]`` before
        taking its square root. Named rather than indexed so that the call site
        reads as the physical quantity it is.

        Args:
            index: The state dimension, ordered per
                :data:`astra.kernel.constants.FAST_STATE_FIELDS`.

        Returns:
            The variance of that dimension.

        Raises:
            DimensionMismatchError: If the index is out of bounds.
        """
        return self.at(index, index)

    def to_rows(self) -> tuple[tuple[float, ...], ...]:
        """Expand to a full square nested tuple.

        The interoperability seam for NumPy, JSON serialisation and any
        consumer that expects a dense matrix.

        Returns:
            A ``dimension x dimension`` nested tuple.
        """
        return tuple(
            tuple(self.at(row, column) for column in range(self.dimension))
            for row in range(self.dimension)
        )

    # ----------------------------------------------------------------- #
    # Numerical properties
    # ----------------------------------------------------------------- #

    def has_admissible_diagonal(self) -> bool:
        """Return whether every variance is non-negative.

        A cheap ``O(n)`` necessary -- but not sufficient -- condition for a
        valid covariance. Provided separately from the full definiteness test
        because it is affordable on the hot path, whereas a factorisation is
        not. A ``False`` result is conclusive evidence of filter corruption; a
        ``True`` result is only the absence of the most obvious symptom.

        Returns:
            ``True`` if no diagonal entry is negative.
        """
        return all(value >= 0.0 for value in self.diagonal)

    def cholesky_factor(self, *, tolerance: float = 1e-12) -> tuple[float, ...] | None:
        """Attempt a Cholesky factorisation, returning the packed lower factor.

        Implemented in pure Python because the matrices involved are at most
        5x5: the fast UKF state, the slow UKF state and the Runtime Context
        Signature. A 5x5 factorisation is roughly 40 floating-point operations,
        far cheaper than the cost of reaching for a linear-algebra dependency
        inside the kernel.

        Args:
            tolerance: A pivot at or below this value is treated as
                non-positive, so a numerically singular matrix fails rather
                than producing a factor built from a near-zero divisor.

        Returns:
            The packed lower-triangular Cholesky factor ``L`` with
            ``A = L L^T``, or ``None`` if the matrix is not positive definite.
        """
        dimension = self.dimension
        factor = [0.0] * (dimension * (dimension + 1) // 2)

        for row in range(dimension):
            for column in range(row + 1):
                accumulated = self.at(row, column)
                for inner in range(column):
                    accumulated -= (
                        factor[_triangular_index(row, inner)]
                        * factor[_triangular_index(column, inner)]
                    )
                if row == column:
                    if accumulated <= tolerance:
                        return None
                    factor[_triangular_index(row, column)] = math.sqrt(accumulated)
                else:
                    factor[_triangular_index(row, column)] = (
                        accumulated / factor[_triangular_index(column, column)]
                    )
        return tuple(factor)

    def is_positive_definite(self, *, tolerance: float = 1e-12) -> bool:
        """Return whether the matrix is positive definite.

        Positive *definiteness* is checked rather than positive
        semi-definiteness, deliberately. A singular covariance asserts that some
        direction of the state is known exactly, which for a UKF tracking a
        physical vehicle means the filter has collapsed rather than that it has
        become certain. Treating that as acceptable would let a collapsed filter
        drive ``sigma(x)`` to zero and, with it, the ICP acceptance band --
        turning a state-estimation failure into an unbounded statistical gate.
        It is a fault, and it should be reported as one.

        Args:
            tolerance: Pivot threshold passed to :meth:`cholesky_factor`.

        Returns:
            ``True`` if a Cholesky factorisation exists.
        """
        return self.cholesky_factor(tolerance=tolerance) is not None
