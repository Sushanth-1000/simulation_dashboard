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
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from astra.config.loader import load_settings
from astra.contracts.actuation import ActuationChannel, ActuationSpace
from astra.kernel.constants import FAST_STATE_FIELDS, SLOW_STATE_FIELDS
from astra.kernel.enums import ContextClass
from astra.kernel.errors import ConfigurationError
from astra.kernel.identifiers import RunId
from astra.kernel.time import Instant, ManualClock, Timeline
from astra.layers.l2_estimation.measurement import Measurement
from astra.layers.l2_estimation.models import fast_transition
from astra.layers.l4_proposer.proposer import Policy
from astra.observability.audit import JsonlAuditSink
from astra.ports.pipeline import CommandProjector
from astra.runtime.assembly import (
    AssembledPipeline,
    assemble_pipeline,
    automotive_actuation_space,
)
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


class _NullExtractor:
    """Produces no measurement. This test never advances a tick."""

    def extract_fast(self, frame: object) -> Measurement | None:
        del frame
        return None

    def extract_slow(self, frame: object) -> Measurement | None:
        del frame
        return None


def _assemble(
    *,
    space: ActuationSpace,
    tmp_path: Path,
    projector: CommandProjector | None,
    policy: Policy | None = None,
) -> AssembledPipeline[Any]:
    """Build a pipeline with an adapter-supplied actuation space.

    Deliberately minimal: no twin, no corpus, no policy. The question is whether
    the composition root *adopts* what it was handed, and answering it needs
    nothing driven.
    """
    resolved = load_settings(environment="simulation", include_environment_variables=False)
    # A fourth coupling, and this one is the configuration layer working. The
    # effectiveness row maps each command channel to the lateral acceleration it
    # produces, so its length IS the channel count -- and the loader already
    # refuses a mismatch with a better message than anything this test could
    # add. A different platform needs a different profile, which is correct and
    # is not an NFR5 violation.
    settings = resolved.settings.model_copy(
        update={
            "twin": resolved.settings.twin.model_copy(
                update={"control_effectiveness": (0.0,) * space.dimension}
            )
        }
    )
    run = RunId("run-nfr5wall0001")
    return assemble_pipeline(
        run=run,
        config_hash=resolved.hash,
        settings=settings,
        clock=ManualClock(Instant(0, Timeline.MANUAL)),
        extractor=_NullExtractor(),
        audit_sink=JsonlAuditSink(run=run, directory=tmp_path, fsync_each_record=False),
        space=space,
        projector=projector,
        policy=policy,
    )


# --------------------------------------------------------------------------- #
# Wall 1 -- the composition root
# --------------------------------------------------------------------------- #


def test_the_actuation_space_can_be_supplied_by_an_adapter() -> None:
    """Wall 1, down on 15 August 2026 (ADR-0034).

    This was a **strict xfail** until then: ``assemble_pipeline`` called
    ``automotive_actuation_space()`` directly and took no parameter for it, so a
    different platform could not supply a different space -- while the module
    docstring three hundred lines above claimed it could. The strict marker is
    what turned the fix into a failing test rather than a silent improvement.

    Asserting the *keyword* and its default, not just that some parameter has
    "space" in its name: the previous assertion would have been satisfied by a
    parameter called ``workspace``.
    """
    parameters = inspect.signature(assemble_pipeline).parameters

    assert "space" in parameters
    assert parameters["space"].kind is inspect.Parameter.KEYWORD_ONLY
    # Defaulted rather than required. This composition root *is* automotive
    # until a second platform exists, and making it required would break every
    # caller to prove a point no adapter is yet making. NFR5 asks that a
    # different platform **can** supply one.
    assert parameters["space"].default is None


def test_the_command_projector_can_be_supplied_by_an_adapter() -> None:
    """Wall 2, down the same day and for the same reason.

    ``AutomotiveCommandProjector`` divides by a steering effectiveness --
    arithmetic a differential drive has no counterpart for, because it has no
    steering channel. That is precisely why it had to become **injectable**
    rather than better: no single projector can serve both platforms, and the
    layer must not know which one it has.
    """
    parameters = inspect.signature(assemble_pipeline).parameters

    assert "projector" in parameters
    assert parameters["projector"].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters["projector"].default is None


class _WheelProjector:
    """A differential drive's projector: no steering channel to divide by.

    Both wheels turn the platform, so a target lateral acceleration is a
    differential between them rather than a division by a steering gain. The
    arithmetic is irrelevant here -- what matters is that it is *possible to
    write one at all*, which is what wall 2 denied.
    """

    def with_lateral_acceleration(
        self, values: Sequence[float], target: float
    ) -> tuple[float, ...]:
        left, right = values
        return (left - target, right + target)

    def with_speed_cap(
        self, values: Sequence[float], *, current_speed: float, cap: float
    ) -> tuple[float, ...]:
        del current_speed
        return tuple(min(value, cap) for value in values)


class _WheelPolicy:
    """A differential drive's fallback: both wheels, no steering channel."""

    def act(self, observation: Sequence[float]) -> Sequence[float]:
        del observation
        return [0.0, 0.0]


def test_a_supplied_space_is_the_one_the_pipeline_uses(tmp_path: Path) -> None:
    """The seam is real, not decorative.

    A parameter that is accepted and ignored would pass both tests above and
    leave the wall standing. This drives the composition root with a
    two-channel space that is not the automotive one and checks the pipeline
    adopted it -- the difference between *injectable* and *has an injection
    point*.
    """
    supplied = ActuationSpace(
        (
            ActuationChannel(name="left_wheel", lower=-1.0, upper=1.0, unit="1"),
            ActuationChannel(name="right_wheel", lower=-1.0, upper=1.0, unit="1"),
        )
    )
    assert supplied.dimension != automotive_actuation_space().dimension, (
        "the fixture must differ from the default or this asserts nothing"
    )

    built = _assemble(
        space=supplied, tmp_path=tmp_path, projector=_WheelProjector(), policy=_WheelPolicy()
    )

    assert built.space is supplied
    assert [channel.name for channel in built.space.channels] == ["left_wheel", "right_wheel"]


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


def test_a_supplied_space_without_a_projector_is_refused(tmp_path: Path) -> None:
    """The two are one decision, and the root says so where it can be acted on.

    The default projector indexes ``STEER_INDEX`` into the space, so a caller
    supplying a two-channel differential drive and leaving the projector
    defaulted used to get ``steer_index 2 is outside a 2-channel actuation
    space`` from deep inside construction. **Refusing beats defaulting**: there
    is no sensible projector for a platform this function has never heard of,
    and a wrong one would divide by a steering effectiveness that does not
    exist.

    Found by the test above rather than by review -- writing an honest
    injection test turned up a half-injected seam.
    """
    supplied = ActuationSpace(
        (
            ActuationChannel(name="left_wheel", lower=-1.0, upper=1.0, unit="1"),
            ActuationChannel(name="right_wheel", lower=-1.0, upper=1.0, unit="1"),
        )
    )

    with pytest.raises(ConfigurationError, match="also needs: projector"):
        _assemble(space=supplied, tmp_path=tmp_path, projector=None, policy=_WheelPolicy())
