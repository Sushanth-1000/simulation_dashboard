"""Is NFR5 true? Tested against a warehouse AGV, and the answer is "partly".

What was tested
----------------
NFR5 claims the platform core is domain-independent: the layers hold no
knowledge of vehicles, and a different platform arrives entirely through
adapters. `ASSUMPTIONS.md` A-1 recorded it as **asserted, structurally
defended, never tested**, and `EVIDENCE.md` N-6 said the same. P4.4's exit
criterion was exact -- get a genuinely non-automotive platform through the
pipeline **without touching ``src/astra/`` outside adapters** -- and it noted
that revealing the claim to be automotive-shaped would be the more valuable
outcome.

:mod:`training.warehouse` is that platform: a differential-drive AGV with two
wheels commanded in rad/s, no throttle, no brake, no steering angle, turning by
driving its wheels at different speeds.

The result, in one line
------------------------
**NFR5 holds for the gates and fails for the plumbing.** L3, L6, L7a and L7b
genuinely do not care what platform they bound -- every input they take is a
number with a unit. What is automotive is the *composition root*, the *process
model* and the *vocabulary*, and the first two are load-bearing.

Why these are strict xfails
----------------------------
Each failing test below asserts what NFR5 *claims*, and is marked
``xfail(strict=True)``. So it fails today, deliberately and visibly -- and the
day someone makes the claim true, the test **XPASSes and the suite goes red**,
forcing the marker off and the evidence row with it. A finding recorded only in
a document drifts; a finding recorded as a strict xfail cannot.

This is the same device E-32 used for the EWC selectivity result, for the same
reason.
"""

from __future__ import annotations

import inspect

import numpy as np
import pytest

from astra.kernel.constants import FAST_STATE_FIELDS, SLOW_STATE_FIELDS
from astra.kernel.enums import ContextClass
from astra.layers.l2_estimation.models import fast_transition
from astra.runtime.assembly import assemble_pipeline
from training.warehouse import (
    AgvSpec,
    DifferentialDriveProjector,
    WarehouseAgv,
    WarehousePolicy,
    differential_drive_actuation_space,
)

pytestmark = pytest.mark.architecture

_ROAD_WORDS = ("road", "tyre", "tire", "highway", "lane", "traffic")


# --------------------------------------------------------------------------- #
# What NFR5 gets right, and it is the majority of the surface
# --------------------------------------------------------------------------- #


def test_the_fast_state_layout_is_domain_neutral() -> None:
    # Position, speed, heading and lateral acceleration are true of anything
    # that moves in a plane. This is the layout every gate reads, and it needed
    # no change at all for a warehouse robot.
    assert not [field for field in FAST_STATE_FIELDS if any(word in field for word in _ROAD_WORDS)]


def test_a_non_automotive_actuation_space_is_expressible() -> None:
    # The *contract* is neutral even though the composition root is not: two
    # channels, named and bounded by the adapter, in the adapter's own units.
    space = differential_drive_actuation_space()

    assert space.dimension == 2
    assert [channel.name for channel in space.channels] == ["left_wheel", "right_wheel"]
    assert all(channel.unit == "rad/s" for channel in space.channels)


def test_a_non_automotive_platform_can_satisfy_the_policy_protocol() -> None:
    policy = WarehousePolicy(AgvSpec())

    command = policy.act((0.0, 0.3, 0.9, 0.0, 0.0, 1.0))

    assert len(command) == 2
    # Off-centre to the left, so it must drive the wheels unequally to correct.
    assert command[0] != command[1]


def test_a_non_automotive_platform_can_satisfy_the_projector_role() -> None:
    spec = AgvSpec()
    projector = DifferentialDriveProjector(spec)

    adjusted = projector.project((9.0, 9.0), lateral_acceleration=0.2)
    forward, yaw = spec.kinematics(*adjusted)

    assert forward == pytest.approx(spec.kinematics(9.0, 9.0)[0])
    assert forward * yaw == pytest.approx(0.2, rel=1e-6)


def test_the_agv_plant_moves_under_its_own_kinematics() -> None:
    # A control on the tests below: the AGV itself works. Where it fails to get
    # through the pipeline, that is the pipeline.
    agv = WarehouseAgv()
    policy = WarehousePolicy(agv.spec)

    started = abs(agv.state[1])
    for _ in range(200):
        agv.step(policy.act((*agv.state, 1.0)))

    # It converges toward the centre and stays well inside the aisle. Not
    # asserted to any particular offset: this is a proportional controller with
    # a steady-state error, and tightening the bound would be testing the
    # controller rather than the claim, which is that the platform works.
    assert abs(agv.state[1]) < started / 4.0
    assert abs(agv.state[1]) < agv.spec.aisle_half_width_m
    assert agv.state[0] > 1.0  # and made progress along it


# --------------------------------------------------------------------------- #
# Wall 1 -- the composition root
# --------------------------------------------------------------------------- #


@pytest.mark.xfail(
    strict=True,
    reason=(
        "NFR5 wall 1: assemble_pipeline calls automotive_actuation_space() directly "
        "and takes no parameter for it, so a different platform cannot supply a "
        "different space. The module docstring three hundred lines above claims it can."
    ),
)
def test_the_actuation_space_can_be_supplied_by_an_adapter() -> None:
    parameters = inspect.signature(assemble_pipeline).parameters

    assert any("space" in name for name in parameters)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "NFR5 wall 2: the command projector is not injectable either, and "
        "AutomotiveCommandProjector divides by a steering effectiveness -- arithmetic "
        "a differential drive has no counterpart for, because it has no steering channel."
    ),
)
def test_the_command_projector_can_be_supplied_by_an_adapter() -> None:
    parameters = inspect.signature(assemble_pipeline).parameters

    assert any("projector" in name for name in parameters)


# --------------------------------------------------------------------------- #
# Wall 3 -- the process model, and the one that is not cosmetic
# --------------------------------------------------------------------------- #


@pytest.mark.xfail(
    strict=True,
    reason=(
        "NFR5 wall 3: L2's process model is a bicycle model. It derives yaw rate from "
        "a_lat / v and refuses below yaw_rate_minimum_speed, so a platform that turns "
        "on the spot cannot be estimated. This is domain knowledge inside a layer, "
        "which is the thing NFR5 forbids -- and unlike walls 1, 2 and 4 it cannot be "
        "fixed by moving a symbol."
    ),
)
def test_the_process_model_can_represent_a_platform_that_turns_on_the_spot() -> None:
    # A warehouse AGV pivots at zero forward speed constantly: it is how it gets
    # into a rack aisle. Under this model its heading does not change at all.
    stationary_but_turning = np.array([0.0, 0.0, 0.0, 0.0, 0.5])

    propagated = fast_transition(stationary_but_turning, 0.05, yaw_rate_minimum_speed=0.5)

    assert propagated[3] != 0.0


def test_the_process_model_takes_an_automotive_parameter() -> None:
    # Not an xfail -- a statement of fact, asserted so that the parameter cannot
    # quietly disappear and take the finding with it.
    parameters = inspect.signature(fast_transition).parameters

    assert "yaw_rate_minimum_speed" in parameters


# --------------------------------------------------------------------------- #
# Wall 4 -- the kernel's vocabulary
# --------------------------------------------------------------------------- #


@pytest.mark.xfail(
    strict=True,
    reason=(
        "NFR5 wall 4: SLOW_STATE_FIELDS names road friction and tyre wear, in "
        "astra.kernel -- the layer with no dependencies and the strongest claim to "
        "neutrality. A warehouse has floors and wheels. The *shape* is right and only "
        "the names are wrong, which makes this the cheapest of the four to fix and the "
        "least urgent."
    ),
)
def test_the_slow_state_layout_is_domain_neutral() -> None:
    assert not [field for field in SLOW_STATE_FIELDS if any(word in field for word in _ROAD_WORDS)]


@pytest.mark.xfail(
    strict=True,
    reason=(
        "NFR5 wall 4, continued: ContextClass is HIGHWAY_CLEAR, URBAN_CLEAR and "
        "RAIN_NIGHT. A warehouse AGV has no highway and no weather, so every tick "
        "classifies UNCLASSIFIED -- which means no certified profile ever matches and "
        "bounded safe exploration engages permanently. Cosmetic in name, operational "
        "in effect."
    ),
)
def test_the_context_classes_are_domain_neutral() -> None:
    assert not [
        context.value
        for context in ContextClass
        if any(word in context.value.lower() for word in _ROAD_WORDS)
    ]
