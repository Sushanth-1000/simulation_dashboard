"""Drive the assembled pipeline through a scripted scenario and print what happened.

    python demo/run_pipeline.py
    python demo/run_pipeline.py --scenario ice --ticks 40

This is the smallest thing that demonstrates ASTRA *as a system* rather than as
ten tested components. It builds all ten layers, drives a synthetic vehicle
through them, and prints one line per tick showing which gates fired, what the
fail-safe machine did, and what was actually issued to the actuators.

What a run here does and does not show
---------------------------------------
It shows the pipeline composing correctly: a command leaving the proposer,
crossing the one-way channel, meeting three gates, passing through the fail-safe
machine, reaching the arbitrator, and landing in the audit log with the
configuration hash and the twin's weights digest.

It shows nothing about how well ASTRA governs a *learned* controller, because
there is no learned controller here. The proposer runs
``KinematicPlaceholderPolicy``, which is deterministic and cannot hallucinate,
drift, or be adversarially perturbed. Every claim about false positives, false
negatives, veto rates or gate independence needs the trained PPO policy and the
Phase 9 scenarios. See ``docs/PROJECT_STATE_AND_ROADMAP.md``.

Prerequisite
------------
A trained twin::

    python training/train_twin.py --out var/twin/synthetic.pt

Without it the twin has random weights and predicts physically absurd commands --
a lateral acceleration of 13 g is representative -- so the physical and
statistical gates veto every tick. They are behaving correctly; the run is simply
not informative.
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Final

from astra.config.loader import load_settings
from astra.contracts.sensing import SensorSample
from astra.kernel.enums import SensorModality
from astra.kernel.identifiers import RunId, TickId
from astra.kernel.time import Instant, ManualClock, Timeline
from astra.kernel.units import Probability, Seconds
from astra.layers.l2_estimation.measurement import fast_measurement, slow_measurement
from astra.layers.l3_trust.corpus import CalibrationCorpus
from astra.observability.audit import JsonlAuditSink
from astra.runtime.assembly import assemble_pipeline
from astra.runtime.pipeline import ColdPathContext

if TYPE_CHECKING:
    from collections.abc import Sequence

    from astra.config.schema import AstraSettings
    from astra.contracts.audit import JsonValue
    from astra.layers.l2_estimation.measurement import Measurement
    from astra.runtime.assembly import AssembledPipeline

DEFAULT_CHECKPOINT = Path("var/twin/synthetic.pt")
DEFAULT_CORPUS = Path("var/calibration/synthetic.json")
ONSET_TICK = 6
CORNERING_LATERAL = 5.0
SPEEDING_MULTIPLIER = 1.8

SCENARIOS = {
    "nominal": "cruise in a straight line on dry tarmac",
    "cornering": "cruise, then a sustained 5 m/s^2 turn on dry tarmac",
    "ice": "the same turn, on a road the slow filter reports as ice",
    "speeding": "accelerate past the configured legal limit",
    "tunnel": "drive into a context no certified profile covers, and out again",
}

TUNNEL_ENTRY = 20
TUNNEL_EXIT = 45
OPEN_ROAD: Final[tuple[float, float]] = (0.90, 0.22)
INSIDE_TUNNEL: Final[tuple[float, float]] = (0.05, 0.95)
ARBITRATION_PERIOD_TICKS = 5
TRAFFIC_DYNAMICITY = 0.32


class _Vehicle:
    """A kinematic ground truth the sensors report on."""

    def __init__(self, speed: float) -> None:
        self.speed = speed
        self.lateral_acceleration = 0.0

    def step(self, *, speed: float, lateral_acceleration: float) -> None:
        self.speed = speed
        self.lateral_acceleration = lateral_acceleration


class _Extractor:
    """Turns the synthetic payload into measurements, as an adapter would."""

    def __init__(self, friction: float) -> None:
        self._friction = friction

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
        return slow_measurement([("road_friction_coefficient", self._friction, 4e-4)])


def _profile(scenario: str, index: int, cruise: float) -> tuple[float, float]:
    """Return the vehicle's speed and lateral acceleration for one tick."""
    if scenario in {"cornering", "ice"}:
        return cruise, CORNERING_LATERAL if index > ONSET_TICK else 0.0
    if scenario == "speeding":
        return (cruise * SPEEDING_MULTIPLIER if index > ONSET_TICK else cruise), 0.0
    return cruise, 0.0


def _print_header(arguments: argparse.Namespace, config_hash: str, friction: float) -> None:
    """Print the run's provenance banner."""
    print(f"scenario      {arguments.scenario} -- {SCENARIOS[arguments.scenario]}")
    print(f"environment   {arguments.environment}")
    print(f"config hash   {config_hash}")
    print(f"road friction {friction}")
    print()
    print(
        "  tick  verdict  STAT PHYS DETR  fsm       TI    envelope   "
        "issued (throttle, brake, steer)"
    )
    print("  " + "-" * 88)


def _publish_all_modalities(
    built: AssembledPipeline[JsonValue],
    clock: ManualClock,
    vehicle: _Vehicle,
    noise: random.Random,
) -> None:
    """Publish one reading per modality.

    Every modality, every tick. The Runtime Context Signature is
    reliability-weighted, so a driver publishing a single stream makes every
    context look like a four-sensor failure -- no certified profile matches, and
    bounded safe exploration engages on open road as readily as in a tunnel.
    That is the signature working correctly on a driver that was lying to it.
    """
    reading: JsonValue = {
        "v": vehicle.speed + noise.gauss(0.0, 0.05),
        "a": vehicle.lateral_acceleration + noise.gauss(0.0, 0.05),
    }
    for modality in SensorModality:
        built.sensor_bus.publish(
            SensorSample(
                modality=modality,
                observed_at=clock.now(),
                quality=Probability(0.95),
                payload=reading,
            )
        )


def _print_tick(index: int, outcome: object, *, exploring: bool) -> None:
    """Print one tick's line: gates, posture, envelope, and what was issued."""
    record = outcome.record  # type: ignore[attr-defined]
    verdicts = {
        gate_verdict.gate.value: gate_verdict.verdict.value
        for gate_verdict in (record.safety_verdict.gate_verdicts if record.safety_verdict else ())
    }
    marks = " ".join(
        "PASS" if verdicts.get(gate) == "PASS" else "VETO"
        for gate in ("STATISTICAL", "PHYSICAL", "DETERMINISTIC")
    )
    issued = outcome.issued  # type: ignore[attr-defined]
    command = (
        ", ".join(f"{value:6.3f}" for value in issued.command.values) if issued else "  -- none --"
    )
    trust = f"{float(record.trust.trust_index):.2f}" if record.trust else " -- "
    state = record.failsafe.state.value if record.failsafe else "-"
    verdict = outcome.verdict.value  # type: ignore[attr-defined]
    envelope = "EXPLORE" if exploring else "nominal"
    print(f"  {index:4d}  {verdict:7}  {marks}  {state:9} {trust}  {envelope:9}  {command}")


def _cold_path(settings: AstraSettings, where: tuple[float, float]) -> ColdPathContext:
    """Build the cold-path context for one stretch of road.

    Visibility and road complexity are *externally supplied*: nothing in the
    state vector carries fog density or road geometry, so the scenario states
    what it authored rather than the pipeline pretending to observe it.
    """
    return ColdPathContext(
        period_ticks=ARBITRATION_PERIOD_TICKS,
        trust_threshold=settings.arbitration.trust_threshold_tau,
        divergence_limit=settings.arbitration.divergence_limit_delta,
        platform="synthetic-prototype",
        legal_speed_limit=settings.shield.legal_speed_limit,
        visibility=Probability(where[0]),
        traffic_dynamicity=Probability(TRAFFIC_DYNAMICITY),
        road_complexity=Probability(where[1]),
    )


def _print_footer(issued: int, ticks: int, log: Path) -> None:
    """Print the run summary and the caveat that travels with it."""
    print()
    print(f"  ticks issued  {issued} of {ticks}")
    print(f"  audit log     {log}")
    print()
    print("  This run used KinematicPlaceholderPolicy, not a trained PPO policy.")
    print("  It shows the pipeline composing; it shows nothing about how ASTRA")
    print("  governs a learned controller. See docs/PROJECT_STATE_AND_ROADMAP.md.")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the demo.

    Args:
        argv: Argument vector, defaulting to ``sys.argv[1:]``.

    Returns:
        ``0`` on a completed run, ``2`` if the twin checkpoint is missing.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), default="nominal")
    parser.add_argument("--ticks", type=int, default=24)
    parser.add_argument("--environment", default="simulation")
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--out", type=Path, default=Path("var/demo"))
    arguments = parser.parse_args(argv)

    if not arguments.checkpoint.exists():
        print(f"no trained twin at {arguments.checkpoint}")
        print("train one first:")
        print(f"    python training/train_twin.py --out {arguments.checkpoint}")
        return 2
    if not arguments.corpus.exists():
        print(f"no calibration corpus at {arguments.corpus}")
        print("generate one first:")
        print(f"    python training/generate_calibration.py --out {arguments.corpus}")
        return 2

    resolved = load_settings(environment=arguments.environment, include_environment_variables=False)
    settings = resolved.settings
    friction = 0.12 if arguments.scenario == "ice" else 0.85
    clock = ManualClock(Instant(0, Timeline.MANUAL))
    noise = random.Random(11)
    run = RunId("run-demopipeline1")

    sink = JsonlAuditSink(run=run, directory=arguments.out, fsync_each_record=False)
    built: AssembledPipeline[JsonValue] = assemble_pipeline(
        run=run,
        config_hash=resolved.hash,
        settings=settings,
        clock=clock,
        extractor=_Extractor(friction),
        audit_sink=sink,
        initial_speed=settings.shield.legal_speed_limit,
        twin_checkpoint=arguments.checkpoint,
        corpus=CalibrationCorpus.read(arguments.corpus),
        cold_path=(_cold_path(settings, OPEN_ROAD) if arguments.scenario == "tunnel" else None),
    )

    period = Seconds(1.0 / settings.estimation.fast_rate_hz)
    cruise = float(settings.shield.legal_speed_limit) * 0.75
    vehicle = _Vehicle(cruise)

    _print_header(arguments, resolved.hash, friction)

    issued_count = 0
    for index in range(arguments.ticks):
        speed, lateral = _profile(arguments.scenario, index, cruise)
        vehicle.step(speed=speed, lateral_acceleration=lateral)
        _publish_all_modalities(built, clock, vehicle, noise)
        if arguments.scenario == "tunnel":
            inside = TUNNEL_ENTRY <= index < TUNNEL_EXIT
            built.pipeline.enter_context(
                _cold_path(settings, INSIDE_TUNNEL if inside else OPEN_ROAD)
            )
        outcome = built.pipeline.tick(TickId(index))
        record = outcome.record
        if record.fast_state is not None:
            built.fallback.observe(record.fast_state)
        issued_count += outcome.was_issued

        _print_tick(index, outcome, exploring=built.pipeline.is_exploring)
        clock.advance(period)

    sink.flush()
    _print_footer(issued_count, arguments.ticks, sink.path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
