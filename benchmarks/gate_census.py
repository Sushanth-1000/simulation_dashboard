"""Which of the three gates actually objects, and to what?

The claim under test
----------------------
The architecture's distinguishing structural claim is **three gates that fail
for unrelated reasons**: L6 scores a proposal against the twin, L7a bounds speed,
lateral acceleration and the lane corridor, L7b bounds jerk and divergence. D-3
in the credibility matrix rests on their independence, and independence is only
worth having if each of them is *load-bearing*.

OD-3 has said since 5 August that L7a is not: it *"never fired across 400,000
ticks"*, and after P2.1 gave it a corridor bound it could fire on, it vetoed
**once in roughly 500,000**. This counts the same thing across the fault suite
rather than across a nominal soak, which is the harder test -- these seven arms
exist specifically to break the gates.

Why PASS and ABSTAIN are counted separately
---------------------------------------------
ADR-0016 added `ABSTAIN` for a gate that *cannot* judge, and dropping abstentions
before the fail-closed merge is what makes bounded exploration possible. So a
gate reporting nothing has two very different explanations:

``ABSTAIN``
    It is uncalibrated or out of its competence. Silence is honest, and the
    right response is to calibrate it.

``PASS``
    It judged, every tick, and found nothing to object to. Silence is a
    *finding* about the gate's thresholds or about the scenarios.

Counting only vetoes cannot tell those apart, and the difference decides whether
a silent gate is a gap or a gate.

What a silent gate does and does not mean
-------------------------------------------
A gate that never fires on a well-behaved system is not obviously wrong -- that
is what a bound is for. A gate that never fires on a **fault suite built to
break it** is a different matter, and that is what this measures.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from astra.kernel.enums import GateId, Verdict
from astra.layers.l4_proposer.learned import LearnedPolicy
from benchmarks.fault_study import SCENARIOS
from training.closed_loop import CHANNEL_SIGMAS, drive_closed_loop
from training.faults import FaultInjector

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["GateTally", "census", "render"]

_DEFAULT_TICKS: Final = 400
_DEFAULT_OPEN_AT: Final = 200
_DEFAULT_SEED: Final = 20260809
_DEFAULT_POLICY: Final = Path("var/policy/synthetic.pt")
_DEFAULT_OUTPUT: Final = Path("var/gate_census")


@dataclass(frozen=True, slots=True)
class GateTally:
    """One gate's verdicts across every arm.

    Attributes:
        gate: Which gate.
        passed: Ticks it judged and accepted.
        vetoed: Ticks it refused.
        abstained: Ticks it declined to judge.
        reasons: Veto reason codes and their counts.
    """

    gate: str
    passed: int
    vetoed: int
    abstained: int
    reasons: dict[str, int]


def census(
    *, ticks: int, open_at: int, seed: int, policy_path: Path
) -> tuple[list[GateTally], int]:
    """Run the clean arm and every fault arm, counting every gate verdict.

    Args:
        ticks: Ticks per arm.
        open_at: The tick each fault opens on.
        seed: The plant seed, shared so arms differ only by fault.
        policy_path: The trained proposer.

    Returns:
        One tally per gate, and the total ticks observed across all arms.
    """
    policy = LearnedPolicy.load(policy_path)
    verdicts: Counter[tuple[str, str]] = Counter()
    reasons: Counter[tuple[str, str]] = Counter()
    observed = 0

    def run(fault: FaultInjector | None) -> None:
        nonlocal observed
        samples: list[object] = []
        drive_closed_loop(
            policy=policy, ticks=ticks, seed=seed, observer=samples.append, fault=fault
        )
        observed += len(samples)
        for sample in samples:
            verdict = sample.record.safety_verdict  # type: ignore[attr-defined]
            if verdict is None:
                continue
            for gate_verdict in verdict.gate_verdicts:
                verdicts[gate_verdict.gate.value, gate_verdict.verdict.value] += 1
                if gate_verdict.verdict is Verdict.VETO:
                    reasons[gate_verdict.gate.value, gate_verdict.reason_code] += 1

    run(None)
    for scenario in SCENARIOS:
        run(FaultInjector(scenario.build(open_at, ticks - 1), seed=seed, sigmas=CHANNEL_SIGMAS))

    tallies = [
        GateTally(
            gate=gate.value,
            passed=verdicts[gate.value, Verdict.PASS.value],
            vetoed=verdicts[gate.value, Verdict.VETO.value],
            abstained=verdicts[gate.value, Verdict.ABSTAIN.value],
            reasons={
                reason: count for (owner, reason), count in reasons.items() if owner == gate.value
            },
        )
        for gate in GateId
    ]
    return tallies, observed


def render(tallies: Sequence[GateTally], *, observed: int) -> list[str]:
    """Return the census table and what it supports.

    Args:
        tallies: One entry per gate.
        observed: Total ticks across every arm.

    Returns:
        Printable lines.
    """
    lines = [
        "",
        f"Gate census -- {observed} ticks across the clean arm and {len(SCENARIOS)} faults",
        "=" * 78,
        f"{'gate':<16}{'PASS':<10}{'VETO':<10}{'ABSTAIN':<10}reasons",
        "-" * 78,
    ]
    for tally in tallies:
        reasons = ", ".join(f"{r} x{n}" for r, n in tally.reasons.items()) or "--"
        lines.append(
            f"{tally.gate:<16}{tally.passed:<10}{tally.vetoed:<10}{tally.abstained:<10}{reasons}"
        )
    lines.append("-" * 78)

    silent = [t for t in tallies if t.vetoed == 0]
    if silent:
        names = ", ".join(t.gate for t in silent)
        abstaining = [t for t in silent if t.abstained > 0]
        lines.extend(
            [
                "",
                f"{len(silent)} of {len(tallies)} gates never object: {names}.",
            ]
        )
        if abstaining:
            lines.append("  Some ABSTAIN -- uncalibrated, and the remedy is calibration.")
        else:
            lines.append("  None abstain: they judge every tick and find nothing to object to,")
            lines.append("  on a suite built to break them. That bears on D-3 -- independence")
            lines.append("  is only worth having if each gate is load-bearing (OD-3).")
    return lines


def main(argv: list[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Command-line arguments, or ``None`` for ``sys.argv``.

    Returns:
        Zero always. A silent gate is a finding, not a build failure.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ticks", "-n", type=int, default=_DEFAULT_TICKS)
    parser.add_argument("--open-at", type=int, default=_DEFAULT_OPEN_AT)
    parser.add_argument("--seed", type=int, default=_DEFAULT_SEED)
    parser.add_argument("--policy", type=Path, default=_DEFAULT_POLICY)
    parser.add_argument("--output", "-o", type=Path, default=_DEFAULT_OUTPUT)
    arguments = parser.parse_args(argv)

    tallies, observed = census(
        ticks=arguments.ticks,
        open_at=arguments.open_at,
        seed=arguments.seed,
        policy_path=arguments.policy,
    )
    for line in render(tallies, observed=observed):
        print(line)

    arguments.output.mkdir(parents=True, exist_ok=True)
    (arguments.output / "census.json").write_text(
        json.dumps(
            {
                "ticks_per_arm": arguments.ticks,
                "arms": len(SCENARIOS) + 1,
                "observed": observed,
                "seed": arguments.seed,
                "gates": [asdict(tally) for tally in tallies],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
