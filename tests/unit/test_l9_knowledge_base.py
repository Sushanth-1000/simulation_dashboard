"""Unit tests for L9's cold-path search, scoring and exploration envelope."""

from __future__ import annotations

import math
from datetime import UTC, datetime

import pytest

from astra.contracts.governance import (
    CalibrationProfile,
    ProfileFieldHistory,
    RuntimeContextSignature,
)
from astra.kernel.enums import ContextClass
from astra.kernel.errors import ConfigurationError, SafetyPathError
from astra.kernel.identifiers import ProfileId, TickId
from astra.kernel.matrix import SymmetricMatrix
from astra.kernel.units import MetresPerSecond, Probability, Radians
from astra.layers.l9_rcm.exploration import (
    MAXIMUM_STEERING_RADIANS,
    SPEED_FRACTION_OF_NEAREST,
    ExplorationEnvelope,
    ExplorationExit,
    exploration_envelope,
)
from astra.layers.l9_rcm.knowledge_base import (
    SearchWeights,
    mahalanobis_distance,
    rejects,
    score_candidates,
)

NOW = datetime(2026, 7, 1, tzinfo=UTC)
LATER = datetime(2027, 7, 1, tzinfo=UTC)
EARLIER = datetime(2026, 1, 1, tzinfo=UTC)
# Strictly before every expiry above: the contract requires a profile to expire
# after it was certified.
CERTIFIED = datetime(2025, 1, 1, tzinfo=UTC)
PLATFORM = "astra-reference-vehicle"
WEIGHTS = SearchWeights(similarity=1.0, validation=1.0, history=0.5, risk=0.25)


def _signature(
    components: tuple[float, ...] = (0.5, 0.5, 0.5, 0.5, 0.5),
) -> RuntimeContextSignature:
    return RuntimeContextSignature(
        tick=TickId(1), components=tuple(Probability(v) for v in components)
    )


def _profile(
    name: str = "highway_clear",
    *,
    centroid: tuple[float, ...] = (0.5, 0.5, 0.5, 0.5, 0.5),
    validation: float = 1.0,
    passed: bool = True,
    platform: str = PLATFORM,
    expires: datetime = LATER,
    deployments: int = 0,
    critical_failures: int = 0,
    context: ContextClass = ContextClass.HIGHWAY_CLEAR,
    spread: float = 0.04,
) -> CalibrationProfile:
    return CalibrationProfile(
        profile_id=ProfileId(name=name, version=1),
        context_class=context,
        centroid=centroid,
        covariance=SymmetricMatrix.from_diagonal([spread] * 5),
        quantile_table=(0.1, 0.3, 0.7, 1.2),
        coverage_level=Probability(0.95),
        validation_fraction=Probability(validation),
        validation_passed=passed,
        max_speed=MetresPerSecond(30.0),
        checksum="0" * 64,
        platform=platform,
        certified_at=CERTIFIED,
        expires_at=expires,
        # The contract forbids more critical failures than deployments, so a
        # test asking for failures implies at least that many deployments.
        field_history=ProfileFieldHistory(
            deployments=max(deployments, critical_failures),
            critical_failures=critical_failures,
        ),
    )


# --------------------------------------------------------------------------- #
# Mahalanobis distance
# --------------------------------------------------------------------------- #


def test_the_distance_to_the_centroid_itself_is_zero() -> None:
    covariance = SymmetricMatrix.from_diagonal([0.25] * 3)

    assert mahalanobis_distance((1.0, 2.0, 3.0), (1.0, 2.0, 3.0), covariance) == pytest.approx(0.0)


def test_the_distance_is_measured_in_units_of_the_profile_spread() -> None:
    # A displacement of one standard deviation is a distance of one, whatever
    # the variance happens to be. This also pins the packed-triangle convention
    # the forward substitution assumes.
    tight = SymmetricMatrix.from_diagonal([0.01, 0.01])
    loose = SymmetricMatrix.from_diagonal([1.0, 1.0])

    assert mahalanobis_distance((0.1, 0.0), (0.0, 0.0), tight) == pytest.approx(1.0)
    assert mahalanobis_distance((1.0, 0.0), (0.0, 0.0), loose) == pytest.approx(1.0)


def test_the_same_displacement_is_further_under_a_tighter_covariance() -> None:
    # The reason similarity is Mahalanobis and not Euclidean: "how unusual is
    # this for *this* profile", not "how far in an arbitrary coordinate system".
    displacement = (0.3, 0.0, 0.0, 0.0, 0.0)
    origin = (0.0,) * 5

    tight = mahalanobis_distance(displacement, origin, SymmetricMatrix.from_diagonal([0.01] * 5))
    loose = mahalanobis_distance(displacement, origin, SymmetricMatrix.from_diagonal([1.0] * 5))

    assert tight > loose


def test_a_dimension_mismatch_fails_closed() -> None:
    with pytest.raises(SafetyPathError, match="dimension mismatch"):
        mahalanobis_distance((1.0, 2.0), (1.0, 2.0, 3.0), SymmetricMatrix.from_diagonal([1.0] * 3))


def test_a_covariance_that_is_not_positive_definite_is_refused() -> None:
    # A covariance admitting no Cholesky factor describes no distribution, so a
    # distance from it would be a plausible number about nothing. Inverting
    # instead would have produced enormous finite values and a profile that
    # appeared to match everything.
    degenerate = SymmetricMatrix.from_diagonal([0.0, 1.0])

    with pytest.raises(SafetyPathError, match="positive definite"):
        mahalanobis_distance((1.0, 1.0), (0.0, 0.0), degenerate)


# --------------------------------------------------------------------------- #
# The mandatory gates -- vetoes, never weights
# --------------------------------------------------------------------------- #


def test_a_current_profile_for_this_platform_passes_every_gate() -> None:
    assert rejects(_profile(), platform=PLATFORM, now=NOW) is None


def test_an_expired_signature_is_rejected() -> None:
    assert rejects(_profile(expires=EARLIER), platform=PLATFORM, now=NOW) == "EXPIRED_SIGNATURE"


def test_expiry_is_inclusive_at_the_instant_it_expires() -> None:
    assert rejects(_profile(expires=NOW), platform=PLATFORM, now=NOW) == "EXPIRED_SIGNATURE"


def test_a_profile_for_another_platform_is_rejected() -> None:
    assert rejects(_profile(platform="other-vehicle"), platform=PLATFORM, now=NOW) == (
        "PLATFORM_MISMATCH"
    )


def test_a_documented_critical_failure_rejects_the_profile() -> None:
    assert rejects(_profile(critical_failures=1), platform=PLATFORM, now=NOW) == (
        "CRITICAL_FAILURE_HISTORY"
    )


def test_a_gated_profile_is_never_scored_however_close_its_centroid() -> None:
    # The ordering that is the safety argument. An expired profile sitting
    # exactly on the signature must not out-score a valid one further away.
    perfect_but_expired = _profile("expired", expires=EARLIER)
    valid_but_distant = _profile("valid_distant", centroid=(0.9, 0.9, 0.9, 0.9, 0.9))

    candidates, rejections = score_candidates(
        signature=_signature(),
        profiles=[perfect_but_expired, valid_but_distant],
        weights=WEIGHTS,
        platform=PLATFORM,
        now=NOW,
    )

    assert [c.profile.profile_id.name for c in candidates] == ["valid_distant"]
    assert [reason for _, reason in rejections] == ["EXPIRED_SIGNATURE"]


def test_rejections_record_why_the_knowledge_base_came_up_empty() -> None:
    # The difference between a diagnosable tunnel scenario and a mysterious one.
    _, rejections = score_candidates(
        signature=_signature(),
        profiles=[
            _profile("expired_one", expires=EARLIER),
            _profile("wrong_platform", platform="other"),
            _profile("failed_in_field", critical_failures=2),
        ],
        weights=WEIGHTS,
        platform=PLATFORM,
        now=NOW,
    )

    assert {reason for _, reason in rejections} == {
        "EXPIRED_SIGNATURE",
        "PLATFORM_MISMATCH",
        "CRITICAL_FAILURE_HISTORY",
    }


# --------------------------------------------------------------------------- #
# Scoring and admissibility
# --------------------------------------------------------------------------- #


def test_a_closer_profile_scores_higher() -> None:
    near = _profile("near_profile", centroid=(0.5, 0.5, 0.5, 0.5, 0.5))
    far = _profile("far_profile", centroid=(0.95, 0.95, 0.95, 0.95, 0.95))

    candidates, _ = score_candidates(
        signature=_signature(),
        profiles=[far, near],
        weights=WEIGHTS,
        platform=PLATFORM,
        now=NOW,
    )

    assert candidates[0].profile.profile_id.name == "near_profile"


def test_similarity_is_bounded_so_one_close_profile_cannot_dominate() -> None:
    candidates, _ = score_candidates(
        signature=_signature(),
        profiles=[_profile()],
        weights=WEIGHTS,
        platform=PLATFORM,
        now=NOW,
    )

    assert 0.0 < candidates[0].similarity <= 1.0


def test_a_profile_that_failed_certification_is_inadmissible_however_high_the_score() -> None:
    # val(c) is a conjunct, not a weight. A profile that failed its
    # certification suite is inadmissible whatever it scores.
    #
    # This is expressed through `validation_passed`, not through a held-out
    # fraction below 1.0. Conflating the two made every correctly-certified
    # profile -- one holding out a sensible 20% -- permanently inadmissible.
    candidates, _ = score_candidates(
        signature=_signature(),
        profiles=[_profile(passed=False)],
        weights=WEIGHTS,
        platform=PLATFORM,
        now=NOW,
    )

    assert not candidates[0].is_valid
    assert not candidates[0].is_admissible(threshold=-1000.0)


def test_a_valid_candidate_above_the_threshold_is_admissible() -> None:
    candidates, _ = score_candidates(
        signature=_signature(),
        profiles=[_profile(validation=1.0)],
        weights=WEIGHTS,
        platform=PLATFORM,
        now=NOW,
    )

    assert candidates[0].is_admissible(threshold=0.5)
    assert not candidates[0].is_admissible(threshold=1000.0)


def test_an_unproven_profile_scores_zero_history_rather_than_full_marks() -> None:
    # Defaulting an unknown to its best possible value is how an unvalidated
    # candidate wins a ranking.
    unproven = _profile("unproven", deployments=0)
    proven = _profile("proven", deployments=100)

    candidates, _ = score_candidates(
        signature=_signature(),
        profiles=[unproven, proven],
        weights=SearchWeights(similarity=0.0, validation=0.0, history=1.0, risk=0.0),
        platform=PLATFORM,
        now=NOW,
    )

    assert candidates[0].profile.profile_id.name == "proven"
    assert candidates[-1].trust_score == pytest.approx(0.0)


def test_the_history_term_saturates_so_it_cannot_dominate() -> None:
    seasoned = _profile("seasoned", deployments=10_000)

    candidates, _ = score_candidates(
        signature=_signature(),
        profiles=[seasoned],
        weights=SearchWeights(similarity=0.0, validation=0.0, history=1.0, risk=0.0),
        platform=PLATFORM,
        now=NOW,
    )

    assert candidates[0].trust_score < 1.0


def test_staying_within_the_active_context_costs_no_transition_risk() -> None:
    staying = _profile("staying", context=ContextClass.HIGHWAY_CLEAR)
    switching = _profile("switching", context=ContextClass.URBAN_CLEAR)

    candidates, _ = score_candidates(
        signature=_signature(),
        profiles=[switching, staying],
        weights=SearchWeights(similarity=0.0, validation=0.0, history=0.0, risk=1.0),
        platform=PLATFORM,
        now=NOW,
        active_profile_context=ContextClass.HIGHWAY_CLEAR,
    )

    assert candidates[0].profile.profile_id.name == "staying"


def test_an_empty_knowledge_base_yields_no_candidates_and_no_rejections() -> None:
    candidates, rejections = score_candidates(
        signature=_signature(), profiles=[], weights=WEIGHTS, platform=PLATFORM, now=NOW
    )

    assert candidates == ()
    assert rejections == ()


# --------------------------------------------------------------------------- #
# The bounded safe-exploration envelope
# --------------------------------------------------------------------------- #


def test_the_speed_cap_is_half_the_nearest_certified_maximum() -> None:
    envelope = exploration_envelope(30.0)

    assert envelope.speed_cap == pytest.approx(30.0 * SPEED_FRACTION_OF_NEAREST)


def test_the_steering_cone_is_fifteen_degrees() -> None:
    assert exploration_envelope(30.0).steering_limit == pytest.approx(math.radians(15.0))


def test_lane_changes_are_never_permitted() -> None:
    assert not exploration_envelope(30.0).lane_changes_permitted


def test_an_envelope_permitting_a_lane_change_is_refused() -> None:
    # Not defensive: an envelope that allowed a lane change would not be a
    # safe-exploration envelope, whatever it was called.
    with pytest.raises(ConfigurationError, match="never permitted"):
        ExplorationEnvelope(
            speed_cap=MetresPerSecond(5.0),
            steering_limit=Radians(0.1),
            lane_changes_permitted=True,
        )


def test_a_steering_limit_beyond_the_cone_is_refused() -> None:
    with pytest.raises(ConfigurationError, match="steering limit"):
        ExplorationEnvelope(
            speed_cap=MetresPerSecond(5.0),
            steering_limit=Radians(MAXIMUM_STEERING_RADIANS * 2.0),
        )


@pytest.mark.parametrize("speed", [-1.0, math.nan, math.inf])
def test_a_nonsensical_nearest_speed_is_refused(speed: float) -> None:
    with pytest.raises(ConfigurationError):
        exploration_envelope(speed)


def test_a_stationary_nearest_profile_yields_a_stationary_envelope() -> None:
    # Legitimate: "the nearest thing we know about is not allowed to move
    # either". Inventing a floor here would be this function overruling the
    # only evidence available.
    assert exploration_envelope(0.0).speed_cap == 0.0


def test_no_exit_condition_is_a_halt() -> None:
    # Every exit leaves the vehicle moving or hands over to L8's graduated
    # posture. Reaching HALT stays L8's decision, on its own counter.
    assert set(ExplorationExit) == {
        ExplorationExit.TIMEOUT,
        ExplorationExit.DEGRADED,
        ExplorationExit.PROFILE_REACQUIRED,
        ExplorationExit.OPERATOR_REQUESTED,
    }
    assert not any("HALT" in exit_reason.value for exit_reason in ExplorationExit)
