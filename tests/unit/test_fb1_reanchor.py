"""FB1: the estimator learns what the vehicle was actually told to do.

Without this loop the fast model asserts that lateral acceleration is constant
between measurements, so the filter can only learn about a manoeuvre once the
IMU reports it -- and if the IMU is degraded or absent, never. The vehicle is
then being steered by a command the estimator does not know was sent, which is
the shared-state common-cause channel the architecture calls out.

The property that matters most here is the one that is easiest to get wrong:
the command must enter the *prediction*, never the state. Writing it into ``x``
would make the estimate agree with the command by construction and destroy the
innovation the system uses to detect that the vehicle is not doing what it was
told. A filter like that reports perfect health exactly when the actuator has
failed.
"""

from __future__ import annotations

import numpy as np
import pytest

from astra.layers.l2_estimation.models import fast_transition

MINIMUM_SPEED = 0.5
STEP = 0.02
CRUISING = np.array([0.0, 0.0, 13.0, 0.0, 0.0])


# --------------------------------------------------------------------------- #
# The transition takes a command input
# --------------------------------------------------------------------------- #


def test_without_a_command_the_model_holds_lateral_acceleration_constant() -> None:
    # The behaviour every run before FB1 had, retained so an ablation can turn
    # the loop off and measure the difference rather than argue about it.
    state = np.array([0.0, 0.0, 13.0, 0.0, 2.0])

    propagated = fast_transition(state, STEP, yaw_rate_minimum_speed=MINIMUM_SPEED)

    assert propagated[4] == pytest.approx(2.0)


def test_a_command_changes_the_heading_the_model_predicts() -> None:
    # The point of the loop. A commanded lateral acceleration is a yaw rate, and
    # a yaw rate is a heading change the filter should already expect.
    without = fast_transition(CRUISING, STEP, yaw_rate_minimum_speed=MINIMUM_SPEED)
    with_command = fast_transition(
        CRUISING,
        STEP,
        yaw_rate_minimum_speed=MINIMUM_SPEED,
        commanded_lateral_acceleration=2.8,
    )

    assert without[3] == pytest.approx(0.0)
    assert with_command[3] > 0.0


def test_the_commanded_value_replaces_the_estimate_only_for_this_step() -> None:
    state = np.array([0.0, 0.0, 13.0, 0.0, 2.0])

    propagated = fast_transition(
        state,
        STEP,
        yaw_rate_minimum_speed=MINIMUM_SPEED,
        commanded_lateral_acceleration=-1.0,
    )

    assert propagated[4] == pytest.approx(-1.0)
    assert state[4] == pytest.approx(2.0), "the input state was mutated"


def test_a_command_of_zero_is_not_the_same_as_no_command() -> None:
    # The distinction the whole loop rests on. `None` means "nobody told me
    # anything, keep assuming"; 0.0 means "the vehicle was commanded straight",
    # which is information. Collapsing them would make a tick that issued a
    # straight-ahead command indistinguishable from a tick that issued nothing.
    state = np.array([0.0, 0.0, 13.0, 0.0, 2.0])

    assuming = fast_transition(state, STEP, yaw_rate_minimum_speed=MINIMUM_SPEED)
    commanded = fast_transition(
        state, STEP, yaw_rate_minimum_speed=MINIMUM_SPEED, commanded_lateral_acceleration=0.0
    )

    assert assuming[4] != pytest.approx(commanded[4])


def test_the_yaw_rate_floor_still_applies_to_a_commanded_value() -> None:
    # Below the floor the yaw rate is taken as zero rather than `a_lat / v`.
    # A command must not be a way around a guard that exists to avoid dividing
    # by a speed near zero.
    stationary = np.array([0.0, 0.0, 0.0, 0.0, 0.0])

    propagated = fast_transition(
        stationary,
        STEP,
        yaw_rate_minimum_speed=MINIMUM_SPEED,
        commanded_lateral_acceleration=50.0,
    )

    assert propagated[3] == pytest.approx(0.0)
