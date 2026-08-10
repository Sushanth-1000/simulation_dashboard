"""What would ADR-0020's estimator learn, if anything read it?

The rule this obeys
--------------------
**No feedback loop gets authority until it has run with none.** That convention
exists because two loops were measured in shadow and both broke the gate they
fed: FB2's network form would have collapsed the non-conformity score 40% in a
context where nothing changed (E-39), and FB3 would have pinned the veto rate to
epsilon by construction (E-40). Neither would have shown up as an error.

ADR-0020 replaces FB2's network with an estimator of the platform's control
effectiveness ``B``, on the reasoning that a target of *measured physics* cannot
drift toward the proposer the way a target of *the proposer's commands* must.
That reasoning is sound and it is not evidence. This script is the evidence.

What is being risked, stated before it is measured
----------------------------------------------------
``B`` is estimated as ``a_lat / steer`` from executed outcomes. The steering
value is the command, which is trustworthy -- the system knows what it sent. The
lateral acceleration is a **sensor reading**, and OD-9 established that sensor
readings are exactly what this architecture cannot currently tell the truth of.

So the failure mode to look for is specific: **under a fault that corrupts
lateral acceleration, does the estimate move?** If it does, wiring this loop
would let a sensor fault rewrite the platform constant that the twin, L7b and
the command projector all share -- turning a single corrupted channel into a
systematic error in the physics reference. That would be a worse defect than the
one ADR-0020 fixes, and the only way to find out before it is wired is to run it
where nothing reads it.

The tick timeline, written down because it caused four errors in a row
------------------------------------------------------------------------
Every quantity here is lateral acceleration, and the three available sources sit
at different points in the tick. Getting the pairing wrong reads the
effectiveness 12-18% low and looks entirely plausible while doing it -- which is
what happened to the earlier ADR-0020 probe (trap 5 in the 9 August handover),
and then three more times while writing this file.

``drive_closed_loop`` does, per tick ``t``::

    publish(plant state)   <- reflects the command issued at t-1
    pipeline.tick()        <- issues command_t, estimates from that publish
    plant.step(command_t)  <- a_lat becomes B * steer_t, instantaneously
    observer(sample_t)

So, for the command issued at tick ``t``:

- ``sample_t.lateral_acceleration_mps2`` -- the plant's truth *after* the step.
  Pair with ``steer_t``, **same tick**.
- ``sample_{t+1}.measured_lateral_acceleration_mps2`` -- what the sensors
  reported. Pair with ``steer_t``, **next tick**.
- ``sample_{t+1}.record.fast_state`` -- what the filter concluded. Also **next
  tick**, for the same reason.

The plant applies steering with no actuator lag -- ``environment.py`` says so in
as many words -- so there is no dynamics term to model. The offsets above are
purely about where in the loop each number is read.

How the shadow works, and the mistake it started with
------------------------------------------------------
The estimator is fed the issued command, **the lateral acceleration the system
believes it achieved**, and the Mondrian class L3 assigned. Nothing in the
pipeline reads the result and no verdict changes: the estimator is constructed
here, in the benchmark, and never handed to anything.

*Believes* is load-bearing, and the first version of this script got it wrong.
It fed the estimator ``TickSample.lateral_acceleration_mps2`` -- the **plant's
truth**, read straight out of the simulator. Every scenario then reported the
configured value to three decimals with zero drift, which looked like a clean
result and was an artefact: the faults corrupt *sensors*, and reading truth
bypasses every sensor in the system. A deployed estimator has no such channel.

It now reads ``record.fast_state``, the filtered estimate -- which is what an
adapter on a real vehicle would actually have, and which is downstream of every
fault this study injects.

Run it with::

    uv run python -m benchmarks.effectiveness
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from astra.config.loader import load_settings
from astra.kernel.constants import FAST_STATE_FIELDS
from astra.kernel.enums import ContextClass
from astra.layers.l4_proposer.learned import LearnedPolicy
from astra.runtime.assembly import ControlEffectivenessEstimator
from benchmarks.fault_study import SCENARIOS
from training.closed_loop import (
    CHANNEL_SIGMAS,
    CORPUS,
    ENVIRONMENT,
    TWIN,
    TickSample,
    drive_closed_loop,
)
from training.environment import EnvironmentSpec
from training.faults import FaultInjector

if TYPE_CHECKING:
    from collections.abc import Sequence

    from training.faults import FaultSpec

_DEFAULT_TICKS = 400
_DEFAULT_OPEN_AT = 200
_DEFAULT_SEED = 20260809
_DEFAULT_POLICY = Path("var/policy/synthetic.pt")
_DEFAULT_OUTPUT = Path("var/effectiveness")

STEERING_INDEX = 2
_LATERAL_INDEX = FAST_STATE_FIELDS.index("lateral_acceleration")

PLATFORM_SHIFTS: tuple[float, ...] = (0.8, 1.2)
"""Platforms whose true effectiveness differs from the configured value.

A worn tyre, a wet road or a load shift *is* a change in ``B``, and tracking
one is the entire purpose of ADR-0020. The fault scenarios above cannot
demonstrate that: the plant's ``B`` is constant in all of them, so "the
estimate did not move" is consistent both with a working estimator and with
one that does nothing at all.

These runs move the plant instead. The configured value stays 140.0 and is
wrong by 20%; a working estimator recovers the platform it is actually
driving, and a broken one keeps reporting the configuration.
"""
SATURATION_LIMIT = 3.0
"""The plant clamps lateral acceleration here, so beyond it a sample says nothing about B."""


@dataclass(frozen=True, slots=True)
class Reading:
    """What the estimator would have concluded on one run.

    Attributes:
        scenario: The fault, or ``"control"``.
        configured: The value in configuration -- what the twin uses today.
        before: The estimate at the tick the fault opens, from the filtered
            estimate -- where ADR-0020 as written would read it.
        after: The same at the end of the run.
        from_measurement: What the estimator concludes when fed the **raw
            sensor reading** instead. The contrast between this and
            :attr:`after` is the finding.
        true_effectiveness: The plant's actual ``B`` for this run.
        samples: Usable samples accumulated, summed across contexts.
        drift_percent: How far ``after`` moved from ``configured``. **The
            number that decides whether this loop may be wired**: a sensor fault
            must not be able to rewrite a platform constant.
    """

    scenario: str
    configured: float
    before: float
    after: float
    samples: int
    drift_percent: float
    from_measurement: float
    true_effectiveness: float

    def to_payload(self) -> dict[str, object]:
        """Return a JSON-serialisable view."""
        return {
            "scenario": self.scenario,
            "configured": self.configured,
            "before": self.before,
            "after": self.after,
            "samples": self.samples,
            "drift_percent": self.drift_percent,
            "from_measurement": self.from_measurement,
            "true_effectiveness": self.true_effectiveness,
        }


def _shadow(
    samples: Sequence[TickSample],
    *,
    configured: float,
    open_at: int,
    scenario: str,
    true_effectiveness: float,
) -> Reading:
    """Feed the estimator from a completed run and report what it would have said."""

    def build() -> ControlEffectivenessEstimator:
        return ControlEffectivenessEstimator(
            steering_index=STEERING_INDEX,
            configured=configured,
            saturation_limit=SATURATION_LIMIT,
        )

    estimator = build()
    from_sensor = build()
    before = configured
    # Paired across the tick boundary, and this is the second thing this script
    # got wrong. `record.fast_state` is the estimate the pipeline held *before*
    # it issued the tick's command, so pairing them reads each command against
    # the acceleration the *previous* one produced. On a clean run that
    # mis-pairing alone read the effectiveness 12% low -- which is the same trap
    # the earlier ADR-0020 probe fell into, where a 17% error turned out to be a
    # property of the probe rather than of the estimator.
    for index, sample in enumerate(samples[:-1]):
        if index == open_at:
            before = _best(estimator, samples, index)
        issued = sample.record.issued
        trust = sample.record.trust
        achieved = samples[index + 1].record.fast_state
        if issued is None or trust is None or achieved is None:
            continue
        estimator.observe(
            command=issued.command.values,
            # The estimate, not the plant's truth. An adapter on a real vehicle
            # has no channel to the truth, and reading one here would make every
            # sensor fault invisible to this measurement -- which is exactly
            # what the first version of this script did.
            lateral_acceleration=float(achieved.mean[_LATERAL_INDEX]),
            context=trust.context_class,
        )
        measured = samples[index + 1].measured_lateral_acceleration_mps2
        if measured is not None:
            from_sensor.observe(
                command=issued.command.values,
                lateral_acceleration=measured,
                context=trust.context_class,
            )
    after = _best(estimator, samples, len(samples) - 1)
    total = sum(estimator.sample_count(context) for context in ContextClass)
    return Reading(
        from_measurement=_best(from_sensor, samples, len(samples) - 1),
        true_effectiveness=true_effectiveness,
        scenario=scenario,
        configured=configured,
        before=before,
        after=after,
        samples=total,
        drift_percent=100.0 * (after - configured) / configured,
    )


def _best(
    estimator: ControlEffectivenessEstimator, samples: Sequence[TickSample], index: int
) -> float:
    """Return the estimate for whichever context the run is currently in."""
    trust = samples[index].record.trust
    context = ContextClass.UNCLASSIFIED if trust is None else trust.context_class
    return estimator.estimate(context)


def run(*, ticks: int, open_at: int, seed: int, policy_path: Path, output: Path) -> list[Reading]:
    """Run the control and every fault scenario, shadowing the estimator on each.

    Args:
        ticks: Control ticks per run.
        open_at: The tick each fault opens on.
        seed: Shared run seed.
        policy_path: The trained proposer.
        output: Where to write the summary.

    Returns:
        One reading per scenario, control first.
    """
    output.mkdir(parents=True, exist_ok=True)
    resolved = load_settings(environment=ENVIRONMENT, include_environment_variables=False)
    configured = float(resolved.settings.twin.control_effectiveness[STEERING_INDEX])

    cases: list[tuple[str, Sequence[FaultSpec] | None]] = [("control", None)]
    cases += [(s.name, s.build(open_at, ticks - 1)) for s in SCENARIOS]

    readings: list[Reading] = []
    for scenario, specs in cases:
        print(f"  {scenario} ...")
        observed: list[TickSample] = []
        injector = None if specs is None else FaultInjector(specs, seed=seed, sigmas=CHANNEL_SIGMAS)
        drive_closed_loop(
            policy=LearnedPolicy.load(policy_path),
            ticks=ticks,
            seed=seed,
            observer=observed.append,
            fault=injector,
        )
        readings.append(
            _shadow(
                observed,
                configured=configured,
                open_at=open_at,
                scenario=scenario,
                true_effectiveness=configured,
            )
        )

    for multiplier in PLATFORM_SHIFTS:
        true_b = configured * multiplier
        print(f"  platform B={true_b:.1f} ...")
        observed = []
        drive_closed_loop(
            policy=LearnedPolicy.load(policy_path),
            ticks=ticks,
            seed=seed,
            spec=EnvironmentSpec(steer_effectiveness=true_b),
            observer=observed.append,
        )
        reading = _shadow(
            observed,
            configured=configured,
            open_at=open_at,
            scenario=f"platform B={true_b:.0f}",
            true_effectiveness=true_b,
        )
        readings.append(reading)

    (output / "summary.json").write_text(
        json.dumps(
            {
                "ticks": ticks,
                "open_at": open_at,
                "seed": seed,
                "readings": [reading.to_payload() for reading in readings],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return readings


def render(readings: Sequence[Reading]) -> list[str]:
    """Return the report, as lines."""
    configured = readings[0].configured
    lines = [
        "",
        f"  Configured control effectiveness: {configured:.3f}",
        "  Nothing reads any of the numbers below. That is the point.",
        "",
        (
            f"  {'scenario':<16} {'true B':>9} {'from estimate':>14} "
            f"{'from sensor':>13} {'samples':>9}"
        ),
        f"  {'-' * 16} {'-' * 9} {'-' * 14} {'-' * 13} {'-' * 9}",
    ]
    lines.extend(
        f"  {reading.scenario:<16} {reading.true_effectiveness:>9.1f} {reading.after:>14.3f} "
        f"{reading.from_measurement:>13.3f} {reading.samples:>9}"
        for reading in readings
    )
    lines += [
        "",
        "  `from estimate` is where ADR-0020 as written would read the value.",
        "  `from sensor` is the same estimator fed the raw reading instead.",
        "",
        "  Where the two disagree on a row whose true B is not 140, the loop as",
        "  specified is reporting the configuration back to itself.",
    ]
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    """Run the shadow measurement and print the table.

    Args:
        argv: Command-line arguments, or ``None`` for ``sys.argv``.

    Returns:
        Zero unless an input artefact is missing.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ticks", "-n", type=int, default=_DEFAULT_TICKS)
    parser.add_argument("--open-at", type=int, default=_DEFAULT_OPEN_AT)
    parser.add_argument("--seed", type=int, default=_DEFAULT_SEED)
    parser.add_argument("--policy", type=Path, default=_DEFAULT_POLICY)
    parser.add_argument("--output", "-o", type=Path, default=_DEFAULT_OUTPUT)
    arguments = parser.parse_args(argv)

    for artefact in (TWIN, CORPUS, arguments.policy):
        if not artefact.exists():
            print(f"missing {artefact}; see docs/EVIDENCE.md for how to regenerate it")
            return 1

    readings = run(
        ticks=arguments.ticks,
        open_at=arguments.open_at,
        seed=arguments.seed,
        policy_path=arguments.policy,
        output=arguments.output,
    )
    for line in render(readings):
        print(line)
    print(f"\n  summary: {arguments.output / 'summary.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
