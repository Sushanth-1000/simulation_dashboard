"""SI-8: cold-path work must never block a hot-path tick.

The invariant catalogue has claimed a non-blocking audit sink since Phase 1, and
until now nothing measured it. A claim of enforcement that nothing implements is
worse than an honest admission of none, so this file measures the property the
claim rests on.

What is actually being asserted
--------------------------------
Not "the sink is fast" -- that is a benchmark, and a benchmark that passes on a
quiet laptop says nothing about a loaded one. What matters is *structural*: the
hot path hands a record to a queue and returns, and the cost of turning it into
bytes and putting it on a disk is paid by a different thread.

So the assertions are about **decoupling**, not about absolute microseconds:

* the hot path's cost does not scale with how slow the *I/O* is;
* a saturated queue drops records rather than blocking the caller;
* the caller's cost does not grow as the backlog grows.

One thing this file deliberately does **not** assert is that serialisation is
free. It is not, and it is not meant to be: `_enqueue` renders the JSON on the
calling thread on purpose, so that a record which cannot be serialised is
detected at its origin instead of vanishing inside a writer no caller can hear.
SI-8 is about keeping *syscalls* off the tick, and every syscall in the sink
happens in `_drain`.

A timing test that asserted "under N milliseconds" would fail on a busy CI
machine for reasons unrelated to the invariant. These comparisons hold whatever
the machine is doing, because both sides of each comparison move together.
"""

from __future__ import annotations

import statistics
import threading
import time
from typing import TYPE_CHECKING

import pytest

from astra.contracts.audit import AuditEvent, DecisionRecord
from astra.kernel.enums import EventSeverity
from astra.kernel.identifiers import EventId, RunId, TickId
from astra.observability.audit import JsonlAuditSink

if TYPE_CHECKING:
    from pathlib import Path

RUN = RunId("run-si8timing0001")
CONFIG_HASH = "af00c940369eaf79"

# A backlog far larger than any tick would produce, so that the "does the cost
# grow with the backlog" comparison has something to measure.
BACKLOG = 2_000
SAMPLES = 400

# The hot path may not be more than this multiple of its own quiet cost when the
# writer is deliberately obstructed. Generous on purpose: the point is that the
# ratio is bounded at all, not that it is close to one. A blocking sink would
# show a ratio in the thousands, because the caller would inherit the writer's
# sleep.
DECOUPLING_RATIO = 25.0


def _record(tick: int) -> DecisionRecord:
    return DecisionRecord(run=RUN, tick=TickId(tick), config_hash=CONFIG_HASH)


def _event(tick: int) -> AuditEvent:
    return AuditEvent(
        event_id=EventId(run=RUN, tick=TickId(tick), sequence=0),
        severity=EventSeverity.INFO,
        kind="si8_probe",
        payload={"tick": tick},
    )


def _median_cost(sink: JsonlAuditSink, *, first_tick: int, samples: int) -> float:
    """Return the median wall-clock cost of one `record_decision`, in seconds."""
    costs: list[float] = []
    for offset in range(samples):
        record = _record(first_tick + offset)
        start = time.perf_counter()
        sink.record_decision(record)
        costs.append(time.perf_counter() - start)
    return statistics.median(costs)


# --------------------------------------------------------------------------- #
# The hot path does not inherit the writer's cost
# --------------------------------------------------------------------------- #


def test_the_hot_path_cost_does_not_track_slow_disk_writes(tmp_path: Path) -> None:
    # The decisive comparison. If `record_decision` did its own I/O, making each
    # write expensive would show up directly in the caller's timing. Because
    # every syscall happens on the writer thread, it does not.
    #
    # `fsync_each_record` is the honest lever for this: it is a real setting that
    # makes the writer do substantially more work per record, and it costs the
    # caller nothing.
    quiet = JsonlAuditSink(run=RUN, directory=tmp_path / "quiet", fsync_each_record=False)
    baseline = _median_cost(quiet, first_tick=0, samples=SAMPLES)
    quiet.close()

    syncing = JsonlAuditSink(run=RUN, directory=tmp_path / "sync", fsync_each_record=True)
    encumbered = _median_cost(syncing, first_tick=0, samples=SAMPLES)
    syncing.close()

    assert encumbered <= max(baseline, 1e-6) * DECOUPLING_RATIO


def test_every_syscall_in_the_sink_happens_on_the_writer_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The structural claim behind SI-8, checked directly rather than inferred
    # from timing: the thread that calls `record_decision` must not be the
    # thread that touches the file.
    sink = JsonlAuditSink(run=RUN, directory=tmp_path, fsync_each_record=True)
    writing_threads: set[int] = set()
    handle = sink._handle
    original_write = handle.write

    def _tracking_write(text: str) -> int:
        writing_threads.add(threading.get_ident())
        return original_write(text)

    monkeypatch.setattr(handle, "write", _tracking_write)
    caller = threading.get_ident()
    for tick in range(200):
        sink.record_decision(_record(tick))
    sink.flush()
    monkeypatch.undo()
    sink.close()

    assert writing_threads, "no write was observed, so the test proved nothing"
    assert caller not in writing_threads


def test_the_hot_path_cost_does_not_grow_with_the_backlog(tmp_path: Path) -> None:
    # A caller that blocked when the queue filled would get slower and slower as
    # the backlog built. Measured early and late in a long burst, it does not.
    sink = JsonlAuditSink(
        run=RUN, directory=tmp_path, queue_size=BACKLOG * 4, fsync_each_record=False
    )

    early = _median_cost(sink, first_tick=0, samples=SAMPLES)
    for tick in range(BACKLOG):
        sink.record_decision(_record(SAMPLES + tick))
    late = _median_cost(sink, first_tick=SAMPLES + BACKLOG, samples=SAMPLES)
    sink.close()

    assert late <= max(early, 1e-6) * DECOUPLING_RATIO


# --------------------------------------------------------------------------- #
# A saturated queue drops rather than blocks
# --------------------------------------------------------------------------- #


def test_a_full_queue_never_blocks_the_caller(tmp_path: Path) -> None:
    # This test completing at all is the proof. A sink that blocked on a full
    # queue with a stalled writer would hang here rather than fail, so the
    # bounded join below is what turns that into a loud failure.
    sink = JsonlAuditSink(run=RUN, directory=tmp_path, queue_size=4, fsync_each_record=False)
    finished = threading.Event()

    def flood() -> None:
        for tick in range(5_000):
            sink.record_decision(_record(tick))
        finished.set()

    worker = threading.Thread(target=flood)
    worker.start()
    worker.join(timeout=30.0)
    completed = finished.is_set()
    sink.close()

    assert completed, "record_decision blocked on a saturated queue"
    assert not worker.is_alive()


def test_dropped_records_are_counted_rather_than_lost_silently(tmp_path: Path) -> None:
    # Dropping under saturation is the correct trade -- a late verdict about a
    # vehicle that has already moved is not a verdict -- but a drop nobody can
    # see would make the evidence archive quietly incomplete.
    sink = JsonlAuditSink(run=RUN, directory=tmp_path, queue_size=2, fsync_each_record=False)

    for tick in range(3_000):
        sink.record_decision(_record(tick))
    sink.close()

    written = sum(
        1
        for path in tmp_path.rglob("*.jsonl")
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    assert written + sink.dropped_records == 3_000


# --------------------------------------------------------------------------- #
# Events take the same path as decisions
# --------------------------------------------------------------------------- #


def test_emitting_an_event_is_as_decoupled_as_recording_a_decision(
    tmp_path: Path,
) -> None:
    sink = JsonlAuditSink(run=RUN, directory=tmp_path, queue_size=8, fsync_each_record=False)
    finished = threading.Event()

    def flood() -> None:
        for tick in range(5_000):
            sink.emit(_event(tick))
        finished.set()

    worker = threading.Thread(target=flood)
    worker.start()
    worker.join(timeout=30.0)
    completed = finished.is_set()
    sink.close()

    assert completed, "emit blocked on a saturated queue"
    assert not worker.is_alive()
