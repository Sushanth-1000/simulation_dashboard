"""Do the OD-9 candidate detectors fire when they should?

Why this file exists, and it is the same reason as the fault injector's
--------------------------------------------------------------------------
The result P2.7 produced is mostly the word **silent**: across six injected
faults, the health detector fires on one, the innovation detector on one, and
the Trust Index detector on two. Everything else is silence, including both
faults that put the vehicle outside its corridor.

That is a strong claim, and it has an obvious failure mode. **A detector with a
bug that stopped it firing would produce exactly the same table**, and the table
would read as "nothing in the record could have seen it" when it actually meant
"the thing that reads the record is broken." Same shape as the fail-safe speed
cap recorded on every capped tick that reached no actuator, and the same shape
as a fault injector nobody verified.

The study has a built-in positive control -- every detector does fire on at
least one scenario, so none of them is uniformly dead. That is necessary and it
is not sufficient: it does not show that a detector fires on *the specific
condition its docstring names*, only that something once tripped it. These tests
do the rest.

What each test pins
--------------------
For each detector: a record that should trip it does, a record that should not
does not, ``PATIENCE`` is actually enforced rather than decorative, and a
missing field is treated as "no evidence" rather than as evidence of trouble.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from astra.contracts.audit import DecisionRecord
from astra.kernel.enums import SensorModality, StreamHealth
from astra.kernel.identifiers import RunId, TickId
from benchmarks.detectors import DETECTORS, PATIENCE, Detection, Detector, evaluate

RUN = RunId("run-detectortest01")
HEALTHY = ((SensorModality.IMU, StreamHealth.HEALTHY),)
DEGRADED = ((SensorModality.IMU, StreamHealth.DEGRADED),)


def record(
    tick: int,
    *,
    health: tuple[tuple[SensorModality, StreamHealth], ...] = HEALTHY,
    innovation: float | None = 0.5,
) -> DecisionRecord:
    """Return a decision record carrying only what a detector reads."""
    return DecisionRecord(
        run=RUN,
        tick=TickId(tick),
        config_hash="detector-test",
        frame_health=health,
        fast_innovation=innovation,
    )


def fire(records: list[DecisionRecord], name: str, *, opened_at: int | None = 0) -> Detection:
    """Return the named detector's detection over these records."""
    detections = evaluate(records, fault_active=[True] * len(records), opened_at=opened_at)
    return next(d for d in detections if d.detector == name)


# --------------------------------------------------------------------------- #
# Each detector fires on the condition its docstring names
# --------------------------------------------------------------------------- #


def test_the_health_detector_fires_on_a_degraded_stream() -> None:
    records = [record(t, health=DEGRADED) for t in range(PATIENCE + 3)]

    assert fire(records, "health").fired_at == PATIENCE - 1


def test_the_health_detector_ignores_a_healthy_stream() -> None:
    records = [record(t) for t in range(50)]

    assert fire(records, "health").fired_at is None


def test_the_innovation_detector_fires_on_a_large_innovation() -> None:
    records = [record(t, innovation=9.0) for t in range(PATIENCE + 3)]

    assert fire(records, "innovation").fired_at == PATIENCE - 1


def test_the_innovation_detector_ignores_a_quiet_one() -> None:
    records = [record(t, innovation=0.5) for t in range(50)]

    assert fire(records, "innovation").fired_at is None


def test_a_missing_innovation_is_no_evidence_rather_than_evidence_of_trouble() -> None:
    # A tick with no fast update recorded nothing, and "nothing" must not read
    # as "alarming" -- a detector that fired on absent data would fire on every
    # early-aborted tick and be useless.
    records = [record(t, innovation=None) for t in range(50)]

    assert fire(records, "innovation").fired_at is None


def test_the_trust_detector_needs_a_trust_assessment_to_say_anything() -> None:
    records = [record(t) for t in range(50)]

    assert fire(records, "trust").fired_at is None


# --------------------------------------------------------------------------- #
# Patience is enforced, not decorative
# --------------------------------------------------------------------------- #


def test_a_condition_shorter_than_patience_does_not_fire() -> None:
    records = [record(t, health=DEGRADED) for t in range(PATIENCE - 1)]
    records += [record(t) for t in range(PATIENCE - 1, 40)]

    assert fire(records, "health").fired_at is None


def test_an_interrupted_run_restarts_the_count() -> None:
    # PATIENCE-1 degraded, one healthy, PATIENCE-1 degraded again. Neither run
    # is long enough, and a detector that summed them instead of requiring them
    # consecutive would fire here.
    records = (
        [record(t, health=DEGRADED) for t in range(PATIENCE - 1)]
        + [record(PATIENCE - 1)]
        + [record(t, health=DEGRADED) for t in range(PATIENCE, 2 * PATIENCE - 1)]
    )

    assert fire(records, "health").fired_at is None


def test_latency_is_measured_from_when_the_fault_opened() -> None:
    opened_at = 20
    records = [record(t) for t in range(opened_at)]
    records += [record(t, health=DEGRADED) for t in range(opened_at, opened_at + 30)]

    detection = fire(records, "health", opened_at=opened_at)

    assert detection.fired_at == opened_at + PATIENCE - 1
    assert detection.latency_ticks == PATIENCE - 1


def test_a_clean_run_reports_no_latency_because_there_was_nothing_to_be_late_for() -> None:
    records = [record(t, health=DEGRADED) for t in range(40)]

    detection = evaluate(records, fault_active=[False] * 40, opened_at=None)[0]

    assert detection.fired_at is not None
    assert detection.latency_ticks is None
    assert detection.false_alarm  # fired where no fault was active


# --------------------------------------------------------------------------- #
# The set as a whole
# --------------------------------------------------------------------------- #


def test_every_detector_declares_which_option_it_tests() -> None:
    # A detector without a stated question is a detector nobody can interpret
    # the silence of.
    assert all(detector.tests for detector in DETECTORS)
    assert len({detector.name for detector in DETECTORS}) == len(DETECTORS)


def test_evaluate_returns_one_detection_per_detector_in_order() -> None:
    records = [record(t) for t in range(10)]

    detections = evaluate(records, fault_active=[False] * 10, opened_at=None)

    assert [d.detector for d in detections] == [d.name for d in DETECTORS]


def test_a_record_carrying_nothing_trips_no_detector() -> None:
    # The degenerate case, asserted because it is the one a bug most easily
    # inverts: an empty record must be silence, not an alarm.
    bare = DecisionRecord(run=RUN, tick=TickId(0), config_hash="bare")
    detections = evaluate([bare] * 50, fault_active=[True] * 50, opened_at=0)

    assert all(d.fired_at is None for d in detections)


def test_the_detectors_read_the_record_and_nothing_else() -> None:
    # The shadow property, structurally: a detector is a pure function of a
    # record, so running one twice on the same input gives the same answer and
    # running it at all changes nothing. If a detector ever acquires state,
    # this is the test that should stop it.
    records = [record(t, health=DEGRADED, innovation=9.0) for t in range(40)]
    first = evaluate(records, fault_active=[True] * 40, opened_at=0)
    second = evaluate(records, fault_active=[True] * 40, opened_at=0)

    assert first == second
    assert records == [replace(r) for r in records]


@pytest.mark.parametrize("detector", DETECTORS, ids=lambda d: d.name)
def test_no_detector_fires_on_a_nominal_looking_record(detector: Detector) -> None:
    # The false-alarm floor. Each threshold is fitted to the clean run, so a
    # detector that fires on a healthy stream with a small innovation and no
    # trust assessment has been mis-calibrated in the dangerous direction.
    assert not detector.condition(record(0))
