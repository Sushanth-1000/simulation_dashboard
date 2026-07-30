"""Boundary guards: every value the system refuses to accept."""

from __future__ import annotations

import math

import pytest

from astra.kernel.constants import FAST_STATE_DIMENSION, RCS_DIMENSION
from astra.kernel.enums import LayerId
from astra.kernel.errors import (
    ContractViolationError,
    DimensionMismatchError,
    NonFiniteValueError,
    RangeViolationError,
)
from astra.kernel.validation import (
    require_dimension,
    require_finite,
    require_non_decreasing,
    require_non_negative,
    require_positive,
    require_probability,
    require_range,
)

_NON_FINITE = [math.nan, math.inf, -math.inf]

# --------------------------------------------------------------------------- #
# require_finite -- the guard that exists because NaN defeats comparison
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("value", [0.0, -0.0, 1.0, -1.0, 1e308, -1e308, 1e-308])
def test_require_finite_returns_a_finite_value_unchanged(value: float) -> None:
    assert require_finite(value, name="score") == value


@pytest.mark.parametrize("value", _NON_FINITE)
def test_require_finite_rejects_nan_and_both_infinities(value: float) -> None:
    with pytest.raises(NonFiniteValueError):
        require_finite(value, name="score")


def test_nan_defeats_a_threshold_comparison_which_is_why_require_finite_exists() -> None:
    threshold = 0.5
    score = math.nan
    # A NaN non-conformity score makes every comparison false, so the gate that
    # would have vetoed silently passes. The guard is what turns that
    # fail-*open* mode into a typed, fail-closed error.
    assert (score > threshold) is False
    assert (score <= threshold) is False
    with pytest.raises(NonFiniteValueError):
        require_finite(score, name="nonconformity_score")


def test_a_non_finite_rejection_names_the_field_and_layer_in_its_audit_record() -> None:
    with pytest.raises(NonFiniteValueError) as excinfo:
        require_finite(math.nan, name="trust_index", layer=LayerId.L3_CONFORMAL_TRUST)
    assert excinfo.value.context == {"field": "trust_index"}
    assert excinfo.value.layer is LayerId.L3_CONFORMAL_TRUST
    assert excinfo.value.code == "ASTRA-CTR-003"
    assert "trust_index" in excinfo.value.message


def test_require_finite_defaults_the_layer_to_none() -> None:
    with pytest.raises(NonFiniteValueError) as excinfo:
        require_finite(math.inf, name="speed")
    assert excinfo.value.layer is None


# --------------------------------------------------------------------------- #
# require_range
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("value", [-1.0, -0.5, 0.0, 0.5, 1.0])
def test_require_range_accepts_values_inside_an_inclusive_interval(value: float) -> None:
    assert require_range(value, minimum=-1.0, maximum=1.0, name="steer") == value


@pytest.mark.parametrize("value", [-1.0000001, 1.0000001, 2.0, -5.0])
def test_require_range_rejects_values_outside_the_interval(value: float) -> None:
    with pytest.raises(RangeViolationError):
        require_range(value, minimum=-1.0, maximum=1.0, name="steer")


def test_require_range_treats_both_endpoints_as_admissible() -> None:
    assert require_range(0.0, minimum=0.0, maximum=0.0, name="pinned") == 0.0


@pytest.mark.parametrize("value", _NON_FINITE)
def test_require_range_rejects_a_non_finite_value_before_comparing_it(value: float) -> None:
    with pytest.raises(NonFiniteValueError):
        require_range(value, minimum=0.0, maximum=1.0, name="trust_index")


def test_a_range_rejection_records_the_bounds_it_was_checked_against() -> None:
    with pytest.raises(RangeViolationError) as excinfo:
        require_range(1.4, minimum=0.0, maximum=1.0, name="trust_index", layer=LayerId.L9_RCM)
    assert excinfo.value.context == {
        "field": "trust_index",
        "value": 1.4,
        "minimum": 0.0,
        "maximum": 1.0,
    }
    assert excinfo.value.layer is LayerId.L9_RCM
    assert excinfo.value.code == "ASTRA-CTR-002"


# --------------------------------------------------------------------------- #
# require_probability
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("value", [0.0, 0.001, 0.5, 0.999, 1.0])
def test_require_probability_accepts_the_closed_unit_interval(value: float) -> None:
    assert require_probability(value, name="trust_index") == value


@pytest.mark.parametrize("value", [-0.0001, 1.0001, -1.0, 2.0, 100.0])
def test_require_probability_rejects_anything_outside_zero_to_one(value: float) -> None:
    with pytest.raises(RangeViolationError):
        require_probability(value, name="trust_index")


@pytest.mark.parametrize("value", _NON_FINITE)
def test_require_probability_rejects_a_non_finite_value(value: float) -> None:
    with pytest.raises(NonFiniteValueError):
        require_probability(value, name="coverage_level")


def test_require_probability_returns_a_plain_float_at_runtime() -> None:
    assert type(require_probability(0.25, name="cdi")) is float


def test_a_probability_rejection_reports_the_unit_interval_as_its_bounds() -> None:
    with pytest.raises(RangeViolationError) as excinfo:
        require_probability(1.5, name="cdi")
    assert excinfo.value.context["minimum"] == 0.0
    assert excinfo.value.context["maximum"] == 1.0


# --------------------------------------------------------------------------- #
# require_non_negative
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("value", [0.0, -0.0, 1e-12, 1.0, 1e9])
def test_require_non_negative_accepts_zero_and_above(value: float) -> None:
    assert require_non_negative(value, name="stopping_distance") == value


@pytest.mark.parametrize("value", [-1e-12, -0.5, -1.0, -1e9])
def test_require_non_negative_rejects_a_negative_value(value: float) -> None:
    with pytest.raises(RangeViolationError):
        require_non_negative(value, name="stopping_distance")


@pytest.mark.parametrize("value", _NON_FINITE)
def test_require_non_negative_rejects_a_non_finite_value(value: float) -> None:
    with pytest.raises(NonFiniteValueError):
        require_non_negative(value, name="stopping_distance")


def test_a_non_negative_rejection_records_the_field_and_value() -> None:
    with pytest.raises(RangeViolationError) as excinfo:
        require_non_negative(-2.0, name="ood_counter", layer=LayerId.L8_FAILSAFE_FSM)
    assert excinfo.value.context == {"field": "ood_counter", "value": -2.0}
    assert excinfo.value.layer is LayerId.L8_FAILSAFE_FSM


# --------------------------------------------------------------------------- #
# require_positive
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("value", [1e-300, 1e-12, 0.5, 1.0, 1e9])
def test_require_positive_accepts_a_strictly_positive_value(value: float) -> None:
    assert require_positive(value, name="variance") == value


@pytest.mark.parametrize("value", [0.0, -0.0, -1e-12, -1.0])
def test_require_positive_rejects_zero_and_below(value: float) -> None:
    with pytest.raises(RangeViolationError):
        require_positive(value, name="variance")


@pytest.mark.parametrize("value", _NON_FINITE)
def test_require_positive_rejects_a_non_finite_value(value: float) -> None:
    with pytest.raises(NonFiniteValueError):
        require_positive(value, name="variance")


def test_zero_variance_is_rejected_because_the_icp_normaliser_would_divide_by_zero() -> None:
    assert require_non_negative(0.0, name="variance") == 0.0
    with pytest.raises(RangeViolationError):
        require_positive(0.0, name="variance")


def test_a_positivity_rejection_records_the_field_and_value() -> None:
    with pytest.raises(RangeViolationError) as excinfo:
        require_positive(0.0, name="sigma", layer=LayerId.L6_MPC_ICP_GATE)
    assert excinfo.value.context == {"field": "sigma", "value": 0.0}
    assert excinfo.value.layer is LayerId.L6_MPC_ICP_GATE


# --------------------------------------------------------------------------- #
# require_dimension
# --------------------------------------------------------------------------- #


def test_require_dimension_returns_the_values_as_an_immutable_tuple() -> None:
    values = [1.0, 2.0, 3.0]
    result = require_dimension(values, expected=3, name="rcs")
    assert result == (1.0, 2.0, 3.0)
    assert isinstance(result, tuple)


def test_the_returned_tuple_cannot_be_mutated_after_validation() -> None:
    source = [1.0, 2.0, 3.0]
    result = require_dimension(source, expected=3, name="rcs")
    source.append(4.0)
    assert result == (1.0, 2.0, 3.0)


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ([], 0),
        ([1.0], 1),
        ([0.0] * FAST_STATE_DIMENSION, FAST_STATE_DIMENSION),
        ([0.0] * RCS_DIMENSION, RCS_DIMENSION),
    ],
)
def test_require_dimension_accepts_a_sequence_of_exactly_the_expected_length(
    values: list[float], expected: int
) -> None:
    assert len(require_dimension(values, expected=expected, name="vector")) == expected


@pytest.mark.parametrize("values", [[], [1.0], [1.0, 2.0], [1.0] * 6])
def test_require_dimension_rejects_a_sequence_of_the_wrong_length(values: list[float]) -> None:
    with pytest.raises(DimensionMismatchError):
        require_dimension(values, expected=5, name="rcs")


def test_a_four_element_rcs_cannot_masquerade_as_a_five_dimensional_centroid() -> None:
    with pytest.raises(DimensionMismatchError) as excinfo:
        require_dimension([0.1, 0.2, 0.3, 0.4], expected=RCS_DIMENSION, name="rcs")
    assert excinfo.value.context == {"field": "rcs", "expected": 5, "actual": 4}
    assert excinfo.value.code == "ASTRA-CTR-004"


def test_require_dimension_accepts_a_tuple_as_well_as_a_list() -> None:
    assert require_dimension((1.0, 2.0), expected=2, name="pair") == (1.0, 2.0)


def test_require_dimension_does_not_inspect_element_finiteness() -> None:
    assert math.isnan(require_dimension([math.nan], expected=1, name="vector")[0])


# --------------------------------------------------------------------------- #
# require_non_decreasing -- separation invariant SI-9
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "values",
    [
        [],
        [1.0],
        [0.0, 1.0, 2.0],
        [0.0, 0.0, 0.0],
        [-5.0, -1.0, 0.0, 0.5, 0.5, 99.0],
    ],
)
def test_require_non_decreasing_accepts_a_monotonic_quantile_table(values: list[float]) -> None:
    assert require_non_decreasing(values, name="quantiles") == tuple(values)


def test_a_flat_table_is_non_decreasing_because_equality_is_permitted() -> None:
    assert require_non_decreasing([0.3, 0.3], name="quantiles") == (0.3, 0.3)


@pytest.mark.parametrize(
    "values",
    [
        [1.0, 0.0],
        [0.0, 1.0, 0.5],
        [0.0, 1.0, 2.0, 1.9999],
        [5.0, 4.0, 3.0],
    ],
)
def test_require_non_decreasing_rejects_a_non_monotonic_table(values: list[float]) -> None:
    with pytest.raises(RangeViolationError):
        require_non_decreasing(values, name="quantiles")


def test_a_non_monotonic_calibration_table_is_rejected_with_the_offending_index() -> None:
    with pytest.raises(RangeViolationError) as excinfo:
        require_non_decreasing(
            [0.1, 0.4, 0.2, 0.9], name="icp_quantiles", layer=LayerId.L6_MPC_ICP_GATE
        )
    assert excinfo.value.context == {"field": "icp_quantiles", "index": 2}
    assert excinfo.value.layer is LayerId.L6_MPC_ICP_GATE
    assert excinfo.value.code == "ASTRA-CTR-002"


def test_the_first_violation_is_the_one_reported() -> None:
    with pytest.raises(RangeViolationError) as excinfo:
        require_non_decreasing([3.0, 2.0, 1.0], name="quantiles")
    assert excinfo.value.context["index"] == 1


@pytest.mark.parametrize("value", _NON_FINITE)
def test_require_non_decreasing_rejects_a_non_finite_element_before_checking_order(
    value: float,
) -> None:
    with pytest.raises(NonFiniteValueError):
        require_non_decreasing([0.0, value, 1.0], name="quantiles")


def test_a_non_finite_element_is_reported_with_its_index_in_the_field_name() -> None:
    with pytest.raises(NonFiniteValueError) as excinfo:
        require_non_decreasing([0.0, math.nan], name="quantiles")
    assert excinfo.value.context == {"field": "quantiles[1]"}


def test_a_nan_element_is_reported_as_non_finite_rather_than_as_a_monotonicity_failure() -> None:
    with pytest.raises(NonFiniteValueError):
        require_non_decreasing([5.0, math.nan, 1.0], name="quantiles")


def test_require_non_decreasing_returns_an_immutable_tuple() -> None:
    source = [0.0, 1.0]
    result = require_non_decreasing(source, name="quantiles")
    source.append(-1.0)
    assert result == (0.0, 1.0)
    assert isinstance(result, tuple)


# --------------------------------------------------------------------------- #
# Shared properties of the guards
# --------------------------------------------------------------------------- #


def test_every_guard_raises_a_contract_violation_so_one_except_clause_covers_them_all() -> None:
    with pytest.raises(ContractViolationError):
        require_finite(math.nan, name="x")
    with pytest.raises(ContractViolationError):
        require_probability(2.0, name="x")
    with pytest.raises(ContractViolationError):
        require_dimension([], expected=1, name="x")
    with pytest.raises(ContractViolationError):
        require_non_decreasing([1.0, 0.0], name="x")


@pytest.mark.parametrize(
    "guard",
    [require_finite, require_non_negative, require_positive, require_probability],
)
def test_every_scalar_guard_returns_the_value_so_it_can_be_used_inline(
    guard: object,
) -> None:
    assert guard(0.75, name="value") == 0.75  # type: ignore[operator]
