"""Unit tests for the L6 ICP statistical gate and its shift detector."""

from __future__ import annotations

import math
import random

import pytest

from astra.contracts.actuation import (
    ActuationChannel,
    ActuationSpace,
    CommandOrigin,
    ControlCommand,
    PredictedCommand,
    ProposedCommand,
)
from astra.contracts.assurance import GateVerdict
from astra.contracts.estimation import FastStateEstimate, InnovationRecord
from astra.kernel.enums import ContextClass, GateId, LayerId, Verdict
from astra.kernel.errors import ConfigurationError, SafetyPathError
from astra.kernel.identifiers import ComponentId, TickId
from astra.kernel.matrix import SymmetricMatrix
from astra.kernel.time import Instant, Timeline
from astra.layers.l3_trust.mondrian import MondrianCalibration
from astra.layers.l6_statistical_gate.gate import (
    REASON_CODES,
    REASON_NOMINAL,
    REASON_SCORE_ABOVE_QUANTILE,
    REASON_UNCALIBRATED,
    IcpStatisticalGate,
)
from astra.layers.l6_statistical_gate.mmd import (
    MmdShiftDetector,
    median_bandwidth,
    squared_mmd,
)
from astra.ports.pipeline import StatisticalGate

AT = Instant(1_000, Timeline.MANUAL)
SPACE = ActuationSpace((ActuationChannel(name="steer", lower=-1.0, upper=1.0, unit="rad"),))
EPSILON = 0.05
CONTEXT = ContextClass.HIGHWAY_CLEAR


class _FixedClassifier:
    def __init__(self, context: ContextClass = CONTEXT) -> None:
        self.context = context

    def classify(
        self, *, state: FastStateEstimate, innovation: InnovationRecord | None
    ) -> ContextClass:
        del state, innovation
        return self.context


def _state(lateral_variance: float = 0.25) -> FastStateEstimate:
    return FastStateEstimate(
        tick=TickId(1),
        valid_at=AT,
        mean=(0.0, 0.0, 20.0, 0.0, 0.5),
        covariance=SymmetricMatrix.from_diagonal([1.0, 1.0, 0.25, 0.1, lateral_variance]),
    )


def _proposal(value: float) -> ProposedCommand:
    return ProposedCommand(
        tick=TickId(1),
        proposed_at=AT,
        command=ControlCommand(space=SPACE, values=(value,)),
        origin=CommandOrigin.PROPOSED,
        source=ComponentId(LayerId.L4_CORE_A_CMDP),
    )


def _prediction(value: float) -> PredictedCommand:
    return PredictedCommand(
        tick=TickId(1),
        predicted_at=AT,
        command=ControlCommand(space=SPACE, values=(value,)),
        source=ComponentId(LayerId.L5_PINN_TWIN),
    )


def _gate(
    *,
    scores: list[float] | None = None,
    multiplier: float = 2.0,
    threshold: float = 0.05,
    window: int = 20,
    context: ContextClass = CONTEXT,
) -> IcpStatisticalGate:
    calibration = MondrianCalibration(window=1000)
    calibration.seed(context, scores if scores is not None else [v / 100.0 for v in range(200)])
    return IcpStatisticalGate(
        calibration=calibration,
        classifier=_FixedClassifier(context),
        detector=MmdShiftDetector(window=window, threshold=threshold),
        significance_epsilon=EPSILON,
        shift_epsilon_multiplier=multiplier,
    )


def _evaluate(
    gate: IcpStatisticalGate, *, proposed: float, predicted: float, variance: float = 0.25
) -> GateVerdict:
    return gate.evaluate(
        tick=TickId(1),
        proposal=_proposal(proposed),
        prediction=_prediction(predicted),
        state=_state(variance),
    )


# --------------------------------------------------------------------------- #
# Port conformance and the score
# --------------------------------------------------------------------------- #


def test_the_gate_satisfies_the_statistical_gate_port() -> None:
    assert isinstance(_gate(), StatisticalGate)


def test_a_proposal_matching_the_twin_passes() -> None:
    verdict = _evaluate(_gate(), proposed=0.3, predicted=0.3)

    assert verdict.verdict is Verdict.PASS
    assert verdict.gate is GateId.STATISTICAL
    assert verdict.reason_code == REASON_NOMINAL


def test_a_wildly_divergent_proposal_is_vetoed() -> None:
    verdict = _evaluate(_gate(), proposed=0.9, predicted=-0.9)

    assert verdict.verdict is Verdict.VETO
    assert verdict.reason_code == REASON_SCORE_ABOVE_QUANTILE


def test_every_reason_code_the_gate_emits_is_declared() -> None:
    emitted = {
        _evaluate(_gate(), proposed=0.3, predicted=0.3).reason_code,
        _evaluate(_gate(), proposed=0.9, predicted=-0.9).reason_code,
        _evaluate(_gate(scores=[]), proposed=0.3, predicted=0.3).reason_code,
    }

    assert emitted <= set(REASON_CODES)


def test_the_score_is_the_departure_normalised_by_the_filter_uncertainty() -> None:
    # departure 0.2, variance 0.25 -> sigma 0.5 -> score 0.4
    verdict = _evaluate(_gate(), proposed=0.5, predicted=0.3, variance=0.25)
    evidence = dict(verdict.evidence)

    assert evidence["departure"] == pytest.approx(0.2)
    assert evidence["sigma"] == pytest.approx(0.5)
    assert evidence["non_conformity_score"] == pytest.approx(0.4)


def test_the_same_departure_scores_higher_when_the_filter_is_confident() -> None:
    # The coupling between state uncertainty and the acceptance band.
    confident = _evaluate(_gate(), proposed=0.5, predicted=0.3, variance=0.01)
    unsure = _evaluate(_gate(), proposed=0.5, predicted=0.3, variance=4.0)

    assert (
        dict(confident.evidence)["non_conformity_score"]
        > dict(unsure.evidence)["non_conformity_score"]
    )


def test_a_near_zero_variance_vetoes_explicitly_rather_than_overflowing() -> None:
    verdict = _evaluate(_gate(), proposed=0.9, predicted=0.3, variance=0.0)
    evidence = dict(verdict.evidence)

    assert math.isfinite(evidence["non_conformity_score"])
    assert verdict.verdict is Verdict.VETO


# --------------------------------------------------------------------------- #
# The direction of the epsilon adjustment -- the trap in this module
# --------------------------------------------------------------------------- #


def test_a_multiplier_below_one_is_refused() -> None:
    # A smaller epsilon raises the quantile and widens the acceptance region, so
    # multiplying below 1 would loosen the gate at exactly the moment covariate
    # shift was detected -- and nothing would raise, because coverage would
    # still be achieved at the weaker level.
    with pytest.raises(SafetyPathError, match="more"):
        _gate(multiplier=0.5)


def test_declared_shift_raises_the_effective_epsilon() -> None:
    gate = _gate(multiplier=3.0, threshold=0.0, window=4)
    for value in (0.1, 0.1, 40.0, 41.0):
        gate.observe_innovation(value)

    assert gate.effective_epsilon() == pytest.approx(EPSILON * 3.0)


def test_a_raised_epsilon_makes_the_gate_stricter_not_looser() -> None:
    # The property the multiplier exists for, asserted on the verdict rather
    # than on the number.
    scores = [v / 100.0 for v in range(200)]
    quiet = _gate(scores=list(scores), multiplier=8.0, threshold=1e9, window=4)
    shifted = _gate(scores=list(scores), multiplier=8.0, threshold=0.0, window=4)
    for value in (0.1, 0.1, 40.0, 41.0):
        quiet.observe_innovation(value)
        shifted.observe_innovation(value)

    quiet_quantile = dict(_evaluate(quiet, proposed=0.3, predicted=0.3).evidence)[
        "conformal_quantile"
    ]
    shifted_quantile = dict(_evaluate(shifted, proposed=0.3, predicted=0.3).evidence)[
        "conformal_quantile"
    ]

    assert shifted_quantile < quiet_quantile


def test_the_effective_epsilon_is_capped_below_one() -> None:
    gate = _gate(multiplier=1000.0, threshold=0.0, window=4)
    for value in (0.1, 0.1, 40.0, 41.0):
        gate.observe_innovation(value)

    assert gate.effective_epsilon() < 1.0


def test_no_shift_leaves_epsilon_at_its_nominal_value() -> None:
    gate = _gate(multiplier=5.0, threshold=1e9)

    assert gate.effective_epsilon() == pytest.approx(EPSILON)


@pytest.mark.parametrize("epsilon", [0.0, 1.0, -0.1, math.nan])
def test_a_significance_level_outside_the_open_unit_interval_is_refused(
    epsilon: float,
) -> None:
    with pytest.raises(SafetyPathError):
        IcpStatisticalGate(
            calibration=MondrianCalibration(window=10),
            classifier=_FixedClassifier(),
            detector=MmdShiftDetector(window=10, threshold=0.1),
            significance_epsilon=epsilon,
            shift_epsilon_multiplier=2.0,
        )


# --------------------------------------------------------------------------- #
# The uncalibrated class
# --------------------------------------------------------------------------- #


def test_an_uncalibrated_class_vetoes_rather_than_passing() -> None:
    # A gate that cannot make a statistical claim must not report that the
    # proposal satisfied one.
    verdict = _evaluate(_gate(scores=[]), proposed=0.3, predicted=0.3)

    assert verdict.verdict is Verdict.VETO
    assert verdict.reason_code == REASON_UNCALIBRATED


def test_the_uncalibrated_quantile_is_logged_as_a_sentinel_not_an_infinity() -> None:
    # The evidence schema carries floats and an infinity would not round-trip.
    verdict = _evaluate(_gate(scores=[]), proposed=0.3, predicted=0.3)

    assert dict(verdict.evidence)["conformal_quantile"] == -1.0
    assert dict(verdict.evidence)["calibration_samples"] == 0.0


# --------------------------------------------------------------------------- #
# Fail-closed behaviour
# --------------------------------------------------------------------------- #


def test_a_dimension_mismatch_fails_closed() -> None:
    two_channel = ActuationSpace(
        (
            ActuationChannel(name="throttle", lower=0.0, upper=1.0, unit="1"),
            ActuationChannel(name="steer", lower=-1.0, upper=1.0, unit="rad"),
        )
    )
    proposal = ProposedCommand(
        tick=TickId(1),
        proposed_at=AT,
        command=ControlCommand(space=two_channel, values=(0.2, 0.1)),
        origin=CommandOrigin.PROPOSED,
        source=ComponentId(LayerId.L4_CORE_A_CMDP),
    )

    with pytest.raises(SafetyPathError, match="channels"):
        _gate().evaluate(
            tick=TickId(1), proposal=proposal, prediction=_prediction(0.1), state=_state()
        )


def test_the_gate_holds_no_verdict_state_between_ticks() -> None:
    gate = _gate(threshold=1e9)
    first = _evaluate(gate, proposed=0.9, predicted=-0.9)
    for _ in range(20):
        _evaluate(gate, proposed=0.3, predicted=0.3)
    last = _evaluate(gate, proposed=0.9, predicted=-0.9)

    assert first.evidence == last.evidence


# --------------------------------------------------------------------------- #
# The MMD detector
# --------------------------------------------------------------------------- #


def test_mmd_is_zero_for_identical_samples() -> None:
    sample = [1.0, 2.0, 3.0, 4.0]

    assert squared_mmd(sample, list(sample), 1.0) == pytest.approx(0.0, abs=1e-12)


def test_mmd_is_never_negative() -> None:
    # The biased estimator is used precisely so this holds; the unbiased one can
    # go slightly negative and a threshold comparison would then never fire.
    rng = random.Random(7)
    for _ in range(50):
        left = [rng.gauss(0.0, 1.0) for _ in range(8)]
        right = [rng.gauss(0.0, 1.0) for _ in range(8)]
        assert squared_mmd(left, right, median_bandwidth(left + right)) >= 0.0


def test_mmd_grows_as_the_distributions_separate() -> None:
    base = [0.0, 0.1, 0.2, 0.3]
    near = [0.4, 0.5, 0.6, 0.7]
    far = [40.0, 41.0, 42.0, 43.0]

    assert squared_mmd(base, far, 1.0) > squared_mmd(base, near, 1.0)


def test_mmd_detects_a_change_in_spread_not_only_in_mean() -> None:
    # An innovation distribution that keeps its average and doubles its spread
    # is what a filter starting to diverge produces, and a mean test misses it.
    tight = [-0.1, 0.1, -0.1, 0.1, -0.1, 0.1]
    wide = [-9.0, 9.0, -9.0, 9.0, -9.0, 9.0]

    assert squared_mmd(tight, wide, median_bandwidth(tight + wide)) > 0.0


def test_the_detector_stays_quiet_until_its_window_fills() -> None:
    detector = MmdShiftDetector(window=8, threshold=0.0)
    for value in (0.1, 0.1, 50.0):
        detector.observe(value)

    assert not detector.has_shifted()
    assert detector.discrepancy() == 0.0


def test_the_detector_fires_on_a_step_change() -> None:
    detector = MmdShiftDetector(window=8, threshold=0.01)
    for _ in range(4):
        detector.observe(0.1)
    for _ in range(4):
        detector.observe(80.0)

    assert detector.has_shifted()


def test_a_non_finite_innovation_is_dropped_rather_than_poisoning_the_window() -> None:
    detector = MmdShiftDetector(window=8, threshold=0.01)

    detector.observe(math.nan)
    detector.observe(math.inf)

    assert detector.sample_count == 0


def test_the_median_bandwidth_never_returns_zero() -> None:
    assert median_bandwidth([5.0, 5.0, 5.0]) == 1.0
    assert median_bandwidth([]) == 1.0


@pytest.mark.parametrize("window", [0, 1, 3])
def test_a_window_too_small_to_split_is_refused(window: int) -> None:
    with pytest.raises(ConfigurationError, match="at least 4"):
        MmdShiftDetector(window=window, threshold=0.1)


def test_a_negative_threshold_is_refused() -> None:
    # The biased estimator is never negative, so this would fire every tick.
    with pytest.raises(ConfigurationError, match="every tick"):
        MmdShiftDetector(window=10, threshold=-0.1)
