"""Unit tests for the L2 process models and the dual-rate UKF."""

from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

import numpy as np
import pytest

from astra.config.schema import EstimationSettings
from astra.contracts.estimation import FastStateEstimate, InnovationRecord, SlowStateEstimate
from astra.contracts.sensing import FusedSensorFrame
from astra.kernel.constants import (
    FAST_STATE_DIMENSION,
    FAST_STATE_FIELDS,
    SLOW_STATE_DIMENSION,
    SLOW_STATE_FIELDS,
)
from astra.kernel.errors import (
    AstraError,
    ContractViolationError,
    DimensionMismatchError,
    SafetyDisposition,
    SafetyPathError,
)
from astra.kernel.identifiers import TickId
from astra.kernel.matrix import SymmetricMatrix
from astra.kernel.time import Instant, Timeline
from astra.layers.l2_estimation.filter import _INNOVATION_HISTORY_LIMIT, DualRateUKF
from astra.layers.l2_estimation.measurement import (
    Measurement,
    MeasurementExtractor,
    fast_measurement,
    slow_measurement,
)
from astra.layers.l2_estimation.models import fast_transition, slow_transition
from astra.ports.pipeline import StateEstimator

if TYPE_CHECKING:
    from numpy.typing import NDArray

# --------------------------------------------------------------------------- #
# The operating point, stated here rather than loaded
# --------------------------------------------------------------------------- #
# Built in the test rather than read from `config/`, so the test declares the
# operating point it is asserting against. A test that loaded the repository
# configuration would change meaning whenever a safety engineer retuned it.

FAST_RATE_HZ = 20.0
SLOW_RATE_HZ = 1.0
INNOVATION_GATE_GAMMA = 3.0
YAW_RATE_MINIMUM_SPEED = 0.1
TICK_PERIOD = 1.0 / FAST_RATE_HZ

SETTINGS = EstimationSettings(
    fast_rate_hz=FAST_RATE_HZ,
    slow_rate_hz=SLOW_RATE_HZ,
    innovation_gate_gamma=INNOVATION_GATE_GAMMA,
    fast_process_noise=(0.02, 0.02, 0.05, 0.005, 0.5),
    slow_process_noise=(1e-4, 1e-4, 1e-4),
    yaw_rate_minimum_speed=YAW_RATE_MINIMUM_SPEED,
)

INITIAL_FAST_STATE = (0.0, 0.0, 12.0, 0.0, 0.0)
INITIAL_FAST_COVARIANCE = SymmetricMatrix.from_diagonal([1.0, 1.0, 1.0, 0.1, 1.0])
INITIAL_SLOW_STATE = (0.8, 0.1, 1.0)
INITIAL_SLOW_COVARIANCE = SymmetricMatrix.from_diagonal([0.01, 0.01, 0.01])

# Indices resolved from the canonical layout, never written as literals, for the
# same reason the source does it: a reordering must break loudly, not silently.
POSITION_X = FAST_STATE_FIELDS.index("position_x")
POSITION_Y = FAST_STATE_FIELDS.index("position_y")
SPEED = FAST_STATE_FIELDS.index("speed")
HEADING = FAST_STATE_FIELDS.index("heading")
LATERAL_ACCELERATION = FAST_STATE_FIELDS.index("lateral_acceleration")

CRUISE_SPEED = 12.0
TURN_LATERAL_ACCELERATION = 2.0
CONVERGENCE_TICKS = 200

POSITION_SIGMA = 0.5
SPEED_SIGMA = 0.2
LATERAL_ACCELERATION_SIGMA = 0.1

# One fixed seed for every simulated run. A local Random instance is used
# throughout: touching the global `random` module state, or NumPy's, would make
# one test's outcome depend on what ran before it.
SEED = 20_260_729


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _fast_state(
    position_x: float = 0.0,
    position_y: float = 0.0,
    speed: float = 0.0,
    heading: float = 0.0,
    lateral_acceleration: float = 0.0,
) -> NDArray[np.float64]:
    return np.array(
        [position_x, position_y, speed, heading, lateral_acceleration], dtype=np.float64
    )


def _frame(index: int) -> FusedSensorFrame[object]:
    return FusedSensorFrame(
        tick=TickId(index),
        fused_at=Instant(index * 50_000_000, Timeline.MANUAL),
        samples=(),
    )


class _GroundTruthVehicle:
    """A deterministic vehicle integrating the same kinematics the filter models.

    Deliberately not the filter's own transition function: it is written out
    here so that a change to the process model shows up as a tracking error
    rather than being cancelled by the test using the same code twice.
    """

    def __init__(self, *, speed: float, lateral_acceleration: float) -> None:
        self.position_x = 0.0
        self.position_y = 0.0
        self.speed = speed
        self.heading = 0.0
        self.lateral_acceleration = lateral_acceleration

    def advance(self) -> None:
        yaw_rate = self.lateral_acceleration / self.speed
        self.position_x += self.speed * math.cos(self.heading) * TICK_PERIOD
        self.position_y += self.speed * math.sin(self.heading) * TICK_PERIOD
        self.heading += yaw_rate * TICK_PERIOD


class _NoisyExtractor:
    """Observes position, speed and lateral acceleration with Gaussian noise.

    Heading is deliberately unobserved: it reaches the filter only through the
    ``psi' = psi + (a_lat / v) dt`` coupling in the process model, which is the
    property that lets a lateral-acceleration reading correct a heading
    estimate at all.
    """

    def __init__(self, vehicle: _GroundTruthVehicle, rng: random.Random) -> None:
        self.vehicle = vehicle
        self.rng = rng
        self.silent = False
        self.position_x_offset = 0.0

    def extract_fast(self, frame: FusedSensorFrame[object]) -> Measurement | None:
        del frame
        if self.silent:
            return None
        vehicle = self.vehicle
        return fast_measurement(
            [
                (
                    "position_x",
                    vehicle.position_x
                    + self.rng.gauss(0.0, POSITION_SIGMA)
                    + self.position_x_offset,
                    POSITION_SIGMA**2,
                ),
                (
                    "position_y",
                    vehicle.position_y + self.rng.gauss(0.0, POSITION_SIGMA),
                    POSITION_SIGMA**2,
                ),
                ("speed", vehicle.speed + self.rng.gauss(0.0, SPEED_SIGMA), SPEED_SIGMA**2),
                (
                    "lateral_acceleration",
                    vehicle.lateral_acceleration + self.rng.gauss(0.0, LATERAL_ACCELERATION_SIGMA),
                    LATERAL_ACCELERATION_SIGMA**2,
                ),
            ]
        )

    def extract_slow(self, frame: FusedSensorFrame[object]) -> Measurement | None:
        del frame
        if self.silent:
            return None
        return slow_measurement(
            [
                ("road_friction_coefficient", 0.85, 0.01),
                ("sensor_health_score", 0.98, 0.01),
            ]
        )


class _SilentExtractor:
    """Derives nothing from any frame: every tick predicts without correcting."""

    def extract_fast(self, frame: FusedSensorFrame[object]) -> Measurement | None:
        del frame
        return None

    def extract_slow(self, frame: FusedSensorFrame[object]) -> Measurement | None:
        del frame
        return None


def _build(
    extractor: MeasurementExtractor[object],
    *,
    initial_fast_state: tuple[float, ...] = INITIAL_FAST_STATE,
    initial_fast_covariance: SymmetricMatrix = INITIAL_FAST_COVARIANCE,
    initial_slow_state: tuple[float, ...] = INITIAL_SLOW_STATE,
    initial_slow_covariance: SymmetricMatrix = INITIAL_SLOW_COVARIANCE,
) -> DualRateUKF[object]:
    return DualRateUKF(
        settings=SETTINGS,
        extractor=extractor,
        initial_fast_state=initial_fast_state,
        initial_fast_covariance=initial_fast_covariance,
        initial_slow_state=initial_slow_state,
        initial_slow_covariance=initial_slow_covariance,
    )


def _simulate(
    *, lateral_acceleration: float, ticks: int
) -> tuple[DualRateUKF[object], _GroundTruthVehicle, list[FastStateEstimate]]:
    vehicle = _GroundTruthVehicle(speed=CRUISE_SPEED, lateral_acceleration=lateral_acceleration)
    estimator = _build(_NoisyExtractor(vehicle, random.Random(SEED)))
    estimates = []
    for index in range(ticks):
        estimates.append(estimator.update_fast(_frame(index)))
        vehicle.advance()
    return estimator, vehicle, estimates


def _trace(covariance: SymmetricMatrix) -> float:
    return sum(covariance.diagonal)


def _position_error(estimate: FastStateEstimate, vehicle: _GroundTruthVehicle) -> float:
    return math.hypot(
        estimate.position_x - vehicle.position_x, estimate.position_y - vehicle.position_y
    )


# --------------------------------------------------------------------------- #
# The fast process model: the yaw guard
# --------------------------------------------------------------------------- #
# `psi' = psi + (a_lat / v) dt` is unbounded as v approaches zero. A stopped
# vehicle registering any lateral noise would otherwise be propagated an
# enormous heading change on that tick.


def test_at_zero_speed_the_transition_moves_neither_position_nor_heading() -> None:
    state = _fast_state(
        position_x=3.0, position_y=-4.0, speed=0.0, heading=0.7, lateral_acceleration=5.0
    )

    result = fast_transition(state, TICK_PERIOD, yaw_rate_minimum_speed=YAW_RATE_MINIMUM_SPEED)

    assert result[POSITION_X] == pytest.approx(3.0)
    assert result[POSITION_Y] == pytest.approx(-4.0)
    assert result[HEADING] == pytest.approx(0.7)


def test_below_the_yaw_guard_speed_a_large_lateral_acceleration_leaves_heading_untouched() -> None:
    state = _fast_state(speed=YAW_RATE_MINIMUM_SPEED / 2.0, heading=0.3, lateral_acceleration=50.0)

    result = fast_transition(state, TICK_PERIOD, yaw_rate_minimum_speed=YAW_RATE_MINIMUM_SPEED)

    assert result[HEADING] == pytest.approx(0.3)


def test_the_yaw_guard_applies_to_reverse_motion_as_well() -> None:
    state = _fast_state(speed=-YAW_RATE_MINIMUM_SPEED / 2.0, heading=0.3, lateral_acceleration=50.0)

    result = fast_transition(state, TICK_PERIOD, yaw_rate_minimum_speed=YAW_RATE_MINIMUM_SPEED)

    assert result[HEADING] == pytest.approx(0.3)


@pytest.mark.parametrize(
    ("speed", "lateral_acceleration"),
    [(10.0, 2.0), (12.0, -3.0), (25.0, 0.5), (YAW_RATE_MINIMUM_SPEED, 0.01)],
)
def test_above_the_yaw_guard_speed_heading_advances_by_the_yaw_rate(
    speed: float, lateral_acceleration: float
) -> None:
    state = _fast_state(speed=speed, heading=0.2, lateral_acceleration=lateral_acceleration)

    result = fast_transition(state, TICK_PERIOD, yaw_rate_minimum_speed=YAW_RATE_MINIMUM_SPEED)

    assert result[HEADING] == pytest.approx(0.2 + (lateral_acceleration / speed) * TICK_PERIOD)


def test_a_zero_lateral_acceleration_holds_the_heading_at_any_speed() -> None:
    state = _fast_state(speed=CRUISE_SPEED, heading=1.1, lateral_acceleration=0.0)

    result = fast_transition(state, TICK_PERIOD, yaw_rate_minimum_speed=YAW_RATE_MINIMUM_SPEED)

    assert result[HEADING] == pytest.approx(1.1)


# --------------------------------------------------------------------------- #
# The fast process model: straight-line motion
# --------------------------------------------------------------------------- #


def test_straight_line_motion_along_the_x_axis_advances_position_x_by_v_dt() -> None:
    state = _fast_state(speed=CRUISE_SPEED, heading=0.0, lateral_acceleration=0.0)

    result = fast_transition(state, TICK_PERIOD, yaw_rate_minimum_speed=YAW_RATE_MINIMUM_SPEED)

    assert result[POSITION_X] == pytest.approx(CRUISE_SPEED * TICK_PERIOD)
    assert result[POSITION_Y] == pytest.approx(0.0, abs=1e-12)


def test_straight_line_motion_along_the_y_axis_advances_position_y_by_v_dt() -> None:
    state = _fast_state(speed=CRUISE_SPEED, heading=math.pi / 2.0, lateral_acceleration=0.0)

    result = fast_transition(state, TICK_PERIOD, yaw_rate_minimum_speed=YAW_RATE_MINIMUM_SPEED)

    assert result[POSITION_X] == pytest.approx(0.0, abs=1e-12)
    assert result[POSITION_Y] == pytest.approx(CRUISE_SPEED * TICK_PERIOD)


def test_straight_line_motion_accumulates_exactly_v_dt_per_step() -> None:
    state = _fast_state(speed=CRUISE_SPEED, heading=0.0, lateral_acceleration=0.0)

    for step in range(1, 11):
        state = fast_transition(state, TICK_PERIOD, yaw_rate_minimum_speed=YAW_RATE_MINIMUM_SPEED)
        assert state[POSITION_X] == pytest.approx(step * CRUISE_SPEED * TICK_PERIOD)


# --------------------------------------------------------------------------- #
# The fast process model: what the model deliberately does not predict
# --------------------------------------------------------------------------- #
# Longitudinal acceleration and the rate of change of lateral acceleration are
# not in the state and are not measured. The model holds them constant and lets
# Q carry the discrepancy, rather than inventing a jerk term.


@pytest.mark.parametrize("lateral_acceleration", [0.0, 2.0, -3.5])
def test_the_transition_holds_speed_and_lateral_acceleration_constant(
    lateral_acceleration: float,
) -> None:
    state = _fast_state(speed=CRUISE_SPEED, heading=0.4, lateral_acceleration=lateral_acceleration)

    result = fast_transition(state, TICK_PERIOD, yaw_rate_minimum_speed=YAW_RATE_MINIMUM_SPEED)

    assert result[SPEED] == pytest.approx(CRUISE_SPEED)
    assert result[LATERAL_ACCELERATION] == pytest.approx(lateral_acceleration)


def test_the_transition_returns_a_new_array_and_leaves_its_input_alone() -> None:
    state = _fast_state(speed=CRUISE_SPEED, heading=0.0, lateral_acceleration=1.0)
    original = state.copy()

    result = fast_transition(state, TICK_PERIOD, yaw_rate_minimum_speed=YAW_RATE_MINIMUM_SPEED)

    assert result is not state
    assert np.array_equal(state, original)


def test_the_transition_returns_a_vector_of_the_fast_state_dimension() -> None:
    result = fast_transition(
        _fast_state(speed=CRUISE_SPEED), TICK_PERIOD, yaw_rate_minimum_speed=YAW_RATE_MINIMUM_SPEED
    )

    assert result.shape == (FAST_STATE_DIMENSION,)


# --------------------------------------------------------------------------- #
# The slow process model: a random walk
# --------------------------------------------------------------------------- #
# x' = x, with all of the movement in Q. That says exactly what is known about
# degradation: it drifts, slowly, in no predicted direction.


def test_the_slow_transition_returns_an_equal_but_distinct_array() -> None:
    state = np.array([0.8, 0.15, 0.95], dtype=np.float64)

    result = slow_transition(state, 1.0)

    assert result is not state
    assert np.array_equal(result, state)


def test_mutating_the_slow_transition_result_does_not_disturb_its_input() -> None:
    state = np.array([0.8, 0.15, 0.95], dtype=np.float64)

    result = slow_transition(state, 1.0)
    result[0] = 0.0

    assert state[0] == pytest.approx(0.8)


@pytest.mark.parametrize("dt", [0.0, 0.05, 1.0, 1000.0])
def test_the_slow_transition_ignores_dt(dt: float) -> None:
    state = np.array([0.8, 0.15, 0.95], dtype=np.float64)

    assert np.array_equal(slow_transition(state, dt), state)


def test_the_slow_transition_preserves_the_slow_state_dimension() -> None:
    state = np.array([0.8, 0.15, 0.95], dtype=np.float64)

    assert slow_transition(state, 1.0).shape == (SLOW_STATE_DIMENSION,)


# --------------------------------------------------------------------------- #
# Construction
# --------------------------------------------------------------------------- #
# A singular initial covariance asserts that some direction of the state is
# known exactly, which is false for a filter that has seen no measurement.


def test_a_singular_initial_fast_covariance_raises_contract_violation() -> None:
    with pytest.raises(ContractViolationError):
        _build(
            _SilentExtractor(),
            initial_fast_covariance=SymmetricMatrix.from_diagonal([1.0, 0.0, 1.0, 0.1, 1.0]),
        )


def test_the_singular_covariance_error_reports_the_diagonal() -> None:
    with pytest.raises(ContractViolationError) as raised:
        _build(
            _SilentExtractor(),
            initial_fast_covariance=SymmetricMatrix.from_diagonal([1.0, 0.0, 1.0, 0.1, 1.0]),
        )

    assert raised.value.context["diagonal"] == [1.0, 0.0, 1.0, 0.1, 1.0]


def test_a_negative_variance_in_the_initial_fast_covariance_raises_contract_violation() -> None:
    with pytest.raises(ContractViolationError):
        _build(
            _SilentExtractor(),
            initial_fast_covariance=SymmetricMatrix.from_diagonal([1.0, -1.0, 1.0, 0.1, 1.0]),
        )


def test_a_singular_initial_slow_covariance_raises_contract_violation() -> None:
    with pytest.raises(ContractViolationError):
        _build(
            _SilentExtractor(),
            initial_slow_covariance=SymmetricMatrix.from_diagonal([0.01, 0.0, 0.01]),
        )


@pytest.mark.parametrize("state", [(0.0, 0.0, 12.0), (0.0, 0.0, 12.0, 0.0, 0.0, 0.0), ()])
def test_a_wrong_dimension_initial_fast_state_raises_dimension_mismatch(
    state: tuple[float, ...],
) -> None:
    with pytest.raises(DimensionMismatchError):
        _build(_SilentExtractor(), initial_fast_state=state)


def test_a_wrong_dimension_initial_slow_state_raises_dimension_mismatch() -> None:
    with pytest.raises(DimensionMismatchError):
        _build(_SilentExtractor(), initial_slow_state=(0.8, 0.1))


def test_a_freshly_constructed_filter_has_run_no_cycles() -> None:
    estimator = _build(_SilentExtractor())

    assert estimator.fast_updates == 0
    assert estimator.slow_updates == 0
    assert estimator.innovation_history == ()
    assert estimator.latest_innovation() is None


def test_a_valid_construction_predicts_forward_from_the_initial_state() -> None:
    estimator = _build(_SilentExtractor())

    estimate = estimator.update_fast(_frame(0))

    assert len(estimate.mean) == FAST_STATE_DIMENSION
    assert estimate.speed == pytest.approx(CRUISE_SPEED, abs=1e-6)
    assert estimate.covariance.is_positive_definite()
    # The advance falls slightly short of v*dt because the unscented transform
    # propagates the heading uncertainty through cos(psi) instead of
    # linearising it away, and E[cos psi] < cos(E[psi]). An EKF would report
    # the full v*dt here, which is the approximation error this filter avoids.
    assert 0.0 < estimate.position_x < CRUISE_SPEED * TICK_PERIOD


# --------------------------------------------------------------------------- #
# Tracking a synthetic vehicle
# --------------------------------------------------------------------------- #
# The bounds below are deliberately loose. The claim under test is that the
# filter tracks the vehicle, not that it reproduces it exactly: a tight bound
# would be asserting a particular noise realisation rather than convergence.


def test_the_filter_converges_on_a_straight_run() -> None:
    _, vehicle, estimates = _simulate(lateral_acceleration=0.0, ticks=CONVERGENCE_TICKS)

    assert _position_error(estimates[-1], vehicle) < 2.0
    assert abs(estimates[-1].speed - vehicle.speed) < 0.5


def test_convergence_improves_on_the_uncorrected_initial_guess() -> None:
    _, _, estimates = _simulate(lateral_acceleration=0.0, ticks=CONVERGENCE_TICKS)

    settled = _trace(estimates[-1].covariance)

    assert settled < _trace(INITIAL_FAST_COVARIANCE)


def test_the_filter_tracks_through_a_steady_turn() -> None:
    _, vehicle, estimates = _simulate(
        lateral_acceleration=TURN_LATERAL_ACCELERATION, ticks=CONVERGENCE_TICKS
    )

    assert _position_error(estimates[-1], vehicle) < 5.0
    assert abs(estimates[-1].heading - vehicle.heading) < 0.2


def test_the_turn_actually_curves_so_the_tracking_claim_is_not_vacuous() -> None:
    _, vehicle, _ = _simulate(
        lateral_acceleration=TURN_LATERAL_ACCELERATION, ticks=CONVERGENCE_TICKS
    )

    assert vehicle.heading > 0.5


@pytest.mark.parametrize("lateral_acceleration", [0.0, TURN_LATERAL_ACCELERATION])
def test_the_fast_covariance_is_positive_definite_on_every_tick(
    lateral_acceleration: float,
) -> None:
    _, _, estimates = _simulate(lateral_acceleration=lateral_acceleration, ticks=CONVERGENCE_TICKS)

    assert all(estimate.covariance.is_positive_definite() for estimate in estimates)


@pytest.mark.parametrize("lateral_acceleration", [0.0, TURN_LATERAL_ACCELERATION])
def test_the_lateral_acceleration_variance_stays_strictly_positive(
    lateral_acceleration: float,
) -> None:
    # This variance is the ICP gate's sigma(x)^2. A zero would divide the
    # non-conformity score by nothing and unbound the acceptance band.
    _, _, estimates = _simulate(lateral_acceleration=lateral_acceleration, ticks=CONVERGENCE_TICKS)

    assert all(estimate.variance_of("lateral_acceleration") > 0.0 for estimate in estimates)


def test_every_fast_estimate_carries_the_tick_and_instant_of_its_frame() -> None:
    estimator, _, estimates = _simulate(lateral_acceleration=0.0, ticks=5)

    assert [estimate.tick for estimate in estimates] == [TickId(index) for index in range(5)]
    assert estimates[3].valid_at == _frame(3).fused_at
    assert estimator.fast_updates == 5


# --------------------------------------------------------------------------- #
# A tick with no measurement predicts without correcting
# --------------------------------------------------------------------------- #
# The mechanism behind the paper's locally adaptive gate: uncertainty grows when
# nothing corrects it, and the widened P_f propagates into sigma(x), so the ICP
# gate becomes more permissive precisely when the state is less certain.


def test_a_tick_with_no_measurement_still_produces_an_estimate() -> None:
    estimator = _build(_SilentExtractor())

    estimate = estimator.update_fast(_frame(0))

    assert isinstance(estimate, FastStateEstimate)
    assert estimator.fast_updates == 1


def test_a_tick_with_no_measurement_widens_the_covariance() -> None:
    vehicle = _GroundTruthVehicle(speed=CRUISE_SPEED, lateral_acceleration=0.0)
    extractor = _NoisyExtractor(vehicle, random.Random(SEED))
    estimator = _build(extractor)
    corrected = estimator.update_fast(_frame(0))
    vehicle.advance()
    for index in range(1, 20):
        corrected = estimator.update_fast(_frame(index))
        vehicle.advance()

    extractor.silent = True
    uncorrected = estimator.update_fast(_frame(20))

    assert _trace(uncorrected.covariance) > _trace(corrected.covariance)
    assert estimator.fast_updates == 21


def test_uncertainty_grows_monotonically_while_no_measurement_arrives() -> None:
    estimator = _build(_SilentExtractor())

    traces = [_trace(estimator.update_fast(_frame(index)).covariance) for index in range(10)]

    assert traces == sorted(traces)
    assert traces[-1] > traces[0]


def test_a_predict_only_tick_records_no_innovation() -> None:
    estimator = _build(_SilentExtractor())

    estimator.update_fast(_frame(0))

    assert estimator.latest_innovation() is None
    assert estimator.innovation_history == ()


# --------------------------------------------------------------------------- #
# The innovation monitor
# --------------------------------------------------------------------------- #
# All three Core-B gates read this filter, so a silent divergence would degrade
# them together. The innovation sequence is the one signal that detects that
# from inside L2, by comparing what the sensors said against what the model
# expected.


def test_latest_innovation_is_none_before_the_first_corrected_update() -> None:
    assert _build(_SilentExtractor()).latest_innovation() is None


def test_the_first_corrected_update_produces_an_innovation_record() -> None:
    estimator, _, _ = _simulate(lateral_acceleration=0.0, ticks=1)

    record = estimator.latest_innovation()

    assert isinstance(record, InnovationRecord)
    assert record.tick == TickId(0)


def test_every_innovation_distance_is_finite_and_non_negative() -> None:
    estimator, _, _ = _simulate(lateral_acceleration=0.0, ticks=CONVERGENCE_TICKS)

    assert all(math.isfinite(distance) for distance in estimator.innovation_history)
    assert all(distance >= 0.0 for distance in estimator.innovation_history)


def test_the_innovation_residual_has_one_element_per_observed_dimension() -> None:
    estimator, _, _ = _simulate(lateral_acceleration=0.0, ticks=10)

    record = estimator.latest_innovation()

    assert record is not None
    assert len(record.residual) == 4


def test_fault_flagged_agrees_with_the_configured_gate_on_every_tick() -> None:
    vehicle = _GroundTruthVehicle(speed=CRUISE_SPEED, lateral_acceleration=0.0)
    estimator = _build(_NoisyExtractor(vehicle, random.Random(SEED)))
    flagged = 0
    unflagged = 0

    for index in range(CONVERGENCE_TICKS):
        estimator.update_fast(_frame(index))
        vehicle.advance()
        record = estimator.latest_innovation()
        assert record is not None
        assert record.fault_flagged is (record.mahalanobis_distance > INNOVATION_GATE_GAMMA)
        if record.fault_flagged:
            flagged += 1
        else:
            unflagged += 1

    # Both branches were exercised, so the agreement above is not vacuous, and a
    # well-tracked run leaves the great majority of ticks unflagged.
    assert unflagged > 0
    assert flagged < CONVERGENCE_TICKS // 4


def test_a_measurement_five_hundred_metres_wrong_flags_a_sensor_fault() -> None:
    vehicle = _GroundTruthVehicle(speed=CRUISE_SPEED, lateral_acceleration=0.0)
    extractor = _NoisyExtractor(vehicle, random.Random(SEED))
    estimator = _build(extractor)
    for index in range(50):
        estimator.update_fast(_frame(index))
        vehicle.advance()

    settled = estimator.latest_innovation()
    assert settled is not None
    assert settled.fault_flagged is False

    extractor.position_x_offset = 500.0
    estimator.update_fast(_frame(50))

    faulted = estimator.latest_innovation()
    assert faulted is not None
    assert faulted.fault_flagged is True
    assert faulted.mahalanobis_distance > INNOVATION_GATE_GAMMA


def test_the_innovation_history_grows_by_one_per_corrected_update() -> None:
    vehicle = _GroundTruthVehicle(speed=CRUISE_SPEED, lateral_acceleration=0.0)
    estimator = _build(_NoisyExtractor(vehicle, random.Random(SEED)))

    for index in range(25):
        estimator.update_fast(_frame(index))
        vehicle.advance()
        assert len(estimator.innovation_history) == index + 1


def test_the_innovation_history_ends_with_what_latest_innovation_reported() -> None:
    estimator, _, _ = _simulate(lateral_acceleration=TURN_LATERAL_ACCELERATION, ticks=30)

    record = estimator.latest_innovation()

    assert record is not None
    assert estimator.innovation_history[-1] == record.mahalanobis_distance


def test_the_innovation_history_is_an_immutable_snapshot() -> None:
    estimator, _, _ = _simulate(lateral_acceleration=0.0, ticks=5)

    snapshot = estimator.innovation_history
    estimator.update_fast(_frame(5))

    assert len(snapshot) == 5
    assert len(estimator.innovation_history) == 6


def test_the_innovation_history_is_bounded_by_the_rolling_window() -> None:
    ticks = _INNOVATION_HISTORY_LIMIT + 64
    estimator, _, _ = _simulate(lateral_acceleration=0.0, ticks=ticks)

    assert len(estimator.innovation_history) == _INNOVATION_HISTORY_LIMIT
    record = estimator.latest_innovation()
    assert record is not None
    assert estimator.innovation_history[-1] == record.mahalanobis_distance


# --------------------------------------------------------------------------- #
# The slow filter
# --------------------------------------------------------------------------- #


def test_update_slow_produces_a_three_dimensional_estimate() -> None:
    vehicle = _GroundTruthVehicle(speed=CRUISE_SPEED, lateral_acceleration=0.0)
    estimator = _build(_NoisyExtractor(vehicle, random.Random(SEED)))

    estimate = estimator.update_slow(_frame(0))

    assert isinstance(estimate, SlowStateEstimate)
    assert len(estimate.mean) == SLOW_STATE_DIMENSION
    assert estimate.covariance.dimension == SLOW_STATE_DIMENSION


def test_the_slow_covariance_stays_positive_definite() -> None:
    vehicle = _GroundTruthVehicle(speed=CRUISE_SPEED, lateral_acceleration=0.0)
    estimator = _build(_NoisyExtractor(vehicle, random.Random(SEED)))

    estimates = [estimator.update_slow(_frame(index)) for index in range(10)]

    assert all(estimate.covariance.is_positive_definite() for estimate in estimates)


def test_slow_updates_increments_once_per_slow_cycle() -> None:
    vehicle = _GroundTruthVehicle(speed=CRUISE_SPEED, lateral_acceleration=0.0)
    estimator = _build(_NoisyExtractor(vehicle, random.Random(SEED)))

    for expected in range(1, 6):
        estimator.update_slow(_frame(expected))
        assert estimator.slow_updates == expected

    assert estimator.fast_updates == 0


def test_the_slow_filter_corrects_towards_its_measurement() -> None:
    vehicle = _GroundTruthVehicle(speed=CRUISE_SPEED, lateral_acceleration=0.0)
    estimator = _build(_NoisyExtractor(vehicle, random.Random(SEED)))

    estimate = estimator.update_slow(_frame(0))
    for index in range(1, 20):
        estimate = estimator.update_slow(_frame(index))

    assert estimate.road_friction_coefficient == pytest.approx(0.85, abs=0.05)


def test_a_slow_cycle_with_no_measurement_widens_the_slow_covariance() -> None:
    estimator = _build(_SilentExtractor())

    first = estimator.update_slow(_frame(0))
    second = estimator.update_slow(_frame(1))

    assert _trace(second.covariance) > _trace(first.covariance)


def test_the_slow_filter_does_not_record_innovations() -> None:
    vehicle = _GroundTruthVehicle(speed=CRUISE_SPEED, lateral_acceleration=0.0)
    estimator = _build(_NoisyExtractor(vehicle, random.Random(SEED)))

    estimator.update_slow(_frame(0))

    assert estimator.latest_innovation() is None
    assert estimator.innovation_history == ()


# --------------------------------------------------------------------------- #
# Protocol conformance
# --------------------------------------------------------------------------- #


def test_the_filter_satisfies_the_state_estimator_protocol() -> None:
    assert isinstance(_build(_SilentExtractor()), StateEstimator)


def test_the_filter_is_usable_through_the_state_estimator_port() -> None:
    estimator: StateEstimator[object] = _build(_SilentExtractor())

    assert isinstance(estimator.update_fast(_frame(0)), FastStateEstimate)
    assert isinstance(estimator.update_slow(_frame(0)), SlowStateEstimate)
    assert estimator.latest_innovation() is None


# --------------------------------------------------------------------------- #
# Fail-closed numerics
# --------------------------------------------------------------------------- #
# A state estimate that could not be computed must never be silently replaced by
# the previous one: the gates above would then validate a command against a
# stale world. Every numerical failure becomes a SafetyPathError, whose
# disposition is FAIL_CLOSED, so the tick is VETOed rather than passed.


def _raise_linear_algebra_error(*_args: object, **_kwargs: object) -> None:
    message = "simulated loss of positive definiteness in the sigma-point Cholesky"
    raise np.linalg.LinAlgError(message)


def _raise_value_error(*_args: object, **_kwargs: object) -> None:
    message = "simulated non-conforming measurement shape"
    raise ValueError(message)


def test_a_linear_algebra_failure_in_the_fast_predict_raises_a_safety_path_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    estimator = _build(_SilentExtractor())
    monkeypatch.setattr(estimator._fast, "predict", _raise_linear_algebra_error)

    with pytest.raises(SafetyPathError):
        estimator.update_fast(_frame(0))


def test_the_fast_numerical_failure_is_dispositioned_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    estimator = _build(_SilentExtractor())
    monkeypatch.setattr(estimator._fast, "predict", _raise_linear_algebra_error)

    with pytest.raises(SafetyPathError) as raised:
        estimator.update_fast(_frame(0))

    assert raised.value.disposition is SafetyDisposition.FAIL_CLOSED
    assert raised.value.context["filter"] == "fast"


def test_a_numerical_failure_in_the_update_step_also_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vehicle = _GroundTruthVehicle(speed=CRUISE_SPEED, lateral_acceleration=0.0)
    estimator = _build(_NoisyExtractor(vehicle, random.Random(SEED)))
    monkeypatch.setattr(estimator._fast, "update", _raise_value_error)

    with pytest.raises(SafetyPathError) as raised:
        estimator.update_fast(_frame(0))

    assert raised.value.disposition is SafetyDisposition.FAIL_CLOSED


def test_a_numerical_failure_in_the_slow_filter_fails_closed_and_names_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    estimator = _build(_SilentExtractor())
    monkeypatch.setattr(estimator._slow, "predict", _raise_linear_algebra_error)

    with pytest.raises(SafetyPathError) as raised:
        estimator.update_slow(_frame(0))

    assert raised.value.disposition is SafetyDisposition.FAIL_CLOSED
    assert raised.value.context["filter"] == "slow"


def test_a_failed_tick_yields_no_estimate_rather_than_a_stale_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vehicle = _GroundTruthVehicle(speed=CRUISE_SPEED, lateral_acceleration=0.0)
    estimator = _build(_NoisyExtractor(vehicle, random.Random(SEED)))
    for index in range(10):
        estimator.update_fast(_frame(index))
        vehicle.advance()

    monkeypatch.setattr(estimator._fast, "predict", _raise_linear_algebra_error)

    with pytest.raises(SafetyPathError):
        estimator.update_fast(_frame(10))

    # The failure was not absorbed: no eleventh cycle and no eleventh innovation.
    assert estimator.fast_updates == 10
    assert len(estimator.innovation_history) == 10


def test_a_singular_innovation_covariance_is_reported_as_a_filter_fault(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A non-finite Mahalanobis distance means the innovation covariance was
    # singular. Reporting it as a distance of zero would mark a broken filter
    # healthy, so it fails closed instead.
    vehicle = _GroundTruthVehicle(speed=CRUISE_SPEED, lateral_acceleration=0.0)
    estimator = _build(_NoisyExtractor(vehicle, random.Random(SEED)))
    monkeypatch.setattr(type(estimator._fast), "mahalanobis", property(lambda _self: float("nan")))

    with pytest.raises(SafetyPathError) as raised:
        estimator.update_fast(_frame(0))

    assert raised.value.disposition is SafetyDisposition.FAIL_CLOSED
    assert estimator.latest_innovation() is None


def test_a_non_finite_covariance_is_reported_as_divergence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    estimator = _build(_SilentExtractor())

    def _corrupt(*_args: object, **_kwargs: object) -> None:
        estimator._fast.P = np.full(
            (FAST_STATE_DIMENSION, FAST_STATE_DIMENSION), float("inf"), dtype=np.float64
        )

    monkeypatch.setattr(estimator._fast, "predict", _corrupt)

    with pytest.raises(SafetyPathError) as raised:
        estimator.update_fast(_frame(0))

    assert raised.value.disposition is SafetyDisposition.FAIL_CLOSED


# --------------------------------------------------------------------------- #
# A measurement built against the wrong state layout is refused
# --------------------------------------------------------------------------- #
# The failure this prevents is silent. A slow-state measurement has indices
# 0, 1, 2 that are perfectly valid in the fast filter, so nothing raises and
# road friction is written into the state as position and speed. Every gate
# above L2 then reads a corrupted state, and the innovation monitor reports it
# as an ordinary sensor fault rather than the wiring fault it is.


class _SlowIntoFastExtractor:
    def extract_fast(self, frame: FusedSensorFrame[object]) -> Measurement | None:
        del frame
        return slow_measurement([("road_friction_coefficient", 0.85, 4e-4)])

    def extract_slow(self, frame: FusedSensorFrame[object]) -> Measurement | None:
        del frame
        return None


class _FastIntoSlowExtractor:
    def extract_fast(self, frame: FusedSensorFrame[object]) -> Measurement | None:
        del frame
        return None

    def extract_slow(self, frame: FusedSensorFrame[object]) -> Measurement | None:
        del frame
        return fast_measurement(
            [
                ("position_x", 1.0, 0.25),
                ("position_y", 1.0, 0.25),
                ("speed", 12.0, 0.01),
                ("heading", 0.0, 0.01),
                ("lateral_acceleration", 0.0, 0.04),
            ]
        )


def test_a_slow_measurement_returned_for_the_fast_filter_is_refused() -> None:
    estimator = _build(_SlowIntoFastExtractor())

    with pytest.raises(ContractViolationError) as raised:
        estimator.update_fast(_frame(0))

    assert raised.value.context["filter"] == "fast"
    assert raised.value.context["measurement_layout"] == list(SLOW_STATE_FIELDS)
    assert raised.value.context["expected_layout"] == list(FAST_STATE_FIELDS)


def test_a_fast_measurement_returned_for_the_slow_filter_is_refused() -> None:
    estimator = _build(_FastIntoSlowExtractor())

    with pytest.raises(ContractViolationError) as raised:
        estimator.update_slow(_frame(0))

    assert raised.value.context["filter"] == "slow"


def test_a_cross_layout_measurement_never_reaches_the_state() -> None:
    # The regression: before the layout check, this drove the speed estimate
    # from 12.0 m/s to about 1.1 m/s without raising anything.
    estimator = _build(_SlowIntoFastExtractor())

    with pytest.raises(ContractViolationError):
        estimator.update_fast(_frame(0))

    assert estimator.fast_updates == 0


def test_a_slow_into_fast_measurement_fails_closed() -> None:
    # Whatever escapes must carry a disposition, or the caller's single
    # reviewable `except` cannot turn the tick into a VETO.
    estimator = _build(_SlowIntoFastExtractor())

    with pytest.raises(AstraError) as raised:
        estimator.update_fast(_frame(0))

    assert raised.value.disposition is SafetyDisposition.FAIL_CLOSED


def test_a_fast_into_slow_measurement_fails_closed() -> None:
    estimator = _build(_FastIntoSlowExtractor())

    with pytest.raises(AstraError) as raised:
        estimator.update_slow(_frame(0))

    assert raised.value.disposition is SafetyDisposition.FAIL_CLOSED


def test_an_index_error_from_the_filter_becomes_a_fail_closed_safety_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An IndexError escaping uncaught would carry no disposition at all, so the
    # caller's `except SafetyPathError` would not fire.
    estimator = _build(
        _NoisyExtractor(_GroundTruthVehicle(speed=12.0, lateral_acceleration=0.0), random.Random(1))
    )

    def _raise(*args: object, **kwargs: object) -> None:
        del args, kwargs
        message = "index 7 is out of bounds for axis 0 with size 5"
        raise IndexError(message)

    monkeypatch.setattr(estimator._fast, "update", _raise)

    with pytest.raises(SafetyPathError) as raised:
        estimator.update_fast(_frame(0))

    assert raised.value.disposition is SafetyDisposition.FAIL_CLOSED
