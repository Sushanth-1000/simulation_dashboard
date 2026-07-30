"""Properties of the packed symmetric matrix used for every covariance.

Symmetry is unrepresentable-otherwise by construction, so the properties worth
generating over are the ones the packing could still get wrong: the expansion
back to a dense form, the triangular indexing, and the factorisation that the
statistical gate's ``sigma(x)`` ultimately rests on.
"""

from __future__ import annotations

import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from astra.kernel.matrix import SymmetricMatrix

pytestmark = pytest.mark.property

# See the note in test_units_props: Hypothesis' deadline is not the project's
# latency budget, and asserting one here would make the suite machine-dependent.
_SETTINGS = settings(deadline=None, max_examples=150)

_MAX_DIMENSION = 5
_RELATIVE_TOLERANCE = 1e-7
_ABSOLUTE_TOLERANCE = 1e-9

_DIMENSIONS = st.integers(min_value=1, max_value=_MAX_DIMENSION)
_ENTRIES = st.floats(
    min_value=-100.0,
    max_value=100.0,
    allow_nan=False,
    allow_infinity=False,
    allow_subnormal=False,
)
_POSITIVE_ENTRIES = st.floats(
    min_value=1e-3,
    max_value=1e3,
    allow_nan=False,
    allow_infinity=False,
    allow_subnormal=False,
)
_OFF_DIAGONALS = st.floats(
    min_value=-2.0,
    max_value=2.0,
    allow_nan=False,
    allow_infinity=False,
    allow_subnormal=False,
)
_FACTOR_DIAGONALS = st.floats(
    min_value=0.5,
    max_value=3.0,
    allow_nan=False,
    allow_infinity=False,
    allow_subnormal=False,
)


def _packed_index(row: int, column: int) -> int:
    """Return the packed offset of a lower-triangular element.

    Args:
        row: Zero-based row index.
        column: Zero-based column index, not greater than ``row``.

    Returns:
        The offset within packed lower-triangular storage.
    """
    return row * (row + 1) // 2 + column


def _element(packed: tuple[float, ...], row: int, column: int) -> float:
    """Return an element of a packed lower-triangular factor, zero above the diagonal.

    Args:
        packed: The packed lower triangle.
        row: Zero-based row index.
        column: Zero-based column index.

    Returns:
        The element value, or ``0.0`` in the strict upper triangle.
    """
    if column > row:
        return 0.0
    return packed[_packed_index(row, column)]


def _times_transpose(packed: tuple[float, ...], dimension: int) -> list[list[float]]:
    """Compute ``L @ L.T`` for a packed lower-triangular factor.

    Args:
        packed: The packed lower-triangular factor.
        dimension: The matrix order.

    Returns:
        The dense product as nested lists.
    """
    return [
        [
            math.fsum(
                _element(packed, row, inner) * _element(packed, column, inner)
                for inner in range(dimension)
            )
            for column in range(dimension)
        ]
        for row in range(dimension)
    ]


@st.composite
def symmetric_matrices(draw: st.DrawFn) -> SymmetricMatrix:
    """Return an arbitrary small symmetric matrix.

    Args:
        draw: Hypothesis' draw callable.

    Returns:
        A symmetric matrix of order 1 to 5.
    """
    dimension = draw(_DIMENSIONS)
    packed = draw(
        st.lists(
            _ENTRIES,
            min_size=dimension * (dimension + 1) // 2,
            max_size=dimension * (dimension + 1) // 2,
        )
    )
    return SymmetricMatrix(dimension=dimension, lower_triangle=tuple(packed))


@st.composite
def positive_definite_matrices(draw: st.DrawFn) -> SymmetricMatrix:
    """Return a matrix built as ``L L^T`` from a well-conditioned lower factor.

    Args:
        draw: Hypothesis' draw callable.

    Returns:
        A positive definite symmetric matrix of order 1 to 5.
    """
    dimension = draw(_DIMENSIONS)
    factor: list[float] = []
    for row in range(dimension):
        for column in range(row + 1):
            if row == column:
                factor.append(draw(_FACTOR_DIAGONALS))
            else:
                factor.append(draw(_OFF_DIAGONALS))
    rows = _times_transpose(tuple(factor), dimension)
    return SymmetricMatrix.from_rows(rows)


@st.composite
def diagonals_with_a_negative_entry(draw: st.DrawFn) -> list[float]:
    """Return a diagonal containing at least one strictly negative variance.

    Args:
        draw: Hypothesis' draw callable.

    Returns:
        The diagonal entries.
    """
    dimension = draw(_DIMENSIONS)
    diagonal = draw(st.lists(_ENTRIES, min_size=dimension, max_size=dimension))
    index = draw(st.integers(min_value=0, max_value=dimension - 1))
    diagonal[index] = -draw(_POSITIVE_ENTRIES)
    return diagonal


# --------------------------------------------------------------------------- #
# Symmetry and the dense round trip
# --------------------------------------------------------------------------- #


@_SETTINGS
@given(matrix=symmetric_matrices())
def test_element_access_is_symmetric_for_every_index_pair(matrix: SymmetricMatrix) -> None:
    for row in range(matrix.dimension):
        for column in range(matrix.dimension):
            assert matrix.at(row, column) == matrix.at(column, row)


@_SETTINGS
@given(matrix=symmetric_matrices())
def test_expanding_to_rows_and_packing_again_reproduces_the_matrix(
    matrix: SymmetricMatrix,
) -> None:
    restored = SymmetricMatrix.from_rows(matrix.to_rows())
    assert restored.dimension == matrix.dimension
    assert restored.lower_triangle == matrix.lower_triangle
    assert restored == matrix


@_SETTINGS
@given(matrix=symmetric_matrices())
def test_the_dense_expansion_is_square_and_symmetric(matrix: SymmetricMatrix) -> None:
    rows = matrix.to_rows()
    assert len(rows) == matrix.dimension
    assert all(len(row) == matrix.dimension for row in rows)
    for row in range(matrix.dimension):
        for column in range(matrix.dimension):
            assert rows[row][column] == rows[column][row]


@_SETTINGS
@given(matrix=symmetric_matrices())
def test_the_diagonal_property_agrees_with_element_access(matrix: SymmetricMatrix) -> None:
    diagonal = matrix.diagonal
    assert len(diagonal) == matrix.dimension
    for index in range(matrix.dimension):
        assert diagonal[index] == matrix.at(index, index)
        assert matrix.variance_of(index) == diagonal[index]


# --------------------------------------------------------------------------- #
# Positive definiteness
# --------------------------------------------------------------------------- #


@_SETTINGS
@given(diagonal=st.lists(_POSITIVE_ENTRIES, min_size=1, max_size=_MAX_DIMENSION))
def test_a_strictly_positive_diagonal_matrix_is_positive_definite(
    diagonal: list[float],
) -> None:
    matrix = SymmetricMatrix.from_diagonal(diagonal)
    assert matrix.has_admissible_diagonal()
    assert matrix.is_positive_definite()
    assert matrix.cholesky_factor() is not None


@_SETTINGS
@given(diagonal=st.lists(_POSITIVE_ENTRIES, min_size=1, max_size=_MAX_DIMENSION))
def test_the_cholesky_factor_of_a_diagonal_matrix_is_the_elementwise_square_root(
    diagonal: list[float],
) -> None:
    matrix = SymmetricMatrix.from_diagonal(diagonal)
    factor = matrix.cholesky_factor()
    assert factor is not None
    for index, entry in enumerate(diagonal):
        assert factor[_packed_index(index, index)] == pytest.approx(math.sqrt(entry))


@_SETTINGS
@given(matrix=positive_definite_matrices())
def test_a_matrix_built_as_l_times_l_transpose_is_positive_definite(
    matrix: SymmetricMatrix,
) -> None:
    assert matrix.has_admissible_diagonal()
    assert matrix.is_positive_definite()


@_SETTINGS
@given(matrix=positive_definite_matrices())
def test_the_cholesky_factor_reconstructs_the_original_matrix(
    matrix: SymmetricMatrix,
) -> None:
    factor = matrix.cholesky_factor()
    assert factor is not None
    assert len(factor) == matrix.dimension * (matrix.dimension + 1) // 2
    product = _times_transpose(factor, matrix.dimension)
    for row in range(matrix.dimension):
        for column in range(matrix.dimension):
            assert product[row][column] == pytest.approx(
                matrix.at(row, column),
                rel=_RELATIVE_TOLERANCE,
                abs=_ABSOLUTE_TOLERANCE,
            )


@_SETTINGS
@given(matrix=positive_definite_matrices())
def test_the_cholesky_factor_has_a_strictly_positive_diagonal(
    matrix: SymmetricMatrix,
) -> None:
    factor = matrix.cholesky_factor()
    assert factor is not None
    for index in range(matrix.dimension):
        assert factor[_packed_index(index, index)] > 0.0


@_SETTINGS
@given(matrix=positive_definite_matrices())
def test_the_strict_upper_triangle_of_the_packed_factor_is_not_stored(
    matrix: SymmetricMatrix,
) -> None:
    factor = matrix.cholesky_factor()
    assert factor is not None
    for row in range(matrix.dimension):
        for column in range(row + 1, matrix.dimension):
            assert _element(factor, row, column) == 0.0


# --------------------------------------------------------------------------- #
# An inadmissible covariance
# --------------------------------------------------------------------------- #


@_SETTINGS
@given(diagonal=diagonals_with_a_negative_entry())
def test_a_negative_variance_makes_the_diagonal_inadmissible(diagonal: list[float]) -> None:
    matrix = SymmetricMatrix.from_diagonal(diagonal)
    assert matrix.has_admissible_diagonal() is False


@_SETTINGS
@given(diagonal=diagonals_with_a_negative_entry())
def test_a_negative_variance_makes_the_matrix_not_positive_definite(
    diagonal: list[float],
) -> None:
    matrix = SymmetricMatrix.from_diagonal(diagonal)
    assert matrix.is_positive_definite() is False
    assert matrix.cholesky_factor() is None


@_SETTINGS
@given(diagonal=st.lists(_POSITIVE_ENTRIES, min_size=1, max_size=_MAX_DIMENSION))
def test_a_zero_variance_is_admissible_but_not_positive_definite(
    diagonal: list[float],
) -> None:
    collapsed = [0.0, *diagonal]
    matrix = SymmetricMatrix.from_diagonal(collapsed)
    assert matrix.has_admissible_diagonal()
    assert matrix.is_positive_definite() is False
