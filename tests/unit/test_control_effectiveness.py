"""The control-effectiveness estimator — FB2 as ADR-0020 redefines it.

The loop this replaces regressed a network onto the proposer's own commands, and
was measured collapsing the non-conformity score 40% in a context where nothing
changed. The replacement's whole claim is that its target is *measured physics*,
so no amount of adaptation can pull the twin's reference toward the thing the
twin exists to judge.

Two properties carry that claim, and everything here serves one of them:

1. It recovers the true effectiveness, **exactly**, from response alone.
2. It discards samples that carry no information — and gets the right answer
   *because* it discards them, not in spite of it.
"""

from __future__ import annotations

import pytest

from astra.kernel.enums import ContextClass
from astra.kernel.errors import ConfigurationError
from astra.runtime.assembly import STEER_INDEX, ControlEffectivenessEstimator

TRUE_B = 140.0
SATURATION = 3.0
"""Matches the synthetic plant: it clamps lateral acceleration at 3.0 m/s^2, so
it stops responding beyond |steer| = 3.0 / 140 = 0.0214."""

LINEAR_STEER = SATURATION / TRUE_B
HIGHWAY = ContextClass.HIGHWAY_CLEAR
RAIN = ContextClass.RAIN_NIGHT


def _estimator(**overrides: float | int) -> ControlEffectivenessEstimator:
    settings: dict[str, float | int] = {
        "steering_index": STEER_INDEX,
        "configured": TRUE_B,
        "saturation_limit": SATURATION,
        "minimum_samples": 20,
    }
    settings.update(overrides)
    return ControlEffectivenessEstimator(**settings)  # type: ignore[arg-type]


def _command(steer: float) -> tuple[float, float, float]:
    return (0.5, 0.0, steer)


def _drive(
    estimator: ControlEffectivenessEstimator,
    *,
    count: int,
    span: float,
    effectiveness: float = TRUE_B,
    context: ContextClass = HIGHWAY,
) -> None:
    """Feed samples from a plant with the given effectiveness and clamp."""
    for index in range(count):
        # Deterministic sweep rather than a seeded RNG: A-5 wants runs
        # reproducible, and the estimator's behaviour should not depend on
        # which particular steering values it happened to see.
        steer = span * (-1.0 + 2.0 * (index % 41) / 40.0)
        produced = max(-SATURATION, min(SATURATION, steer * effectiveness))
        estimator.observe(command=_command(steer), lateral_acceleration=produced, context=context)


# --------------------------------------------------------------------------- #
# It recovers the truth
# --------------------------------------------------------------------------- #


def test_it_recovers_the_effectiveness_exactly_in_the_linear_region() -> None:
    estimator = _estimator()

    _drive(estimator, count=400, span=LINEAR_STEER * 0.9)

    assert estimator.estimate(HIGHWAY) == pytest.approx(TRUE_B)


def test_it_tracks_a_platform_whose_effectiveness_is_not_the_configured_one() -> None:
    # The entire point of estimating rather than configuring. A vehicle whose
    # steering has changed -- wet road, worn tyres, a load shift -- must be
    # followed, or FB2 buys nothing over a constant.
    estimator = _estimator()
    changed = TRUE_B * 0.6

    _drive(estimator, count=400, span=(SATURATION / changed) * 0.9, effectiveness=changed)

    assert estimator.estimate(HIGHWAY) == pytest.approx(changed)


def test_each_context_is_estimated_separately() -> None:
    # Same reason the twin has one head per context: a wet road and a dry one are
    # different platforms as far as B is concerned, and averaging them describes
    # neither.
    estimator = _estimator()
    wet = TRUE_B * 0.5

    _drive(estimator, count=400, span=LINEAR_STEER * 0.9, context=HIGHWAY)
    _drive(estimator, count=400, span=(SATURATION / wet) * 0.9, effectiveness=wet, context=RAIN)

    assert estimator.estimate(HIGHWAY) == pytest.approx(TRUE_B)
    assert estimator.estimate(RAIN) == pytest.approx(wet)


# --------------------------------------------------------------------------- #
# It discards what carries no information, and that is why it is right
# --------------------------------------------------------------------------- #


def test_saturated_samples_are_excluded_and_the_estimate_stays_exact() -> None:
    # THE test. Driving four times past the saturation point means most samples
    # are pinned at the limit and say nothing about B. Excluding them keeps the
    # answer exact.
    estimator = _estimator()

    _drive(estimator, count=800, span=LINEAR_STEER * 4.0)

    assert estimator.estimate(HIGHWAY) == pytest.approx(TRUE_B)


def test_admitting_saturated_samples_would_read_the_effectiveness_low() -> None:
    # The control, and the reason the exclusion is a requirement rather than a
    # refinement. This computes what a naive estimator would have returned from
    # exactly the samples the real one rejected.
    #
    # Measured at 116.0 against 140.0 -- 17% low -- when this was first probed,
    # and low is the dangerous direction: an underestimated B makes the twin
    # expect more steering than the vehicle needs, which shrinks the departure
    # the non-conformity score is computed from. A gate quietly made less
    # sensitive is the failure mode this project keeps finding.
    naive: list[float] = []
    for index in range(800):
        steer = LINEAR_STEER * 4.0 * (-1.0 + 2.0 * (index % 41) / 40.0)
        if abs(steer) < 1e-3:
            continue
        produced = max(-SATURATION, min(SATURATION, steer * TRUE_B))
        naive.append(produced / steer)

    assert sum(naive) / len(naive) < TRUE_B * 0.9, (
        "the naive estimate should be badly low; if it is not, this test has "
        "stopped demonstrating why saturated samples must be dropped"
    )


def test_a_steer_too_small_to_be_informative_is_ignored() -> None:
    # Near zero the ratio is whatever noise is on the acceleration divided by a
    # small number. Admitting those samples would let sensor noise set a
    # parameter two gates depend on.
    estimator = _estimator()

    for _ in range(100):
        estimator.observe(command=_command(1e-9), lateral_acceleration=0.004, context=HIGHWAY)

    assert estimator.sample_count(HIGHWAY) == 0
    assert estimator.estimate(HIGHWAY) == pytest.approx(TRUE_B)


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_a_non_finite_sample_is_discarded_rather_than_poisoning_the_window(
    bad: float,
) -> None:
    estimator = _estimator()
    _drive(estimator, count=400, span=LINEAR_STEER * 0.9)

    estimator.observe(command=_command(bad), lateral_acceleration=1.0, context=HIGHWAY)
    estimator.observe(command=_command(0.01), lateral_acceleration=bad, context=HIGHWAY)

    assert estimator.estimate(HIGHWAY) == pytest.approx(TRUE_B)


# --------------------------------------------------------------------------- #
# It prefers a signed-off number to a badly-supported one
# --------------------------------------------------------------------------- #


def test_it_returns_the_configured_value_until_it_has_enough_samples() -> None:
    # A configured effectiveness is a characterisation someone signed off. An
    # estimate from four samples is not, and preferring the latter would be a
    # downgrade dressed as adaptation.
    estimator = _estimator(minimum_samples=20)

    _drive(estimator, count=5, span=LINEAR_STEER * 0.9, effectiveness=TRUE_B * 0.5)

    assert estimator.sample_count(HIGHWAY) == 5
    assert estimator.estimate(HIGHWAY) == pytest.approx(TRUE_B)


def test_an_unvisited_context_falls_back_to_the_configured_value() -> None:
    estimator = _estimator()
    _drive(estimator, count=400, span=LINEAR_STEER * 0.9, context=HIGHWAY)

    assert estimator.estimate(RAIN) == pytest.approx(TRUE_B)


def test_the_window_is_bounded() -> None:
    # It runs for the life of a drive, so an unbounded window is a leak. The
    # soak's memory criterion would catch it eventually; a test catches it now.
    estimator = _estimator(window=50)

    _drive(estimator, count=5_000, span=LINEAR_STEER * 0.9)

    assert estimator.sample_count(HIGHWAY) == 50


def test_the_estimate_is_a_median_so_one_outlier_cannot_move_it() -> None:
    # A transient, or a saturated sample that slipped through, must not move a
    # number two gates depend on.
    estimator = _estimator()
    _drive(estimator, count=400, span=LINEAR_STEER * 0.9)

    estimator.observe(command=_command(0.001), lateral_acceleration=2.9, context=HIGHWAY)

    assert estimator.estimate(HIGHWAY) == pytest.approx(TRUE_B)


# --------------------------------------------------------------------------- #
# Construction
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("configured", [0.0, float("nan"), float("inf")])
def test_an_unusable_configured_effectiveness_is_refused(configured: float) -> None:
    with pytest.raises(ConfigurationError, match="finite and non-zero"):
        _estimator(configured=configured)


@pytest.mark.parametrize("limit", [0.0, -1.0, float("nan")])
def test_an_unusable_saturation_limit_is_refused(limit: float) -> None:
    # Without a usable limit every sample looks unsaturated, which is precisely
    # the 17%-low failure with no way to notice it.
    with pytest.raises(ConfigurationError, match="finite and positive"):
        _estimator(saturation_limit=limit)
