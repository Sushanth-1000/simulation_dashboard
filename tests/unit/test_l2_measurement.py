"""Unit tests for the L2 measurement contract and its named constructors."""

from __future__ import annotations

import itertools
from typing import TYPE_CHECKING

import pytest

from astra.contracts.sensing import FusedSensorFrame
from astra.kernel.constants import FAST_STATE_FIELDS, SLOW_STATE_FIELDS
from astra.kernel.errors import (
    ContractViolationError,
    DimensionMismatchError,
    NonFiniteValueError,
    RangeViolationError,
)
from astra.layers.l2_estimation.measurement import (
    Measurement,
    MeasurementExtractor,
    fast_measurement,
    slow_measurement,
)

if TYPE_CHECKING:
    from astra.kernel.identifiers import TickId
    from astra.kernel.time import Instant

POSITION_X = FAST_STATE_FIELDS.index("position_x")
POSITION_Y = FAST_STATE_FIELDS.index("position_y")
SPEED = FAST_STATE_FIELDS.index("speed")
HEADING = FAST_STATE_FIELDS.index("heading")
LATERAL_ACCELERATION = FAST_STATE_FIELDS.index("lateral_acceleration")

# Three fast fields with values that are individually recognisable, so a
# permuted assembly that mis-pairs a value with a name is visible in the result
# rather than merely plausible.
SHUFFLE_FIXTURE: tuple[tuple[str, float, float], ...] = (
    ("lateral_acceleration", 2.5, 0.01),
    ("position_x", 100.0, 0.25),
    ("speed", 13.0, 0.04),
)

SLOW_SHUFFLE_FIXTURE: tuple[tuple[str, float, float], ...] = (
    ("sensor_health_score", 0.97, 0.001),
    ("road_friction_coefficient", 0.82, 0.002),
    ("tyre_wear_index", 0.11, 0.003),
)


def _observation(field: str, value: float = 1.0, variance: float = 0.1) -> tuple[str, float, float]:
    return (field, value, variance)


# --------------------------------------------------------------------------- #
# Shape validation
# --------------------------------------------------------------------------- #


def test_a_measurement_observing_nothing_raises_contract_violation() -> None:
    with pytest.raises(ContractViolationError):
        Measurement(values=(), state_indices=(), noise_variances=())


def test_more_values_than_indices_raises_contract_violation() -> None:
    with pytest.raises(ContractViolationError):
        Measurement(values=(1.0, 2.0), state_indices=(0,), noise_variances=(0.1, 0.1))


def test_more_variances_than_values_raises_contract_violation() -> None:
    with pytest.raises(ContractViolationError):
        Measurement(values=(1.0,), state_indices=(0,), noise_variances=(0.1, 0.2))


def test_the_length_mismatch_error_reports_all_three_lengths() -> None:
    with pytest.raises(ContractViolationError) as raised:
        Measurement(values=(1.0, 2.0, 3.0), state_indices=(0, 1), noise_variances=(0.1,))

    assert raised.value.context == {"values": 3, "indices": 2, "variances": 1}


# --------------------------------------------------------------------------- #
# Index validation -- the layout is the authority
# --------------------------------------------------------------------------- #


def test_an_index_past_the_end_of_the_layout_raises_dimension_mismatch() -> None:
    with pytest.raises(DimensionMismatchError):
        Measurement(values=(1.0,), state_indices=(len(FAST_STATE_FIELDS),), noise_variances=(0.1,))


def test_the_out_of_range_index_error_carries_the_index_and_the_dimension() -> None:
    with pytest.raises(DimensionMismatchError) as raised:
        Measurement(values=(1.0,), state_indices=(9,), noise_variances=(0.1,))

    assert raised.value.context == {"index": 9, "dimension": len(FAST_STATE_FIELDS)}


def test_a_negative_index_raises_dimension_mismatch() -> None:
    with pytest.raises(DimensionMismatchError):
        Measurement(values=(1.0,), state_indices=(-1,), noise_variances=(0.1,))


def test_an_index_valid_for_the_fast_layout_is_out_of_range_for_the_slow_layout() -> None:
    with pytest.raises(DimensionMismatchError):
        Measurement(
            values=(1.0,),
            state_indices=(LATERAL_ACCELERATION,),
            noise_variances=(0.1,),
            layout=SLOW_STATE_FIELDS,
        )


def test_duplicate_indices_raise_contract_violation() -> None:
    with pytest.raises(ContractViolationError):
        Measurement(values=(1.0, 2.0), state_indices=(1, 1), noise_variances=(0.1, 0.1))


def test_decreasing_indices_raise_contract_violation() -> None:
    with pytest.raises(ContractViolationError):
        Measurement(values=(1.0, 2.0), state_indices=(3, 1), noise_variances=(0.1, 0.1))


def test_the_non_increasing_index_error_carries_the_offending_ordering() -> None:
    with pytest.raises(ContractViolationError) as raised:
        Measurement(values=(1.0, 2.0), state_indices=(2, 0), noise_variances=(0.1, 0.1))

    assert raised.value.context == {"indices": [2, 0]}


def test_strictly_increasing_indices_are_accepted() -> None:
    measurement = Measurement(
        values=(1.0, 2.0, 3.0),
        state_indices=(POSITION_X, SPEED, LATERAL_ACCELERATION),
        noise_variances=(0.1, 0.2, 0.3),
    )

    assert measurement.state_indices == (POSITION_X, SPEED, LATERAL_ACCELERATION)


# --------------------------------------------------------------------------- #
# Numerical admissibility
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_observed_value_raises_non_finite_value(value: float) -> None:
    with pytest.raises(NonFiniteValueError):
        Measurement(values=(value,), state_indices=(SPEED,), noise_variances=(0.1,))


def test_the_non_finite_value_error_names_the_observed_field() -> None:
    with pytest.raises(NonFiniteValueError) as raised:
        Measurement(values=(float("nan"),), state_indices=(HEADING,), noise_variances=(0.1,))

    assert raised.value.context["field"] == "measurement.heading"


# A zero-variance measurement asserts a perfect sensor: it drives the Kalman
# gain to unity and lets one reading overwrite the filter's entire history.
@pytest.mark.parametrize("variance", [0.0, -1e-12, -1.0])
def test_a_non_positive_noise_variance_raises_range_violation(variance: float) -> None:
    with pytest.raises(RangeViolationError):
        Measurement(values=(1.0,), state_indices=(SPEED,), noise_variances=(variance,))


def test_the_non_positive_variance_error_names_the_offending_field_and_value() -> None:
    with pytest.raises(RangeViolationError) as raised:
        Measurement(values=(1.0,), state_indices=(LATERAL_ACCELERATION,), noise_variances=(0.0,))

    assert raised.value.context["field"] == "measurement_noise.lateral_acceleration"
    assert raised.value.context["value"] == 0.0


@pytest.mark.parametrize("variance", [float("nan"), float("inf")])
def test_a_non_finite_noise_variance_raises_non_finite_value(variance: float) -> None:
    with pytest.raises(NonFiniteValueError):
        Measurement(values=(1.0,), state_indices=(SPEED,), noise_variances=(variance,))


# --------------------------------------------------------------------------- #
# Derived properties
# --------------------------------------------------------------------------- #


def test_dimension_counts_the_observed_state_dimensions() -> None:
    measurement = Measurement(
        values=(1.0, 2.0), state_indices=(POSITION_X, POSITION_Y), noise_variances=(0.1, 0.2)
    )

    assert measurement.dimension == 2


def test_a_full_state_measurement_has_the_layout_dimension() -> None:
    measurement = Measurement(
        values=tuple(float(index) for index in range(len(FAST_STATE_FIELDS))),
        state_indices=tuple(range(len(FAST_STATE_FIELDS))),
        noise_variances=(0.1,) * len(FAST_STATE_FIELDS),
    )

    assert measurement.dimension == len(FAST_STATE_FIELDS)
    assert measurement.observed_fields == FAST_STATE_FIELDS


def test_observed_fields_resolves_indices_against_the_layout() -> None:
    measurement = Measurement(
        values=(1.0, 2.0),
        state_indices=(POSITION_Y, HEADING),
        noise_variances=(0.1, 0.2),
    )

    assert measurement.observed_fields == ("position_y", "heading")


def test_observed_fields_resolves_against_the_slow_layout_when_that_is_carried() -> None:
    measurement = Measurement(
        values=(0.8, 0.99),
        state_indices=(0, 2),
        noise_variances=(0.01, 0.02),
        layout=SLOW_STATE_FIELDS,
    )

    assert measurement.observed_fields == ("road_friction_coefficient", "sensor_health_score")


# --------------------------------------------------------------------------- #
# The layout attribute
# --------------------------------------------------------------------------- #


def test_the_layout_defaults_to_the_fast_state_fields() -> None:
    measurement = Measurement(values=(1.0,), state_indices=(0,), noise_variances=(0.1,))

    assert measurement.layout == FAST_STATE_FIELDS


def test_a_supplied_layout_is_carried_on_the_measurement() -> None:
    measurement = Measurement(
        values=(0.8,), state_indices=(0,), noise_variances=(0.1,), layout=SLOW_STATE_FIELDS
    )

    assert measurement.layout == SLOW_STATE_FIELDS


def test_fast_measurement_carries_the_fast_layout() -> None:
    assert fast_measurement([_observation("speed", 12.0, 0.04)]).layout == FAST_STATE_FIELDS


def test_slow_measurement_carries_the_slow_layout() -> None:
    measurement = slow_measurement([_observation("tyre_wear_index", 0.1, 0.01)])

    assert measurement.layout == SLOW_STATE_FIELDS


# --------------------------------------------------------------------------- #
# Name resolution -- the anti-mis-wiring property
# --------------------------------------------------------------------------- #
# The extractor assembles observations in whatever order its sensors arrived.
# Resolution must depend on the *name*, never on that order, or a reordering
# inside an adapter would silently repoint an observation at a different
# physical quantity while still producing plausible numbers.


@pytest.mark.parametrize("permutation", list(itertools.permutations(SHUFFLE_FIXTURE)), ids=range(6))
def test_fast_measurement_resolves_to_canonical_order_whatever_order_it_is_given(
    permutation: tuple[tuple[str, float, float], ...],
) -> None:
    measurement = fast_measurement(list(permutation))

    assert measurement.state_indices == (POSITION_X, SPEED, LATERAL_ACCELERATION)
    assert measurement.state_indices == tuple(sorted(measurement.state_indices))
    assert measurement.observed_fields == ("position_x", "speed", "lateral_acceleration")


@pytest.mark.parametrize("permutation", list(itertools.permutations(SHUFFLE_FIXTURE)), ids=range(6))
def test_fast_measurement_keeps_every_value_and_variance_with_its_own_field_name(
    permutation: tuple[tuple[str, float, float], ...],
) -> None:
    measurement = fast_measurement(list(permutation))

    expected = {name: (value, variance) for name, value, variance in SHUFFLE_FIXTURE}
    paired = dict(
        zip(
            measurement.observed_fields,
            zip(measurement.values, measurement.noise_variances, strict=True),
            strict=True,
        )
    )

    assert paired == expected


@pytest.mark.parametrize(
    "permutation", list(itertools.permutations(SLOW_SHUFFLE_FIXTURE)), ids=range(6)
)
def test_slow_measurement_resolves_to_canonical_order_whatever_order_it_is_given(
    permutation: tuple[tuple[str, float, float], ...],
) -> None:
    measurement = slow_measurement(list(permutation))

    assert measurement.observed_fields == SLOW_STATE_FIELDS
    assert measurement.state_indices == tuple(sorted(measurement.state_indices))

    expected = {name: (value, variance) for name, value, variance in SLOW_SHUFFLE_FIXTURE}
    paired = dict(
        zip(
            measurement.observed_fields,
            zip(measurement.values, measurement.noise_variances, strict=True),
            strict=True,
        )
    )
    assert paired == expected


def test_a_single_field_fast_measurement_resolves_its_index_from_the_layout() -> None:
    measurement = fast_measurement([_observation("heading", 0.25, 0.01)])

    assert measurement.state_indices == (HEADING,)
    assert measurement.values == (0.25,)


# --------------------------------------------------------------------------- #
# Unknown and repeated field names
# --------------------------------------------------------------------------- #


def test_fast_measurement_rejects_an_unknown_field_name() -> None:
    with pytest.raises(ContractViolationError) as raised:
        fast_measurement([_observation("velocity")])

    assert raised.value.context["field"] == "velocity"
    assert "velocity" in str(raised.value)


def test_slow_measurement_rejects_an_unknown_field_name() -> None:
    with pytest.raises(ContractViolationError) as raised:
        slow_measurement([_observation("brake_wear")])

    assert raised.value.context["field"] == "brake_wear"
    assert "brake_wear" in str(raised.value)


def test_an_unknown_name_is_rejected_even_when_the_other_names_are_valid() -> None:
    with pytest.raises(ContractViolationError) as raised:
        fast_measurement([_observation("speed", 12.0, 0.04), _observation("yaw_rate")])

    assert raised.value.context["field"] == "yaw_rate"


def test_fast_measurement_rejects_the_same_field_observed_twice() -> None:
    with pytest.raises(ContractViolationError):
        fast_measurement([_observation("speed", 12.0, 0.04), _observation("speed", 13.0, 0.04)])


def test_slow_measurement_rejects_the_same_field_observed_twice() -> None:
    with pytest.raises(ContractViolationError):
        slow_measurement(
            [
                _observation("road_friction_coefficient", 0.8, 0.01),
                _observation("road_friction_coefficient", 0.9, 0.01),
            ]
        )


def test_the_repeated_field_error_lists_the_fields_that_were_offered() -> None:
    with pytest.raises(ContractViolationError) as raised:
        fast_measurement(
            [
                _observation("position_x", 1.0, 0.1),
                _observation("position_x", 2.0, 0.1),
            ]
        )

    assert raised.value.context["fields"] == ["position_x", "position_x"]


# --------------------------------------------------------------------------- #
# The two layouts are distinct
# --------------------------------------------------------------------------- #
# This is what stops a fast-state observation being applied to the slow filter
# and vice versa. The two field sets are disjoint, and each constructor resolves
# names against exactly one of them.


def test_the_two_state_layouts_share_no_field_name() -> None:
    assert set(FAST_STATE_FIELDS).isdisjoint(SLOW_STATE_FIELDS)


@pytest.mark.parametrize("field", SLOW_STATE_FIELDS)
def test_fast_measurement_refuses_a_slow_state_field_name(field: str) -> None:
    with pytest.raises(ContractViolationError) as raised:
        fast_measurement([_observation(field)])

    assert raised.value.context["field"] == field


@pytest.mark.parametrize("field", FAST_STATE_FIELDS)
def test_slow_measurement_refuses_a_fast_state_field_name(field: str) -> None:
    with pytest.raises(ContractViolationError) as raised:
        slow_measurement([_observation(field)])

    assert raised.value.context["field"] == field


# --------------------------------------------------------------------------- #
# The extractor seam
# --------------------------------------------------------------------------- #


class _MinimalExtractor:
    """The smallest thing an adapter must supply: two methods, no inheritance."""

    def extract_fast(self, frame: FusedSensorFrame[str]) -> Measurement | None:
        del frame
        return fast_measurement([_observation("speed", 12.0, 0.04)])

    def extract_slow(self, frame: FusedSensorFrame[str]) -> Measurement | None:
        del frame
        return None


class _HalfAnExtractor:
    """Missing ``extract_slow``, so it must not satisfy the protocol."""

    def extract_fast(self, frame: FusedSensorFrame[str]) -> Measurement | None:
        del frame
        return None


def test_the_measurement_extractor_protocol_is_runtime_checkable() -> None:
    assert isinstance(_MinimalExtractor(), MeasurementExtractor)


def test_an_object_missing_extract_slow_does_not_satisfy_the_protocol() -> None:
    assert not isinstance(_HalfAnExtractor(), MeasurementExtractor)


def test_an_unrelated_object_does_not_satisfy_the_protocol() -> None:
    assert not isinstance(object(), MeasurementExtractor)


def test_a_duck_typed_extractor_is_usable_through_the_protocol(tick: TickId, now: Instant) -> None:
    extractor: MeasurementExtractor[str] = _MinimalExtractor()
    frame: FusedSensorFrame[str] = FusedSensorFrame(tick=tick, fused_at=now, samples=())

    measurement = extractor.extract_fast(frame)

    assert measurement is not None
    assert measurement.observed_fields == ("speed",)
    assert measurement.layout == FAST_STATE_FIELDS
