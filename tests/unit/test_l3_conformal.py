"""Correctness tests for the conformal core of L3 (risk RK-2).

These are deliberately isolated from the rest of the pipeline. The roadmap
prescribes verifying the conformal machinery on synthetic series *before*
integration, because the failure mode is silence: a wrong implementation gives
an invalid guarantee without anything raising.
"""

from __future__ import annotations

import math
import random

import pytest

from astra.kernel.enums import ContextClass
from astra.kernel.errors import ConfigurationError, ContractViolationError
from astra.layers.l3_trust.mondrian import MondrianCalibration
from astra.layers.l3_trust.quantile import (
    conformal_quantile,
    empirical_cdf,
    minimum_samples_for,
)

# --------------------------------------------------------------------------- #
# The quantile rank -- mistake one
# --------------------------------------------------------------------------- #


def test_the_rank_includes_the_test_point_that_joins_the_calibration_set() -> None:
    # n = 19, epsilon = 0.05: ceil(20 * 0.95) = 19, the largest score.
    # The naive rank ceil(19 * 0.95) = 19 agrees here by coincidence, so the
    # discriminating case is below.
    scores = list(range(1, 20))

    assert conformal_quantile(scores, 0.05) == 19


def test_the_correction_makes_a_visible_difference_at_a_discriminating_size() -> None:
    # n = 39, epsilon = 0.05.
    #   correct: ceil(40 * 0.95) = 38  -> 38th smallest
    #   naive:   ceil(39 * 0.95) = 38  -> same
    # n = 20:
    #   correct: ceil(21 * 0.95) = 20  -> 20th smallest, the maximum
    #   naive:   ceil(20 * 0.95) = 19  -> one below the maximum
    scores = list(range(1, 21))
    naive = sorted(scores)[math.ceil(len(scores) * 0.95) - 1]

    assert conformal_quantile(scores, 0.05) == 20
    assert naive == 19


def test_a_higher_significance_level_gives_a_lower_threshold() -> None:
    scores = list(range(1, 101))

    assert conformal_quantile(scores, 0.20) < conformal_quantile(scores, 0.05)


def test_the_threshold_is_one_of_the_observed_scores() -> None:
    # Conformal thresholds are order statistics, never interpolations.
    scores = [0.3, 1.7, 2.9, 4.1, 5.5, 6.2, 7.8, 8.4, 9.0, 9.9] * 4

    assert conformal_quantile(scores, 0.1) in set(scores)


# --------------------------------------------------------------------------- #
# The infinite threshold -- mistake two
# --------------------------------------------------------------------------- #


def test_too_few_samples_gives_an_infinite_threshold_not_the_maximum() -> None:
    # n = 10, epsilon = 0.05: ceil(11 * 0.95) = 11 > 10. There is no finite
    # threshold that supports the guarantee. Returning max(scores) here is the
    # single line that turns "not enough data to promise anything" into a
    # rejection made on the authority of a guarantee that does not exist.
    scores = [float(value) for value in range(10)]

    assert conformal_quantile(scores, 0.05) == math.inf
    assert conformal_quantile(scores, 0.05) != max(scores)


def test_an_empty_class_gives_an_infinite_threshold() -> None:
    assert conformal_quantile([], 0.05) == math.inf


def test_the_threshold_becomes_finite_exactly_at_the_minimum_sample_count() -> None:
    epsilon = 0.05
    needed = minimum_samples_for(epsilon)

    just_below = [float(v) for v in range(needed - 1)]
    just_enough = [float(v) for v in range(needed)]

    assert conformal_quantile(just_below, epsilon) == math.inf
    assert math.isfinite(conformal_quantile(just_enough, epsilon))


@pytest.mark.parametrize(("epsilon", "expected"), [(0.05, 19), (0.1, 9), (0.2, 4), (0.5, 1)])
def test_the_minimum_sample_count_matches_the_rank_condition(epsilon: float, expected: int) -> None:
    assert minimum_samples_for(epsilon) == expected


# --------------------------------------------------------------------------- #
# Empirical coverage -- the roadmap's exit criterion
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("epsilon", [0.05, 0.1])
def test_empirical_coverage_meets_the_guarantee_on_exchangeable_data(
    epsilon: float,
) -> None:
    # The property the whole module exists for. Draw exchangeable scores, split
    # calibration and test, and check the realised coverage is at least the
    # promised 1 - epsilon. Repeated over many trials so a single lucky split
    # cannot carry it.
    rng = random.Random(20260730)
    trials = 400
    calibration_size = 200
    covered = 0

    for _ in range(trials):
        draws = [rng.gauss(0.0, 1.0) for _ in range(calibration_size + 1)]
        calibration, test = draws[:-1], draws[-1]
        threshold = conformal_quantile([abs(value) for value in calibration], epsilon)
        if abs(test) <= threshold:
            covered += 1

    realised = covered / trials
    assert realised >= (1.0 - epsilon) - 0.03, (
        f"realised coverage {realised:.3f} fell short of {1 - epsilon:.2f}"
    )


def test_coverage_holds_per_class_not_merely_on_average() -> None:
    # Mondrian's whole purpose. A pooled set can satisfy marginal coverage by
    # over-covering the common class and under-covering the rare one, and the
    # rare one is why the system exists.
    rng = random.Random(4242)
    epsilon = 0.1
    calibration = MondrianCalibration(window=500)

    # Highway scores are small and tight; rain-night scores are large and wide.
    for _ in range(300):
        calibration.observe(ContextClass.HIGHWAY_CLEAR, abs(rng.gauss(0.0, 1.0)))
        calibration.observe(ContextClass.RAIN_NIGHT, abs(rng.gauss(0.0, 5.0)))

    for context, sigma in (
        (ContextClass.HIGHWAY_CLEAR, 1.0),
        (ContextClass.RAIN_NIGHT, 5.0),
    ):
        threshold = calibration.quantile(context, epsilon)
        covered = sum(1 for _ in range(400) if abs(rng.gauss(0.0, sigma)) <= threshold)
        assert covered / 400 >= (1.0 - epsilon) - 0.04, f"{context} under-covered"


def test_a_pooled_threshold_under_covers_the_wide_class() -> None:
    # The failure Mondrian prevents, demonstrated rather than asserted.
    rng = random.Random(99)
    epsilon = 0.1
    narrow = [abs(rng.gauss(0.0, 1.0)) for _ in range(900)]
    wide = [abs(rng.gauss(0.0, 5.0)) for _ in range(100)]

    pooled = conformal_quantile(narrow + wide, epsilon)
    conditioned = conformal_quantile(wide, epsilon)

    pooled_coverage = sum(1 for _ in range(500) if abs(rng.gauss(0.0, 5.0)) <= pooled) / 500

    assert pooled < conditioned
    assert pooled_coverage < 1.0 - epsilon


# --------------------------------------------------------------------------- #
# The empirical CDF and the Trust Index it produces
# --------------------------------------------------------------------------- #


def test_the_cdf_of_an_unremarkable_score_is_middling() -> None:
    scores = [float(value) for value in range(1, 101)]

    assert empirical_cdf(scores, 50.0) == pytest.approx(0.5)


def test_an_extreme_score_drives_the_trust_index_to_zero() -> None:
    scores = [float(value) for value in range(1, 101)]

    trust_index = 1.0 - empirical_cdf(scores, 1000.0)

    assert trust_index == pytest.approx(0.0)


def test_an_unseen_class_reports_no_trust_rather_than_full_trust() -> None:
    # An empty class means nothing is known. Returning 0.0 from the CDF would
    # give a Trust Index of 1.0 -- maximum confidence from zero evidence.
    assert empirical_cdf([], 0.5) == 1.0
    assert 1.0 - empirical_cdf([], 0.5) == 0.0


# --------------------------------------------------------------------------- #
# Refusing inputs that would produce a plausible wrong answer
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("epsilon", [0.0, 1.0, -0.1, 1.5, math.nan, math.inf])
def test_a_significance_level_outside_the_open_unit_interval_is_refused(
    epsilon: float,
) -> None:
    with pytest.raises(ContractViolationError):
        conformal_quantile([1.0, 2.0, 3.0], epsilon)


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_a_non_finite_calibration_score_is_refused(bad: float) -> None:
    # A NaN sorts unpredictably and could land anywhere in the ordering.
    with pytest.raises(ContractViolationError):
        conformal_quantile([1.0, bad, 3.0], 0.05)


def test_a_non_finite_evaluation_point_is_refused() -> None:
    with pytest.raises(ContractViolationError):
        empirical_cdf([1.0, 2.0], math.nan)


# --------------------------------------------------------------------------- #
# The calibration store
# --------------------------------------------------------------------------- #


def test_every_context_class_gets_a_bucket() -> None:
    calibration = MondrianCalibration(window=10)

    for context in ContextClass:
        assert calibration.sample_count(context) == 0


def test_the_window_bounds_each_class_independently() -> None:
    calibration = MondrianCalibration(window=5)

    for value in range(20):
        calibration.observe(ContextClass.HIGHWAY_CLEAR, float(value))

    assert calibration.sample_count(ContextClass.HIGHWAY_CLEAR) == 5
    assert calibration.sample_count(ContextClass.RAIN_NIGHT) == 0
    # Oldest evicted, most recent retained.
    assert calibration.scores(ContextClass.HIGHWAY_CLEAR) == (15.0, 16.0, 17.0, 18.0, 19.0)


def test_unclassified_is_a_real_bucket_and_starts_empty() -> None:
    # The tunnel scenario: no certified class matches, so the threshold is
    # infinite and the tick routes to bounded safe exploration rather than to a
    # rejection the system cannot justify.
    calibration = MondrianCalibration(window=10)

    assert calibration.quantile(ContextClass.UNCLASSIFIED, 0.05) == math.inf


def test_seeding_installs_offline_calibration() -> None:
    calibration = MondrianCalibration(window=100)

    calibration.seed(ContextClass.URBAN_CLEAR, [float(v) for v in range(50)])

    assert calibration.sample_count(ContextClass.URBAN_CLEAR) == 50


def test_a_zero_window_is_refused() -> None:
    with pytest.raises(ConfigurationError, match="never reject"):
        MondrianCalibration(window=0)
