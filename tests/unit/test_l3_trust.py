"""Unit tests for the L3 Trust Module's port implementation."""

from __future__ import annotations

import math

import pytest

from astra.contracts.estimation import FastStateEstimate, InnovationRecord
from astra.kernel.enums import ContextClass
from astra.kernel.errors import ConfigurationError, NonFiniteValueError
from astra.kernel.identifiers import TickId
from astra.kernel.matrix import SymmetricMatrix
from astra.kernel.time import Instant, Timeline
from astra.layers.l3_trust.mondrian import MondrianCalibration
from astra.layers.l3_trust.quantile import minimum_samples_for
from astra.layers.l3_trust.trust import ConformalTrustModule, ContextClassifier
from astra.ports.pipeline import TrustEstimator

AT = Instant(1_000, Timeline.MANUAL)
COVERAGE = 0.95
EPSILON = 0.05


class _FixedClassifier:
    """Returns whatever class the test asked for."""

    def __init__(self, context: ContextClass = ContextClass.HIGHWAY_CLEAR) -> None:
        self.context = context

    def classify(
        self, *, state: FastStateEstimate, innovation: InnovationRecord | None
    ) -> ContextClass:
        del state, innovation
        return self.context


def _state() -> FastStateEstimate:
    return FastStateEstimate(
        tick=TickId(1),
        valid_at=AT,
        mean=(0.0, 0.0, 20.0, 0.0, 0.5),
        covariance=SymmetricMatrix.from_diagonal([1.0, 1.0, 0.25, 0.1, 0.5]),
    )


def _innovation(distance: float) -> InnovationRecord:
    return InnovationRecord(
        tick=TickId(1),
        residual=(0.1, 0.2),
        mahalanobis_distance=distance,
        fault_flagged=False,
    )


def _module(
    classifier: ContextClassifier | None = None, *, window: int = 500
) -> ConformalTrustModule:
    return ConformalTrustModule(
        classifier=classifier or _FixedClassifier(),
        calibration=MondrianCalibration(window=window),
        coverage_level=COVERAGE,
    )


def _calibrated(context: ContextClass, count: int = 200) -> ConformalTrustModule:
    module = _module(_FixedClassifier(context))
    module._calibration.seed(context, [float(v) / 10.0 for v in range(count)])
    return module


# --------------------------------------------------------------------------- #
# Port conformance and the assessment record
# --------------------------------------------------------------------------- #


def test_the_module_satisfies_the_trust_estimator_port() -> None:
    assert isinstance(_module(), TrustEstimator)


def test_the_stub_classifier_satisfies_the_classifier_protocol() -> None:
    assert isinstance(_FixedClassifier(), ContextClassifier)


def test_the_assessment_records_the_class_the_classifier_returned() -> None:
    module = _module(_FixedClassifier(ContextClass.RAIN_NIGHT))

    assessment = module.assess(tick=TickId(5), state=_state(), innovation=None)

    assert assessment.tick == TickId(5)
    assert assessment.context_class is ContextClass.RAIN_NIGHT
    assert assessment.coverage_target == pytest.approx(COVERAGE)


def test_the_assessment_records_how_many_scores_backed_the_quantile() -> None:
    module = _calibrated(ContextClass.HIGHWAY_CLEAR, count=120)

    assessment = module.assess(tick=TickId(1), state=_state(), innovation=None)

    assert assessment.calibration_sample_count == 120


# --------------------------------------------------------------------------- #
# The uncalibrated case the contract cannot express
# --------------------------------------------------------------------------- #


def test_an_uncalibrated_class_reports_a_zero_quantile_not_an_infinite_one() -> None:
    # TrustAssessment validates the quantile with require_non_negative, which
    # rejects infinity. Zero is the fail-closed encoding; the sample count is
    # what lets a reader tell it from a real threshold of zero.
    module = _module()

    assessment = module.assess(tick=TickId(1), state=_state(), innovation=None)

    assert assessment.class_conditional_quantile == 0.0
    assert assessment.calibration_sample_count == 0


def test_is_calibrated_recovers_the_distinction_the_record_loses() -> None:
    module = _module()
    needed = minimum_samples_for(EPSILON)

    assert not module.is_calibrated(ContextClass.HIGHWAY_CLEAR)

    module._calibration.seed(ContextClass.HIGHWAY_CLEAR, [float(v) for v in range(needed)])

    assert module.is_calibrated(ContextClass.HIGHWAY_CLEAR)


def test_a_calibrated_class_reports_a_real_finite_quantile() -> None:
    module = _calibrated(ContextClass.HIGHWAY_CLEAR)

    assessment = module.assess(tick=TickId(1), state=_state(), innovation=None)

    assert assessment.class_conditional_quantile > 0.0
    assert math.isfinite(assessment.class_conditional_quantile)


def test_an_unclassified_context_is_never_calibrated_by_default() -> None:
    # The tunnel scenario. L9 supplies the nearest table in a real run; this is
    # the backstop for when it does not.
    module = _module(_FixedClassifier(ContextClass.UNCLASSIFIED))

    assessment = module.assess(tick=TickId(1), state=_state(), innovation=None)

    assert assessment.trust_index == 0.0
    assert not module.is_calibrated(ContextClass.UNCLASSIFIED)


# --------------------------------------------------------------------------- #
# The Trust Index itself
# --------------------------------------------------------------------------- #


def test_an_unremarkable_innovation_gives_high_trust() -> None:
    module = _calibrated(ContextClass.HIGHWAY_CLEAR)

    assessment = module.assess(tick=TickId(1), state=_state(), innovation=_innovation(0.5))

    assert assessment.trust_index > 0.7


def test_an_extreme_innovation_drives_trust_to_zero() -> None:
    module = _calibrated(ContextClass.HIGHWAY_CLEAR)

    assessment = module.assess(tick=TickId(1), state=_state(), innovation=_innovation(500.0))

    assert assessment.trust_index == pytest.approx(0.0)


def test_trust_falls_as_the_innovation_grows() -> None:
    module = _calibrated(ContextClass.HIGHWAY_CLEAR)

    calm = module.assess(tick=TickId(1), state=_state(), innovation=_innovation(1.0))
    tense = module.assess(tick=TickId(2), state=_state(), innovation=_innovation(15.0))

    assert tense.trust_index < calm.trust_index


def test_no_innovation_yet_is_the_least_surprising_score() -> None:
    # Before the first filter update nothing has contradicted the model.
    module = _calibrated(ContextClass.HIGHWAY_CLEAR)

    assessment = module.assess(tick=TickId(1), state=_state(), innovation=None)

    assert assessment.trust_index > 0.9


def test_a_non_finite_innovation_cannot_be_constructed_at_all() -> None:
    # The Trust Module carries no finiteness guard on the distance, because the
    # contract makes a non-finite one unrepresentable rather than unlikely. This
    # test pins that reliance: if InnovationRecord ever stopped validating, a
    # NaN would reach the empirical CDF and produce a Trust Index that is
    # neither high nor low but meaningless.
    with pytest.raises(NonFiniteValueError):
        _innovation(math.nan)


# --------------------------------------------------------------------------- #
# FB3 -- recalibration
# --------------------------------------------------------------------------- #


def test_recalibration_lands_in_the_class_that_was_last_assessed() -> None:
    module = _module(_FixedClassifier(ContextClass.URBAN_CLEAR))
    module.assess(tick=TickId(1), state=_state(), innovation=None)

    module.recalibrate(non_conformity_score=1.5, was_correct=True)

    assert module._calibration.sample_count(ContextClass.URBAN_CLEAR) == 1
    assert module._calibration.sample_count(ContextClass.HIGHWAY_CLEAR) == 0


def test_an_incorrect_outcome_is_still_calibrated_on() -> None:
    # Filtering the calibration set to outcomes that went well would bias the
    # quantile downward and produce a guarantee about a distribution the
    # vehicle does not drive in.
    module = _module()
    module.assess(tick=TickId(1), state=_state(), innovation=None)

    module.recalibrate(non_conformity_score=9.0, was_correct=False)

    assert module._calibration.sample_count(ContextClass.HIGHWAY_CLEAR) == 1


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf, -1.0])
def test_a_corrupt_score_is_dropped_rather_than_admitted(bad: float) -> None:
    # Admitting it would silently move every future threshold, and this is the
    # cold path: it must not take down a tick that has already been decided.
    module = _module()
    module.assess(tick=TickId(1), state=_state(), innovation=None)

    module.recalibrate(non_conformity_score=bad, was_correct=True)

    assert module._calibration.sample_count(ContextClass.HIGHWAY_CLEAR) == 0


def test_recalibration_moves_the_quantile_it_will_report() -> None:
    module = _calibrated(ContextClass.HIGHWAY_CLEAR, count=100)
    before = module.assess(
        tick=TickId(1), state=_state(), innovation=None
    ).class_conditional_quantile

    for _ in range(100):
        module.assess(tick=TickId(2), state=_state(), innovation=None)
        module.recalibrate(non_conformity_score=50.0, was_correct=True)

    after = module.assess(
        tick=TickId(3), state=_state(), innovation=None
    ).class_conditional_quantile

    assert after > before


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("coverage", [0.0, 1.0, -0.1, 1.5, math.nan, math.inf])
def test_a_coverage_level_outside_the_open_unit_interval_is_refused(
    coverage: float,
) -> None:
    with pytest.raises(ConfigurationError):
        ConformalTrustModule(
            classifier=_FixedClassifier(),
            calibration=MondrianCalibration(window=10),
            coverage_level=coverage,
        )


def test_the_significance_level_is_the_complement_of_the_coverage_level() -> None:
    assert _module().epsilon == pytest.approx(EPSILON)
