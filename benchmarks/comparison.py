"""ASTRA against raw Core-A, same seed, same fault, side by side.

What P3.5 expected, and what it actually shows
------------------------------------------------
``PENDING.md`` calls this *"the single most persuasive artefact available"* and
describes the result as **"one keeps moving; one does not."**

That framing was written before anything had been injected. Now that something
has, it needs correcting, and the correction is the interesting part: under a
sensor fault, **both arms keep moving and both leave the corridor**, because
Core-B's gates read the same corrupted estimate the proposer reads (OD-9, E-48).
A harness that only reported the flattering scenario would be a demo. This one
reports whichever way each fault falls, and the table is mixed.

The two arms, stated precisely because the comparison is only worth what its
definitions are
------------------------------------------------------------------------------
**ASTRA** — the full assembled pipeline: L1 fusion, the UKF, the Trust Module,
the proposer behind the one-way channel, all three Core-B gates, the fail-safe
machine, RCM. What ``drive_closed_loop`` runs.

**Core-A raw** — the learned policy alone. It reads the published sensor
readings *directly*, with no filter to reject noise, no gate to veto a command
and no fallback controller to take over. It commands the plant on every tick.

Three things make that arm honest, and all three favour it:

1. **It sees the same corrupted readings, bit for bit.** The same seed drives
   the same measurement-noise stream drawn in the same order, and a second
   injector built from the same specification and seed produces the identical
   corruption. Neither arm has an easier fault than the other.
2. **It is given ground truth for what no sensor publishes.** The observation
   the policy takes is ``(px, py, v, psi, a_lat, TI)``, and nothing in this
   plant measures longitudinal position or heading. ASTRA's UKF estimates them;
   the raw arm is simply handed the plant's true values. That is generous, and
   it is the right kind of generous — any advantage ASTRA shows is then not an
   artefact of the baseline being blindfolded.
3. **Its Trust Index is pinned at 1.0.** There is no L3 to compute one. Full
   confidence, always, which is what "no runtime assurance" means.

What it found, and it is not what the entry predicted
------------------------------------------------------
Under an IMU dropout the table **inverts**: ASTRA ends 4.199 m off centre with
73 ticks outside the corridor, and the ungated baseline ends at 1.707 m and
never leaves it.

The mechanism, measured rather than assumed (E-58). A frozen position reading is
*maximally self-consistent* -- it says the same thing every tick, at a declared
sigma of 0.1 m -- so the filter grows confident in it. To keep "y is not
changing" consistent with its motion model, the UKF has to conclude the vehicle
is not moving laterally, and it pushes that conclusion into the one state
nothing observes: **heading**. True heading reaches **0.0686 rad** while the
estimate reports **0.0017 rad**, a fortyfold understatement. The controller
reads *centred and straight*, issues no correction, and the vehicle drifts.

So the fault does not stay in the channel it was injected into. It propagates
from an observed quantity into an unobserved one, and everything downstream --
proposer and all three gates alike -- reads the result.

**The honest reading of that row, which is narrower than it first looks.** The
baseline avoids this only because clause 2 above hands it a true heading, and no
sensor in this plant publishes one. That baseline is not realisable. The row
therefore measures *the filter's failure mode under a frozen sensor*, not an
advantage of having no filter -- and the control row is the check on that
reading: with no fault, ASTRA holds 0.009 m against the baseline's 0.055 m, so
the heading it is handed does not make it better in general. It makes it better
exactly when the filter is being lied to.

What this harness does *not* separate
--------------------------------------
It compares ASTRA against **no ASTRA**. It does not isolate which layer earned
any difference — a run with the gates removed but the UKF kept is a different
experiment and belongs to P3.4's ablation, where `AblationProfile` exists to
make it measurable without ever making a gate optional (ADR-0021).

Run it with::

    uv run python -m benchmarks.comparison
    uv run python -m benchmarks.comparison --ticks 1200 --open-at 400
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from astra.layers.l4_proposer.learned import LearnedPolicy
from benchmarks.fault_study import SCENARIOS
from training.closed_loop import (
    CHANNEL_SIGMAS,
    CORPUS,
    LATERAL_SIGMA,
    POSITION_SIGMA,
    SPEED_SIGMA,
    TWIN,
    TickSample,
    drive_closed_loop,
)
from training.environment import EnvironmentSpec, SyntheticDrivingEnv
from training.faults import FaultInjector

if TYPE_CHECKING:
    from collections.abc import Sequence

    from training.faults import FaultSpec

_DEFAULT_TICKS = 400
_DEFAULT_OPEN_AT = 200
_DEFAULT_SEED = 20260809
_DEFAULT_POLICY = Path("var/policy/synthetic.pt")
_DEFAULT_OUTPUT = Path("var/comparison")

CORRIDOR_HALF_WIDTH_M = 1.75
"""The bound L7a is configured with in `simulation`, and the line both arms are scored against.

Hard-coded rather than read from settings on purpose: the raw arm has no
settings, no shield and no notion of a corridor. This is the *analyst's* line,
applied identically to a system that knows about it and one that does not.
"""

_FULL_TRUST = 1.0


@dataclass(frozen=True, slots=True)
class ArmResult:
    """What one arm did under one scenario.

    Attributes:
        arm: ``"astra"`` or ``"core_a_raw"``.
        scenario: The fault, or ``"control"``.
        final_deviation_m: Where the vehicle ended, in metres off centre.
        max_deviation_m: The worst it got.
        ticks_outside_corridor: How long it spent beyond
            :data:`CORRIDOR_HALF_WIDTH_M`. **The headline**: a vehicle that
            recovers is not the same as one that never left.
        final_speed_mps: Recorded because every other field here is satisfied
            perfectly by a vehicle that has come to a stop, and one did.
        issued: Ticks on which a command reached the plant.
        ticks: How many ticks ran.
    """

    arm: str
    scenario: str
    final_deviation_m: float
    max_deviation_m: float
    ticks_outside_corridor: int
    final_speed_mps: float
    issued: int
    ticks: int

    def to_payload(self) -> dict[str, object]:
        """Return a JSON-serialisable view."""
        return {
            "arm": self.arm,
            "scenario": self.scenario,
            "final_deviation_m": self.final_deviation_m,
            "max_deviation_m": self.max_deviation_m,
            "ticks_outside_corridor": self.ticks_outside_corridor,
            "final_speed_mps": self.final_speed_mps,
            "issued": self.issued,
            "ticks": self.ticks,
        }


def _injector(specs: Sequence[FaultSpec] | None, seed: int) -> FaultInjector | None:
    """Build an injector, or ``None`` for the control arm."""
    return None if specs is None else FaultInjector(specs, seed=seed, sigmas=CHANNEL_SIGMAS)


def drive_core_a_raw(
    *,
    policy: LearnedPolicy,
    ticks: int,
    seed: int,
    fault: FaultInjector | None,
    spec: EnvironmentSpec | None = None,
) -> ArmResult:
    """Drive the plant with the policy alone: no filter, no gates, no fallback.

    The noise draws mirror :func:`training.closed_loop._publish_state` exactly --
    same seed, same order, same sigmas -- so the readings this arm sees are
    bit-identical to the ones ASTRA sees on the same tick. Without that the two
    arms would differ in the fault *and* in every reading after it, and no
    difference in outcome could be attributed to either.

    Args:
        policy: The trained proposer.
        ticks: How many control ticks to run.
        seed: The run seed, shared with the ASTRA arm.
        fault: The injector, or ``None``.
        spec: The plant definition.

    Returns:
        What this arm did.
    """
    plant = SyntheticDrivingEnv(spec or EnvironmentSpec())
    plant.reset(seed=seed)
    noise = random.Random(seed)
    lower = np.asarray(plant.spec_.channel_lower, dtype=np.float64)
    upper = np.asarray(plant.spec_.channel_upper, dtype=np.float64)

    outside = 0
    worst = 0.0
    issued = 0
    held: dict[str, float] | None = None
    for tick in range(ticks):
        state = plant._state  # noqa: SLF001 - the plant is the test fixture
        # Drawn in the same order as the closed-loop harness: y, v, a. The draw
        # happens on every tick whether or not the reading survives, so the noise
        # stream stays in phase with ASTRA's even across a dropout.
        payload = {
            "y": float(state[1]) + noise.gauss(0.0, POSITION_SIGMA),
            "v": float(state[2]) + noise.gauss(0.0, SPEED_SIGMA),
            "a": float(state[4]) + noise.gauss(0.0, LATERAL_SIGMA),
        }
        reading = payload if fault is None else fault.corrupt(payload, tick=tick)
        if reading is None:
            # The stream dropped out. A raw controller has no staleness rule and
            # no health field to consult, so it does what an unguarded consumer
            # does with a missing message: **keeps using the last one it got**.
            #
            # It must be the last one, not this tick's clean draw. Handing it a
            # fresh reading here would mean the baseline never experienced the
            # dropout at all, and the comparison would be measuring ASTRA
            # against a system the fault was not applied to. That is what this
            # branch did on its first run, and it inverted the `imu_dropout`
            # row -- the bug arrived as a *flattering-to-the-baseline* result,
            # which is the direction that gets published.
            reading = held if held is not None else payload
        held = reading

        observation = (
            float(state[0]),  # px -- unmeasured, handed over as truth
            reading["y"],
            reading["v"],
            float(state[3]),  # psi -- unmeasured, handed over as truth
            reading["a"],
            _FULL_TRUST,
        )
        command = np.asarray([float(v) for v in policy.act(observation)], dtype=np.float64)
        plant.step((2.0 * (command - lower) / (upper - lower) - 1.0).astype(np.float32))
        issued += 1

        deviation = abs(float(plant._state[1]))  # noqa: SLF001
        worst = max(worst, deviation)
        outside += int(deviation > CORRIDOR_HALF_WIDTH_M)

    return ArmResult(
        arm="core_a_raw",
        scenario="",
        final_deviation_m=abs(float(plant._state[1])),  # noqa: SLF001
        max_deviation_m=worst,
        ticks_outside_corridor=outside,
        final_speed_mps=float(plant._state[2]),  # noqa: SLF001
        issued=issued,
        ticks=ticks,
    )


def drive_astra(
    *, policy_path: Path, ticks: int, seed: int, fault: FaultInjector | None
) -> ArmResult:
    """Drive the full pipeline and reduce it to the same figures.

    Args:
        policy_path: The trained proposer.
        ticks: How many control ticks to run.
        seed: The run seed, shared with the raw arm.
        fault: The injector, or ``None``.

    Returns:
        What this arm did.
    """
    samples: list[TickSample] = []
    result = drive_closed_loop(
        policy=LearnedPolicy.load(policy_path),
        ticks=ticks,
        seed=seed,
        observer=samples.append,
        fault=fault,
    )
    deviations = [abs(s.lane_deviation_m) for s in samples]
    return ArmResult(
        arm="astra",
        scenario="",
        final_deviation_m=result.final_absolute_deviation_m,
        max_deviation_m=max(deviations),
        ticks_outside_corridor=sum(d > CORRIDOR_HALF_WIDTH_M for d in deviations),
        final_speed_mps=result.final_speed_mps,
        issued=result.issued,
        ticks=result.ticks,
    )


def run(
    *, ticks: int, open_at: int, seed: int, policy_path: Path, output: Path
) -> list[tuple[str, ArmResult, ArmResult]]:
    """Run both arms against the control and every scenario.

    Args:
        ticks: Control ticks per run.
        open_at: The tick each fault opens on.
        seed: Shared run seed.
        policy_path: The trained proposer.
        output: Where to write the summary.

    Returns:
        One ``(scenario, astra, core_a_raw)`` triple per scenario, control first.
    """
    output.mkdir(parents=True, exist_ok=True)
    policy = LearnedPolicy.load(policy_path)
    rows: list[tuple[str, ArmResult, ArmResult]] = []

    cases: list[tuple[str, Sequence[FaultSpec] | None]] = [("control", None)]
    cases += [(s.name, s.build(open_at, ticks - 1)) for s in SCENARIOS]

    for name, specs in cases:
        print(f"  running {name} ...")
        # A fresh injector per arm, same specification and seed, so both arms
        # see the identical corruption without sharing mutable state.
        astra = drive_astra(
            policy_path=policy_path, ticks=ticks, seed=seed, fault=_injector(specs, seed)
        )
        raw = drive_core_a_raw(policy=policy, ticks=ticks, seed=seed, fault=_injector(specs, seed))
        rows.append((name, astra, raw))

    (output / "summary.json").write_text(
        json.dumps(
            {
                "ticks": ticks,
                "open_at": open_at,
                "seed": seed,
                "corridor_half_width_m": CORRIDOR_HALF_WIDTH_M,
                "rows": [
                    {"scenario": name, "astra": a.to_payload(), "core_a_raw": r.to_payload()}
                    for name, a, r in rows
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return rows


def render(rows: Sequence[tuple[str, ArmResult, ArmResult]]) -> list[str]:
    """Return the two-column report, as lines."""
    lines = [
        "",
        f"  {'':<16} {'ASTRA':>27}  |  {'Core-A raw':>27}",
        (
            f"  {'scenario':<16} {'final |dev|':>12} {'ticks out':>10}"
            f"  |  {'final |dev|':>12} {'ticks out':>10}"
        ),
        f"  {'-' * 16} {'-' * 12} {'-' * 10}  |  {'-' * 12} {'-' * 10}",
    ]
    for name, astra, raw in rows:
        lines.append(
            f"  {name:<16} {astra.final_deviation_m:>10.3f} m {astra.ticks_outside_corridor:>10}"
            f"  |  {raw.final_deviation_m:>10.3f} m {raw.ticks_outside_corridor:>10}"
        )
    lines += [
        "",
        f"  'ticks out' is time spent beyond the +/-{CORRIDOR_HALF_WIDTH_M} m corridor.",
        "  Both arms issue a command on every tick; neither ever stops.",
        "",
        "  A row where both columns agree is a row where ASTRA added nothing,",
        "  and those rows are the point of running this rather than a demo.",
    ]
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    """Run the comparison and print the table.

    Args:
        argv: Command-line arguments, or ``None`` for ``sys.argv``.

    Returns:
        Zero unless an input artefact is missing. Never keyed on which arm won.
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

    rows = run(
        ticks=arguments.ticks,
        open_at=arguments.open_at,
        seed=arguments.seed,
        policy_path=arguments.policy,
        output=arguments.output,
    )
    for line in render(rows):
        print(line)
    print(f"\n  summary: {arguments.output / 'summary.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
