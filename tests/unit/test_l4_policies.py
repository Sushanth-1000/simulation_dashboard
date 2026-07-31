"""Unit tests for the placeholder proposer policy.

The property most of this file is about is the one that was got wrong twice
while the pipeline was being assembled, and that the physical gate caught both
times: a steering command must name the lateral acceleration the vehicle should
have *next* tick, within one tick's jerk allowance of the one it has now.
"""

from __future__ import annotations

import pytest

from astra.kernel.constants import FAST_STATE_FIELDS
from astra.kernel.errors import (
    ContractViolationError,
    NonFiniteValueError,
    RangeViolationError,
)
from astra.layers.l4_proposer.policies import KinematicPlaceholderPolicy
from astra.layers.l4_proposer.proposer import Policy

CHANNELS = 3
THROTTLE = 0
BRAKE = 1
STEER = 2

STEER_EFFECTIVENESS = 140.0
TICK_PERIOD = 0.05
MAXIMUM_JERK = 8.0
TARGET_SPEED = 26.67

SPEED_POSITION = FAST_STATE_FIELDS.index("speed")
LATERAL_POSITION = FAST_STATE_FIELDS.index("lateral_acceleration")


def _policy(**overrides: float) -> KinematicPlaceholderPolicy:
    arguments: dict[str, float] = {
        "target_speed": TARGET_SPEED,
        "steer_effectiveness": STEER_EFFECTIVENESS,
        "tick_period": TICK_PERIOD,
        "maximum_jerk": MAXIMUM_JERK,
    }
    arguments.update(overrides)
    return KinematicPlaceholderPolicy(
        channel_count=CHANNELS,
        speed_index=THROTTLE,
        steer_index=STEER,
        **arguments,
    )


def _observation(*, speed: float, lateral: float) -> tuple[float, ...]:
    values = [0.0] * (len(FAST_STATE_FIELDS) + 1)
    values[SPEED_POSITION] = speed
    values[LATERAL_POSITION] = lateral
    values[-1] = 0.5  # the Trust Index the proposer appends
    return tuple(values)


# --------------------------------------------------------------------------- #
# Construction
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(("speed_index", "steer_index"), [(3, 2), (0, 3), (-1, 2), (0, -1)])
def test_a_channel_index_outside_the_space_is_refused(speed_index: int, steer_index: int) -> None:
    with pytest.raises(ContractViolationError):
        KinematicPlaceholderPolicy(
            channel_count=CHANNELS,
            speed_index=speed_index,
            steer_index=steer_index,
            target_speed=TARGET_SPEED,
            steer_effectiveness=STEER_EFFECTIVENESS,
            tick_period=TICK_PERIOD,
            maximum_jerk=MAXIMUM_JERK,
        )


@pytest.mark.parametrize(
    "field", ["target_speed", "speed_gain", "damping_fraction", "maximum_jerk"]
)
def test_a_negative_gain_or_limit_is_refused(field: str) -> None:
    with pytest.raises(RangeViolationError):
        _policy(**{field: -1.0})


@pytest.mark.parametrize("field", ["steer_effectiveness", "tick_period"])
def test_a_non_positive_plant_parameter_is_refused(field: str) -> None:
    # Both appear in a denominator or scale a denominator; zero is not merely
    # small here, it is undefined.
    with pytest.raises(RangeViolationError):
        _policy(**{field: 0.0})


# --------------------------------------------------------------------------- #
# Shape and the longitudinal channel
# --------------------------------------------------------------------------- #


def test_the_command_has_one_value_per_channel() -> None:
    command = _policy().act(_observation(speed=20.0, lateral=0.0))

    assert len(command) == CHANNELS


def test_the_brake_channel_is_never_commanded() -> None:
    # The placeholder holds a speed; it has no braking law, and commanding a
    # channel it has no policy for would be inventing behaviour.
    command = _policy().act(_observation(speed=40.0, lateral=0.0))

    assert command[BRAKE] == 0.0


@pytest.mark.parametrize("speed", [0.0, 10.0, 20.0, 26.0, 30.0, 50.0])
def test_the_throttle_stays_in_the_unit_interval(speed: float) -> None:
    command = _policy().act(_observation(speed=speed, lateral=0.0))

    assert 0.0 <= command[THROTTLE] <= 1.0


def test_the_throttle_rises_as_the_vehicle_falls_below_target() -> None:
    policy = _policy()

    slow = policy.act(_observation(speed=TARGET_SPEED - 10.0, lateral=0.0))
    near = policy.act(_observation(speed=TARGET_SPEED - 1.0, lateral=0.0))

    assert slow[THROTTLE] > near[THROTTLE]


def test_the_throttle_is_closed_above_the_target_speed() -> None:
    command = _policy().act(_observation(speed=TARGET_SPEED + 5.0, lateral=0.0))

    assert command[THROTTLE] == 0.0


# --------------------------------------------------------------------------- #
# The steering property the physical gate exists to check
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("lateral", [0.0, 0.5, -0.5, 1.5, -1.5, 3.0, -3.0, 6.0])
def test_the_commanded_lateral_acceleration_is_within_one_ticks_jerk_allowance(
    lateral: float,
) -> None:
    # The regression this pins: a damping law proportional to `-lateral` asks a
    # vehicle turning at 1.5 m/s^2 to be at roughly zero one tick later -- about
    # 30 m/s^3 against a limit of 8 -- so it vetoed on every tick of every turn.
    policy = _policy()
    allowance = MAXIMUM_JERK * TICK_PERIOD

    command = policy.act(_observation(speed=25.0, lateral=lateral))
    commanded_lateral = command[STEER] * STEER_EFFECTIVENESS

    assert abs(commanded_lateral - lateral) <= allowance + 1e-9


@pytest.mark.parametrize("lateral", [0.4, 1.5, 3.0])
def test_the_command_unwinds_a_turn_rather_than_holding_it(lateral: float) -> None:
    policy = _policy()

    commanded = policy.act(_observation(speed=25.0, lateral=lateral))[STEER]

    assert 0.0 <= commanded * STEER_EFFECTIVENESS < lateral


@pytest.mark.parametrize("lateral", [-0.4, -1.5, -3.0])
def test_a_turn_the_other_way_unwinds_the_other_way(lateral: float) -> None:
    policy = _policy()

    commanded = policy.act(_observation(speed=25.0, lateral=lateral))[STEER]

    assert lateral < commanded * STEER_EFFECTIVENESS <= 0.0


def test_a_vehicle_going_straight_is_commanded_straight() -> None:
    command = _policy().act(_observation(speed=25.0, lateral=0.0))

    assert command[STEER] == pytest.approx(0.0)


@pytest.mark.parametrize("lateral", [50.0, -50.0])
def test_the_steering_command_is_clamped_to_the_channel_bound(lateral: float) -> None:
    command = _policy().act(_observation(speed=25.0, lateral=lateral))

    assert abs(command[STEER]) <= 0.5


def test_a_smaller_damping_fraction_unwinds_more_slowly() -> None:
    gentle = _policy(damping_fraction=0.1)
    brisk = _policy(damping_fraction=0.5)
    observation = _observation(speed=25.0, lateral=2.0)

    gentle_target = gentle.act(observation)[STEER] * STEER_EFFECTIVENESS
    brisk_target = brisk.act(observation)[STEER] * STEER_EFFECTIVENESS

    assert gentle_target > brisk_target


# --------------------------------------------------------------------------- #
# Non-finite input and determinism
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_speed_is_refused(bad: float) -> None:
    with pytest.raises(NonFiniteValueError):
        _policy().act(_observation(speed=bad, lateral=0.0))


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_lateral_acceleration_is_refused(bad: float) -> None:
    with pytest.raises(NonFiniteValueError):
        _policy().act(_observation(speed=25.0, lateral=bad))


def test_the_policy_is_deterministic() -> None:
    # Determinism is what makes this a placeholder rather than a stand-in for a
    # learned policy: it cannot drift, and so it cannot exercise the gates.
    policy = _policy()
    observation = _observation(speed=22.0, lateral=1.1)

    assert policy.act(observation) == policy.act(observation)


def test_the_policy_satisfies_the_policy_protocol() -> None:
    assert isinstance(_policy(), Policy)
