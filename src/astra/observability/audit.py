"""The append-only JSONL audit sink. This file *is* the certification evidence.

What the architecture demands of this module
--------------------------------------------
NFR8 requires that every veto, Trust Index, FSM transition and calibration
switch be recorded with timestamps for post-hoc analysis and certification
evidence. SI-8 requires that cold-path work never block a hot-path tick. Those
two requirements are in direct tension: durable evidence means file I/O, and
file I/O inside a 50 ms tick with a 10 ms end-to-end budget is exactly the
blocking call that breaks the budget.

The resolution is a bounded queue and a background writer thread.
:meth:`JsonlAuditSink.emit` appends to an in-memory queue and returns; the
writer drains it and performs every syscall. The hot path pays a queue append.

Why the queue is bounded
------------------------
An unbounded queue turns a stalled disk into unbounded memory growth, which on
a real-time system is a worse failure than losing records. The queue is
therefore bounded, and an overflow is *counted and reported* rather than
silently discarded: :attr:`JsonlAuditSink.dropped_records` is non-zero if any
record was lost, and the run's evidence is then known to be incomplete. An
evidence archive that is silently incomplete is worse than one that admits a
gap, because only the second can be assessed honestly.

Why JSONL, one file per run
---------------------------
Append-only means a written record is never rewritten, so the log has the
tamper-evidence property a certification archive needs at prototype stage. One
file per run makes a run the unit of archival and replay. Line-delimited JSON
means a partially written file is still readable up to the last complete line --
which matters precisely when a run ended abnormally, the case whose evidence is
most interesting. Assumption A-3 records that this is adequate at prototype
stage and may need a signed log or a database for real certification.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import queue
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from astra.kernel.constants import AUDIT_SCHEMA_VERSION
from astra.kernel.errors import AdapterError

if TYPE_CHECKING:
    from types import TracebackType

    from astra.contracts.audit import AuditEvent, DecisionRecord, ExecutionOutcome, JsonValue
    from astra.kernel.identifiers import RunId

__all__ = ["EVENTS_FILENAME", "GENESIS_DIGEST", "ChainBreak", "JsonlAuditSink", "verify_chain"]

GENESIS_DIGEST: Final = "0" * 64
"""The ``previous_digest`` of a run's first record.

A fixed value rather than a random one, so a verifier needs nothing but the
file to check the chain from its first line.
"""

EVENTS_FILENAME: Final = "events.jsonl"
"""Name of the evidence file written inside each run's directory."""

_SHUTDOWN_SENTINEL: Final = None
_WRITER_JOIN_TIMEOUT_S: Final = 5.0


class JsonlAuditSink:
    """An append-only, non-blocking, one-file-per-run JSONL evidence sink.

    Satisfies the :class:`~astra.ports.infrastructure.EventSink` protocol
    structurally; it does not inherit from it, because the port exists to keep
    the dependency arrow pointing inward.

    Use as a context manager, or call :meth:`close` explicitly. Failing to close
    leaves the writer thread draining and the final records unflushed, so the
    composition root owns the lifetime rather than any layer.

    Attributes:
        dropped_records: How many records were discarded because the queue was
            full. Non-zero means this run's evidence has a gap and must be
            reported as incomplete.
    """

    __slots__ = (
        "_closed",
        "_fsync",
        "_handle",
        "_path",
        "_previous_digest",
        "_queue",
        "_seal",
        "_thread",
        "dropped_records",
    )

    def __init__(
        self,
        *,
        run: RunId,
        directory: Path,
        queue_size: int = 10_000,
        fsync_each_record: bool = False,
    ) -> None:
        """Open the sink and start its background writer.

        Args:
            run: The run whose evidence this sink records. Names the directory.
            directory: Root under which the run's directory is created.
            queue_size: Bound on the in-memory queue.
            fsync_each_record: Whether to force each record to disk as it is
                written. Durable but slow; never blocks a tick either way.

        Raises:
            AdapterError: If the run directory or evidence file cannot be
                created.
        """
        self._path = Path(directory) / run.value / EVENTS_FILENAME
        self._fsync = fsync_each_record
        self.dropped_records = 0
        self._closed = False
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = self._path.open("a", encoding="utf-8")
        except OSError as error:
            message = f"cannot open the audit log at {self._path}"
            raise AdapterError(message, context={"path": str(self._path)}) from error

        self._previous_digest = GENESIS_DIGEST
        self._seal = threading.Lock()
        self._queue: queue.Queue[str | None] = queue.Queue(maxsize=queue_size)
        self._thread = threading.Thread(
            target=self._drain,
            name=f"astra-audit-{run.value}",
            daemon=True,
        )
        self._thread.start()

    @property
    def path(self) -> Path:
        """Return the path of the evidence file this sink writes."""
        return self._path

    # ----------------------------------------------------------------- #
    # EventSink protocol
    # ----------------------------------------------------------------- #

    def emit(self, event: AuditEvent) -> None:
        """Record one audit event. Non-blocking.

        Args:
            event: The event to record.
        """
        self._enqueue(event.to_payload())

    def record_decision(self, record: DecisionRecord) -> None:
        """Record one tick's full decision provenance. Non-blocking.

        Args:
            record: The decision record for the tick.
        """
        payload = record.to_payload()
        payload["record_type"] = "decision"
        self._enqueue(payload)

    def record_outcome(self, outcome: ExecutionOutcome) -> None:
        """Record what actually happened after a command was applied. Non-blocking.

        Args:
            outcome: The executed outcome and the loops it feeds.
        """
        payload = outcome.to_payload()
        payload["record_type"] = "outcome"
        self._enqueue(payload)

    def flush(self) -> None:
        """Drain the queue and force buffered records to durable storage.

        Blocking, and therefore never called from within a tick. Called at
        shutdown so a run's evidence is complete even as the process stops.

        Raises:
            AdapterError: If the underlying file could not be flushed.
        """
        self._queue.join()
        if self._closed:
            return
        try:
            self._handle.flush()
        except (OSError, ValueError) as error:
            # ValueError as well as OSError: flushing a handle that has already
            # been closed raises ValueError, and a caller must not have to
            # distinguish "the disk failed" from "the sink was already shut
            # down" at the point of use. Both are AdapterError.
            message = f"cannot flush the audit log at {self._path}"
            raise AdapterError(message, context={"path": str(self._path)}) from error

    # ----------------------------------------------------------------- #
    # Lifetime
    # ----------------------------------------------------------------- #

    def close(self) -> None:
        """Stop the writer, drain the queue and close the file.

        Idempotent, so a composition root that closes on both the success and
        the error path is correct rather than merely tolerable.
        """
        if self._closed:
            return
        self._closed = True
        self._queue.put(_SHUTDOWN_SENTINEL)
        self._thread.join(timeout=_WRITER_JOIN_TIMEOUT_S)
        try:
            self._handle.flush()
        finally:
            self._handle.close()

    def __enter__(self) -> JsonlAuditSink:
        """Enter the sink's scope.

        Returns:
            This sink.
        """
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the sink on scope exit, including on an exception path.

        Args:
            exc_type: The exception type, if the block raised.
            exc_value: The exception, if the block raised.
            traceback: The traceback, if the block raised.
        """
        self.close()

    # ----------------------------------------------------------------- #
    # Internals
    # ----------------------------------------------------------------- #

    def _enqueue(self, payload: dict[str, JsonValue]) -> None:
        """Serialise a payload and queue it without blocking.

        Serialisation happens on the calling thread deliberately: it is cheap
        and CPU-bound, and doing it here means a record that cannot be
        serialised is detected at its origin rather than silently dropped inside
        the writer, where no caller could learn of it.

        Args:
            payload: The JSON-serialisable record.
        """
        payload.setdefault("schema_version", AUDIT_SCHEMA_VERSION)
        # The chain is sealed here rather than in the writer thread because this
        # is where the queue's order is fixed, and the queue is FIFO into a
        # single writer -- so enqueue order *is* file order. Sealing in the
        # writer would be equally correct and would move a hash computation onto
        # the thread whose job is not to fall behind.
        with self._seal:
            payload["previous_digest"] = self._previous_digest
            line = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
            self._previous_digest = hashlib.sha256(line.encode("utf-8")).hexdigest()
        try:
            self._queue.put_nowait(line)
        except queue.Full:
            # Counted, never silently ignored: a run whose evidence has a gap
            # must be reportable as incomplete.
            self.dropped_records += 1

    def _drain(self) -> None:
        """Write queued records until the shutdown sentinel arrives.

        Runs on the background thread. Every syscall in this class happens here,
        which is what keeps the hot path free of I/O (SI-8).
        """
        while True:
            line = self._queue.get()
            if line is _SHUTDOWN_SENTINEL:
                self._queue.task_done()
                return
            try:
                self._handle.write(line)
                self._handle.write("\n")
                if self._fsync:
                    self._handle.flush()
            except (OSError, ValueError):
                # The evidence writer must never take down the pipeline it is
                # observing: a lost log line is a FAIL_OPERATIONAL condition,
                # accounted for in `dropped_records`, not a safety event.
                self.dropped_records += 1
            finally:
                self._queue.task_done()


@dataclass(frozen=True, slots=True)
class ChainBreak:
    """Where an evidence log stops being self-consistent.

    Attributes:
        index: Zero-based line number of the first record that does not follow
            from its predecessor.
        expected: The digest that record should have carried.
        found: The digest it did carry, or ``None`` if the field was absent.
        reason: Which check failed, for a human reading a report.
    """

    index: int
    expected: str | None
    found: str | None
    reason: str


def verify_chain(path: Path) -> ChainBreak | None:
    """Check that an evidence file is an unbroken hash chain.

    Each record carries the SHA-256 digest of the *serialised line* before it,
    the first carrying :data:`GENESIS_DIGEST`. Altering, removing or inserting a
    record therefore breaks every link after it.

    **What this detects, and the one thing it does not.** Alteration, deletion
    and insertion anywhere in the file are caught. **Truncation of the tail is
    not**, and cannot be by a chain alone: a prefix of a valid chain is itself a
    valid chain. Catching that needs an external record of the expected length,
    or a signed root -- and signing needs key management, which this project
    does not have. See ``docs/THREAT_MODEL.md`` §5.4.

    This makes the log **tamper-evident**, not tamper-proof. An adversary who
    can rewrite the file can also recompute the chain. What it removes is the
    *silent* alteration: changing one record now requires rewriting every record
    after it, which a verifier comparing against an independently held digest
    of the final record will still catch.

    Args:
        path: The evidence file.

    Returns:
        The first break, or ``None`` if the chain is intact.

    Raises:
        AdapterError: If the file cannot be read.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as error:
        message = f"cannot read the audit log at {path}"
        raise AdapterError(message, context={"path": str(path)}) from error

    expected = GENESIS_DIGEST
    for index, line in enumerate(text.splitlines()):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return ChainBreak(index=index, expected=expected, found=None, reason="unparseable")
        found = payload.get("previous_digest")
        if not isinstance(found, str):
            return ChainBreak(index=index, expected=expected, found=None, reason="missing")
        if not hmac.compare_digest(found, expected):
            return ChainBreak(index=index, expected=expected, found=found, reason="mismatch")
        expected = hashlib.sha256(line.encode("utf-8")).hexdigest()
    return None
