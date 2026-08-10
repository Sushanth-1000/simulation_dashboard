"""What does each gate catch? One injected fault at a time, against a control.

Why this exists
----------------
Every number this project has published says the machinery **runs**: a hundred
thousand ticks of stable driving, a bounded resident set, a flat latency
profile, a veto rate near zero. Not one of them says what any gate **catches**,
and that is the product claim. Section D of ``docs/CREDIBILITY_MATRIX.md`` --
gate efficacy -- had one row before this script, and D-0 explains why: nothing
in the synthetic plant is out-of-distribution in the sense L6 is calibrated
for, so no miss rate can be computed from nominal driving no matter how much of
it is run.

A fault with **known ground truth** is what changes that. :mod:`training.faults`
provides it; this script drives it.

What the study is, in one line
-------------------------------
For each scenario: the same seed, the same policy, the same plant, one injected
fault, and a clean control run beside it. Report what the vehicle did and what
Core-B said about it, side by side.

The control run is not optional and is not a formality. A veto count under fault
means nothing without the veto count without it -- the startup transient alone
produces three, and a study that reported "3 vetoes under an IMU dropout"
without the control would have reported the transient as a detection.

What this measures, and what it does not
-----------------------------------------
It measures whether Core-B's *verdicts* change when a sensor lies. It does not
measure a false-negative rate, and no run of this script ever will: a rate needs
a population of faults drawn from something, and these five are chosen by hand
to defeat five named defences. What it produces is the qualitative half --
*does anything fire at all* -- which is the half that was missing, and which
turns out to be the more interesting one.

Run it with::

    uv run python -m benchmarks.fault_study
    uv run python -m benchmarks.fault_study --ticks 2000 --open-at 1000

Invoked as a module, not a path: it imports ``training``, which lives at the
repository root rather than in ``src``.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from astra.layers.l4_proposer.learned import LearnedPolicy
from benchmarks.detectors import evaluate
from training.closed_loop import CHANNEL_SIGMAS, CORPUS, TWIN, TickSample, drive_closed_loop
from training.faults import (
    FaultChannel,
    FaultInjector,
    FaultSpec,
    bias,
    drift,
    dropout,
    noise_burst,
    stuck_at,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

_DEFAULT_TICKS = 400
_DEFAULT_OPEN_AT = 200
_DEFAULT_SEED = 20260809
_DEFAULT_POLICY = Path("var/policy/synthetic.pt")
_DEFAULT_OUTPUT = Path("var/faults")

_BIAS_METRES = 1.0
_DRIFT_METRES = 2.0
_SPEED_BIAS_MPS = 3.0
_NOISE_MULTIPLIER = 25.0


@dataclass(frozen=True, slots=True)
class Scenario:
    """One fault, and the sentence it is meant to test.

    Attributes:
        name: Short identifier, used for the artefact directory.
        defence: The defence this fault is chosen to defeat, in one clause. The
            field exists so that a scenario cannot be added without saying what
            question it answers -- a study that accretes faults for variety
            reports coverage it does not have.
        build: Returns the specifications, given the window.
    """

    name: str
    defence: str
    build: Callable[[int, int], tuple[FaultSpec, ...]]


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        "imu_dropout",
        "the 50 ms staleness rule -- the one defence built for exactly this",
        lambda first, last: (dropout(first_tick=first, last_tick=last),),
    ),
    Scenario(
        "position_bias",
        "the UKF innovation sequence: fresh, well-formed and confidently wrong",
        lambda first, last: (
            bias(FaultChannel.POSITION_Y, first_tick=first, last_tick=last, offset=_BIAS_METRES),
        ),
    ),
    Scenario(
        "position_drift",
        "any per-tick threshold: no single step is anomalous",
        lambda first, last: (
            drift(FaultChannel.POSITION_Y, first_tick=first, last_tick=last, final=_DRIFT_METRES),
        ),
    ),
    Scenario(
        "speed_stuck",
        "staleness again, from the other side: the reading never goes stale",
        lambda first, last: (stuck_at(FaultChannel.SPEED, first_tick=first, last_tick=last),),
    ),
    Scenario(
        "speed_bias",
        "L7a's speed bound, which reads the estimate the fault has captured",
        lambda first, last: (
            bias(FaultChannel.SPEED, first_tick=first, last_tick=last, offset=_SPEED_BIAS_MPS),
        ),
    ),
    Scenario(
        "lateral_noise",
        "the Trust Index, which reads normalised innovations",
        lambda first, last: (
            noise_burst(
                FaultChannel.LATERAL_ACCELERATION,
                first_tick=first,
                last_tick=last,
                sigma_multiplier=_NOISE_MULTIPLIER,
            ),
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class Outcome:
    """What one run produced, reduced to what the comparison needs."""

    name: str
    final_deviation_m: float
    max_deviation_m: float
    max_estimator_error_m: float
    vetoed: int
    reasons: dict[str, int]
    failsafe_states: dict[str, int]
    issued: int
    ticks: int
    faulted_ticks: int
    peak_injected_error: float | None
    detections: tuple[object, ...] = ()

    def to_payload(self) -> dict[str, object]:
        """Return a JSON-serialisable view."""
        return {
            "name": self.name,
            "final_deviation_m": self.final_deviation_m,
            "max_deviation_m": self.max_deviation_m,
            "max_estimator_error_m": self.max_estimator_error_m,
            "vetoed": self.vetoed,
            "reasons": self.reasons,
            "failsafe_states": self.failsafe_states,
            "issued": self.issued,
            "ticks": self.ticks,
            "faulted_ticks": self.faulted_ticks,
            "peak_injected_error": self.peak_injected_error,
            "detections": [
                {
                    "detector": d.detector,
                    "fired_at": d.fired_at,
                    "latency_ticks": d.latency_ticks,
                    "fired_ticks": d.fired_ticks,
                    "false_alarm": d.false_alarm,
                }
                for d in self.detections  # type: ignore[attr-defined]
            ],
        }


def _measure(
    name: str,
    samples: Sequence[TickSample],
    result: object,
    *,
    opened_at: int,
    faulted: bool,
) -> Outcome:
    """Reduce one run to the figures the comparison is made on."""
    errors = [
        abs(float(s.record.fast_state.position_y) - s.lane_deviation_m)
        for s in samples[opened_at:]
        if s.record.fast_state is not None
    ]
    states: dict[str, int] = {}
    for sample in samples:
        if sample.record.failsafe is not None:
            key = sample.record.failsafe.state.value
            states[key] = states.get(key, 0) + 1
    peaks = [
        episode.peak_absolute_error
        for episode in result.fault_episodes  # type: ignore[attr-defined]
        if episode.peak_absolute_error is not None
    ]
    detections = evaluate(
        [s.record for s in samples],
        fault_active=[s.fault_active for s in samples],
        opened_at=opened_at if faulted else None,
    )
    return Outcome(
        name=name,
        final_deviation_m=result.final_absolute_deviation_m,  # type: ignore[attr-defined]
        max_deviation_m=max(abs(s.lane_deviation_m) for s in samples),
        max_estimator_error_m=max(errors) if errors else float("nan"),
        vetoed=result.vetoed,  # type: ignore[attr-defined]
        reasons=dict(result.reasons),  # type: ignore[attr-defined]
        failsafe_states=states,
        issued=result.issued,  # type: ignore[attr-defined]
        ticks=result.ticks,  # type: ignore[attr-defined]
        faulted_ticks=result.faulted_ticks,  # type: ignore[attr-defined]
        peak_injected_error=max(peaks) if peaks else None,
        detections=detections,
    )


def run(*, ticks: int, open_at: int, seed: int, policy_path: Path, output: Path) -> list[Outcome]:
    """Run the control and every scenario, and return their outcomes.

    Args:
        ticks: How many control ticks per run.
        open_at: The tick each fault opens on. It closes at the last tick.
        seed: The run seed, shared by every arm so they differ by the fault.
        policy_path: The trained proposer.
        output: Where to write the summary.

    Returns:
        The control first, then one outcome per scenario.
    """
    output.mkdir(parents=True, exist_ok=True)

    def drive(name: str, specs: tuple[FaultSpec, ...] | None) -> Outcome:
        samples: list[TickSample] = []
        injector = None if specs is None else FaultInjector(specs, seed=seed, sigmas=CHANNEL_SIGMAS)
        result = drive_closed_loop(
            policy=LearnedPolicy.load(policy_path),
            ticks=ticks,
            seed=seed,
            observer=samples.append,
            fault=injector,
        )
        return _measure(name, samples, result, opened_at=open_at, faulted=specs is not None)

    outcomes = [drive("control", None)]
    for scenario in SCENARIOS:
        print(f"  running {scenario.name} ...")
        outcomes.append(drive(scenario.name, scenario.build(open_at, ticks - 1)))

    (output / "summary.json").write_text(
        json.dumps(
            {
                "ticks": ticks,
                "open_at": open_at,
                "seed": seed,
                "scenarios": {s.name: s.defence for s in SCENARIOS},
                "outcomes": [outcome.to_payload() for outcome in outcomes],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return outcomes


def render(outcomes: Sequence[Outcome]) -> list[str]:
    """Return the report, as lines."""
    control = outcomes[0]
    lines = [
        "",
        (
            f"  {'scenario':<16} {'final |dev|':>12} {'max est err':>12} "
            f"{'vetoes':>7} {'not NOMINAL':>12} {'issued':>10}"
        ),
        f"  {'-' * 16} {'-' * 12} {'-' * 12} {'-' * 7} {'-' * 12} {'-' * 10}",
    ]
    for outcome in outcomes:
        degraded = sum(
            count for state, count in outcome.failsafe_states.items() if state != "NOMINAL"
        )
        lines.append(
            f"  {outcome.name:<16} {outcome.final_deviation_m:>10.3f} m "
            f"{outcome.max_estimator_error_m:>10.3f} m {outcome.vetoed:>7} "
            f"{degraded:>12} {outcome.issued:>6}/{outcome.ticks}"
        )
    lines.append("")
    lines.append(f"  control vetoes: {control.vetoed} {control.reasons}")
    lines.append("")
    lines.append("  A scenario whose veto count and reason codes equal the control's")
    lines.append("  was not detected, however far the vehicle went.")
    lines.append("")
    lines.append("  Shadow detectors -- read the record, change no verdict (P2.7):")
    lines.append("")
    names = [d.detector for d in control.detections]  # type: ignore[attr-defined]
    header = f"  {'scenario':<16}" + "".join(f"{n:>16}" for n in names)
    lines.append(header)
    lines.append(f"  {'-' * 16}" + "".join(f"{'-' * 15:>16}" for _ in names))
    for outcome in outcomes:
        cells = []
        for d in outcome.detections:  # type: ignore[attr-defined]
            if d.fired_at is None:
                cells.append(f"{'silent':>16}")
            elif d.latency_ticks is None:
                cells.append(f"{'FALSE ALARM':>16}")
            else:
                cells.append(f"{f'+{d.latency_ticks} ticks':>16}")
        lines.append(f"  {outcome.name:<16}" + "".join(cells))
    lines.append("")
    lines.append("  'silent' means the signal did not move at all -- not that a")
    lines.append("  threshold was set too high. That is the finding, not the gap.")
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    """Run the study and print the table.

    Args:
        argv: Command-line arguments, or ``None`` for ``sys.argv``.

    Returns:
        Process exit status. Zero unless an input artefact is missing --
        **not** whether anything was detected, because a study that failed when
        the answer was uncomfortable would be a study nobody could trust.
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

    outcomes = run(
        ticks=arguments.ticks,
        open_at=arguments.open_at,
        seed=arguments.seed,
        policy_path=arguments.policy,
        output=arguments.output,
    )
    for line in render(outcomes):
        print(line)
    print(f"\n  summary: {arguments.output / 'summary.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
