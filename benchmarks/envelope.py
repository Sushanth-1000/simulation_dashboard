"""Where is this vehicle repeatedly driving that nothing has certified?

The idea
---------
The commissioning certificate says which contexts a platform is fit for. Most of
them come back ``BOUNDED`` -- no profile matched, the vehicle drove anyway inside
the narrowed envelope, and nothing was learned from it. That is the architecture
working, and it is also a waste: the vehicle has just accumulated hours of
evidence about a context nobody has calibrated for, and thrown it away.

So: read the evidence log, find the sustained stretches spent outside every
certified profile, and **propose them as calibration work**.

What it proposes, and the line it must not cross
--------------------------------------------------
**It proposes a calibration *request*, never a calibration *profile*.**

That distinction is the whole safety argument and it is not a stylistic
preference. A profile carries a **conformal quantile table**, and a quantile
table derived from the vehicle's own exploration episode is FB3 wearing a new
hat: requantilising on self-generated scores drives the veto rate to
``significance_epsilon`` **by construction**, because epsilon of any distribution
lies above its own 1-epsilon quantile (E-40). The gate stops being a detector and
becomes a fixed-rate sampler, and nothing about the change looks like an error.

So a request carries what the vehicle can honestly claim to know:

- the **centroid and spread** of the signature it kept meeting,
- its **safety record** while there -- veto rate, worst deviation, fail-safe
  posture, whether every tick issued a command,
- the **nearest certified profile** and how far away it is,
- and a pointer to the ticks in the evidence log that back all of it.

It carries **no quantile table, no coverage level, and no certification dates**,
because those are claims the vehicle has no basis to make. Turning a request into
a profile requires an offline calibration run against held-out data and a human
signature. That is not a limitation to be engineered away later; it is the
mechanism.

Why this is offline, reading records
--------------------------------------
It never runs inside a tick. It is a pure function of an audit log, which gives
three things at once:

*It cannot influence anything.* The standing convention -- no mechanism gets
authority until it has run with none -- is satisfied structurally rather than by
discipline. There is no wire to cut because none was ever laid.

*It is how a fleet would actually work.* Vehicles upload evidence; a backend
aggregates it and proposes calibration work. Putting this in the tick loop would
model a fleet of one.

*It inherits the audit log's integrity.* The log is a hash chain, so a proposal
derived from it is derived from evidence whose alteration is detectable.

This depends on OD-14 being closed
------------------------------------
Until 11 August 2026 the arbitration record carried the outcome and the trust
score but **not the signature RCM decided on**, so the log could say
``SAFE_EXPLORATION`` and could not say *what context* that was about. A proposal
needs exactly that field. Audit schema 6 -> 7 added it; this module is
unbuildable against a version-6 archive and says so rather than guessing.

What makes an episode proposable
----------------------------------
Three conditions, and the third is the one that is easy to forget.

**Sustained.** A handful of ticks outside every profile is a transition, not a
context. ``_MINIMUM_TICKS`` sets the floor.

**Safe.** If the vehicle was escalating, vetoing heavily, or outside its
corridor, the episode is evidence *against* operating there, not for it. A
request built from an unsafe episode would ask an engineer to certify a context
the vehicle handled badly.

**Coherent.** The signature must have stayed in one place. A vehicle that passes
through three unfamiliar contexts in one stretch produces a mean signature
describing **none of them**, and a request built on that average would point
calibration effort at a context that does not exist. ``_COHERENCE_LIMIT`` bounds
the spread; an incoherent episode is reported as such rather than silently
averaged.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from astra.kernel.constants import RCS_DIMENSION, RCS_FIELDS
from astra.kernel.enums import ArbitrationOutcome

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

__all__ = ["Episode", "Request", "propose", "read_ticks"]

_MINIMUM_TICKS = 200
"""Ticks an episode must last before it is worth proposing. Ten seconds at 20 Hz.

Below this a stretch outside every profile is a *transition* -- entering a
tunnel, a sensor recovering, a manoeuvre -- rather than a context anyone would
calibrate for. Set an order of magnitude above the arbitration period, so an
episode must survive several independent re-evaluations.
"""

_COHERENCE_LIMIT = 0.15
"""Largest per-component standard deviation an episode may have and still be one.

The signature components are all normalised to ``[0, 1]``, so this is 15% of the
full range of any component. An episode whose visibility wandered from 0.05 to
0.9 is two contexts, and its mean describes neither.

Deliberately generous. A tight limit would reject real contexts that vary --
weather does -- and the failure mode of being too generous is a request an
engineer reads and declines, while the failure mode of being too tight is a
context nobody ever hears about.
"""

_MAXIMUM_VETO_RATE = 0.10
"""Veto rate above which an episode is evidence against the context, not for it."""


@dataclass(slots=True)
class Episode:
    """One sustained stretch outside every certified profile.

    Attributes:
        first_tick: Where it started.
        last_tick: Where it ended.
        signatures: Every signature recorded during it.
        vetoed: Ticks whose aggregate verdict was blocking.
        issued: Ticks that issued a command.
        escalated: Ticks whose fail-safe posture was not NOMINAL.
        active_profile: The profile that stayed active throughout -- the nearest
            thing to a neighbour this episode has.
    """

    first_tick: int
    last_tick: int
    signatures: list[tuple[float, ...]] = field(default_factory=list)
    vetoed: int = 0
    issued: int = 0
    escalated: int = 0
    active_profile: str = "-"

    @property
    def ticks(self) -> int:
        """Return how many ticks the episode ran for."""
        return self.last_tick - self.first_tick + 1


@dataclass(frozen=True, slots=True)
class Request:
    """A calibration request, not a profile -- and the difference is the point.

    Attributes:
        first_tick: Where the evidence starts.
        last_tick: Where it ends.
        ticks: How long the episode lasted.
        centroid: The mean signature, ordered per ``RCS_FIELDS``. What an
            engineer would calibrate *around*.
        spread: Per-component standard deviation. What they would calibrate
            *across*, and the number that decides whether this is one context.
        nearest_profile: The profile active throughout -- the closest thing the
            knowledge base already has.
        veto_rate: Blocking verdicts per tick during the episode.
        escalated_ticks: Ticks whose fail-safe posture was not NOMINAL.
        availability: Ticks that issued a command, over ticks. Should be 1.0;
            anything less means the vehicle was not driving.
        coherent: Whether every component's spread is inside
            :data:`_COHERENCE_LIMIT`.
        proposable: Whether this passes every condition. **An unproposable
            request is still reported**, with the reason -- a proposer that
            silently dropped what it rejected would give an engineer no way to
            find out its filters were wrong.
        reason: Why it is or is not proposable.

    """

    first_tick: int
    last_tick: int
    ticks: int
    centroid: tuple[float, ...]
    spread: tuple[float, ...]
    nearest_profile: str
    veto_rate: float
    escalated_ticks: int
    availability: float
    coherent: bool
    proposable: bool
    reason: str


def read_ticks(path: Path) -> Iterator[dict[str, object]]:
    """Yield the decision records in an audit log, in order.

    Args:
        path: A JSONL audit log, or a directory containing one.

    Yields:
        Each record as a mapping.

    Raises:
        ValueError: If the log predates audit schema 7 and therefore carries no
            signature. Guessing one would invent the very field this module
            exists to read.
    """
    if path.is_dir():
        candidates = sorted(path.glob("*.jsonl"))
        if not candidates:
            message = f"no .jsonl audit log under {path}"
            raise ValueError(message)
        path = candidates[0]

    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            version = record.get("schema_version")
            if isinstance(version, int) and version < _REQUIRED_SCHEMA:
                message = (
                    f"{path} is audit schema v{version}; this needs v{_REQUIRED_SCHEMA} or "
                    "later, which is the version that began recording the arbitration "
                    "signature (OD-14). A v6 archive cannot say what context a decision "
                    "was about."
                )
                raise ValueError(message)
            yield record


_REQUIRED_SCHEMA = 7
"""The audit schema version that began recording the arbitration signature."""


def _episodes(records: Sequence[dict[str, object]]) -> list[Episode]:
    """Split a record stream into sustained exploration episodes.

    Args:
        records: Decision records in tick order.

    Returns:
        Every stretch of consecutive ticks in ``SAFE_EXPLORATION``, however
        short. Filtering happens later, in :func:`propose`, so that a rejected
        episode can still be reported with its reason.
    """
    episodes: list[Episode] = []
    current: Episode | None = None

    for record in records:
        arbitration = record.get("arbitration")
        exploring = (
            isinstance(arbitration, dict)
            and arbitration.get("outcome") == ArbitrationOutcome.SAFE_EXPLORATION.value
        )
        if not exploring:
            current = None
            continue

        if not isinstance(arbitration, dict):  # pragma: no cover - `exploring` implies it
            continue

        raw_tick = record.get("tick")
        if not isinstance(raw_tick, int):  # pragma: no cover - every record carries one
            continue
        tick = raw_tick
        if current is None or tick != current.last_tick + 1:
            current = Episode(first_tick=tick, last_tick=tick)
            episodes.append(current)
        current.last_tick = tick

        signature = arbitration.get("signature")
        if isinstance(signature, list) and len(signature) == RCS_DIMENSION:
            current.signatures.append(tuple(float(value) for value in signature))
        current.active_profile = str(arbitration.get("active_profile", "-"))

        verdict = record.get("safety_verdict")
        if isinstance(verdict, dict) and verdict.get("aggregate") == "VETO":
            current.vetoed += 1
        if record.get("issued") is not None:
            current.issued += 1
        failsafe = record.get("failsafe")
        if isinstance(failsafe, dict) and failsafe.get("state") != "NOMINAL":
            current.escalated += 1

    return episodes


def _summarise(episode: Episode) -> Request:
    """Reduce one episode to a request, judged against every condition.

    Args:
        episode: The episode.

    Returns:
        The request, proposable or not, with the reason either way.
    """
    columns = list(zip(*episode.signatures, strict=True)) if episode.signatures else []
    centroid = tuple(statistics.fmean(column) for column in columns)
    spread = tuple(statistics.stdev(column) if len(column) > 1 else 0.0 for column in columns)
    coherent = bool(spread) and max(spread) <= _COHERENCE_LIMIT
    veto_rate = episode.vetoed / episode.ticks if episode.ticks else 0.0
    availability = episode.issued / episode.ticks if episode.ticks else 0.0

    if not episode.signatures:
        reason, proposable = "no signature recorded; needs audit schema v7", False
    elif episode.ticks < _MINIMUM_TICKS:
        reason, proposable = (
            f"a transition, not a context: {episode.ticks} ticks < {_MINIMUM_TICKS}",
            False,
        )
    elif not coherent:
        worst = max(range(len(spread)), key=lambda index: spread[index])
        reason, proposable = (
            (
                f"incoherent: {RCS_FIELDS[worst]} spread {spread[worst]:.3f} "
                f"> {_COHERENCE_LIMIT}; this is more than one context"
            ),
            False,
        )
    elif veto_rate > _MAXIMUM_VETO_RATE:
        reason, proposable = (
            f"unsafe: {veto_rate:.1%} of ticks vetoed; evidence against this context",
            False,
        )
    elif episode.escalated:
        reason, proposable = (
            f"unsafe: {episode.escalated} ticks with the fail-safe escalated",
            False,
        )
    elif not math.isclose(availability, 1.0):
        reason, proposable = (
            f"the vehicle was not driving: {availability:.1%} of ticks issued a command",
            False,
        )
    else:
        reason, proposable = (
            f"{episode.ticks} ticks, {veto_rate:.1%} vetoed, NOMINAL throughout",
            True,
        )

    return Request(
        first_tick=episode.first_tick,
        last_tick=episode.last_tick,
        ticks=episode.ticks,
        centroid=centroid,
        spread=spread,
        nearest_profile=episode.active_profile,
        veto_rate=veto_rate,
        escalated_ticks=episode.escalated,
        availability=availability,
        coherent=coherent,
        proposable=proposable,
        reason=reason,
    )


def propose(records: Sequence[dict[str, object]]) -> list[Request]:
    """Return one request per exploration episode, proposable or not.

    Args:
        records: Decision records in tick order.

    Returns:
        Every episode, judged. Rejected ones are included with their reason.
    """
    return [_summarise(episode) for episode in _episodes(records)]


def render(requests: Sequence[Request]) -> list[str]:
    """Return the requests, as lines.

    Args:
        requests: What :func:`propose` returned.

    Returns:
        Lines to print.
    """
    lines = [
        "",
        "  CALIBRATION REQUESTS -- read from the evidence log, proposing nothing",
        "  that could activate. A request is work for an engineer, not a profile.",
        "",
    ]
    if not requests:
        lines.append("  No exploration episodes in this log.")
        return lines

    for index, request in enumerate(requests, start=1):
        mark = "PROPOSE" if request.proposable else "reject "
        lines.append(
            f"  [{mark}] episode {index}: ticks {request.first_tick}-{request.last_tick} "
            f"({request.ticks}), nearest {request.nearest_profile}"
        )
        lines.append(f"            {request.reason}")
        if request.centroid:
            components = ", ".join(
                f"{name}={value:.3f}+-{deviation:.3f}"
                for name, value, deviation in zip(
                    RCS_FIELDS, request.centroid, request.spread, strict=True
                )
            )
            lines.append(f"            {components}")
        lines.append("")

    proposable = sum(1 for request in requests if request.proposable)
    lines.extend(
        [
            f"  {proposable} of {len(requests)} episodes are proposable.",
            "",
            "  A request carries a centroid, a spread, a safety record and a",
            "  pointer to the ticks behind it. It carries NO quantile table and",
            "  NO coverage level: a table fitted to the vehicle's own exploration",
            "  is FB3 by another name, and would pin the veto rate to epsilon by",
            "  construction (E-40). Turning a request into a certified profile",
            "  needs an offline calibration run and a human signature.",
        ]
    )
    return lines


def main(argv: list[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Command-line arguments, or ``None`` for ``sys.argv``.

    Returns:
        Zero unless the log is unreadable.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("log", type=Path, help="a JSONL audit log, or a directory holding one")
    parser.add_argument("--output", "-o", type=Path, default=None)
    arguments = parser.parse_args(argv)

    try:
        records = list(read_ticks(arguments.log))
    except (OSError, ValueError) as error:
        print(f"  {error}")
        return 1

    requests = propose(records)
    for line in render(requests):
        print(line)

    if arguments.output is not None:
        arguments.output.mkdir(parents=True, exist_ok=True)
        (arguments.output / "requests.json").write_text(
            json.dumps([asdict(request) for request in requests], indent=2),
            encoding="utf-8",
        )
        print(f"\n  requests: {arguments.output / 'requests.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
