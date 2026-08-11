"""Does bounded safe exploration survive a platform the twin was never fitted to?

The question, and why it is the sharpest one available
-------------------------------------------------------
The architecture's distinguishing sentence is that it does not halt outside its
certified envelope. Every other measurement in this pack tests behaviour *inside*
one. This script tests the sentence itself, by the cheapest honest means: change
the **plant** and leave everything else alone.

The twin, the calibration corpus and the policy are all fitted to one vehicle --
``EnvironmentSpec()``'s defaults, with ``B = 140`` rad-to-lateral-acceleration,
3.0 m/s^2 of throttle authority and 8.0 of brake. Give the pipeline a different
vehicle and the twin mispredicts by construction. L6 scores proposal against
twin and vetoes; L7b checks the same prediction against physics and vetoes; RCM
finds no certified profile matching the resulting context and declares
``SAFE_EXPLORATION``. That is the mechanism doing exactly what it is for.

What it found, on 10 August 2026
----------------------------------
Two defects, each hiding the other. Both reproduce from this script by checking
out the three source files at their pre-fix revision and re-running it -- which
is how the control-arm figures below were taken, at the same seed.

**OD-12 -- the vehicle did not continue.** L8 counted the same vetoes RCM had
already responded to, escalated NOMINAL -> DEGRADED -> LIMP -> HALT, and HALT is
terminal. Two of the five platforms reached it: **weak acceleration HALTed at
t398** after 520 exploring ticks and 352 vetoes, **weak brakes at t404** after
580 and 315. Both finished at **0.00 m/s** under an arbitrator still reporting
``SAFE_EXPLORATION``. One condition, two owners, and the terminal answer won.

**OD-13 -- it was not bounded.** Visible in the same control arm and only
because the run is instrumented for it: before halting, the weak-braking
platform reached **23.43 m/s** against the calibrated platform's 14.27, with
**zero** ticks marked ``SPEED_CAPPED``. ``exploration_envelope`` computed a
``speed_cap`` and ``restricted_space`` turned the envelope into narrowed
*channel* bounds, which limit throttle per tick and bound speed not at all. Had
OD-12 been fixed alone, the vehicle would have kept accelerating instead of
halting -- which is why the two are recorded as separate defects and fixed
together.

Both are closed. The cap now flows through the projector seam P2.1 built for the
fail-safe cap, and the counter freezes while exploration is engaged
(`ADR-0023 <../docs/adr/0023-the-ood-counter-freezes-during-bounded-exploration.md>`_).
After the fix, every platform finishes NOMINAL and moving, and the weak-braking
platform is held at **16.72 m/s across 105 SPEED_CAPPED ticks** -- half the
highway profile's 33.34 maximum, plus one tick of plant integration.

What this script is not
------------------------
It is **not** a claim that the vehicle drives *well* on an unfamiliar platform.
It measures three things and only three: a command issues on every tick, the
fail-safe posture stays out of HALT, and the realised speed stays under the
envelope's cap. Driving quality on a platform nothing was fitted to needs a real
simulator and is Phase 7.

Usage::

    uv run python -m benchmarks.platform_transfer
    uv run python -m benchmarks.platform_transfer --ticks 600
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from astra.config.loader import load_settings
from astra.contracts.actuation import CommandOrigin
from astra.kernel.enums import ArbitrationOutcome, FailSafeState
from astra.kernel.units import Probability
from astra.layers.l4_proposer.learned import LearnedPolicy
from astra.runtime.pipeline import ColdPathContext
from training.closed_loop import CORPUS, ENVIRONMENT, TWIN, TickSample, drive_closed_loop
from training.environment import EnvironmentSpec

_DEFAULT_TICKS = 600
_DEFAULT_SEED = 20260810
_DEFAULT_POLICY = Path("var/policy/synthetic.pt")
_DEFAULT_OUTPUT = Path("var/platform")

#: The context the cold path evaluates against. Deliberately *certified* --
#: a tunnel would make exploration engage for a reason that has nothing to do
#: with the platform, and the whole point here is that the **platform** is what
#: no profile covers.
CERTIFIED_CONTEXT = (0.85, 0.7, 0.7)

#: Arbitration period. Short enough that a 600-tick run re-evaluates often.
_PERIOD_TICKS = 20


@dataclass(frozen=True, slots=True)
class Platform:
    """A vehicle to drive the pipeline at.

    Attributes:
        name: How the row is labelled.
        spec: The plant. ``EnvironmentSpec()`` is the one everything was fitted
            to and is the control arm.
        note: Why this platform is interesting, for the rendered table.
    """

    name: str
    spec: EnvironmentSpec
    note: str


#: The control first, then four ways of being a different vehicle. Each varies
#: exactly one physical constant, so a row that misbehaves names its own cause.
PLATFORMS: tuple[Platform, ...] = (
    Platform("calibrated", EnvironmentSpec(), "the platform the twin was fitted to"),
    Platform(
        "weak acceleration",
        replace(EnvironmentSpec(), acceleration_authority_mps2=1.5),
        "half the throttle authority",
    ),
    Platform(
        "weak brakes",
        replace(EnvironmentSpec(), braking_authority_mps2=3.0),
        "8.0 -> 3.0 m/s^2 of brake",
    ),
    Platform(
        "worn tyres",
        replace(EnvironmentSpec(), steer_effectiveness=112.0),
        "B 140 -> 112, 20% less bite",
    ),
    Platform(
        "sharp steer",
        replace(EnvironmentSpec(), steer_effectiveness=182.0),
        "B 140 -> 182, 30% more",
    ),
)


@dataclass(slots=True)
class Outcome:
    """What one platform did.

    Attributes:
        platform: Which row.
        ticks: How many ticks ran.
        issued: How many of them issued a command. Reported for completeness
            and **not** the pass criterion: a HALTed vehicle still issues, it
            issues a stop. ``final_speed_mps`` and ``first_halt_tick`` are what
            distinguish continuing from stopping.
        exploring: Ticks whose arbitration outcome was ``SAFE_EXPLORATION``.
        vetoed: Ticks whose aggregate verdict was blocking.
        max_speed_mps: The largest true speed the plant reached.
        final_speed_mps: Speed on the last tick.
        final_deviation_m: ``|lane deviation|`` on the last tick.
        worst_failsafe: The most escalated posture reached, by name.
        first_halt_tick: The first tick at which the posture was HALT, or
            ``None``. **The OD-12 signal.**
        speed_capped: Ticks on which the issued command carried the
            ``SPEED_CAPPED`` reason -- the cap altering a command rather than
            merely being computed. **The OD-13 signal.**
    """

    platform: str
    ticks: int
    issued: int
    exploring: int
    vetoed: int
    max_speed_mps: float
    final_speed_mps: float
    final_deviation_m: float
    worst_failsafe: str
    first_halt_tick: int | None
    speed_capped: int


_ESCALATION = (
    FailSafeState.NOMINAL,
    FailSafeState.DEGRADED,
    FailSafeState.LIMP,
    FailSafeState.HALT,
)


def drive(*, platform: Platform, ticks: int, seed: int, policy: LearnedPolicy | None) -> Outcome:
    """Run one platform and reduce the tick stream to an outcome.

    Args:
        platform: The vehicle.
        ticks: How many control ticks.
        seed: Plant and sensor-noise seed.
        policy: The proposer, or ``None`` for the placeholder.

    Returns:
        What the run did.
    """
    settings = load_settings(environment=ENVIRONMENT, include_environment_variables=False).settings
    cold = ColdPathContext(
        period_ticks=_PERIOD_TICKS,
        trust_threshold=settings.arbitration.trust_threshold_tau,
        divergence_limit=settings.arbitration.divergence_limit_delta,
        platform="synthetic-prototype",
        legal_speed_limit=settings.shield.legal_speed_limit,
        visibility=Probability(CERTIFIED_CONTEXT[0]),
        traffic_dynamicity=Probability(CERTIFIED_CONTEXT[1]),
        road_complexity=Probability(CERTIFIED_CONTEXT[2]),
    )

    exploring = 0
    capped = 0
    worst = 0
    first_halt: int | None = None
    peak_speed = 0.0

    def watch(sample: TickSample) -> None:
        nonlocal exploring, capped, worst, first_halt, peak_speed
        peak_speed = max(peak_speed, sample.speed_mps)
        arbitration = sample.record.arbitration
        if arbitration is not None and arbitration.outcome is ArbitrationOutcome.SAFE_EXPLORATION:
            exploring += 1
        failsafe = sample.record.failsafe
        if failsafe is not None:
            worst = max(worst, _ESCALATION.index(failsafe.state))
            if failsafe.state is FailSafeState.HALT and first_halt is None:
                first_halt = sample.tick
        issued = sample.record.issued
        if issued is not None and issued.origin is CommandOrigin.SPEED_CAPPED:
            capped += 1

    result = drive_closed_loop(
        policy=policy,
        ticks=ticks,
        seed=seed,
        spec=platform.spec,
        observer=watch,
        cold_path=cold,
    )

    return Outcome(
        platform=platform.name,
        ticks=result.ticks,
        issued=result.issued,
        exploring=exploring,
        vetoed=result.vetoed,
        max_speed_mps=peak_speed,
        final_speed_mps=result.final_speed_mps,
        final_deviation_m=result.final_absolute_deviation_m,
        worst_failsafe=_ESCALATION[worst].name,
        first_halt_tick=first_halt,
        speed_capped=capped,
    )


def render(outcomes: list[Outcome]) -> list[str]:
    """Return the table, as lines.

    Args:
        outcomes: One per platform, in ``PLATFORMS`` order.

    Returns:
        Lines to print.
    """
    lines = [
        "",
        "  platform           issued   explore   veto   max m/s  final  |dev| m   fail-safe  halt",
        "  " + "-" * 88,
    ]
    for outcome in outcomes:
        halt = "-" if outcome.first_halt_tick is None else f"t{outcome.first_halt_tick}"
        lines.append(
            f"  {outcome.platform:<17}"
            f"{outcome.issued:>4}/{outcome.ticks:<4}"
            f"{outcome.exploring:>8}"
            f"{outcome.vetoed:>7}"
            f"{outcome.max_speed_mps:>10.2f}"
            f"{outcome.final_speed_mps:>7.2f}"
            f"{outcome.final_deviation_m:>9.3f}"
            f"  {outcome.worst_failsafe:>10}"
            f"  {halt:>5}"
        )
    lines.extend(
        [
            "",
            "  A row passes only if the fail-safe posture stays out of HALT, the",
            "  vehicle is still moving at the end, and max m/s sits under the",
            "  exploration cap. Note that `issued` does *not* discriminate: a",
            "  HALTed vehicle still issues -- it issues a stop.",
            "",
            "  Pre-ADR-0023 at this seed: weak acceleration HALT t398 final 0.00,",
            "  weak brakes HALT t404 final 0.00 having first reached 23.43 m/s",
            "  with zero SPEED_CAPPED ticks.",
        ]
    )
    return lines


def run(*, ticks: int, seed: int, policy_path: Path, output: Path) -> list[Outcome]:
    """Drive every platform and write the summary.

    Args:
        ticks: Control ticks per platform.
        seed: Shared seed, so the platforms differ only in their physics.
        policy_path: The trained proposer checkpoint.
        output: Directory for ``summary.json``.

    Returns:
        One outcome per platform.
    """
    policy = LearnedPolicy.load(policy_path)
    outcomes = [
        drive(platform=platform, ticks=ticks, seed=seed, policy=policy) for platform in PLATFORMS
    ]

    output.mkdir(parents=True, exist_ok=True)
    (output / "summary.json").write_text(
        json.dumps(
            {
                "ticks": ticks,
                "seed": seed,
                "context": CERTIFIED_CONTEXT,
                "platforms": [
                    {
                        "name": platform.name,
                        "note": platform.note,
                        "steer_effectiveness": platform.spec.steer_effectiveness,
                        "acceleration_authority_mps2": platform.spec.acceleration_authority_mps2,
                        "braking_authority_mps2": platform.spec.braking_authority_mps2,
                    }
                    for platform in PLATFORMS
                ],
                "outcomes": [asdict(outcome) for outcome in outcomes],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return outcomes


def main(argv: list[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Command-line arguments, or ``None`` for ``sys.argv``.

    Returns:
        Zero unless an input artefact is missing, or a platform halted.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ticks", "-n", type=int, default=_DEFAULT_TICKS)
    parser.add_argument("--seed", type=int, default=_DEFAULT_SEED)
    parser.add_argument("--policy", type=Path, default=_DEFAULT_POLICY)
    parser.add_argument("--output", "-o", type=Path, default=_DEFAULT_OUTPUT)
    arguments = parser.parse_args(argv)

    for artefact in (TWIN, CORPUS, arguments.policy):
        if not artefact.exists():
            print(f"missing {artefact}; see docs/EVIDENCE.md for how to regenerate it")
            return 1

    outcomes = run(
        ticks=arguments.ticks,
        seed=arguments.seed,
        policy_path=arguments.policy,
        output=arguments.output,
    )
    for line in render(outcomes):
        print(line)
    print(f"\n  summary: {arguments.output / 'summary.json'}")

    halted = [outcome.platform for outcome in outcomes if outcome.first_halt_tick is not None]
    if halted:
        print(f"\n  HALTED: {', '.join(halted)} -- OD-12 has regressed")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
