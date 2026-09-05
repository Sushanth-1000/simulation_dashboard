"""The pipeline, tick by tick, in a terminal.

The dashboard shows you *that* the layers ran. This shows you **what each one
decided, on which tick, and why the next one did what it did with it.** It is
the same run, the same pipeline and the same records -- rendered as a scrolling
trace instead of a page, because a trace is what you read when you want to
follow a single decision through nine layers rather than watch the whole system
at once.

Nothing here is computed for display
------------------------------------
Every field comes from :class:`demo.dashboard.Frame`, which is a pure projection
of one ``DecisionRecord`` and is asserted field-by-field against its source in
``tests/unit/test_dashboard_frame.py``. This module deliberately reuses that
projection rather than reading the record itself: a second, independently
written view of the same record is a second thing that can drift away from it,
and the dashboard has already been through one incident of exactly that kind.

The two exceptions are the same two the dashboard carries, and they are labelled
wherever they appear: ``truth`` and the belief error are **simulator only**. No
deployed vehicle knows either. They are shown because the central finding is
invisible without them -- the estimate and the truth separate while every gate
stays green, and a trace of only what the system knows renders that as a
completely nominal run.

Three views
-----------
``--explain`` is the teaching view: one labelled block per tick, every layer
named, in the order the tick actually travels through them. It is verbose on
purpose -- at 20 Hz you will want ``--every`` or ``--pause``.

The default is one line per tick, which is what you want when you are looking
for *when* something changed rather than what everything was.

``--events`` prints only the ticks where something changed -- a gate flipped, a
fault opened, the posture moved -- with the reason. On a clean run that is
almost silent, which is itself the point: it makes the blind spot legible, since
a sustained sensor failure produces a suspiciously short event log.

Run it::

    uv run python -m demo.narrate --explain --every 20
    uv run python -m demo.narrate --fault dropout --at 200 --events
    uv run python -m demo.narrate --fault position_bias --at 100 --explain --pause

"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

from astra.kernel.enums import SensorModality
from astra.layers.l4_proposer.learned import LearnedPolicy
from demo.dashboard import (
    CERTIFIED,
    FAULT_WINDOW_TICKS,
    POSITION_FAULTS,
    POSITION_MAGNITUDE,
    TUNNEL,
    Frame,
    build_injector,
    cold_path,
)
from training.closed_loop import (
    CHANNEL_SIGMAS,
    CORPUS,
    DEFAULT_CHANNEL_SIGMAS,
    TWIN,
    RedundantSensing,
    drive_closed_loop,
)
from training.faults import FaultInjector

if TYPE_CHECKING:
    from collections.abc import Sequence

    from training.closed_loop import TickSample

__all__ = ["main", "narrate"]

_DEFAULT_POLICY = Path("var/policy/synthetic.pt")
_DEFAULT_SEED = 20260810

#: Faults this trace can inject, matching the dashboard's buttons exactly so a
#: number seen here is the number the demonstration would have shown.
FAULTS = ("dropout", "position_bias", "position_drift", "speed_bias", "speed_stuck", "lateral_noise")


class Palette:
    """ANSI colours, or empty strings when the output is not a terminal.

    Colour is decided once, here, rather than at each use site. A trace piped
    into a file or a pager should not carry escape sequences, and ``NO_COLOR``
    is honoured because a user who set it has already said so.
    """

    __slots__ = ("bold", "cyan", "dim", "green", "off", "red", "violet", "yellow")

    def __init__(self, *, enabled: bool) -> None:
        """Initialise the palette.

        Args:
            enabled: Whether to emit escape sequences at all.
        """
        codes = {
            "dim": "\033[2m", "bold": "\033[1m", "off": "\033[0m",
            "green": "\033[32m", "red": "\033[31m", "yellow": "\033[33m",
            "cyan": "\033[36m", "violet": "\033[35m",
        }
        for name, code in codes.items():
            setattr(self, name, code if enabled else "")

    def verdict(self, value: str) -> str:
        """Colour a gate verdict by what it means.

        Args:
            value: ``PASS``, ``VETO``, ``ABSTAIN`` or similar.

        Returns:
            The value, coloured.
        """
        colour = {"PASS": self.green, "VETO": self.red, "ABSTAIN": self.yellow}.get(value, self.dim)
        return f"{colour}{value}{self.off}"


def _fmt(value: float | None, places: int = 3) -> str:
    """Format an optional number for a fixed-width column.

    Args:
        value: The number, or ``None`` when the layer did not report.
        places: Decimal places.

    Returns:
        The formatted number, or a dash.
    """
    return "--" if value is None else f"{value:+.{places}f}"


def _health(frame: Frame) -> str:
    """Summarise per-modality stream health.

    Args:
        frame: The tick.

    Returns:
        A compact ``NAME=STATE`` list for anything not healthy, else ``all ok``.
    """
    bad = [f"{name}={state}" for name, state in frame.health if state != "HEALTHY"]
    return "all ok" if not bad else " ".join(bad)


def _line(frame: Frame, palette: Palette) -> str:
    """Render one tick as a single row.

    Args:
        frame: The tick.
        palette: Colours.

    Returns:
        The row.
    """
    gates = {name: verdict for name, verdict, _ in frame.gates}
    worst = "VETO" if frame.blocking else ("PASS" if gates else "--")
    error = (
        None
        if frame.truth_y is None or frame.estimate_y is None
        else abs(frame.truth_y - frame.estimate_y)
    )
    fault = f"{palette.violet}FAULT{palette.off}" if frame.fault_active else "     "
    return (
        f"{palette.dim}{frame.tick:>6}{palette.off} "
        f"{fault} "
        f"est {_fmt(frame.estimate_y)}  "
        f"truth {_fmt(frame.truth_y)}  "
        f"err {_fmt(error)}  "
        f"innov {_fmt(frame.innovation, 2)}  "
        f"TI {_fmt(frame.trust_index, 2)}  "
        f"L6 {palette.verdict(gates.get('STATISTICAL', '--'))} "
        f"L7 {palette.verdict(gates.get('DETERMINISTIC', '--'))} "
        f"L8 {frame.failsafe_state or '--':<8} "
        f"{palette.verdict(worst)}"
    )


def _block(frame: Frame, palette: Palette) -> str:
    """Render one tick as a labelled, layer-by-layer block.

    The order is the order the tick actually travels: sense, estimate, trust,
    propose, twin, gate, shield, posture, arbitrate, issue. Reading it top to
    bottom is reading the decision being made.

    Args:
        frame: The tick.
        palette: Colours.

    Returns:
        The block.
    """
    gates = {name: (verdict, reason) for name, verdict, reason in frame.gates}
    error = (
        None
        if frame.truth_y is None or frame.estimate_y is None
        else abs(frame.truth_y - frame.estimate_y)
    )
    issued = (
        "nothing issued"
        if frame.issued is None
        else "  ".join(f"{v:+.4f}" for v in frame.issued)
    )

    def gate(name: str) -> str:
        verdict, reason = gates.get(name, ("--", "did not report"))
        return f"{palette.verdict(verdict):<20} {palette.dim}{reason}{palette.off}"

    head = f"{palette.bold}tick {frame.tick}{palette.off}"
    if frame.fault_active:
        head += f"   {palette.violet}[a sensor is lying]{palette.off}"
    rule = palette.dim + "-" * 74 + palette.off

    rows = [
        rule,
        head,
        f"  L1 sensing      {_health(frame)}",
        f"  L2 estimate     lateral {_fmt(frame.estimate_y)} m"
        f"     innovation {_fmt(frame.innovation, 2)}",
        f"  L3 trust        Trust Index {_fmt(frame.trust_index, 2)}"
        f"     context {frame.context or '--'}",
        f"  L4 proposer     learned policy -- proposes only, never commands",
        f"  L5 twin         physics reference L6 measures the proposal against",
        f"  L6 conformal    {gate('STATISTICAL')}",
        f"                  {palette.dim}quantile {_fmt(frame.quantile, 4)}{palette.off}",
        f"  L7b physical    {gate('PHYSICAL')}",
        f"  L7a hard bound  {gate('DETERMINISTIC')}",
        f"  L8 fail-safe    {frame.failsafe_state or '--':<12}"
        f" OOD {frame.ood_counter if frame.ood_counter is not None else '--'}"
        f"   cap {'none' if frame.speed_cap is None else f'{frame.speed_cap:.1f} m/s'}",
        f"  L9 arbitration  {frame.arbitration or '--':<17}"
        f" profile {frame.active_profile or '--'}"
        + (f"  {palette.violet}EXPLORING{palette.off}" if frame.exploring else ""),
        f"  -> issued       {frame.origin or 'none'}   {issued}",
        f"  {palette.dim}ground truth    y {_fmt(frame.truth_y)} m"
        f"   speed {_fmt(frame.truth_speed, 2)} m/s"
        f"   belief off by {_fmt(error)} m   (simulator only){palette.off}",
    ]
    return "\n".join(rows)


class Narrator:
    """Formats ticks, and remembers enough to report what changed."""

    __slots__ = ("_every", "_last", "_mode", "_pause", "_palette", "_stream", "printed")

    def __init__(
        self,
        *,
        mode: str,
        every: int,
        pause: float,
        palette: Palette,
        stream: object = sys.stdout,
    ) -> None:
        """Initialise the narrator.

        Args:
            mode: ``line``, ``explain`` or ``events``.
            every: Print one tick in this many.
            pause: Seconds to sleep after each printed tick.
            palette: Colours.
            stream: Where to write.
        """
        self._mode = mode
        self._every = max(1, every)
        self._pause = pause
        self._palette = palette
        self._stream = stream
        self._last: dict[str, object] = {}
        self.printed = 0

    def _say(self, text: str) -> None:
        """Write a line and count it.

        Args:
            text: The line.
        """
        print(text, file=self._stream)
        self.printed += 1

    def _events(self, frame: Frame) -> list[str]:
        """Return the notable changes on this tick, with reasons.

        Args:
            frame: The tick.

        Returns:
            Zero or more lines.
        """
        p = self._palette
        out: list[str] = []

        first = "fault" not in self._last
        if first:
            # Seed from the opening tick rather than narrating a transition out
            # of nothing: None != False would otherwise report "fault closes"
            # on tick 0 of every clean run.
            self._last.update(
                fault=frame.fault_active,
                failsafe=frame.failsafe_state,
                arbitration=frame.arbitration,
                exploring=frame.exploring,
            )
            return out

        if frame.fault_active != self._last.get("fault"):
            if frame.fault_active:
                out.append(
                    f"{p.violet}FAULT OPENS{p.off}  a sensor begins lying. Watch the belief "
                    f"and the truth separate -- and watch the gates not react."
                )
            else:
                out.append(
                    f"{p.green}fault closes{p.off}  the sensor is honest again. Any alarm "
                    f"from here on is the recovery, not the fault."
                )
            self._last["fault"] = frame.fault_active

        if frame.failsafe_state != self._last.get("failsafe"):
            why = {
                "NOMINAL": "full envelope, no restriction in force",
                "DEGRADED": "OOD counter crossed the first threshold; speed capped",
                "LIMP": "second threshold; severely restricted envelope",
                "HALT": "third threshold; a commanded stop -- terminal, only a reset leaves it",
            }.get(frame.failsafe_state or "", "")
            if self._last.get("failsafe") is not None:
                colour = p.green if frame.failsafe_state == "NOMINAL" else p.red
                out.append(
                    f"{colour}L8 -> {frame.failsafe_state}{p.off}  {p.dim}{why}{p.off}"
                )
            self._last["failsafe"] = frame.failsafe_state

        if frame.blocking:
            fired = [f"{n}: {r}" for n, v, r in frame.gates if v == "VETO"]
            out.append(f"{p.red}VETO{p.off}  {p.dim}{' | '.join(fired)}{p.off}")

        if frame.arbitration != self._last.get("arbitration") and frame.arbitration:
            if self._last.get("arbitration") is not None:
                out.append(f"{p.cyan}L9 -> {frame.arbitration}{p.off}")
            self._last["arbitration"] = frame.arbitration

        if frame.exploring != self._last.get("exploring"):
            if frame.exploring:
                out.append(
                    f"{p.violet}BOUNDED SAFE EXPLORATION{p.off}  {p.dim}no certified profile "
                    f"covers this context; RCM narrows the envelope and keeps driving{p.off}"
                )
            self._last["exploring"] = frame.exploring

        return out

    def observe(self, sample: TickSample) -> None:
        """Render one tick.

        Args:
            sample: The tick, from the harness's observer callback.
        """
        frame = Frame.from_sample(sample)
        events = self._events(frame)

        if self._mode == "events":
            for line in events:
                self._say(f"{self._palette.dim}{frame.tick:>6}{self._palette.off}  {line}")
            if events and self._pause > 0.0:
                time.sleep(self._pause)
            return

        due = frame.tick % self._every == 0
        if due:
            self._say(_block(frame, self._palette) if self._mode == "explain" else _line(frame, self._palette))
        for line in events:
            self._say(f"{'':>6}  {line}")
        if (due or events) and self._pause > 0.0:
            time.sleep(self._pause)


def _arm(kind: str, at: int, seed: int) -> tuple[FaultInjector, RedundantSensing]:
    """Build the injector and sensing spec for a chosen fault.

    Mirrors ``FrameStream.arm``: the two position faults travel the redundant
    sensing path, because a POSITION_Y fault armed on the injector is
    regenerated from ground truth by ``_publish_state`` and reaches nothing.

    Args:
        kind: One of :data:`FAULTS`, or ``""`` for a clean run.
        at: The tick the fault opens on.
        seed: The run seed.

    Returns:
        The injector and the sensing spec, both ready to hand to the harness.
    """
    injector = FaultInjector((), seed=seed, sigmas=CHANNEL_SIGMAS)
    sensing = RedundantSensing.build(sigmas=DEFAULT_CHANNEL_SIGMAS, seed=seed)
    if not kind:
        return injector, sensing

    if kind in POSITION_FAULTS:
        magnitude = POSITION_MAGNITUDE[kind]
        sensing.faulted = SensorModality.IMU
        sensing.also_faulted = (SensorModality.GPS,)
        sensing.opens_at = at
        sensing.closes_at = at + FAULT_WINDOW_TICKS
        if kind == "position_bias":
            sensing.bias, sensing.drift_per_tick = magnitude, 0.0
        else:
            sensing.bias = 0.0
            sensing.drift_per_tick = magnitude / float(FAULT_WINDOW_TICKS)
    else:
        injector.arm(build_injector(kind, tick=at, seed=seed))
    return injector, sensing


def narrate(
    *,
    ticks: int,
    seed: int,
    policy_path: Path,
    mode: str,
    every: int,
    pause: float,
    fault: str,
    at: int,
    tunnel: bool,
    colour: bool,
) -> int:
    """Drive the pipeline and narrate it.

    Args:
        ticks: How many control ticks to drive.
        seed: The run seed.
        policy_path: The trained proposer.
        mode: ``line``, ``explain`` or ``events``.
        every: Print one tick in this many.
        pause: Seconds to sleep after each printed tick.
        fault: The fault to inject, or ``""`` for a clean run.
        at: The tick the fault opens on.
        tunnel: Start in the uncertified context rather than the certified one.
        colour: Whether to colour the output.

    Returns:
        Process exit status.
    """
    palette = Palette(enabled=colour)
    policy = LearnedPolicy.load(policy_path)
    injector, sensing = _arm(fault, at, seed)
    narrator = Narrator(mode=mode, every=every, pause=pause, palette=palette)

    where = TUNNEL if tunnel else CERTIFIED
    print(f"{palette.bold}ASTRA -- the pipeline, tick by tick{palette.off}")
    print(
        f"{palette.dim}  {ticks} ticks at 20 Hz from seed {seed}"
        f" | context {'tunnel (uncertified)' if tunnel else 'certified road'}"
        f" | {f'{fault} at tick {at}, for {FAULT_WINDOW_TICKS} ticks (3.0 s)' if fault else 'no fault'}"
        f"\n  every value below is read from that tick's DecisionRecord; truth is"
        f" simulator-only and labelled{palette.off}\n"
    )

    drive_closed_loop(
        policy=policy,
        ticks=ticks,
        seed=seed,
        observer=narrator.observe,
        fault=injector,
        redundant=sensing,
        cold_path=cold_path(where),
    )
    print(f"\n{palette.dim}{narrator.printed} lines over {ticks} ticks.{palette.off}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments and narrate.

    Args:
        argv: Command-line arguments, or ``None`` for ``sys.argv``.

    Returns:
        Process exit status.
    """
    parser = argparse.ArgumentParser(
        description="Watch the ASTRA pipeline decide, one tick at a time.",
    )
    parser.add_argument("--ticks", "-n", type=int, default=400)
    parser.add_argument("--seed", type=int, default=_DEFAULT_SEED)
    parser.add_argument("--policy", type=Path, default=_DEFAULT_POLICY)
    parser.add_argument(
        "--explain",
        action="store_true",
        help="one labelled block per tick, every layer named",
    )
    parser.add_argument(
        "--events",
        action="store_true",
        help="only the ticks where something changed, with the reason",
    )
    parser.add_argument("--every", type=int, default=1, help="print one tick in this many")
    parser.add_argument(
        "--pause",
        type=float,
        default=0.0,
        help="seconds to wait after each printed tick; 0.05 is real time",
    )
    parser.add_argument("--fault", choices=FAULTS, default=None)
    parser.add_argument("--at", type=int, default=200, help="tick the fault opens on")
    parser.add_argument("--tunnel", action="store_true", help="start in the uncertified context")
    parser.add_argument("--no-color", action="store_true")
    arguments = parser.parse_args(argv)

    for artefact in (TWIN, CORPUS, arguments.policy):
        if not artefact.exists():
            print(f"missing {artefact}; see docs/EVIDENCE.md for how to regenerate it")
            return 1

    mode = "explain" if arguments.explain else ("events" if arguments.events else "line")
    colour = (
        not arguments.no_color
        and not os.environ.get("NO_COLOR")
        and hasattr(sys.stdout, "isatty")
        and sys.stdout.isatty()
    )
    return narrate(
        ticks=arguments.ticks,
        seed=arguments.seed,
        policy_path=arguments.policy,
        mode=mode,
        every=arguments.every,
        pause=arguments.pause,
        fault=arguments.fault or "",
        at=arguments.at,
        tunnel=arguments.tunnel,
        colour=colour,
    )


if __name__ == "__main__":
    raise SystemExit(main())
