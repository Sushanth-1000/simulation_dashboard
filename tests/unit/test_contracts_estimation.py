"""Unit tests for the L2 dual-rate UKF output contracts."""

from __future__ import annotations

import pytest

from astra.contracts.estimation import FastStateEstimate, InnovationRecord, SlowStateEstimate
from astra.kernel.constants import FAST_STATE_FIELDS, SLOW_STATE_FIELDS
from astra.kernel.errors import (
    ContractViolationError,
    DimensionMismatchError,
    NonFiniteValueError,
    RangeViolationError,
)
from astra.kernel.identifiers import TickId
from astra.kernel.matrix import SymmetricMatrix
from astra.kernel.time import Instant

FAST_MEAN = (10.0, -2.0, 13.5, 0.25, 1.75)
SLOW_MEAN = (0.8, 0.15, 0.95)


def _slow_covariance() -> SymmetricMatrix:
    return SymmetricMatrix.from_diagonal([0.01, 0.02, 0.03])


# --------------------------------------------------------------------------- #
# FastStateEstimate -- dimensional validation
# --------------------------------------------------------------------------- #


def test_fast_state_accepts_the_canonical_five_dimensional_layout(
    tick: TickId, now: Instant, identity_covariance: SymmetricMatrix
) -> None:
    estimate = FastStateEstimate(
        tick=tick, valid_at=now, mean=FAST_MEAN, covariance=identity_covariance
    )

    assert estimate.mean == FAST_MEAN
    assert len(estimate.mean) == len(FAST_STATE_FIELDS)


def test_fast_state_with_a_four_element_mean_raises_dimension_mismatch(
    tick: TickId, now: Instant, identity_covariance: SymmetricMatrix
) -> None:
    with pytest.raises(DimensionMismatchError):
        FastStateEstimate(
            tick=tick, valid_at=now, mean=(1.0, 2.0, 3.0, 4.0), covariance=identity_covariance
        )


def test_fast_state_with_a_six_element_mean_raises_dimension_mismatch(
    tick: TickId, now: Instant, identity_covariance: SymmetricMatrix
) -> None:
    with pytest.raises(DimensionMismatchError):
        FastStateEstimate(
            tick=tick,
            valid_at=now,
            mean=(*FAST_MEAN, 0.0),
            covariance=identity_covariance,
        )


def test_fast_state_with_a_three_by_three_covariance_raises_dimension_mismatch(
    tick: TickId, now: Instant
) -> None:
    with pytest.raises(DimensionMismatchError) as raised:
        FastStateEstimate(tick=tick, valid_at=now, mean=FAST_MEAN, covariance=_slow_covariance())

    assert raised.value.context == {"expected": 5, "actual": 3}


def test_fast_state_normalises_a_list_mean_into_an_immutable_tuple(
    tick: TickId, now: Instant, identity_covariance: SymmetricMatrix
) -> None:
    mutable = list(FAST_MEAN)
    estimate = FastStateEstimate(
        tick=tick,
        valid_at=now,
        mean=mutable,  # type: ignore[arg-type]
        covariance=identity_covariance,
    )
    mutable[0] = 999.0

    assert isinstance(estimate.mean, tuple)
    assert estimate.mean == FAST_MEAN


# --------------------------------------------------------------------------- #
# FastStateEstimate -- covariance admissibility
# --------------------------------------------------------------------------- #


def test_fast_state_with_a_negative_variance_reports_a_diverged_filter(
    tick: TickId, now: Instant
) -> None:
    diverged = SymmetricMatrix.from_diagonal([1.0, 1.0, -0.25, 0.1, 0.5])

    with pytest.raises(ContractViolationError) as raised:
        FastStateEstimate(tick=tick, valid_at=now, mean=FAST_MEAN, covariance=diverged)

    assert "diverged" in raised.value.message


def test_fast_state_accepts_a_zero_variance_because_only_negatives_prove_divergence(
    tick: TickId, now: Instant
) -> None:
    collapsed = SymmetricMatrix.from_diagonal([1.0, 1.0, 0.0, 0.1, 0.5])

    estimate = FastStateEstimate(tick=tick, valid_at=now, mean=FAST_MEAN, covariance=collapsed)

    assert estimate.variance_of("speed") == 0.0


# --------------------------------------------------------------------------- #
# FastStateEstimate -- named accessors
# --------------------------------------------------------------------------- #


def test_fast_state_named_accessors_return_the_canonically_ordered_elements(
    tick: TickId, now: Instant, identity_covariance: SymmetricMatrix
) -> None:
    estimate = FastStateEstimate(
        tick=tick, valid_at=now, mean=FAST_MEAN, covariance=identity_covariance
    )

    assert estimate.position_x == FAST_MEAN[0]
    assert estimate.position_y == FAST_MEAN[1]
    assert estimate.speed == FAST_MEAN[2]
    assert estimate.heading == FAST_MEAN[3]
    assert estimate.lateral_acceleration == FAST_MEAN[4]


def test_fast_state_named_accessors_agree_with_the_declared_field_ordering(
    tick: TickId, now: Instant, identity_covariance: SymmetricMatrix
) -> None:
    estimate = FastStateEstimate(
        tick=tick, valid_at=now, mean=FAST_MEAN, covariance=identity_covariance
    )
    accessors = {
        "position_x": estimate.position_x,
        "position_y": estimate.position_y,
        "speed": estimate.speed,
        "heading": estimate.heading,
        "lateral_acceleration": estimate.lateral_acceleration,
    }

    assert tuple(accessors) == FAST_STATE_FIELDS
    assert tuple(accessors.values()) == FAST_MEAN


# --------------------------------------------------------------------------- #
# FastStateEstimate.variance_of
# --------------------------------------------------------------------------- #


def test_variance_of_returns_the_marginal_variance_for_each_named_field(
    tick: TickId, now: Instant, identity_covariance: SymmetricMatrix
) -> None:
    estimate = FastStateEstimate(
        tick=tick, valid_at=now, mean=FAST_MEAN, covariance=identity_covariance
    )

    assert tuple(estimate.variance_of(field) for field in FAST_STATE_FIELDS) == (
        identity_covariance.diagonal
    )


def test_variance_of_the_icp_normalisation_dimension_uses_the_right_diagonal_entry(
    tick: TickId, now: Instant, identity_covariance: SymmetricMatrix
) -> None:
    estimate = FastStateEstimate(
        tick=tick, valid_at=now, mean=FAST_MEAN, covariance=identity_covariance
    )

    assert estimate.variance_of("lateral_acceleration") == 0.5
    assert estimate.variance_of("speed") == 0.25


def test_variance_of_an_unknown_field_raises_contract_violation(
    tick: TickId, now: Instant, identity_covariance: SymmetricMatrix
) -> None:
    estimate = FastStateEstimate(
        tick=tick, valid_at=now, mean=FAST_MEAN, covariance=identity_covariance
    )

    with pytest.raises(ContractViolationError) as raised:
        estimate.variance_of("yaw_rate")

    assert raised.value.context["field"] == "yaw_rate"


def test_variance_of_rejects_a_slow_state_field_name(
    tick: TickId, now: Instant, identity_covariance: SymmetricMatrix
) -> None:
    estimate = FastStateEstimate(
        tick=tick, valid_at=now, mean=FAST_MEAN, covariance=identity_covariance
    )

    with pytest.raises(ContractViolationError):
        estimate.variance_of("road_friction_coefficient")


# --------------------------------------------------------------------------- #
# SlowStateEstimate
# --------------------------------------------------------------------------- #


def test_slow_state_named_accessors_return_the_canonically_ordered_elements(
    tick: TickId, now: Instant
) -> None:
    estimate = SlowStateEstimate(
        tick=tick, valid_at=now, mean=SLOW_MEAN, covariance=_slow_covariance()
    )

    assert estimate.road_friction_coefficient == SLOW_MEAN[0]
    assert estimate.tyre_wear_index == SLOW_MEAN[1]
    assert estimate.sensor_health_score == SLOW_MEAN[2]
    assert len(SLOW_STATE_FIELDS) == 3


def test_slow_state_with_a_two_element_mean_raises_dimension_mismatch(
    tick: TickId, now: Instant
) -> None:
    with pytest.raises(DimensionMismatchError):
        SlowStateEstimate(tick=tick, valid_at=now, mean=(0.8, 0.15), covariance=_slow_covariance())


def test_slow_state_with_a_five_by_five_covariance_raises_dimension_mismatch(
    tick: TickId, now: Instant, identity_covariance: SymmetricMatrix
) -> None:
    with pytest.raises(DimensionMismatchError):
        SlowStateEstimate(tick=tick, valid_at=now, mean=SLOW_MEAN, covariance=identity_covariance)


def test_slow_state_with_a_negative_variance_reports_a_diverged_filter(
    tick: TickId, now: Instant
) -> None:
    diverged = SymmetricMatrix.from_diagonal([0.01, -0.02, 0.03])

    with pytest.raises(ContractViolationError) as raised:
        SlowStateEstimate(tick=tick, valid_at=now, mean=SLOW_MEAN, covariance=diverged)

    assert "diverged" in raised.value.message


# --------------------------------------------------------------------------- #
# InnovationRecord
# --------------------------------------------------------------------------- #


def test_innovation_record_carries_its_residual_and_fault_decision(tick: TickId) -> None:
    record = InnovationRecord(
        tick=tick, residual=(0.1, -0.2), mahalanobis_distance=1.5, fault_flagged=False
    )

    assert record.residual == (0.1, -0.2)
    assert record.mahalanobis_distance == 1.5
    assert record.fault_flagged is False


def test_innovation_record_with_an_empty_residual_raises_contract_violation(
    tick: TickId,
) -> None:
    with pytest.raises(ContractViolationError):
        InnovationRecord(tick=tick, residual=(), mahalanobis_distance=0.0, fault_flagged=False)


def test_innovation_record_with_a_negative_distance_raises_range_violation(tick: TickId) -> None:
    with pytest.raises(RangeViolationError):
        InnovationRecord(
            tick=tick, residual=(0.1,), mahalanobis_distance=-0.000_001, fault_flagged=True
        )


def test_innovation_record_with_a_nan_distance_raises_non_finite_value(tick: TickId) -> None:
    with pytest.raises(NonFiniteValueError):
        InnovationRecord(
            tick=tick, residual=(0.1,), mahalanobis_distance=float("nan"), fault_flagged=True
        )


def test_innovation_record_accepts_a_zero_distance(tick: TickId) -> None:
    record = InnovationRecord(
        tick=tick, residual=(0.0,), mahalanobis_distance=0.0, fault_flagged=False
    )

    assert record.mahalanobis_distance == 0.0


def test_innovation_record_normalises_a_list_residual_into_an_immutable_tuple(
    tick: TickId,
) -> None:
    mutable = [0.3, 0.4]
    record = InnovationRecord(
        tick=tick,
        residual=mutable,  # type: ignore[arg-type]
        mahalanobis_distance=0.5,
        fault_flagged=False,
    )
    mutable.append(99.0)

    assert isinstance(record.residual, tuple)
    assert record.residual == (0.3, 0.4)
