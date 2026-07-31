"""Unit tests for the deterministic fallback controller."""

from __future__ import annotations

import pytest

from astra.contracts.estimation import FastStateEstimate
from astra.kernel.errors import (
    ContractViolationError,
    NonFiniteValueError,
    RangeViolationError,
)
from astra.kernel.identifiers import TickId
from astra.kernel.matrix import SymmetricMatrix
from astra.kernel.time import Instant, Timeline
from astra.kernel.units import MetresPerSecond, Seconds
from astra.layers.l9_rcm.arbiter import FallbackController
from astra.layers.l9_rcm.fallback import ProportionalFallbackController

CHANNELS = 3
SPEED_CHANNEL = 0
TARGET = MetresPerSecond(16.0)
GAIN = 0.2
PERIOD = Seconds(0.05)
LIMIT = 1.0
COVARIANCE = SymmetricMatrix.from_diagonal([1.0, 1.0, 0.25, 0.1, 0.5])


def _controller(**overrides: object) -> ProportionalFallbackController:
    arguments: dict[str, object] = {
        "channel_count": CHANNELS,
        "speed_index": SPEED_CHANNEL,
        "target_speed": TARGET,
        "proportional_gain": GAIN,
        "tick_period": PERIOD,
        "integral_limit": LIMIT,
    }
    arguments.update(overrides)
    return ProportionalFallbackController(**arguments)  # type: ignore[arg-type]


def _state(speed: float) -> FastStateEstimate:
    return FastStateEstimate(
        tick=TickId(0),
        valid_at=Instant(0, Timeline.MANUAL),
        mean=(0.0, 0.0, speed, 0.0, 0.0),
        covariance=COVARIANCE,
    )


# --------------------------------------------------------------------------- #
# Construction
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("count", [0, -1])
def test_a_space_with_no_channels_is_refused(count: int) -> None:
    with pytest.raises(ContractViolationError):
        _controller(channel_count=count)


@pytest.mark.parametrize("index", [3, 4, -1])
def test_a_speed_channel_outside_the_space_is_refused(index: int) -> None:
    with pytest.raises(ContractViolationError):
        _controller(speed_index=index)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("target_speed", MetresPerSecond(-1.0)),
        ("proportional_gain", -0.1),
        ("tick_period", Seconds(-0.05)),
        ("integral_limit", -1.0),
    ],
)
def test_a_negative_parameter_is_refused(field: str, value: object) -> None:
    with pytest.raises(RangeViolationError):
        _controller(**{field: value})


def test_the_integral_starts_at_zero() -> None:
    assert _controller().integral == 0.0


# --------------------------------------------------------------------------- #
# Command shape
# --------------------------------------------------------------------------- #


def test_the_command_has_one_value_per_channel() -> None:
    assert len(_controller().command()) == CHANNELS


def test_every_channel_but_the_speed_channel_is_commanded_zero() -> None:
    # A vetoed tick is not evidence that the previous steering command was good.
    # Continuing to turn on the strength of a command nobody validated is how a
    # fallback becomes the fault.
    controller = _controller()
    for _ in range(20):
        controller.observe(_state(0.0))

    command = controller.command()

    assert command[SPEED_CHANNEL] != 0.0
    assert all(value == 0.0 for index, value in enumerate(command) if index != SPEED_CHANNEL)


def test_the_command_is_clamped_to_the_unit_interval() -> None:
    controller = _controller(proportional_gain=1000.0)
    for _ in range(200):
        controller.observe(_state(0.0))

    assert abs(controller.command()[SPEED_CHANNEL]) <= 1.0


# --------------------------------------------------------------------------- #
# The integral term
# --------------------------------------------------------------------------- #


def test_the_integral_rises_while_the_vehicle_is_below_target() -> None:
    controller = _controller()

    controller.observe(_state(float(TARGET) - 5.0))
    first = controller.integral
    controller.observe(_state(float(TARGET) - 5.0))

    assert first > 0.0
    assert controller.integral > first


def test_the_integral_falls_while_the_vehicle_is_above_target() -> None:
    controller = _controller()

    controller.observe(_state(float(TARGET) + 5.0))
    first = controller.integral
    controller.observe(_state(float(TARGET) + 5.0))

    assert first < 0.0
    assert controller.integral < first


def test_the_integral_is_unchanged_at_the_target_speed() -> None:
    controller = _controller()

    controller.observe(_state(float(TARGET)))

    assert controller.integral == pytest.approx(0.0)


@pytest.mark.parametrize("speed", [0.0, 100.0])
def test_the_integral_is_clamped_against_windup(speed: float) -> None:
    # An unclamped integrator accumulating through a long veto sequence would
    # produce a large command the moment the vehicle is released back to it --
    # turning a recovery into a lurch.
    controller = _controller()

    for _ in range(5000):
        controller.observe(_state(speed))

    assert abs(controller.integral) <= LIMIT


def test_a_tighter_limit_clamps_sooner() -> None:
    loose = _controller(integral_limit=2.0)
    tight = _controller(integral_limit=0.25)
    for _ in range(500):
        loose.observe(_state(0.0))
        tight.observe(_state(0.0))

    assert loose.integral > tight.integral
    assert tight.integral == pytest.approx(0.25)


# --------------------------------------------------------------------------- #
# Reset and non-finite input
# --------------------------------------------------------------------------- #


def test_reset_clears_the_accumulated_error() -> None:
    controller = _controller()
    for _ in range(50):
        controller.observe(_state(0.0))
    assert controller.integral != 0.0

    controller.reset()

    assert controller.integral == 0.0
    assert controller.command()[SPEED_CHANNEL] == 0.0


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_speed_is_refused(bad: float) -> None:
    with pytest.raises(NonFiniteValueError):
        _controller().observe(_state(bad))


def test_a_refused_observation_leaves_the_integral_untouched() -> None:
    controller = _controller()
    controller.observe(_state(0.0))
    before = controller.integral

    with pytest.raises(NonFiniteValueError):
        controller.observe(_state(float("nan")))

    assert controller.integral == before


# --------------------------------------------------------------------------- #
# Protocol conformance
# --------------------------------------------------------------------------- #


def test_the_controller_satisfies_the_fallback_controller_protocol() -> None:
    assert isinstance(_controller(), FallbackController)
