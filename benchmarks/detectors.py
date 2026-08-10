"""Candidate answers to OD-9, run with no authority over any verdict.

Why they are here and not in ``src/astra/``
--------------------------------------------
Because none of them has earned it yet. The standing convention this project
adopted after FB2 and FB3 is that **no mechanism gets authority until it has run
with none**, and it exists because two feedback loops were measured in shadow
and both turned out to break the gate they fed. FB2 would have collapsed the
non-conformity score 40% while every metric continued to look healthy (E-39);
FB3 would have pinned the veto rate to epsilon by construction (E-40). Neither
would have shown up as an error.

So a detector here is a **pure function of a**
:class:`~astra.contracts.audit.DecisionRecord`. It reads what the pipeline
already recorded, returns a boolean, and cannot influence anything. That is not
a limitation of this module, it is the whole design: a detector that cannot
change a verdict cannot flatter itself, and the table it produces is the
evidence for whether it deserves to be wired.

What OD-9 is
-------------
Every Core-B gate reads L2's fast estimate, and the proposer closes the loop on
that same estimate — so it actively drives a corrupted reading to the value the
gates consider safe. Measured: a 200-tick IMU dropout put the vehicle 4.199 m
off a 1.75 m lane while the corridor bound read **0.023 m**, with a verdict
trace identical to the clean control's (E-46, E-48).

The question these detectors answer is narrow and precise: **was there anything
in the record that could have seen it?**

The three candidates, and what each is a test of
-------------------------------------------------
``health``
    Fire when any modality is not ``HEALTHY`` for a sustained run of ticks. Tests
    P2.7 option A. L1's staleness machinery already produces this and only L9's
    context signature reads it; no gate does. Cheap, and expected to catch
    ``DROPOUT`` and nothing else — ``BIAS``, ``DRIFT`` and ``STUCK_AT`` all keep
    the stream perfectly *fresh*, which is why those faults were chosen.
``innovation``
    Fire when the fast innovation's Mahalanobis distance stays above a threshold.
    Tests P2.7 option B, and it is the principled candidate: the innovation is
    the one recorded quantity that can *disagree* with the estimate, because it
    is measured before the filter settles rather than after.
``trust``
    Fire when the Trust Index stays below a threshold. Not a fourth idea — L3
    derives it from the innovation sequence — but it is what a monitor could
    gate on **today** with no new plumbing at all, so the gap between it and
    ``innovation`` is worth having on the record.

Thresholds, and the honest problem with them
----------------------------------------------
Every threshold below is fitted to the *control* run and to nothing else: take
the clean run's distribution, place the threshold outside it, require ``PATIENCE``
consecutive ticks. That gives a detector which by construction does not fire on
nominal driving, and it is the weakest possible calibration — a threshold chosen
against six hand-picked faults would be fitted to its own test set, which is the
defect E-41 records for the conformal corpus and it would be no better here.

**A detector that fires below is worth investigating. A detector that stays
silent is the finding**, because silence cannot be an artefact of a threshold
placed too high when the fault moved the signal not at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from astra.kernel.enums import StreamHealth

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from astra.contracts.audit import DecisionRecord

__all__ = ["DETECTORS", "Detection", "Detector", "evaluate"]

PATIENCE = 5
"""Consecutive ticks a condition must hold before a detector fires.

A quarter of a second at 20 Hz. Long enough that a single noisy reading is not
an alarm, short enough that a fault which is going to put the vehicle out of its
corridor is caught with time to act: the measured departures took 73 and 34
ticks to develop.
"""

_TRUST_FLOOR = 0.80
"""Below the clean run's minimum Trust Index of 0.85 (E-23 territory)."""

_INNOVATION_CEILING = 3.0
"""Three sigma on a Mahalanobis distance the clean run holds well below."""


@dataclass(frozen=True, slots=True)
class Detector:
    """One candidate, and the sentence it is a test of.

    Attributes:
        name: Short identifier.
        tests: Which P2.7 option this is evidence for.
        condition: Returns whether this tick looks wrong. Pure, and reading only
            what the pipeline already recorded.
    """

    name: str
    tests: str
    condition: Callable[[DecisionRecord], bool]


def _health_is_degraded(record: DecisionRecord) -> bool:
    """Return whether any modality reports worse than healthy."""
    return any(health is not StreamHealth.HEALTHY for _, health in record.frame_health)


def _innovation_is_high(record: DecisionRecord) -> bool:
    """Return whether the fast innovation exceeds its ceiling."""
    return record.fast_innovation is not None and record.fast_innovation > _INNOVATION_CEILING


def _trust_is_low(record: DecisionRecord) -> bool:
    """Return whether the Trust Index sits below its floor."""
    return record.trust is not None and float(record.trust.trust_index) < _TRUST_FLOOR


DETECTORS: tuple[Detector, ...] = (
    Detector("health", "P2.7 option A -- gate on StreamHealth", _health_is_degraded),
    Detector("innovation", "P2.7 option B -- gate on the innovation sequence", _innovation_is_high),
    Detector("trust", "what a monitor could gate on today, with no new plumbing", _trust_is_low),
)


@dataclass(frozen=True, slots=True)
class Detection:
    """What one detector did on one run.

    Attributes:
        detector: Which candidate.
        fired_at: The first tick it fired on, or ``None`` if it never did.
        latency_ticks: Ticks between the fault opening and the detector firing,
            or ``None`` if it never fired or no fault was injected. **The number
            that decides whether a detector is useful**: a detector that fires
            after the vehicle has left its corridor has reported history.
        fired_ticks: How many ticks the condition held in total.
        false_alarm: Whether it fired on ticks where no fault was active. On the
            control run every firing is a false alarm by definition.
    """

    detector: str
    fired_at: int | None
    latency_ticks: int | None
    fired_ticks: int
    false_alarm: bool


def evaluate(
    records: Sequence[DecisionRecord],
    *,
    fault_active: Sequence[bool],
    opened_at: int | None,
) -> tuple[Detection, ...]:
    """Run every detector over one run's records and score it against ground truth.

    Args:
        records: The run's decision records, in tick order.
        fault_active: Per-tick ground truth, the same length as ``records``.
        opened_at: The tick the fault opened, or ``None`` for a clean run.

    Returns:
        One detection per detector, in :data:`DETECTORS` order.
    """
    results: list[Detection] = []
    for detector in DETECTORS:
        run_length = 0
        fired_at: int | None = None
        fired_ticks = 0
        false_alarm = False
        for index, record in enumerate(records):
            if detector.condition(record):
                run_length += 1
                if run_length >= PATIENCE:
                    fired_ticks += 1
                    if fired_at is None:
                        fired_at = index
                    if not fault_active[index]:
                        false_alarm = True
            else:
                run_length = 0
        results.append(
            Detection(
                detector=detector.name,
                fired_at=fired_at,
                latency_ticks=(
                    None if fired_at is None or opened_at is None else fired_at - opened_at
                ),
                fired_ticks=fired_ticks,
                false_alarm=false_alarm,
            )
        )
    return tuple(results)
