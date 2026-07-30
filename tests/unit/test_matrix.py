"""The packed symmetric matrix used for every covariance in the system."""

from __future__ import annotations

import math

import pytest

from astra.kernel.errors import (
    ContractViolationError,
    DimensionMismatchError,
    NonFiniteValueError,
)
from astra.kernel.matrix import SymmetricMatrix

_IDENTITY_2X2 = SymmetricMatrix(dimension=2, lower_triangle=(1.0, 0.0, 1.0))
_KNOWN_POSITIVE_DEFINITE = SymmetricMatrix.from_rows([[4.0, 2.0], [2.0, 3.0]])
_NOT_POSITIVE_DEFINITE = SymmetricMatrix.from_rows([[1.0, 2.0], [2.0, 1.0]])


def _reconstruct(dimension: int, packed_factor: tuple[float, ...]) -> list[list[float]]:
    def element(row: int, column: int) -> float:
        return packed_factor[row * (row + 1) // 2 + column] if column <= row else 0.0

    return [
        [
            sum(element(row, inner) * element(column, inner) for inner in range(dimension))
            for column in range(dimension)
        ]
        for row in range(dimension)
    ]


# --------------------------------------------------------------------------- #
# Packed representation
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("dimension", "packed_length"),
    [(1, 1), (2, 3), (3, 6), (4, 10), (5, 15)],
)
def test_the_packed_length_is_n_times_n_plus_one_over_two(
    dimension: int, packed_length: int
) -> None:
    matrix = SymmetricMatrix.from_diagonal([1.0] * dimension)
    assert len(matrix.lower_triangle) == packed_length


def test_a_five_by_five_covariance_stores_fifteen_numbers_not_twenty_five() -> None:
    matrix = SymmetricMatrix.from_diagonal([1.0, 1.0, 0.25, 0.1, 0.5])
    assert len(matrix.lower_triangle) == 15
    assert matrix.dimension == 5


@pytest.mark.parametrize("packed", [(), (1.0,), (1.0, 2.0), (1.0, 2.0, 3.0, 4.0)])
def test_a_packed_length_inconsistent_with_the_dimension_is_rejected(
    packed: tuple[float, ...],
) -> None:
    with pytest.raises(DimensionMismatchError):
        SymmetricMatrix(dimension=2, lower_triangle=packed)


def test_the_packed_length_error_reports_the_expected_element_count() -> None:
    with pytest.raises(DimensionMismatchError) as excinfo:
        SymmetricMatrix(dimension=3, lower_triangle=(1.0,))
    assert excinfo.value.context == {"dimension": 3, "expected": 6}


@pytest.mark.parametrize("dimension", [0, -1, -5])
def test_a_non_positive_dimension_is_rejected(dimension: int) -> None:
    with pytest.raises(ContractViolationError) as excinfo:
        SymmetricMatrix(dimension=dimension, lower_triangle=())
    assert excinfo.value.context == {"dimension": dimension}


@pytest.mark.parametrize("dimension", [2.0, "2", None, True])
def test_a_non_integer_dimension_from_a_persisted_record_is_rejected(dimension: object) -> None:
    with pytest.raises(ContractViolationError):
        SymmetricMatrix(dimension=dimension, lower_triangle=(1.0, 0.0, 1.0))  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_a_non_finite_covariance_element_is_rejected(bad: float) -> None:
    with pytest.raises(NonFiniteValueError):
        SymmetricMatrix(dimension=2, lower_triangle=(1.0, bad, 1.0))


def test_a_non_finite_element_is_reported_with_its_packed_index() -> None:
    with pytest.raises(NonFiniteValueError) as excinfo:
        SymmetricMatrix(dimension=2, lower_triangle=(1.0, 0.0, math.nan))
    assert excinfo.value.context == {"field": "covariance[2]"}


def test_a_symmetric_matrix_is_frozen_and_hashable() -> None:
    assert hash(_IDENTITY_2X2) == hash(SymmetricMatrix(2, (1.0, 0.0, 1.0)))
    with pytest.raises(AttributeError):
        _IDENTITY_2X2.dimension = 3  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# at
# --------------------------------------------------------------------------- #


def test_at_reads_the_packed_lower_triangle_in_row_major_order() -> None:
    matrix = SymmetricMatrix(dimension=3, lower_triangle=(1.0, 2.0, 3.0, 4.0, 5.0, 6.0))
    assert matrix.at(0, 0) == 1.0
    assert matrix.at(1, 0) == 2.0
    assert matrix.at(1, 1) == 3.0
    assert matrix.at(2, 0) == 4.0
    assert matrix.at(2, 1) == 5.0
    assert matrix.at(2, 2) == 6.0


def test_at_is_symmetric_because_asymmetry_has_no_encoding() -> None:
    matrix = SymmetricMatrix(dimension=3, lower_triangle=(1.0, 2.0, 3.0, 4.0, 5.0, 6.0))
    for row in range(3):
        for column in range(3):
            assert matrix.at(row, column) == matrix.at(column, row)


@pytest.mark.parametrize(
    ("row", "column"),
    [(-1, 0), (0, -1), (2, 0), (0, 2), (5, 5), (2, 2)],
)
def test_at_rejects_an_index_outside_the_matrix(row: int, column: int) -> None:
    with pytest.raises(DimensionMismatchError):
        _IDENTITY_2X2.at(row, column)


def test_an_out_of_bounds_access_records_the_index_and_the_dimension() -> None:
    with pytest.raises(DimensionMismatchError) as excinfo:
        _IDENTITY_2X2.at(7, 1)
    assert excinfo.value.context == {"row": 7, "column": 1, "dimension": 2}


# --------------------------------------------------------------------------- #
# diagonal, variance_of, to_rows
# --------------------------------------------------------------------------- #


def test_the_diagonal_is_the_per_dimension_variance_vector() -> None:
    matrix = SymmetricMatrix.from_diagonal([1.0, 0.25, 0.5])
    assert matrix.diagonal == (1.0, 0.25, 0.5)


def test_the_diagonal_of_a_dense_matrix_skips_the_off_diagonal_entries() -> None:
    matrix = SymmetricMatrix(dimension=3, lower_triangle=(1.0, 2.0, 3.0, 4.0, 5.0, 6.0))
    assert matrix.diagonal == (1.0, 3.0, 6.0)


@pytest.mark.parametrize(("index", "variance"), [(0, 1.0), (1, 0.25), (2, 0.5)])
def test_variance_of_returns_the_variance_of_one_state_dimension(
    index: int, variance: float
) -> None:
    assert SymmetricMatrix.from_diagonal([1.0, 0.25, 0.5]).variance_of(index) == variance


def test_variance_of_agrees_with_the_diagonal() -> None:
    matrix = SymmetricMatrix.from_diagonal([1.0, 1.0, 0.25, 0.1, 0.5])
    assert tuple(matrix.variance_of(index) for index in range(5)) == matrix.diagonal


@pytest.mark.parametrize("index", [-1, 3, 99])
def test_variance_of_rejects_an_out_of_range_state_dimension(index: int) -> None:
    with pytest.raises(DimensionMismatchError):
        SymmetricMatrix.from_diagonal([1.0, 2.0, 3.0]).variance_of(index)


def test_to_rows_expands_to_a_full_square_nested_tuple() -> None:
    matrix = SymmetricMatrix(dimension=3, lower_triangle=(1.0, 2.0, 3.0, 4.0, 5.0, 6.0))
    assert matrix.to_rows() == (
        (1.0, 2.0, 4.0),
        (2.0, 3.0, 5.0),
        (4.0, 5.0, 6.0),
    )


def test_to_rows_of_a_diagonal_matrix_has_zero_off_diagonal_entries() -> None:
    assert SymmetricMatrix.from_diagonal([2.0, 3.0]).to_rows() == ((2.0, 0.0), (0.0, 3.0))


def test_to_rows_round_trips_through_from_rows() -> None:
    matrix = SymmetricMatrix(dimension=3, lower_triangle=(1.0, 2.0, 3.0, 4.0, 5.0, 6.0))
    assert SymmetricMatrix.from_rows(matrix.to_rows()) == matrix


def test_to_rows_yields_immutable_tuples_so_the_seam_cannot_leak_a_mutable_view() -> None:
    rows = SymmetricMatrix.from_diagonal([1.0]).to_rows()
    assert isinstance(rows, tuple)
    assert all(isinstance(row, tuple) for row in rows)


# --------------------------------------------------------------------------- #
# from_rows
# --------------------------------------------------------------------------- #


def test_from_rows_keeps_the_lower_triangle_of_a_symmetric_input() -> None:
    matrix = SymmetricMatrix.from_rows([[1.0, 2.0], [2.0, 3.0]])
    assert matrix.lower_triangle == (1.0, 2.0, 3.0)


def test_from_rows_accepts_asymmetry_within_the_default_tolerance() -> None:
    matrix = SymmetricMatrix.from_rows([[1.0, 2.0], [2.0 + 5e-10, 3.0]])
    assert matrix.at(0, 1) == 2.0 + 5e-10


def test_from_rows_accepts_asymmetry_exactly_at_the_default_tolerance() -> None:
    matrix = SymmetricMatrix.from_rows([[1.0, 0.0], [1e-9, 1.0]])
    assert matrix.at(1, 0) == 1e-9


@pytest.mark.parametrize("difference", [1e-8, 1e-3, 0.5, 3.0])
def test_from_rows_rejects_asymmetry_beyond_the_default_tolerance(difference: float) -> None:
    with pytest.raises(ContractViolationError) as excinfo:
        SymmetricMatrix.from_rows([[1.0, 0.0], [difference, 1.0]])
    assert excinfo.value.code == "ASTRA-CTR-001"


def test_an_asymmetry_rejection_names_the_offending_cell_and_the_difference() -> None:
    with pytest.raises(ContractViolationError) as excinfo:
        SymmetricMatrix.from_rows([[1.0, 2.0], [5.0, 3.0]])
    assert excinfo.value.context == {"row": 1, "column": 0, "difference": 3.0}


def test_a_wider_tolerance_admits_an_asymmetry_the_default_would_reject() -> None:
    matrix = SymmetricMatrix.from_rows([[1.0, 0.0], [0.5, 1.0]], symmetry_tolerance=1.0)
    assert matrix.at(0, 1) == 0.5


def test_a_zero_tolerance_rejects_even_a_single_bit_of_asymmetry() -> None:
    with pytest.raises(ContractViolationError):
        SymmetricMatrix.from_rows([[1.0, 0.0], [1e-18, 1.0]], symmetry_tolerance=0.0)


@pytest.mark.parametrize(
    "rows",
    [
        [[1.0, 2.0], [2.0]],
        [[1.0], [1.0, 2.0]],
        [[1.0, 2.0, 3.0], [2.0, 1.0, 0.0]],
    ],
)
def test_from_rows_rejects_a_non_square_input(rows: list[list[float]]) -> None:
    with pytest.raises(DimensionMismatchError):
        SymmetricMatrix.from_rows(rows)


def test_a_non_square_rejection_names_the_offending_row() -> None:
    with pytest.raises(DimensionMismatchError) as excinfo:
        SymmetricMatrix.from_rows([[1.0, 2.0], [2.0]])
    assert excinfo.value.context == {"row": 1, "dimension": 2}


def test_from_rows_rejects_an_empty_input_because_a_zero_dimension_matrix_is_meaningless() -> None:
    with pytest.raises(ContractViolationError):
        SymmetricMatrix.from_rows([])


def test_from_rows_accepts_a_one_by_one_matrix() -> None:
    assert SymmetricMatrix.from_rows([[2.5]]).lower_triangle == (2.5,)


# --------------------------------------------------------------------------- #
# from_diagonal
# --------------------------------------------------------------------------- #


def test_from_diagonal_zeroes_every_off_diagonal_entry() -> None:
    matrix = SymmetricMatrix.from_diagonal([1.0, 2.0, 3.0])
    assert matrix.lower_triangle == (1.0, 0.0, 2.0, 0.0, 0.0, 3.0)


def test_from_diagonal_agrees_with_from_rows_on_the_same_matrix() -> None:
    assert SymmetricMatrix.from_diagonal([2.0, 3.0]) == SymmetricMatrix.from_rows(
        [[2.0, 0.0], [0.0, 3.0]]
    )


def test_from_diagonal_rejects_an_empty_diagonal() -> None:
    with pytest.raises(ContractViolationError):
        SymmetricMatrix.from_diagonal([])


def test_from_diagonal_rejects_a_non_finite_variance() -> None:
    with pytest.raises(NonFiniteValueError):
        SymmetricMatrix.from_diagonal([1.0, math.nan])


# --------------------------------------------------------------------------- #
# has_admissible_diagonal
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "diagonal",
    [[1.0], [0.0], [1.0, 0.0, 3.0], [1e-30, 2.0]],
)
def test_a_non_negative_diagonal_is_admissible(diagonal: list[float]) -> None:
    assert SymmetricMatrix.from_diagonal(diagonal).has_admissible_diagonal() is True


@pytest.mark.parametrize(
    "diagonal",
    [[-1.0], [1.0, -1e-12], [-0.5, 2.0, 3.0]],
)
def test_a_negative_variance_is_conclusive_evidence_of_filter_corruption(
    diagonal: list[float],
) -> None:
    assert SymmetricMatrix.from_diagonal(diagonal).has_admissible_diagonal() is False


def test_an_admissible_diagonal_does_not_imply_positive_definiteness() -> None:
    matrix = SymmetricMatrix.from_rows([[1.0, 2.0], [2.0, 1.0]])
    assert matrix.has_admissible_diagonal() is True
    assert matrix.is_positive_definite() is False


# --------------------------------------------------------------------------- #
# cholesky_factor
# --------------------------------------------------------------------------- #


def test_cholesky_factor_of_a_known_positive_definite_matrix_is_the_known_factor() -> None:
    factor = _KNOWN_POSITIVE_DEFINITE.cholesky_factor()
    assert factor is not None
    assert factor == pytest.approx((2.0, 1.0, math.sqrt(2.0)))


def test_the_cholesky_factor_of_the_identity_is_the_identity() -> None:
    assert _IDENTITY_2X2.cholesky_factor() == pytest.approx((1.0, 0.0, 1.0))


@pytest.mark.parametrize(
    "rows",
    [
        [[4.0, 2.0], [2.0, 3.0]],
        [[2.0]],
        [[4.0, 1.0, 0.5], [1.0, 3.0, 0.25], [0.5, 0.25, 2.0]],
        [[1.0, 0.0], [0.0, 1.0]],
    ],
)
def test_the_factor_multiplied_by_its_transpose_reconstructs_the_matrix(
    rows: list[list[float]],
) -> None:
    matrix = SymmetricMatrix.from_rows(rows)
    factor = matrix.cholesky_factor()
    assert factor is not None
    reconstructed = [value for row in _reconstruct(matrix.dimension, factor) for value in row]
    original = [value for row in matrix.to_rows() for value in row]
    assert reconstructed == pytest.approx(original)


@pytest.mark.parametrize(
    "rows",
    [
        [[1.0, 2.0], [2.0, 1.0]],
        [[-1.0]],
        [[0.0]],
        [[0.0, 0.0], [0.0, 0.0]],
        [[1.0, 1.0], [1.0, 1.0]],
        [[1.0, 0.0, 0.0], [0.0, -2.0, 0.0], [0.0, 0.0, 3.0]],
    ],
)
def test_cholesky_factor_returns_none_for_a_matrix_that_is_not_positive_definite(
    rows: list[list[float]],
) -> None:
    assert SymmetricMatrix.from_rows(rows).cholesky_factor() is None


def test_a_numerically_singular_matrix_fails_rather_than_dividing_by_a_near_zero_pivot() -> None:
    assert SymmetricMatrix.from_diagonal([1e-13]).cholesky_factor() is None


def test_a_looser_tolerance_admits_a_pivot_the_default_would_reject() -> None:
    matrix = SymmetricMatrix.from_diagonal([1e-13])
    assert matrix.cholesky_factor() is None
    assert matrix.cholesky_factor(tolerance=1e-20) is not None


def test_a_stricter_tolerance_rejects_a_pivot_the_default_would_admit() -> None:
    matrix = SymmetricMatrix.from_diagonal([0.5])
    assert matrix.cholesky_factor() is not None
    assert matrix.cholesky_factor(tolerance=1.0) is None


# --------------------------------------------------------------------------- #
# is_positive_definite
# --------------------------------------------------------------------------- #


def test_a_well_conditioned_covariance_is_positive_definite() -> None:
    assert _KNOWN_POSITIVE_DEFINITE.is_positive_definite() is True


def test_the_indefinite_matrix_is_not_positive_definite() -> None:
    assert _NOT_POSITIVE_DEFINITE.is_positive_definite() is False


def test_a_collapsed_filter_with_a_zero_variance_is_reported_as_a_fault() -> None:
    collapsed = SymmetricMatrix.from_diagonal([1.0, 0.0, 1.0])
    assert collapsed.has_admissible_diagonal() is True
    assert collapsed.is_positive_definite() is False


def test_positive_semi_definite_is_deliberately_not_good_enough() -> None:
    semi_definite = SymmetricMatrix.from_rows([[1.0, 1.0], [1.0, 1.0]])
    assert semi_definite.is_positive_definite() is False


def test_is_positive_definite_agrees_with_cholesky_factor(
    identity_covariance: SymmetricMatrix,
) -> None:
    assert identity_covariance.is_positive_definite() is (
        identity_covariance.cholesky_factor() is not None
    )


def test_the_shared_five_by_five_fixture_covariance_is_positive_definite(
    identity_covariance: SymmetricMatrix,
) -> None:
    assert identity_covariance.dimension == 5
    assert identity_covariance.is_positive_definite() is True
    assert identity_covariance.has_admissible_diagonal() is True


def test_is_positive_definite_forwards_its_tolerance_to_the_factorisation() -> None:
    matrix = SymmetricMatrix.from_diagonal([1e-13])
    assert matrix.is_positive_definite() is False
    assert matrix.is_positive_definite(tolerance=1e-20) is True
