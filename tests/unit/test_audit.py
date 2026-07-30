"""Unit tests for the append-only JSONL audit sink.

Nothing here waits on the writer thread by sleeping. The sink exposes
:meth:`JsonlAuditSink.flush`, which joins the queue, and :meth:`close`, which
joins the thread; both are deterministic synchronisation points, and a test that
slept instead would be a timing-dependent test in a safety codebase.
"""

from __future__ import annotations

import json
import queue
from typing import TYPE_CHECKING

import pytest

from astra.contracts.actuation import CommandOrigin, ControlCommand, IssuedCommand
from astra.contracts.audit import AuditEvent, DecisionRecord, ExecutionOutcome
from astra.kernel.constants import AUDIT_SCHEMA_VERSION
from astra.kernel.enums import EventSeverity, FeedbackLoop
from astra.kernel.errors import AdapterError
from astra.kernel.identifiers import EventId, RunId, TickId
from astra.observability.audit import EVENTS_FILENAME, JsonlAuditSink

if TYPE_CHECKING:
    from pathlib import Path

    from astra.contracts.actuation import ActuationSpace
    from astra.kernel.identifiers import ComponentId
    from astra.kernel.time import Instant

CONFIG_HASH = "sha256:9f86d081884c7d65"


def _event(run: RunId, tick: TickId, sequence: int, kind: str) -> AuditEvent:
    return AuditEvent(
        event_id=EventId(run=run, tick=tick, sequence=sequence),
        severity=EventSeverity.NOTICE,
        kind=kind,
        payload={"sequence": sequence},
    )


def _issued(tick: TickId, now: Instant, space: ActuationSpace, rcm: ComponentId) -> IssuedCommand:
    return IssuedCommand(
        tick=tick,
        issued_at=now,
        command=ControlCommand(space=space, values=(0.4, 0.2)),
        origin=CommandOrigin.PROPOSED,
        issuer=rcm,
    )


def _lines(sink: JsonlAuditSink) -> list[dict[str, object]]:
    sink.flush()
    text = sink.path.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines()]


# --------------------------------------------------------------------------- #
# Layout: one file per run
# --------------------------------------------------------------------------- #


def test_the_sink_writes_one_evidence_file_beneath_a_directory_named_for_the_run(
    run: RunId, tmp_path: Path
) -> None:
    with JsonlAuditSink(run=run, directory=tmp_path) as sink:
        assert sink.path == tmp_path / run.value / EVENTS_FILENAME


def test_the_run_directory_and_the_evidence_file_exist_as_soon_as_the_sink_opens(
    run: RunId, tmp_path: Path
) -> None:
    with JsonlAuditSink(run=run, directory=tmp_path) as sink:
        assert sink.path.is_file()
        assert sink.path.parent.is_dir()


def test_two_sinks_for_two_runs_write_to_two_separate_files(tmp_path: Path) -> None:
    first = RunId("run-alpha0001")
    second = RunId("run-beta00002")

    with (
        JsonlAuditSink(run=first, directory=tmp_path) as alpha,
        JsonlAuditSink(run=second, directory=tmp_path) as beta,
    ):
        assert alpha.path != beta.path
        assert alpha.path.parent.name == first.value
        assert beta.path.parent.name == second.value


# --------------------------------------------------------------------------- #
# Append-only, in order, one JSON line per record
# --------------------------------------------------------------------------- #


def test_each_emitted_event_lands_as_exactly_one_json_line(
    audit_sink: JsonlAuditSink, run: RunId, tick: TickId
) -> None:
    for sequence in range(5):
        audit_sink.emit(_event(run, tick, sequence, "tick_start"))

    assert len(_lines(audit_sink)) == 5


def test_events_are_written_in_the_order_they_were_emitted(
    audit_sink: JsonlAuditSink, run: RunId, tick: TickId
) -> None:
    kinds = ("tick_start", "veto", "fsm_transition", "calibration_switch", "tick_end")
    for sequence, kind in enumerate(kinds):
        audit_sink.emit(_event(run, tick, sequence, kind))

    assert tuple(record["kind"] for record in _lines(audit_sink)) == kinds


def test_a_second_batch_of_events_is_appended_after_the_first(
    audit_sink: JsonlAuditSink, run: RunId, tick: TickId
) -> None:
    audit_sink.emit(_event(run, tick, 0, "first"))
    audit_sink.flush()
    audit_sink.emit(_event(run, tick, 1, "second"))

    assert [record["kind"] for record in _lines(audit_sink)] == ["first", "second"]


def test_every_written_line_parses_as_json_and_carries_the_audit_schema_version(
    *,
    audit_sink: JsonlAuditSink,
    run: RunId,
    tick: TickId,
    now: Instant,
    actuation_space: ActuationSpace,
    rcm_component: ComponentId,
) -> None:
    audit_sink.emit(_event(run, tick, 0, "tick_start"))
    audit_sink.record_decision(DecisionRecord(run=run, tick=tick, config_hash=CONFIG_HASH))
    audit_sink.record_outcome(
        ExecutionOutcome(tick=tick, applied=_issued(tick, now, actuation_space, rcm_component))
    )

    records = _lines(audit_sink)

    assert len(records) == 3
    assert all(record["schema_version"] == AUDIT_SCHEMA_VERSION for record in records)


def test_a_written_line_is_compact_and_contains_no_embedded_newline(
    audit_sink: JsonlAuditSink, run: RunId, tick: TickId
) -> None:
    audit_sink.emit(_event(run, tick, 0, "tick_start"))
    audit_sink.flush()

    text = audit_sink.path.read_text(encoding="utf-8")

    assert text.endswith("\n")
    assert text.count("\n") == 1
    assert ", " not in text


# --------------------------------------------------------------------------- #
# The three record-writing entry points
# --------------------------------------------------------------------------- #


def test_emit_writes_the_events_flattened_identity_and_payload(
    audit_sink: JsonlAuditSink, run: RunId, tick: TickId
) -> None:
    audit_sink.emit(_event(run, tick, 3, "veto"))

    (record,) = _lines(audit_sink)

    assert record["run"] == run.value
    assert record["tick"] == tick.value
    assert record["sequence"] == 3
    assert record["kind"] == "veto"
    assert record["payload"] == {"sequence": 3}


def test_record_decision_marks_the_line_as_a_decision(
    audit_sink: JsonlAuditSink, run: RunId, tick: TickId
) -> None:
    audit_sink.record_decision(DecisionRecord(run=run, tick=tick, config_hash=CONFIG_HASH))

    (record,) = _lines(audit_sink)

    assert record["record_type"] == "decision"
    assert record["config_hash"] == CONFIG_HASH


def test_record_outcome_marks_the_line_as_an_outcome(
    audit_sink: JsonlAuditSink,
    tick: TickId,
    now: Instant,
    actuation_space: ActuationSpace,
    rcm_component: ComponentId,
) -> None:
    audit_sink.record_outcome(
        ExecutionOutcome(
            tick=tick,
            applied=_issued(tick, now, actuation_space, rcm_component),
            measured=(("a_lat", 1.2),),
            feeds=frozenset({FeedbackLoop.FB1_UKF_REANCHOR}),
        )
    )

    (record,) = _lines(audit_sink)

    assert record["record_type"] == "outcome"
    assert record["measured"] == {"a_lat": 1.2}


def test_a_plain_audit_event_carries_no_record_type(
    audit_sink: JsonlAuditSink, run: RunId, tick: TickId
) -> None:
    audit_sink.emit(_event(run, tick, 0, "tick_start"))

    (record,) = _lines(audit_sink)

    assert "record_type" not in record


# --------------------------------------------------------------------------- #
# The bounded queue: overflow is counted, never silent
# --------------------------------------------------------------------------- #


def test_a_record_that_cannot_be_queued_is_counted_rather_than_silently_discarded(
    run: RunId, tmp_path: Path
) -> None:
    sink = JsonlAuditSink(run=run, directory=tmp_path, queue_size=1)
    drained = sink._queue
    # Swap in a queue that is already at its bound and that nothing is draining.
    # This exercises the overflow branch deterministically: the alternative --
    # racing the background writer by emitting fast enough to outpace it -- would
    # be a timing-dependent test, which is worse than no test at all here.
    blocked: queue.Queue[str | None] = queue.Queue(maxsize=1)
    blocked.put_nowait("already-at-the-bound")
    sink._queue = blocked
    try:
        for sequence in range(3):
            sink.emit(_event(run, TickId(0), sequence, "overflowed"))
    finally:
        sink._queue = drained
        sink.close()

    assert sink.dropped_records == 3


def test_a_sink_that_never_overflowed_reports_no_dropped_records(
    audit_sink: JsonlAuditSink, run: RunId, tick: TickId
) -> None:
    for sequence in range(64):
        audit_sink.emit(_event(run, tick, sequence, "tick_start"))
    audit_sink.flush()

    assert audit_sink.dropped_records == 0


def test_the_records_that_did_fit_are_still_written_when_others_were_dropped(
    run: RunId, tmp_path: Path
) -> None:
    sink = JsonlAuditSink(run=run, directory=tmp_path, queue_size=8)
    sink.emit(_event(run, TickId(0), 0, "kept"))
    sink.flush()

    drained = sink._queue
    blocked: queue.Queue[str | None] = queue.Queue(maxsize=1)
    blocked.put_nowait("already-at-the-bound")
    sink._queue = blocked
    try:
        sink.emit(_event(run, TickId(0), 1, "lost"))
    finally:
        sink._queue = drained
        sink.close()

    records = [json.loads(line) for line in sink.path.read_text(encoding="utf-8").splitlines()]
    assert [record["kind"] for record in records] == ["kept"]
    assert sink.dropped_records == 1


def test_a_record_the_writer_could_not_write_is_counted_rather_than_taking_down_the_run(
    run: RunId, tmp_path: Path
) -> None:
    sink = JsonlAuditSink(run=run, directory=tmp_path)
    broken = (tmp_path / "broken").open("a", encoding="utf-8")
    broken.close()
    healthy = sink._handle
    sink._handle = broken
    try:
        sink.emit(_event(run, TickId(0), 0, "unwritable"))
        # `join` is the sink's own synchronisation point, not a sleep: it returns
        # once the writer has called `task_done` for the queued record.
        sink._queue.join()
    finally:
        sink._handle = healthy
        sink.close()

    assert sink.dropped_records == 1


# --------------------------------------------------------------------------- #
# Lifetime
# --------------------------------------------------------------------------- #


def test_the_context_manager_closes_the_sink_on_exit(run: RunId, tmp_path: Path) -> None:
    with JsonlAuditSink(run=run, directory=tmp_path) as sink:
        sink.emit(_event(run, TickId(0), 0, "tick_start"))

    assert sink.path.read_text(encoding="utf-8").count("\n") == 1
    assert not sink._thread.is_alive()


def test_the_context_manager_closes_the_sink_when_the_block_raises(
    run: RunId, tmp_path: Path
) -> None:
    sink = JsonlAuditSink(run=run, directory=tmp_path)

    def emit_then_fail() -> None:
        with sink:
            sink.emit(_event(run, TickId(0), 0, "tick_start"))
            raise ZeroDivisionError

    with pytest.raises(ZeroDivisionError):
        emit_then_fail()

    assert sink.path.read_text(encoding="utf-8").count("\n") == 1


def test_closing_the_sink_twice_is_harmless(run: RunId, tmp_path: Path) -> None:
    sink = JsonlAuditSink(run=run, directory=tmp_path)
    sink.emit(_event(run, TickId(0), 0, "tick_start"))

    sink.close()
    sink.close()

    assert sink.path.read_text(encoding="utf-8").count("\n") == 1


def test_flushing_a_closed_sink_does_not_touch_the_closed_file_handle(
    run: RunId, tmp_path: Path
) -> None:
    sink = JsonlAuditSink(run=run, directory=tmp_path)
    sink.emit(_event(run, TickId(0), 0, "tick_start"))
    sink.close()

    sink.flush()

    assert sink.path.read_text(encoding="utf-8").count("\n") == 1


def test_flushing_a_sink_whose_handle_was_closed_underneath_it_raises_adapter_error(
    run: RunId, tmp_path: Path
) -> None:
    # Flushing a closed handle raises ValueError, not OSError. A caller must not
    # have to distinguish "the disk failed" from "the handle went away": both
    # are reported as AdapterError.
    sink = JsonlAuditSink(run=run, directory=tmp_path)
    try:
        sink._handle.close()

        with pytest.raises(AdapterError):
            sink.flush()
    finally:
        sink._closed = True


def test_an_fsyncing_sink_still_writes_every_record(run: RunId, tmp_path: Path) -> None:
    with JsonlAuditSink(run=run, directory=tmp_path, fsync_each_record=True) as sink:
        for sequence in range(3):
            sink.emit(_event(run, TickId(0), sequence, "tick_start"))

    assert sink.path.read_text(encoding="utf-8").count("\n") == 3


# --------------------------------------------------------------------------- #
# Failure to open
# --------------------------------------------------------------------------- #


def test_opening_the_sink_where_the_directory_is_actually_a_file_raises_an_adapter_error(
    run: RunId, tmp_path: Path
) -> None:
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("this is a file, not a directory", encoding="utf-8")

    with pytest.raises(AdapterError) as raised:
        JsonlAuditSink(run=run, directory=blocker)

    assert raised.value.context["path"] == str(blocker / run.value / EVENTS_FILENAME)
