"""The tunnel: a context no certified profile covers, and the vehicle keeps moving.

This is the behaviour that most distinguishes ASTRA from the systems in its
prior-art table. Those degrade to a halt when they leave their certified
envelope. ASTRA is built not to: with no admissible profile, RCM engages bounded
safe exploration -- half the nearest certified speed, inside a +/-15 degree
steering cone, no lane changes, evidence logged -- and the vehicle continues.

What these tests assert, and what they do not
-----------------------------------------------
They assert the *mechanism*: that an out-of-envelope context is detected, that
the envelope narrows, that it widens again on the way out, and that no tick in
between fails to issue a command.

They do not assert that the vehicle drives *well* in a tunnel. It is running a
deterministic placeholder policy against a synthetic vehicle; "keeps moving
safely through an unmodelled context" is a claim that needs the trained policy
and a real simulator. What is demonstrated is that the architecture's answer to
an unrecognised context is a narrowed envelope rather than a stop.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

import pytest

from astra.config.loader import load_settings
from astra.contracts.sensing import SensorSample
from astra.kernel.enums import ArbitrationOutcome, FailSafeState, SensorModality
from astra.kernel.identifiers import RunId, TickId
from astra.kernel.time import Instant, ManualClock, Timeline
from astra.kernel.units import Probability, Seconds
from astra.layers.l2_estimation.measurement import fast_measurement, slow_measurement
from astra.layers.l3_trust.corpus import CalibrationCorpus
from astra.layers.l9_rcm.exploration import (
    MAXIMUM_STEERING_RADIANS,
    exploration_envelope,
    restricted_space,
)
from astra.observability.audit import JsonlAuditSink
from astra.runtime.assembly import assemble_pipeline, automotive_actuation_space
from astra.runtime.pipeline import ColdPathContext, TickOutcome

if TYPE_CHECKING:
    from astra.contracts.audit import JsonValue
    from astra.contracts.governance import ArbitrationDecision
    from astra.layers.l2_estimation.measurement import Measurement
    from astra.runtime.assembly import AssembledPipeline

TWIN = Path("var/twin/synthetic.pt")
CORPUS = Path("var/calibration/synthetic.json")

OPEN_ROAD = (0.90, 0.22)
INSIDE_TUNNEL = (0.05, 0.95)
ENTRY = 15
EXIT = 35
TICKS = 50
PERIOD_TICKS = 5

pytestmark = pytest.mark.skipif(
    not (TWIN.exists() and CORPUS.exists()),
    reason=(
        "needs a trained twin and a calibration corpus:\n"
        "  python training/train_twin.py --out var/twin/synthetic.pt\n"
        "  python training/generate_calibration.py --out var/calibration/synthetic.json"
    ),
)


class _Observed(NamedTuple):
    """One tick, with the cold-path state that tick ended in."""

    outcome: TickOutcome
    exploring: bool
    arbitration: ArbitrationDecision | None


class _Extractor:
    def extract_fast(self, frame: object) -> Measurement | None:
        sample = frame.sample_for(SensorModality.IMU)  # type: ignore[attr-defined]
        if sample is None:
            return None
        payload = sample.payload
        return fast_measurement(
            [
                ("speed", float(payload["v"]), 0.01),
                ("lateral_acceleration", float(payload["a"]), 0.04),
            ]
        )

    def extract_slow(self, frame: object) -> Measurement | None:
        del frame
        return slow_measurement([("road_friction_coefficient", 0.85, 4e-4)])


def _context(settings: object, where: tuple[float, float]) -> ColdPathContext:
    return ColdPathContext(
        period_ticks=PERIOD_TICKS,
        trust_threshold=settings.arbitration.trust_threshold_tau,  # type: ignore[attr-defined]
        divergence_limit=settings.arbitration.divergence_limit_delta,  # type: ignore[attr-defined]
        platform="synthetic-prototype",
        legal_speed_limit=settings.shield.legal_speed_limit,  # type: ignore[attr-defined]
        visibility=Probability(where[0]),
        traffic_dynamicity=Probability(0.32),
        road_complexity=Probability(where[1]),
    )


def _drive(tmp_path: Path, *, enter_tunnel: bool) -> list[_Observed]:
    """Drive through the tunnel, or straight past it, and return every outcome."""
    resolved = load_settings(environment="simulation", include_environment_variables=False)
    settings = resolved.settings
    clock = ManualClock(Instant(0, Timeline.MANUAL))
    run = RunId("run-tunnelscene01")
    sink = JsonlAuditSink(run=run, directory=tmp_path, fsync_each_record=False)
    built: AssembledPipeline[JsonValue] = assemble_pipeline(
        run=run,
        config_hash=resolved.hash,
        settings=settings,
        clock=clock,
        extractor=_Extractor(),
        audit_sink=sink,
        initial_speed=settings.shield.legal_speed_limit,
        twin_checkpoint=TWIN,
        corpus=CalibrationCorpus.read(CORPUS),
        cold_path=_context(settings, OPEN_ROAD),
    )
    period = Seconds(1.0 / settings.estimation.fast_rate_hz)
    speed = float(settings.shield.legal_speed_limit) * 0.78
    outcomes: list[_Observed] = []

    for index in range(TICKS):
        inside = enter_tunnel and ENTRY <= index < EXIT
        built.pipeline.enter_context(_context(settings, INSIDE_TUNNEL if inside else OPEN_ROAD))
        for modality in SensorModality:
            built.sensor_bus.publish(
                SensorSample(
                    modality=modality,
                    observed_at=clock.now(),
                    quality=Probability(0.95),
                    payload={"v": speed, "a": 0.0},
                )
            )
        outcome = built.pipeline.tick(TickId(index))
        if outcome.record.fast_state is not None:
            built.fallback.observe(outcome.record.fast_state)
        outcomes.append(_Observed(outcome, built.pipeline.is_exploring, built.pipeline.arbitration))
        clock.advance(period)

    sink.flush()
    return outcomes


# --------------------------------------------------------------------------- #
# The vehicle never stops
# --------------------------------------------------------------------------- #


def test_no_tick_of_a_tunnel_transit_fails_to_issue_a_command(tmp_path: Path) -> None:
    # The headline property. Every exploration exit condition leaves the vehicle
    # moving; none of them is a halt, and this asserts that end to end.
    outcomes = _drive(tmp_path, enter_tunnel=True)

    unissued = [index for index, (outcome, _, _) in enumerate(outcomes) if not outcome.was_issued]

    assert unissued == []


def test_the_fail_safe_machine_never_leaves_nominal_in_a_tunnel(tmp_path: Path) -> None:
    # An unrecognised *context* is not a safety fault. If entering a tunnel drove
    # the OOD counter up, the graduated response would fire for a situation the
    # gates never objected to.
    outcomes = _drive(tmp_path, enter_tunnel=True)

    for observed in outcomes:
        failsafe = observed.outcome.record.failsafe
        assert failsafe is not None
        assert failsafe.state is FailSafeState.NOMINAL


# --------------------------------------------------------------------------- #
# The envelope narrows, and widens again
# --------------------------------------------------------------------------- #


def test_entering_the_tunnel_engages_bounded_safe_exploration(tmp_path: Path) -> None:
    outcomes = _drive(tmp_path, enter_tunnel=True)

    before = any(exploring for _, exploring, _ in outcomes[:ENTRY])
    during = [exploring for _, exploring, _ in outcomes[ENTRY + PERIOD_TICKS : EXIT]]

    assert not before, "exploration engaged on open road"
    assert all(during), "exploration did not engage inside the tunnel"


def test_leaving_the_tunnel_restores_the_nominal_envelope(tmp_path: Path) -> None:
    # PROFILE_REACQUIRED. Exploration is a response to the situation, not a
    # latch: a system that stayed narrowed after the context returned would be
    # permanently degraded by one tunnel.
    outcomes = _drive(tmp_path, enter_tunnel=True)

    after = [exploring for _, exploring, _ in outcomes[EXIT + PERIOD_TICKS :]]

    assert after, "the drive ended too early to observe the exit"
    assert not any(after)


def test_the_arbitration_outcome_is_recorded_as_safe_exploration(tmp_path: Path) -> None:
    outcomes = _drive(tmp_path, enter_tunnel=True)

    inside = {
        arbitration.outcome
        for _, _, arbitration in outcomes[ENTRY + PERIOD_TICKS : EXIT]
        if arbitration is not None
    }

    assert ArbitrationOutcome.SAFE_EXPLORATION in inside


def test_a_drive_that_never_enters_the_tunnel_never_explores(tmp_path: Path) -> None:
    # The control. Without it, "exploration engaged" could mean the knowledge
    # base simply never matches anything -- which is what a badly seeded profile
    # set actually did.
    outcomes = _drive(tmp_path, enter_tunnel=False)

    assert not any(exploring for _, exploring, _ in outcomes)
    assert all(outcome.was_issued for outcome, _, _ in outcomes)


# --------------------------------------------------------------------------- #
# The envelope is enforced by the actuation space, not by convention
# --------------------------------------------------------------------------- #


def test_the_exploration_envelope_narrows_the_steering_cone() -> None:
    # Narrowing the space rather than clamping at the point of issue routes the
    # envelope through the check that already guards every command: an
    # IssuedCommand outside its space is refused at construction.
    nominal = automotive_actuation_space()
    narrowed = restricted_space(nominal, exploration_envelope(30.0))

    assert narrowed.channel("steer").upper == pytest.approx(MAXIMUM_STEERING_RADIANS)
    assert narrowed.channel("steer").lower == pytest.approx(-MAXIMUM_STEERING_RADIANS)
    assert narrowed.channel("throttle").upper < nominal.channel("throttle").upper
    assert narrowed.names == nominal.names


def test_braking_authority_is_not_reduced_during_exploration() -> None:
    # Exploration bounds what the vehicle may *do*. Taking away its ability to
    # stop would make the safety envelope less safe.
    nominal = automotive_actuation_space()
    narrowed = restricted_space(nominal, exploration_envelope(30.0))

    assert narrowed.channel("brake") == nominal.channel("brake")
