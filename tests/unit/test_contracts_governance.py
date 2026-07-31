"""Unit tests for the governance contracts, including SI-9 and the admissibility gate."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from astra.contracts.governance import (
    ArbitrationDecision,
    CalibrationProfile,
    ProfileFieldHistory,
    RuntimeContextSignature,
    is_candidate_admissible,
)
from astra.kernel.constants import RCS_DIMENSION, RCS_FIELDS
from astra.kernel.enums import ArbitrationOutcome, ContextClass
from astra.kernel.errors import (
    ContractViolationError,
    DimensionMismatchError,
    NonFiniteValueError,
    RangeViolationError,
)
from astra.kernel.identifiers import ProfileId, TickId
from astra.kernel.matrix import SymmetricMatrix
from astra.kernel.units import MetresPerSecond, Probability

RCS_COMPONENTS = (0.9, 0.4, 0.25, 0.8, 0.15)
ACTIVE_PROFILE = ProfileId(name="highway_clear", version=2)
CANDIDATE_PROFILE = ProfileId(name="rain_night", version=1)


def _signature(
    tick: TickId, components: tuple[float, ...] = RCS_COMPONENTS
) -> RuntimeContextSignature:
    return RuntimeContextSignature(
        tick=tick, components=tuple(Probability(value) for value in components)
    )


def _profile(
    *,
    certified_at: datetime,
    expires_at: datetime,
    covariance: SymmetricMatrix,
    centroid: tuple[float, ...] = (0.5, 0.5, 0.5, 0.5, 0.5),
    quantile_table: tuple[float, ...] = (0.1, 0.4, 0.4, 1.9),
    checksum: str = "sha256:0f1e2d",
    platform: str = "carla-model3",
    field_history: ProfileFieldHistory | None = None,
) -> CalibrationProfile:
    return CalibrationProfile(
        profile_id=ACTIVE_PROFILE,
        context_class=ContextClass.HIGHWAY_CLEAR,
        centroid=centroid,
        covariance=covariance,
        quantile_table=quantile_table,
        coverage_level=Probability(0.9),
        validation_fraction=Probability(0.2),
        validation_passed=True,
        max_speed=MetresPerSecond(31.0),
        checksum=checksum,
        platform=platform,
        certified_at=certified_at,
        expires_at=expires_at,
        field_history=field_history if field_history is not None else ProfileFieldHistory(),
    )


# --------------------------------------------------------------------------- #
# RuntimeContextSignature
# --------------------------------------------------------------------------- #


def test_runtime_context_signature_accepts_the_five_dimensional_layout(tick: TickId) -> None:
    signature = _signature(tick)

    assert len(signature.components) == RCS_DIMENSION
    assert RCS_DIMENSION == 5


def test_runtime_context_signature_with_four_components_raises_dimension_mismatch(
    tick: TickId,
) -> None:
    with pytest.raises(DimensionMismatchError):
        RuntimeContextSignature(
            tick=tick, components=tuple(Probability(value) for value in (0.1, 0.2, 0.3, 0.4))
        )


def test_runtime_context_signature_with_six_components_raises_dimension_mismatch(
    tick: TickId,
) -> None:
    with pytest.raises(DimensionMismatchError):
        RuntimeContextSignature(
            tick=tick,
            components=tuple(Probability(value) for value in (*RCS_COMPONENTS, 0.5)),
        )


def test_runtime_context_signature_with_a_component_above_one_raises_range_violation(
    tick: TickId,
) -> None:
    with pytest.raises(RangeViolationError) as raised:
        _signature(tick, (0.9, 0.4, 1.5, 0.8, 0.15))

    assert raised.value.context["field"] == "rcs.traffic_dynamicity"


def test_runtime_context_signature_with_a_negative_component_raises_range_violation(
    tick: TickId,
) -> None:
    with pytest.raises(RangeViolationError) as raised:
        _signature(tick, (-0.001, 0.4, 0.25, 0.8, 0.15))

    assert raised.value.context["field"] == "rcs.visibility"


def test_runtime_context_signature_with_a_nan_component_raises_non_finite_value(
    tick: TickId,
) -> None:
    with pytest.raises(NonFiniteValueError):
        _signature(tick, (0.9, 0.4, 0.25, float("nan"), 0.15))


def test_runtime_context_signature_accessors_map_to_the_declared_field_indices(
    tick: TickId,
) -> None:
    signature = _signature(tick)
    accessors = {
        "visibility": signature.visibility,
        "ego_speed": signature.ego_speed,
        "traffic_dynamicity": signature.traffic_dynamicity,
        "sensor_reliability": signature.sensor_reliability,
        "road_complexity": signature.road_complexity,
    }

    assert tuple(accessors) == RCS_FIELDS
    for index, field in enumerate(RCS_FIELDS):
        assert accessors[field] == RCS_COMPONENTS[index]


def test_runtime_context_signature_as_vector_returns_plain_floats_in_canonical_order(
    tick: TickId,
) -> None:
    vector = _signature(tick).as_vector()

    assert vector == RCS_COMPONENTS
    assert all(type(value) is float for value in vector)


def test_runtime_context_signature_accepts_the_closed_unit_interval_endpoints(
    tick: TickId,
) -> None:
    signature = _signature(tick, (0.0, 1.0, 0.0, 1.0, 0.0))

    assert signature.as_vector() == (0.0, 1.0, 0.0, 1.0, 0.0)


# --------------------------------------------------------------------------- #
# ProfileFieldHistory
# --------------------------------------------------------------------------- #


def test_profile_field_history_defaults_to_an_unused_profile() -> None:
    history = ProfileFieldHistory()

    assert history.deployments == 0
    assert history.critical_failures == 0
    assert not history.has_critical_failure_history


def test_profile_field_history_with_negative_deployments_raises_contract_violation() -> None:
    with pytest.raises(ContractViolationError):
        ProfileFieldHistory(deployments=-1, critical_failures=0)


def test_profile_field_history_with_negative_critical_failures_raises_contract_violation() -> None:
    with pytest.raises(ContractViolationError):
        ProfileFieldHistory(deployments=5, critical_failures=-1)


def test_profile_field_history_with_more_failures_than_deployments_raises_contract_violation() -> (
    None
):
    with pytest.raises(ContractViolationError) as raised:
        ProfileFieldHistory(deployments=2, critical_failures=3)

    assert raised.value.context == {"deployments": 2, "critical_failures": 3}


def test_profile_field_history_reports_a_critical_failure_history_when_any_failure_occurred() -> (
    None
):
    history = ProfileFieldHistory(deployments=40, critical_failures=1)

    assert history.has_critical_failure_history


def test_profile_field_history_reports_no_history_for_a_clean_record() -> None:
    history = ProfileFieldHistory(deployments=40, critical_failures=0)

    assert not history.has_critical_failure_history


# --------------------------------------------------------------------------- #
# CalibrationProfile -- SI-9, quantile monotonicity
# --------------------------------------------------------------------------- #


def test_calibration_profile_with_a_monotonic_quantile_table_is_accepted_under_si9(
    certified_at: datetime, expires_at: datetime, identity_covariance: SymmetricMatrix
) -> None:
    profile = _profile(
        certified_at=certified_at,
        expires_at=expires_at,
        covariance=identity_covariance,
        quantile_table=(0.1, 0.4, 0.4, 1.9),
    )

    assert profile.quantile_table == (0.1, 0.4, 0.4, 1.9)


def test_calibration_profile_with_a_non_monotonic_quantile_table_violates_si9(
    certified_at: datetime, expires_at: datetime, identity_covariance: SymmetricMatrix
) -> None:
    with pytest.raises(RangeViolationError) as raised:
        _profile(
            certified_at=certified_at,
            expires_at=expires_at,
            covariance=identity_covariance,
            quantile_table=(0.1, 0.9, 0.4, 1.9),
        )

    assert raised.value.context == {"field": "quantile_table", "index": 2}


def test_calibration_profile_with_a_nan_in_the_quantile_table_violates_si9(
    certified_at: datetime, expires_at: datetime, identity_covariance: SymmetricMatrix
) -> None:
    with pytest.raises(NonFiniteValueError):
        _profile(
            certified_at=certified_at,
            expires_at=expires_at,
            covariance=identity_covariance,
            quantile_table=(0.1, float("nan"), 1.9),
        )


# --------------------------------------------------------------------------- #
# CalibrationProfile -- structure and ranges
# --------------------------------------------------------------------------- #


def test_calibration_profile_with_a_four_element_centroid_raises_dimension_mismatch(
    certified_at: datetime, expires_at: datetime, identity_covariance: SymmetricMatrix
) -> None:
    with pytest.raises(DimensionMismatchError):
        _profile(
            certified_at=certified_at,
            expires_at=expires_at,
            covariance=identity_covariance,
            centroid=(0.5, 0.5, 0.5, 0.5),
        )


def test_calibration_profile_with_a_centroid_component_above_one_raises_range_violation(
    certified_at: datetime, expires_at: datetime, identity_covariance: SymmetricMatrix
) -> None:
    with pytest.raises(RangeViolationError):
        _profile(
            certified_at=certified_at,
            expires_at=expires_at,
            covariance=identity_covariance,
            centroid=(0.5, 0.5, 1.5, 0.5, 0.5),
        )


def test_calibration_profile_with_a_wrongly_sized_covariance_raises_dimension_mismatch(
    certified_at: datetime, expires_at: datetime
) -> None:
    with pytest.raises(DimensionMismatchError) as raised:
        _profile(
            certified_at=certified_at,
            expires_at=expires_at,
            covariance=SymmetricMatrix.from_diagonal([1.0, 1.0, 1.0]),
        )

    assert raised.value.context == {"expected": RCS_DIMENSION}


def test_calibration_profile_with_an_empty_checksum_raises_contract_violation(
    certified_at: datetime, expires_at: datetime, identity_covariance: SymmetricMatrix
) -> None:
    with pytest.raises(ContractViolationError) as raised:
        _profile(
            certified_at=certified_at,
            expires_at=expires_at,
            covariance=identity_covariance,
            checksum="",
        )

    assert raised.value.context["profile"] == "highway_clear@v2"


def test_calibration_profile_with_an_empty_platform_raises_contract_violation(
    certified_at: datetime, expires_at: datetime, identity_covariance: SymmetricMatrix
) -> None:
    with pytest.raises(ContractViolationError):
        _profile(
            certified_at=certified_at,
            expires_at=expires_at,
            covariance=identity_covariance,
            platform="",
        )


# --------------------------------------------------------------------------- #
# CalibrationProfile -- certification dates
# --------------------------------------------------------------------------- #


def test_calibration_profile_with_a_naive_certification_date_raises_contract_violation(
    expires_at: datetime, identity_covariance: SymmetricMatrix
) -> None:
    naive = datetime(2026, 1, 1)  # noqa: DTZ001 - a naive datetime is the thing under test

    with pytest.raises(ContractViolationError) as raised:
        _profile(certified_at=naive, expires_at=expires_at, covariance=identity_covariance)

    assert raised.value.context["field"] == "certified_at"


def test_calibration_profile_with_a_naive_expiry_date_raises_contract_violation(
    certified_at: datetime, identity_covariance: SymmetricMatrix
) -> None:
    naive = datetime(2027, 1, 1)  # noqa: DTZ001 - a naive datetime is the thing under test

    with pytest.raises(ContractViolationError) as raised:
        _profile(certified_at=certified_at, expires_at=naive, covariance=identity_covariance)

    assert raised.value.context["field"] == "expires_at"


def test_calibration_profile_with_an_expiry_before_certification_raises_contract_violation(
    certified_at: datetime, identity_covariance: SymmetricMatrix
) -> None:
    with pytest.raises(ContractViolationError):
        _profile(
            certified_at=certified_at,
            expires_at=certified_at - timedelta(days=1),
            covariance=identity_covariance,
        )


def test_calibration_profile_with_an_expiry_equal_to_certification_raises_contract_violation(
    certified_at: datetime, identity_covariance: SymmetricMatrix
) -> None:
    with pytest.raises(ContractViolationError):
        _profile(
            certified_at=certified_at,
            expires_at=certified_at,
            covariance=identity_covariance,
        )


def test_calibration_profile_is_expired_before_at_and_after_the_expiry_instant(
    certified_at: datetime, expires_at: datetime, identity_covariance: SymmetricMatrix
) -> None:
    profile = _profile(
        certified_at=certified_at, expires_at=expires_at, covariance=identity_covariance
    )

    assert not profile.is_expired(expires_at - timedelta(seconds=1))
    assert profile.is_expired(expires_at)
    assert profile.is_expired(expires_at + timedelta(days=365))


def test_calibration_profile_is_expired_with_a_naive_now_raises_contract_violation(
    certified_at: datetime, expires_at: datetime, identity_covariance: SymmetricMatrix
) -> None:
    profile = _profile(
        certified_at=certified_at, expires_at=expires_at, covariance=identity_covariance
    )
    naive = datetime(2026, 6, 1)  # noqa: DTZ001 - a naive datetime is the thing under test

    with pytest.raises(ContractViolationError):
        profile.is_expired(naive)


def test_calibration_profile_retains_the_field_history_the_mandatory_gates_read(
    certified_at: datetime, expires_at: datetime, identity_covariance: SymmetricMatrix
) -> None:
    profile = _profile(
        certified_at=certified_at,
        expires_at=expires_at,
        covariance=identity_covariance,
        field_history=ProfileFieldHistory(deployments=12, critical_failures=1),
    )

    assert profile.field_history.has_critical_failure_history
    assert profile.certified_at.tzinfo is UTC


# --------------------------------------------------------------------------- #
# ArbitrationDecision
# --------------------------------------------------------------------------- #


def test_arbitration_decision_continue_needs_no_candidate_profile(tick: TickId) -> None:
    decision = ArbitrationDecision(
        tick=tick, outcome=ArbitrationOutcome.CONTINUE, active_profile=ACTIVE_PROFILE
    )

    assert decision.candidate_profile is None
    assert decision.trust_score is None


def test_arbitration_decision_safe_exploration_needs_no_candidate_profile(tick: TickId) -> None:
    decision = ArbitrationDecision(
        tick=tick, outcome=ArbitrationOutcome.SAFE_EXPLORATION, active_profile=ACTIVE_PROFILE
    )

    assert decision.candidate_profile is None


@pytest.mark.parametrize(
    "outcome",
    [
        ArbitrationOutcome.SHADOW_EXECUTION,
        ArbitrationOutcome.SWITCH_COMMITTED,
        ArbitrationOutcome.ROLLBACK,
    ],
)
def test_arbitration_decision_without_a_required_candidate_raises_contract_violation(
    tick: TickId, outcome: ArbitrationOutcome
) -> None:
    with pytest.raises(ContractViolationError) as raised:
        ArbitrationDecision(tick=tick, outcome=outcome, active_profile=ACTIVE_PROFILE)

    assert raised.value.context["outcome"] == outcome.value


@pytest.mark.parametrize(
    "outcome",
    [
        ArbitrationOutcome.SHADOW_EXECUTION,
        ArbitrationOutcome.SWITCH_COMMITTED,
        ArbitrationOutcome.ROLLBACK,
    ],
)
def test_arbitration_decision_with_the_required_candidate_is_accepted(
    tick: TickId, outcome: ArbitrationOutcome
) -> None:
    decision = ArbitrationDecision(
        tick=tick,
        outcome=outcome,
        active_profile=ACTIVE_PROFILE,
        candidate_profile=CANDIDATE_PROFILE,
        trust_score=0.75,
        calibration_divergence_index=Probability(0.05),
    )

    assert decision.candidate_profile == CANDIDATE_PROFILE


def test_arbitration_decision_accepts_a_negative_trust_score_because_risk_may_dominate(
    tick: TickId,
) -> None:
    decision = ArbitrationDecision(
        tick=tick,
        outcome=ArbitrationOutcome.CONTINUE,
        active_profile=ACTIVE_PROFILE,
        trust_score=-3.5,
    )

    assert decision.trust_score == -3.5


def test_arbitration_decision_with_a_nan_trust_score_raises_non_finite_value(tick: TickId) -> None:
    with pytest.raises(NonFiniteValueError):
        ArbitrationDecision(
            tick=tick,
            outcome=ArbitrationOutcome.CONTINUE,
            active_profile=ACTIVE_PROFILE,
            trust_score=float("nan"),
        )


def test_arbitration_decision_with_a_divergence_index_above_one_raises_range_violation(
    tick: TickId,
) -> None:
    with pytest.raises(RangeViolationError):
        ArbitrationDecision(
            tick=tick,
            outcome=ArbitrationOutcome.CONTINUE,
            active_profile=ACTIVE_PROFILE,
            calibration_divergence_index=Probability(1.2),
        )


# --------------------------------------------------------------------------- #
# is_candidate_admissible -- the hard AND
# --------------------------------------------------------------------------- #


def test_is_candidate_admissible_accepts_a_valid_candidate_meeting_the_threshold() -> None:
    assert is_candidate_admissible(trust_score=0.8, threshold=0.7, is_valid=True)


def test_is_candidate_admissible_accepts_a_valid_candidate_exactly_at_the_threshold() -> None:
    assert is_candidate_admissible(trust_score=0.7, threshold=0.7, is_valid=True)


def test_is_candidate_admissible_rejects_a_valid_candidate_below_the_threshold() -> None:
    assert not is_candidate_admissible(trust_score=0.69, threshold=0.7, is_valid=True)


def test_is_candidate_admissible_rejects_an_invalid_candidate_despite_a_huge_trust_score() -> None:
    assert not is_candidate_admissible(trust_score=1e9, threshold=0.7, is_valid=False)


def test_is_candidate_admissible_is_a_hard_conjunction_over_every_input_combination() -> None:
    outcomes = {
        (score, valid): is_candidate_admissible(trust_score=score, threshold=0.5, is_valid=valid)
        for score in (0.1, 0.5, 1_000_000.0)
        for valid in (True, False)
    }

    assert outcomes == {
        (0.1, True): False,
        (0.1, False): False,
        (0.5, True): True,
        (0.5, False): False,
        (1_000_000.0, True): True,
        (1_000_000.0, False): False,
    }
