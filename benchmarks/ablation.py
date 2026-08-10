"""What is each gate worth? Disarm one at a time and re-measure.

The question, and why it could not be asked until now
------------------------------------------------------
``PENDING.md`` P3.4 wants a table quantifying each layer's contribution. Its
original premise was that the ``None`` paths had been preserved for exactly this
-- and checked against the code, **one of the six ablations had one**. The other
five needed building, and three of them are the safety spine.

ADR-0021 is how they were built: the gate parameters stay required, and an
ablated run supplies a *transparent* gate -- a subtype that runs, is evaluated,
writes a verdict, and cannot block. A pipeline with no gate is still
unconstructible. Every decision record carries which layers were disarmed, so a
run measured here can never be mistaken for a governed one.

FB2 and FB3 are deliberately absent from the table. Neither was ever wired, so
"FB2 off" *is* the shipped configuration and ablating it would measure nothing.
The comparison those rows want is against FB2 and FB3 **on**, which the shadow
harness already measured -- a stronger result, because it changed no verdict
(E-39, E-40).

What the table means, and the one reading to avoid
----------------------------------------------------
Each row is a profile; each column is a scenario. The cell is what the vehicle
did. **A gate's contribution is the difference between the governed row and the
row where it is disarmed** -- not the absolute number in either.

The reading to avoid: *"disarming L7a changed nothing, so L7a is worthless."*
A gate that never fires on the traffic it was shown has not been shown to be
worthless; it has been shown to be untested by that traffic. L7a vetoed **once
in roughly 500,000 ticks** of nominal driving (N-9), and a study over 400-tick
runs is not going to find the second one. What this measures is what each gate
contributes **on these scenarios** -- six hand-chosen faults and a control -- and
that is the whole of the claim.

Run it with::

    uv run python -m benchmarks.ablation
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from astra.layers.l4_proposer.learned import LearnedPolicy
from astra.runtime.ablation import ABLATED_REASON_CODE, AblationProfile
from benchmarks.comparison import CORRIDOR_HALF_WIDTH_M
from benchmarks.fault_study import SCENARIOS
from training.closed_loop import CHANNEL_SIGMAS, CORPUS, TWIN, TickSample, drive_closed_loop
from training.faults import FaultInjector

if TYPE_CHECKING:
    from collections.abc import Sequence

    from training.faults import FaultSpec

_DEFAULT_TICKS = 400
_DEFAULT_OPEN_AT = 200
_DEFAULT_SEED = 20260809
_DEFAULT_POLICY = Path("var/policy/synthetic.pt")
_DEFAULT_OUTPUT = Path("var/ablation")

PROFILES: tuple[tuple[str, AblationProfile], ...] = (
    ("governed", AblationProfile.NONE),
    ("L6 off", AblationProfile.NONE.without("statistical_gate")),
    ("L7b off", AblationProfile.NONE.without("physical_gate")),
    ("L7a off", AblationProfile.NONE.without("shield")),
)
"""The governed run and one disarmed gate at a time.

Deliberately not the full lattice. Disarming two gates at once measures their
interaction, which is a question worth asking only once the single-gate rows
have said something -- and on these scenarios they mostly do not.
"""


@dataclass(frozen=True, slots=True)
class Cell:
    """One profile against one scenario."""

    profile: str
    scenario: str
    vetoed: int
    ablated_passes: int
    final_deviation_m: float
    ticks_outside_corridor: int
    not_nominal_ticks: int
    issued: int
    ticks: int

    def to_payload(self) -> dict[str, object]:
        """Return a JSON-serialisable view."""
        return {
            "profile": self.profile,
            "scenario": self.scenario,
            "vetoed": self.vetoed,
            "ablated_passes": self.ablated_passes,
            "final_deviation_m": self.final_deviation_m,
            "ticks_outside_corridor": self.ticks_outside_corridor,
            "not_nominal_ticks": self.not_nominal_ticks,
            "issued": self.issued,
            "ticks": self.ticks,
        }


def _measure(profile: str, scenario: str, samples: Sequence[TickSample], result: object) -> Cell:
    """Reduce one run to a cell."""
    deviations = [abs(s.lane_deviation_m) for s in samples]
    ablated = 0
    not_nominal = 0
    for sample in samples:
        verdict = sample.record.safety_verdict
        if verdict is not None:
            ablated += sum(
                1 for gv in verdict.gate_verdicts if gv.reason_code == ABLATED_REASON_CODE
            )
        failsafe = sample.record.failsafe
        if failsafe is not None and failsafe.state.value != "NOMINAL":
            not_nominal += 1
    return Cell(
        profile=profile,
        scenario=scenario,
        vetoed=result.vetoed,  # type: ignore[attr-defined]
        ablated_passes=ablated,
        final_deviation_m=result.final_absolute_deviation_m,  # type: ignore[attr-defined]
        ticks_outside_corridor=sum(d > CORRIDOR_HALF_WIDTH_M for d in deviations),
        not_nominal_ticks=not_nominal,
        issued=result.issued,  # type: ignore[attr-defined]
        ticks=result.ticks,  # type: ignore[attr-defined]
    )


def run(*, ticks: int, open_at: int, seed: int, policy_path: Path, output: Path) -> list[Cell]:
    """Run every profile against every scenario.

    Args:
        ticks: Control ticks per run.
        open_at: The tick each fault opens on.
        seed: Shared run seed, so profiles differ only in what is disarmed.
        policy_path: The trained proposer.
        output: Where to write the summary.

    Returns:
        One cell per (profile, scenario) pair.
    """
    output.mkdir(parents=True, exist_ok=True)
    cases: list[tuple[str, Sequence[FaultSpec] | None]] = [("control", None)]
    cases += [(s.name, s.build(open_at, ticks - 1)) for s in SCENARIOS]

    cells: list[Cell] = []
    for label, profile in PROFILES:
        print(f"  {label} ...")
        for scenario, specs in cases:
            samples: list[TickSample] = []
            injector = (
                None if specs is None else FaultInjector(specs, seed=seed, sigmas=CHANNEL_SIGMAS)
            )
            result = drive_closed_loop(
                policy=LearnedPolicy.load(policy_path),
                ticks=ticks,
                seed=seed,
                observer=samples.append,
                fault=injector,
                ablation=profile,
            )
            cells.append(_measure(label, scenario, samples, result))

    (output / "summary.json").write_text(
        json.dumps(
            {
                "ticks": ticks,
                "open_at": open_at,
                "seed": seed,
                "corridor_half_width_m": CORRIDOR_HALF_WIDTH_M,
                "cells": [cell.to_payload() for cell in cells],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return cells


def render(cells: Sequence[Cell]) -> list[str]:
    """Return the ablation table, as lines."""
    scenarios = list(dict.fromkeys(cell.scenario for cell in cells))
    by_key = {(cell.profile, cell.scenario): cell for cell in cells}
    lines = ["", "  Vetoes per run. Governed row first; each other row disarms one gate.", ""]
    header = f"  {'profile':<10}" + "".join(f"{s[:13]:>15}" for s in scenarios)
    lines += [header, f"  {'-' * 10}" + "".join(f"{'-' * 14:>15}" for _ in scenarios)]
    for label, _ in PROFILES:
        row = f"  {label:<10}"
        for scenario in scenarios:
            cell = by_key[label, scenario]
            row += f"{cell.vetoed:>15}"
        lines.append(row)

    lines += ["", "  Final |deviation| in metres.", "", header]
    lines.append(f"  {'-' * 10}" + "".join(f"{'-' * 14:>15}" for _ in scenarios))
    for label, _ in PROFILES:
        row = f"  {label:<10}"
        for scenario in scenarios:
            row += f"{by_key[label, scenario].final_deviation_m:>14.3f} "
        lines.append(row)

    governed = [by_key["governed", s] for s in scenarios]
    lines += [
        "",
        f"  Every run issued a command on all {governed[0].ticks} ticks"
        if all(c.issued == c.ticks for c in cells)
        else "  Some run failed to issue on every tick -- see summary.json",
        "",
        "  A column where every row agrees is a scenario no gate influenced.",
        "  A gate's contribution is its row minus the governed row, and nothing else.",
        "",
        "  Disarmed gates still run and still write a verdict: the `ablated_passes`",
        "  field in summary.json counts them, and it is non-zero exactly where a",
        "  gate was disarmed. A zero there would mean the ablation did not happen.",
    ]
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    """Run the ablation study and print the table.

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

    cells = run(
        ticks=arguments.ticks,
        open_at=arguments.open_at,
        seed=arguments.seed,
        policy_path=arguments.policy,
        output=arguments.output,
    )
    for line in render(cells):
        print(line)
    print(f"\n  summary: {arguments.output / 'summary.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
