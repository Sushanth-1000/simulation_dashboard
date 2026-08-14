"""If this sensor fails, what does the vehicle stop being able to do?

The question, and who asks it
------------------------------
A safety engineer signing off a deployment needs one table: **per sensor, what
its loss withdraws and where the posture lands.** That table is the degradation
concept, it is required by every functional-safety argument worth the name, and
in most projects it is a document maintained by hand beside a state machine
maintained separately -- which is to say, a document that is wrong.

Here it is *derived*. Both halves come from the profile the vehicle actually
loads: ``failsafe.capabilities`` says what each function requires, and
``failsafe.critical_modalities`` says which sensors may move the posture. This
tool drives the real :class:`~astra.layers.l8_failsafe.machine.FailSafeStateMachine`
with one modality dark at a time and prints what happened. Nothing here restates
the configuration; it reports the machine's response to it.

That is the difference worth selling: the degradation table and the running
system cannot disagree, because the table is a measurement of the system.

The two axes, and why a row has two answers
---------------------------------------------
ADR-0029 gave the machine a second axis. A row therefore answers two independent
questions, and the interesting rows are the ones where the answers differ:

``posture``
    How bad it got -- NOMINAL, DEGRADED, LIMP, HALT. Driven by
    ``critical_modalities`` and the integrity counter.

``withdrawn``
    What broke -- the functions that named this modality. Driven by
    ``capabilities``, and *not* filtered by the critical set.

A row reading ``NOMINAL`` with functions withdrawn is the behaviour the design
existed to produce: the vehicle keeps driving and declines what it can no longer
do. A row reading ``HALT`` with nothing withdrawn means a sensor the deployment
calls critical carries no declared function -- which is worth a second look,
though it is not necessarily wrong.

The flag this tool exists to raise
------------------------------------
``INERT``. A modality that is neither critical nor required by any capability
has **no effect whatsoever** when it fails: the posture does not move and no
function is withdrawn. That is either a sensor nobody needs or, far more likely,
a sensor somebody added and forgot to wire a failure response for. It is a real
and ordinary integration bug, it is invisible in the code, and it falls straight
out of this table.

The check cannot live in a config validator, because nothing in the
configuration declares which sensors are *installed* -- a deployment genuinely
without a radar should not be nagged about one. Here the installed set is an
input, so the question is answerable.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from astra.config.loader import load_settings
from astra.contracts.assurance import GateVerdict, SafetyVerdict
from astra.kernel.enums import FailSafeState, GateId, SensorModality, StreamHealth, Verdict
from astra.kernel.identifiers import TickId
from astra.layers.l8_failsafe.machine import FailSafeStateMachine

if TYPE_CHECKING:
    from collections.abc import Sequence

    from astra.config.schema import FailSafeSettings

__all__ = ["Row", "assess", "render"]

_DEFAULT_ENVIRONMENT: Final = "simulation"
_DEFAULT_TICKS: Final = 60
"""Three seconds at 20 Hz -- comfortably past ``integrity_threshold_halt`` (40),
so a critical modality has time to reach its terminal posture. A shorter window
would report the posture on the way to somewhere else."""

_DEFAULT_OUTPUT: Final = Path("artifacts/degradation")


@dataclass(frozen=True, slots=True)
class Row:
    """One modality's entry in the degradation table.

    Attributes:
        modality: The sensor whose loss this row describes.
        critical: Whether the deployment declared it able to move the posture.
        withdrawn: The functions withdrawn while it is dark.
        posture: Where the fail-safe machine settled after the window.
        integrity_counter: The counter at the end of the window, so a reader can
            tell a posture that arrived from one that is still climbing.
        inert: Whether losing this modality does nothing at all.
    """

    modality: str
    critical: bool
    withdrawn: tuple[str, ...]
    posture: str
    integrity_counter: int
    inert: bool


def _passing(tick: int) -> SafetyVerdict:
    """Return a verdict every gate passed.

    The verdict stream is clean for the whole measurement, deliberately. This
    table is about what *sensor health* alone does; letting the gates refuse as
    well would mix the two axes and make every row unattributable.
    """
    return SafetyVerdict(
        tick=TickId(tick),
        gate_verdicts=(
            GateVerdict(
                tick=TickId(tick),
                gate=GateId.STATISTICAL,
                verdict=Verdict.PASS,
                reason_code="NOMINAL",
            ),
        ),
    )


def assess(
    *,
    settings: FailSafeSettings,
    installed: Sequence[SensorModality],
    ticks: int = _DEFAULT_TICKS,
) -> list[Row]:
    """Drive the fail-safe machine once per modality and record what happened.

    Args:
        settings: The deployment's fail-safe configuration.
        installed: The modalities the platform actually carries. Supplied rather
            than inferred, because no part of the configuration declares it and
            a vehicle without a radar must not be told its radar is inert.
        ticks: How long to hold each fault. Must outlast the HALT threshold or
            the posture column reports a value still on its way somewhere.

    Returns:
        One row per installed modality, in the order supplied.
    """
    rows: list[Row] = []
    for dark in installed:
        machine = FailSafeStateMachine(settings)
        health = tuple(
            (modality, StreamHealth.ABSENT if modality is dark else StreamHealth.HEALTHY)
            for modality in installed
        )
        for tick in range(ticks):
            machine.observe(tick=TickId(tick), verdict=_passing(tick), frame_health=health)

        critical = dark in settings.critical_modalities
        rows.append(
            Row(
                modality=dark.value,
                critical=critical,
                withdrawn=machine.withdrawn_capabilities,
                posture=machine.state.value,
                integrity_counter=machine.integrity_counter,
                # Measured, not deduced. `critical and required` is what the
                # configuration *says*; this asks the machine what it *did*, and
                # the two would part company the moment the derivation regressed
                # -- which is the failure this table would otherwise hide.
                inert=(
                    machine.state is FailSafeState.NOMINAL
                    and not machine.withdrawn_capabilities
                    and machine.integrity_counter == 0
                ),
            )
        )
    return rows


def render(rows: Sequence[Row]) -> list[str]:
    """Return the degradation table as printable lines.

    Args:
        rows: The assessed rows.

    Returns:
        Lines of a fixed-width table, followed by any warnings it earned.
    """
    lines = [
        "",
        "Degradation table -- what each sensor's loss costs",
        "=" * 78,
        f"{'sensor':<9}{'critical':<10}{'posture':<10}{'phi':<6}withdrawn",
        "-" * 78,
    ]
    for row in rows:
        withdrawn = ", ".join(row.withdrawn) if row.withdrawn else "--"
        flag = "  <-- INERT" if row.inert else ""
        lines.append(
            f"{row.modality:<9}{'yes' if row.critical else 'no':<10}"
            f"{row.posture:<10}{row.integrity_counter:<6}{withdrawn}{flag}"
        )
    lines.append("-" * 78)

    inert = [row.modality for row in rows if row.inert]
    if inert:
        lines.extend(
            [
                "",
                f"WARNING: {len(inert)} modality/modalities do nothing when they fail: "
                + ", ".join(inert),
                "  Losing one moves no posture and withdraws no function. Either the",
                "  sensor is genuinely unneeded, or a failure response was never wired.",
            ]
        )
    graceful = [row for row in rows if row.withdrawn and row.posture == FailSafeState.NOMINAL.value]
    if graceful:
        lines.extend(
            [
                "",
                f"{len(graceful)} modality/modalities degrade gracefully: the vehicle keeps",
                "  driving and declines only what it can no longer do. This is the",
                "  behaviour ADR-0029 exists to make expressible.",
            ]
        )
    return lines


def main(argv: list[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Command-line arguments, or ``None`` for ``sys.argv``.

    Returns:
        Zero always. An inert modality is a finding for a human to judge, not a
        failure: a deployment may have a good reason, and exiting non-zero would
        put this tool in the way of a build it has no authority to stop.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--environment", "-e", default=_DEFAULT_ENVIRONMENT)
    parser.add_argument("--ticks", "-n", type=int, default=_DEFAULT_TICKS)
    parser.add_argument("--output", "-o", type=Path, default=_DEFAULT_OUTPUT)
    arguments = parser.parse_args(argv)

    resolved = load_settings(environment=arguments.environment, include_environment_variables=False)
    rows = assess(
        settings=resolved.settings.failsafe,
        installed=tuple(SensorModality),
        ticks=arguments.ticks,
    )
    for line in render(rows):
        print(line)

    arguments.output.mkdir(parents=True, exist_ok=True)
    (arguments.output / "degradation.json").write_text(
        json.dumps(
            {
                # Same argument as the commissioning certificate: a degradation
                # table is about one build's configuration, and a table that
                # cannot say which is a screenshot rather than an artefact.
                "config_hash": resolved.hash,
                "environment": arguments.environment,
                "ticks": arguments.ticks,
                "rows": [asdict(row) for row in rows],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
