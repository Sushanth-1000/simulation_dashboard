"""Capturing a run's inputs to a replay tape.

The recorder sits beside the sensor bus, not inside it. L1's job is to fuse and
classify; persisting a tape is a separate concern with a separate failure mode,
and wiring it into the bus would mean a disk problem could affect sensing.

Blocking, and deliberately so
------------------------------
Unlike the audit sink, the recorder writes synchronously. The two have different
jobs and therefore different rules. The audit sink runs during live operation on
the hot path, so SI-8 forbids it from blocking a tick. Recording is a
*development and investigation* activity: a tape is captured when someone is
studying a run, and a dropped frame there would silently produce a tape that
replays into different behaviour than the run it claims to reproduce. Between
"slower" and "quietly wrong", a debugging instrument must choose slower.

This is stated rather than assumed because the asymmetry looks like an
inconsistency until the reason is known.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from astra.kernel.errors import AdapterError
from astra.replay.tape import TapeHeader, encode_frame, render_line

if TYPE_CHECKING:
    from types import TracebackType

    from astra.contracts.sensing import FusedSensorFrame
    from astra.kernel.identifiers import RunId
    from astra.kernel.time import Timeline
    from astra.replay.tape import PayloadCodec

__all__ = ["StateRecorder"]


class StateRecorder[PayloadT]:
    """Writes a run's fused sensor frames to a replay tape.

    Use as a context manager so the tape is closed on both the success and the
    error path -- a truncated tape from an aborted run is still replayable up to
    its last complete line, which is usually the interesting part.

    Attributes:
        frames_recorded: How many frames have been written.
    """

    __slots__ = ("_codec", "_handle", "_header", "_path", "frames_recorded")

    def __init__(
        self,
        *,
        run: RunId,
        timeline: Timeline,
        config_hash: str,
        codec: PayloadCodec[PayloadT],
        path: Path,
    ) -> None:
        """Open a tape and write its header.

        Args:
            run: The run being recorded.
            timeline: The timeline every recorded instant is measured against.
            config_hash: The configuration hash the run is executing under.
            codec: The payload codec supplied by the adapter.
            path: Where to write the tape.

        Raises:
            AdapterError: If the tape cannot be created.
            ContractViolationError: If the configuration hash is empty.
        """
        self._path = Path(path)
        self._codec = codec
        self._header = TapeHeader(run=run, timeline=timeline, config_hash=config_hash)
        self.frames_recorded = 0
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = self._path.open("w", encoding="utf-8")
            self._handle.write(render_line(self._header.to_payload()))
            self._handle.write("\n")
        except OSError as error:
            message = f"cannot open the replay tape at {self._path}"
            raise AdapterError(message, context={"path": str(self._path)}) from error

    @property
    def path(self) -> Path:
        """Return the path of the tape being written."""
        return self._path

    @property
    def header(self) -> TapeHeader:
        """Return the header written at the top of the tape."""
        return self._header

    def record(self, frame: FusedSensorFrame[PayloadT]) -> None:
        """Append one fused frame to the tape.

        Args:
            frame: The frame to record.

        Raises:
            AdapterError: If the frame cannot be written, or if the recorder has
                already been closed.
        """
        try:
            self._handle.write(render_line(encode_frame(frame, self._codec)))
            self._handle.write("\n")
        except (OSError, ValueError) as error:
            message = f"cannot write to the replay tape at {self._path}"
            raise AdapterError(message, context={"path": str(self._path)}) from error
        self.frames_recorded += 1

    def close(self) -> None:
        """Flush and close the tape. Idempotent."""
        if self._handle.closed:
            return
        try:
            self._handle.flush()
        finally:
            self._handle.close()

    def __enter__(self) -> StateRecorder[PayloadT]:
        """Enter the recorder's scope.

        Returns:
            This recorder.
        """
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the tape on scope exit, including on an exception path.

        Args:
            exc_type: The exception type, if the block raised.
            exc_value: The exception, if the block raised.
            traceback: The traceback, if the block raised.
        """
        self.close()
