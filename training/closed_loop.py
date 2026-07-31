"""Driving the real pipeline against the training plant, with the loop closed.

Why this exists
----------------
Every scenario written before this one drove the pipeline open-loop: the harness
published a fixed sensor payload each tick regardless of what the vehicle had
been commanded to do. That is fine for exercising the plumbing, and it silently
invalidates any measurement involving a gate that compares a proposal against
the current state.

Concretely: L7b vetoes when ``|a_proposed - a_current| / dt`` exceeds the jerk
limit. Under an open-loop harness reporting zero lateral acceleration forever,
``a_current`` is pinned at zero, so *every* non-zero proposal is a jerk
violation and the measured veto rate is an artefact of the harness. The first
learned policy measured that way scored a 100% veto rate. The number said
nothing about the policy.

Closing the loop means the plant integrates the command the pipeline actually
issued, and the sensors report the state that produced. Then a veto rate is a
statement about the proposer.

What is still synthetic
------------------------
The plant is :class:`~training.environment.SyntheticDrivingEnv` -- the same
kinematic model the UKF assumes and the twin was fitted to. So this measures
whether the learned policy is *physically admissible on the modelled platform*,
which is a real question with a real answer. It does not measure gate accuracy
under distribution shift, because there is no shift: one set of equations
generates the data and another fitted to the same equations judges it.
"""

from __future__ import annotations

import tempfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from astra.config.loader import load_settings
from astra.contracts.sensing import SensorSample
from astra.kernel.enums import SensorModality
from astra.kernel.identifiers import RunId, TickId
from astra.kernel.time import Instant, ManualClock, Timeline
from astra.kernel.units import Probability, Seconds
from astra.layers.l2_estimation.measurement import fast_measurement, slow_measurement
from astra.layers.l3_trust.corpus import CalibrationCorpus
from astra.observability.audit import JsonlAuditSink
from astra.runtime.assembly import AssembledPipeline, assemble_pipeline
from training.environment import EnvironmentSpec, SyntheticDrivingEnv

if TYPE_CHECKING:
    from astra.layers.l2_estimation.measurement import Measurement
    from astra.layers.l4_proposer.proposer import Policy

__all__ = ["ClosedLoopResult", "drive_closed_loop"]

TWIN = Path("var/twin/synthetic.pt")
CORPUS = Path("var/calibration/synthetic.json")

_SENSOR_QUALITY = Probability(0.95)
_SPEED_SIGMA = 0.01
_LATERAL_SIGMA = 0.04
_FRICTION_SIGMA = 4e-4
_FRICTION = 0.85


class _Extractor:
    """Turns the plant's published frame into fast and slow measurements."""

    def extract_fast(self, frame: object) -> Measurement | None:
        """Return the fast measurement for a frame, or ``None`` if IMU is absent.

        Args:
            frame: The fused sensor frame.

        Returns:
            Speed and lateral acceleration, or ``None``.
        """
        sample = frame.sample_for(SensorModality.IMU)  # type: ignore[attr-defined]
        if sample is None:
            return None
        payload = sample.payload
        return fast_measurement(
            [
                ("speed", float(payload["v"]), _SPEED_SIGMA),
                ("lateral_acceleration", float(payload["a"]), _LATERAL_SIGMA),
            ]
        )

    def extract_slow(self, frame: object) -> Measurement | None:
        """Return the slow measurement.

        Args:
            frame: The fused sensor frame, unused.

        Returns:
            The road friction coefficient.
        """
        del frame
        return slow_measurement([("road_friction_coefficient", _FRICTION, _FRICTION_SIGMA)])


@dataclass(slots=True)
class ClosedLoopResult:
    """What a closed-loop run produced.

    Attributes:
        ticks: How many control ticks ran.
        issued: Ticks on which a command reached the actuation sink. The
            headline availability number: ASTRA's claim is that this equals
            ``ticks`` even when the proposer is being vetoed.
        vetoed: Ticks on which Core-B's aggregate verdict was blocking.
        reasons: Veto counts by ``gate:reason_code``.
        peak_lateral_jerk_mps3: Largest single-tick lateral jerk the *proposals*
            demanded, whether or not they were issued.
        mean_absolute_deviation_m: Mean ``|lane deviation|`` the vehicle held.
    """

    ticks: int = 0
    issued: int = 0
    vetoed: int = 0
    reasons: Counter[str] = field(default_factory=Counter)
    peak_lateral_jerk_mps3: float = 0.0
    mean_absolute_deviation_m: float = 0.0

    @property
    def veto_rate(self) -> float:
        """Return the fraction of ticks Core-B blocked.

        A **diagnostic**. SI-6 permits logging it and forbids it reaching
        Core-A's objective; nothing in :mod:`training.environment` can read this
        type, and nothing tries.
        """
        return self.vetoed / self.ticks if self.ticks else 0.0


def drive_closed_loop(
    *,
    policy: Policy | None,
    ticks: int = 400,
    seed: int = 20260731,
    spec: EnvironmentSpec | None = None,
    directory: Path | None = None,
) -> ClosedLoopResult:
    """Run the pipeline against the plant, feeding issued commands back in.

    Args:
        policy: The proposer's policy, or ``None`` for the placeholder.
        ticks: How many control ticks to run.
        seed: Seed for the plant's initial condition.
        spec: The plant definition. Defaults to :class:`EnvironmentSpec`.
        directory: Where to write the audit log. A temporary directory by
            default.

    Returns:
        The run's outcome.
    """
    resolved = load_settings(environment="simulation", include_environment_variables=False)
    settings = resolved.settings
    plant = SyntheticDrivingEnv(spec or EnvironmentSpec())
    plant.reset(seed=seed)

    clock = ManualClock(Instant(0, Timeline.MANUAL))
    run = RunId("run-closedloop0001")
    sink = JsonlAuditSink(
        run=run,
        directory=directory or Path(tempfile.mkdtemp()),
        fsync_each_record=False,
    )
    built: AssembledPipeline[Any] = assemble_pipeline(
        run=run,
        config_hash=resolved.hash,
        settings=settings,
        clock=clock,
        extractor=_Extractor(),
        audit_sink=sink,
        initial_speed=settings.shield.legal_speed_limit,
        twin_checkpoint=TWIN,
        corpus=CalibrationCorpus.read(CORPUS),
        policy=policy,
    )

    period = Seconds(1.0 / settings.estimation.fast_rate_hz)
    result = ClosedLoopResult(ticks=ticks)
    lower = np.asarray(plant.spec_.channel_lower, dtype=np.float64)
    upper = np.asarray(plant.spec_.channel_upper, dtype=np.float64)
    previous_lateral = 0.0
    deviation_total = 0.0

    for index in range(ticks):
        speed = float(plant._state[2])  # noqa: SLF001 - the plant is the test fixture
        lateral = float(plant._state[4])  # noqa: SLF001
        for modality in SensorModality:
            built.sensor_bus.publish(
                SensorSample(
                    modality=modality,
                    observed_at=clock.now(),
                    quality=_SENSOR_QUALITY,
                    payload={"v": speed, "a": lateral},
                )
            )

        outcome = built.pipeline.tick(TickId(index))
        record = outcome.record
        if record.fast_state is not None:
            built.fallback.observe(record.fast_state)

        result.issued += int(outcome.was_issued)
        if record.proposal is not None:
            demanded = float(record.proposal.command.values[2]) * plant.spec_.steer_effectiveness
            result.peak_lateral_jerk_mps3 = max(
                result.peak_lateral_jerk_mps3,
                abs(demanded - previous_lateral) / float(period),
            )
        verdict = record.safety_verdict
        if verdict is not None and verdict.is_blocking:
            result.vetoed += 1
        for gate_verdict in verdict.gate_verdicts if verdict else ():
            if gate_verdict.verdict.is_blocking:
                result.reasons[f"{gate_verdict.gate.value}:{gate_verdict.reason_code}"] += 1

        # Close the loop: whatever L9 actually issued is what the plant applies.
        # A veto therefore changes the vehicle's trajectory, which is the whole
        # point and what an open-loop harness cannot show.
        if record.issued is not None:
            values = np.asarray(record.issued.command.values, dtype=np.float64)
            action = 2.0 * (values - lower) / (upper - lower) - 1.0
        else:
            action = np.array([0.0, 1.0, 0.0])
        plant.step(action.astype(np.float32))
        previous_lateral = float(plant._state[4])  # noqa: SLF001
        deviation_total += abs(float(plant._state[1]))  # noqa: SLF001
        clock.advance(period)

    sink.flush()
    sink.close()
    result.mean_absolute_deviation_m = deviation_total / ticks
    return result


def _report(label: str, result: ClosedLoopResult) -> None:
    """Print one run's outcome.

    Args:
        label: A name for the run.
        result: What it produced.
    """
    print(
        f"{label:14} issued {result.issued}/{result.ticks}  "
        f"veto rate {result.veto_rate:6.1%}  "
        f"|dev| {result.mean_absolute_deviation_m:.3f} m  "
        f"peak jerk {result.peak_lateral_jerk_mps3:8.1f} m/s^3"
    )
    print(f"{'':14} {dict(result.reasons) or 'no vetoes'}")


def main() -> int:
    """Compare the learned policy against the placeholder, closed-loop.

    Returns:
        Always ``0``; this is a report, not a gate.
    """
    from astra.layers.l4_proposer.learned import LearnedPolicy  # noqa: PLC0415

    checkpoint = Path("var/policy/synthetic.pt")
    _report("placeholder", drive_closed_loop(policy=None))
    if checkpoint.exists():
        _report("learned", drive_closed_loop(policy=LearnedPolicy.load(checkpoint)))
    else:
        print(f"no policy at {checkpoint}; train one with `python -m training.train_policy`")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
