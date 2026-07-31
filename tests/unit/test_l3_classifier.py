"""Unit tests for the rule-based operational context classifier."""

from __future__ import annotations

import pytest

from astra.contracts.estimation import FastStateEstimate, InnovationRecord
from astra.kernel.enums import ContextClass
from astra.kernel.errors import NonFiniteValueError, RangeViolationError
from astra.kernel.identifiers import TickId
from astra.kernel.matrix import SymmetricMatrix
from astra.kernel.time import Instant, Timeline
from astra.kernel.units import MetresPerSecond
from astra.layers.l3_trust.classifier import RuleBasedContextClassifier
from astra.layers.l3_trust.trust import ContextClassifier

BOUNDARY = MetresPerSecond(19.44)
COVARIANCE = SymmetricMatrix.from_diagonal([1.0, 1.0, 0.25, 0.1, 0.5])


def _state(speed: float) -> FastStateEstimate:
    return FastStateEstimate(
        tick=TickId(0),
        valid_at=Instant(0, Timeline.MANUAL),
        mean=(0.0, 0.0, speed, 0.0, 0.0),
        covariance=COVARIANCE,
    )


def _innovation(*, flagged: bool) -> InnovationRecord:
    return InnovationRecord(
        tick=TickId(0),
        residual=(0.1, 0.2),
        mahalanobis_distance=12.0 if flagged else 0.4,
        fault_flagged=flagged,
    )


def _classifier() -> RuleBasedContextClassifier:
    return RuleBasedContextClassifier(highway_speed=BOUNDARY)


# --------------------------------------------------------------------------- #
# A flagged sensor fault dominates
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("speed", [0.0, 5.0, 19.43, 19.44, 30.0, 80.0])
def test_a_flagged_innovation_gives_degraded_sensor_at_any_speed(speed: float) -> None:
    # A degraded sensor changes which population the tick belongs to whatever
    # the vehicle is doing, so it is checked before the speed rule.
    classifier = _classifier()

    context = classifier.classify(state=_state(speed), innovation=_innovation(flagged=True))

    assert context is ContextClass.DEGRADED_SENSOR


@pytest.mark.parametrize("speed", [5.0, 30.0])
def test_an_unflagged_innovation_falls_through_to_the_speed_rule(speed: float) -> None:
    classifier = _classifier()

    context = classifier.classify(state=_state(speed), innovation=_innovation(flagged=False))

    assert context is not ContextClass.DEGRADED_SENSOR


def test_a_missing_innovation_falls_through_to_the_speed_rule() -> None:
    classifier = _classifier()

    assert classifier.classify(state=_state(30.0), innovation=None) is ContextClass.HIGHWAY_CLEAR
    assert classifier.classify(state=_state(5.0), innovation=None) is ContextClass.URBAN_CLEAR


# --------------------------------------------------------------------------- #
# The speed boundary
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("speed", "expected"),
    [
        (0.0, ContextClass.URBAN_CLEAR),
        (10.0, ContextClass.URBAN_CLEAR),
        (float(BOUNDARY) - 0.01, ContextClass.URBAN_CLEAR),
        (float(BOUNDARY), ContextClass.HIGHWAY_CLEAR),
        (float(BOUNDARY) + 0.01, ContextClass.HIGHWAY_CLEAR),
        (45.0, ContextClass.HIGHWAY_CLEAR),
    ],
)
def test_the_boundary_is_inclusive_of_highway(speed: float, expected: ContextClass) -> None:
    classifier = _classifier()

    assert classifier.classify(state=_state(speed), innovation=None) is expected


def test_the_configured_boundary_is_readable() -> None:
    assert _classifier().highway_speed == BOUNDARY


# --------------------------------------------------------------------------- #
# RAIN_NIGHT is unreachable, and that is documented rather than approximated
# --------------------------------------------------------------------------- #


def test_rain_night_is_never_returned_for_any_input() -> None:
    # Precipitation and ambient light are not in the fast state vector, so this
    # classifier cannot decide RAIN_NIGHT and does not pretend to. The test
    # exists so that nobody "fixes" the gap with a friction heuristic without
    # also updating the module docstring that explains why it is a gap.
    classifier = _classifier()
    speeds = [index * 2.5 for index in range(40)]

    produced = {
        classifier.classify(state=_state(speed), innovation=innovation)
        for speed in speeds
        for innovation in (None, _innovation(flagged=False), _innovation(flagged=True))
    }

    assert ContextClass.RAIN_NIGHT not in produced
    assert produced == {
        ContextClass.HIGHWAY_CLEAR,
        ContextClass.URBAN_CLEAR,
        ContextClass.DEGRADED_SENSOR,
    }


def test_unclassified_is_never_returned_either() -> None:
    # UNCLASSIFIED is L9's answer when no certified profile matches an RCS, not
    # a classification this rule can reach.
    classifier = _classifier()

    produced = {
        classifier.classify(state=_state(speed), innovation=None)
        for speed in (0.0, 15.0, 25.0, 60.0)
    }

    assert ContextClass.UNCLASSIFIED not in produced


# --------------------------------------------------------------------------- #
# Construction
# --------------------------------------------------------------------------- #


def test_a_negative_boundary_speed_is_refused() -> None:
    with pytest.raises(RangeViolationError):
        RuleBasedContextClassifier(highway_speed=MetresPerSecond(-1.0))


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_a_non_finite_boundary_speed_is_refused(bad: float) -> None:
    with pytest.raises(NonFiniteValueError):
        RuleBasedContextClassifier(highway_speed=MetresPerSecond(bad))


def test_a_zero_boundary_makes_everything_highway() -> None:
    classifier = RuleBasedContextClassifier(highway_speed=MetresPerSecond(0.0))

    assert classifier.classify(state=_state(0.0), innovation=None) is ContextClass.HIGHWAY_CLEAR


# --------------------------------------------------------------------------- #
# Statelessness and protocol conformance
# --------------------------------------------------------------------------- #


def test_the_classifier_is_stateless() -> None:
    # A classification must be reproducible from an evidence record without
    # replaying the run that produced it.
    classifier = _classifier()
    state = _state(30.0)

    first = classifier.classify(state=state, innovation=None)
    classifier.classify(state=_state(1.0), innovation=_innovation(flagged=True))
    second = classifier.classify(state=state, innovation=None)

    assert first is second


def test_the_classifier_satisfies_the_context_classifier_protocol() -> None:
    assert isinstance(_classifier(), ContextClassifier)
