"""Re-driving a recorded run.

The harness reads a tape and replays it as two things at once: a sequence of
fused frames, and a :class:`~astra.kernel.time.Clock` that reports the instants
those frames were fused at. That pairing is the point. Replaying frames while
components read a live clock would reproduce the *data* of a run but not its
*timing*, and every staleness classification -- the whole of FR1 -- is a
statement about timing. A replay that got staleness wrong would exonerate bugs
that a real run exhibits.

Segments
--------
:meth:`ReplayHarness.frames` accepts a tick range, which is the "freeze and
replay a specific tick range" capability the Demo Plan asks for. Investigating
an oscillation means re-running the fifty ticks around it repeatedly, not the
whole drive.

What the harness does not do
-----------------------------
It does not construct a pipeline. It yields frames and offers a clock; wiring
those into a sensor bus, a filter or a whole runtime is the caller's decision,
because different investigations need different amounts of the system. Building
the pipeline in here would make the harness useless for the cases that only need
part of it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from astra.contracts.audit import JsonValue
from astra.kernel.errors import AdapterError, ContractViolationError
from astra.kernel.time import UNIX_EPOCH, Instant
from astra.replay.tape import TapeHeader, decode_frame

if TYPE_CHECKING:
    from collections.abc import Iterator
    from datetime import datetime

    from astra.contracts.sensing import FusedSensorFrame
    from astra.kernel.identifiers import RunId, TickId
    from astra.kernel.time import Timeline
    from astra.replay.tape import PayloadCodec

__all__ = ["ReplayClock", "ReplayHarness"]


class ReplayClock:
    """A clock that reports the instant of the frame currently being replayed.

    Satisfies :class:`~astra.kernel.time.Clock` structurally. Time advances only
    when the harness moves to the next frame, so a component under replay sees
    exactly the timeline the recorded run saw.

    :meth:`wall_clock` returns a fixed epoch rather than the real civil time.
    Replay must be byte-reproducible, and a real civil time would differ on every
    replay; a fixed value keeps any record derived from it stable. It is
    documented on the ``Clock`` protocol as being for human correlation only and
    never for arithmetic, so a constant is safe here in a way it would not be for
    :meth:`now`.
    """

    __slots__ = ("_instant", "_timeline")

    def __init__(self, timeline: Timeline) -> None:
        """Initialise the clock at the timeline's origin.

        Args:
            timeline: The timeline recorded in the tape header.
        """
        self._timeline = timeline
        self._instant = Instant(0, timeline)

    @property
    def timeline(self) -> Timeline:
        """Return the timeline this clock measures against."""
        return self._timeline

    def now(self) -> Instant:
        """Return the instant of the frame currently being replayed.

        Returns:
            The current instant on the recorded timeline.
        """
        return self._instant

    def wall_clock(self) -> datetime:
        """Return a fixed civil time, so replayed records stay byte-stable.

        Returns:
            The Unix epoch, timezone-aware in UTC.
        """
        return UNIX_EPOCH

    def _rewind(self) -> None:
        """Return the clock to the timeline's origin, ready for another pass.

        Called by :class:`ReplayHarness` at the start of each traversal. Replay
        is expected to be repeated -- investigating an oscillation means running
        the same fifty ticks over and over -- so a harness whose clock could
        only move forwards once would refuse the second pass. Rewinding is
        legitimate here in a way it never is for a live clock, because a replay
        clock is re-reading recorded history rather than measuring time.
        """
        self._instant = Instant(0, self._timeline)

    def _advance_to(self, instant: Instant) -> None:
        """Move the clock to a recorded instant.

        Called only by :class:`ReplayHarness`.

        Args:
            instant: The instant of the frame about to be yielded.

        Raises:
            ContractViolationError: If the instant is on a different timeline, or
                would move the clock backwards. A tape whose instants are not
                monotonic did not come from a monotonic clock, and replaying it
                would produce staleness values the original run could not have
                seen.
        """
        if instant.timeline is not self._timeline:
            message = (
                f"replayed instant is on timeline {instant.timeline.value}, "
                f"but the tape declares {self._timeline.value}"
            )
            raise ContractViolationError(message)
        if instant.nanoseconds < self._instant.nanoseconds:
            message = (
                f"replay tape moves backwards in time, from {self._instant.nanoseconds} ns "
                f"to {instant.nanoseconds} ns"
            )
            raise ContractViolationError(
                message,
                context={
                    "from_ns": self._instant.nanoseconds,
                    "to_ns": instant.nanoseconds,
                },
            )
        self._instant = instant


class ReplayHarness[PayloadT]:
    """Reads a replay tape and re-drives the frames it recorded."""

    __slots__ = ("_clock", "_codec", "_header", "_path")

    def __init__(self, *, path: Path, codec: PayloadCodec[PayloadT]) -> None:
        """Open a tape and read its header.

        Args:
            path: The tape to replay.
            codec: The payload codec supplied by the adapter. Must be the same
                codec, or a compatible one, as the recording used.

        Raises:
            AdapterError: If the tape cannot be read.
            ContractViolationError: If the tape is empty or its header is
                malformed.
            SchemaVersionError: If the tape was written by another version.
        """
        self._path = Path(path)
        self._codec = codec
        self._header = self._read_header()
        self._clock = ReplayClock(self._header.timeline)

    def _read_header(self) -> TapeHeader:
        """Read and validate the tape's first line.

        Returns:
            The header.

        Raises:
            AdapterError: If the tape cannot be opened.
            ContractViolationError: If the tape is empty or the header is not a
                JSON object.
        """
        try:
            with self._path.open(encoding="utf-8") as handle:
                first = handle.readline()
        except OSError as error:
            message = f"cannot read the replay tape at {self._path}"
            raise AdapterError(message, context={"path": str(self._path)}) from error
        if not first.strip():
            message = f"replay tape at {self._path} is empty"
            raise ContractViolationError(message, context={"path": str(self._path)})
        return TapeHeader.from_payload(_parse_object(first, self._path, line_number=1))

    @property
    def header(self) -> TapeHeader:
        """Return the tape's header."""
        return self._header

    @property
    def run(self) -> RunId:
        """Return the identity of the run this tape reproduces.

        Replay adopts this identity rather than generating a fresh one, so the
        replayed records carry the identity of the run being reproduced and the
        two event streams are directly comparable.
        """
        return self._header.run

    @property
    def clock(self) -> ReplayClock:
        """Return the clock that tracks the frame currently being replayed.

        Inject this wherever the recorded run used its own clock.
        """
        return self._clock

    def frames(
        self,
        *,
        first_tick: TickId | None = None,
        last_tick: TickId | None = None,
    ) -> Iterator[FusedSensorFrame[PayloadT]]:
        """Yield the recorded frames, advancing the clock to each in turn.

        The harness is reusable: each call rewinds the clock first, so the same
        segment can be replayed repeatedly against successive fixes. That is the
        intended workflow, not an edge case.

        Args:
            first_tick: Skip frames before this tick. ``None`` starts at the
                beginning.
            last_tick: Stop after this tick, inclusive. ``None`` runs to the end.

        Yields:
            Each recorded frame, in tape order, with :attr:`clock` already moved
            to that frame's fusion instant.

        Raises:
            AdapterError: If the tape cannot be read.
            ContractViolationError: If a record is malformed, or the tape moves
                backwards in time.
        """
        try:
            handle = self._path.open(encoding="utf-8")
        except OSError as error:
            message = f"cannot read the replay tape at {self._path}"
            raise AdapterError(message, context={"path": str(self._path)}) from error

        self._clock._rewind()  # noqa: SLF001 - the harness owns the clock

        with handle:
            for line_number, line in enumerate(handle, start=1):
                if line_number == 1 or not line.strip():
                    continue
                payload = _parse_object(line, self._path, line_number=line_number)
                if payload.get("record_type") != "frame":
                    continue
                frame = decode_frame(payload, self._codec, self._header.timeline)
                if first_tick is not None and frame.tick.value < first_tick.value:
                    continue
                if last_tick is not None and frame.tick.value > last_tick.value:
                    return
                self._clock._advance_to(frame.fused_at)  # noqa: SLF001 - the harness owns the clock
                yield frame


def _parse_object(line: str, path: Path, *, line_number: int) -> dict[str, JsonValue]:
    """Parse one tape line into a JSON object.

    Args:
        line: The raw line.
        path: The tape's path, for diagnostics.
        line_number: The 1-based line number, for diagnostics.

    Returns:
        The parsed object.

    Raises:
        ContractViolationError: If the line is not a JSON object.
    """
    try:
        parsed = json.loads(line)
    except ValueError as error:
        message = f"replay tape {path} line {line_number} is not valid JSON: {error}"
        raise ContractViolationError(
            message, context={"path": str(path), "line": line_number}
        ) from error
    if not isinstance(parsed, dict):
        message = f"replay tape {path} line {line_number} is not a JSON object"
        raise ContractViolationError(message, context={"path": str(path), "line": line_number})
    return parsed
