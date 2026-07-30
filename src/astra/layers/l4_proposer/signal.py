"""The closed set of quantities Core-A is permitted to learn from (SI-6).

Why this type exists at all
---------------------------
Separation invariant SI-6 says Core-B's veto rate may be logged as a diagnostic
but must never enter Core-A's reward or constraint computation. The rationale in
the catalogue is worth restating because it is not obvious:

    Rewarding a low veto rate trains the proposer to avoid *detection* rather
    than to be *safe*. The two are indistinguishable to the optimiser and
    opposite in effect.

An agent penalised for being vetoed will find the cheapest way to stop being
vetoed. Being safer is one way. Learning the gate's blind spots is another, and
it is usually cheaper. The optimiser cannot tell them apart, so the only safe
move is to withhold the signal entirely.

Why a frozen record rather than a rule
---------------------------------------
Until now SI-6 was enforced by code review -- the catalogue records its
enforcement as ``REVIEW``, the one invariant of ten with no mechanism behind it.
A review catches a field named ``veto_rate``. It does not reliably catch a
reward shaped from ``gate_verdicts`` three call sites away, added in a hurry by
someone who did not read this docstring.

:class:`TrainingSignal` closes the set. It is frozen, it forbids extra fields at
construction, and :data:`PERMITTED_FIELDS` is asserted against its annotations by
the test suite. Adding a Core-B observable to Core-A's training signal now means
editing this file, and editing this file fails a test that names the invariant.

What is deliberately absent
----------------------------
No verdict. No gate identity. No veto count, rate or streak. No fail-safe state.
No conformal score, quantile or Trust Index. The last one deserves a note: the
Trust Index *is* passed to
:meth:`~astra.ports.pipeline.CommandProposer.propose` as a monitoring input, and
that is permitted -- SI-4 keeps it out of Core-B's verdict, not out of Core-A's
observation. It is excluded *here* because a monitoring input that reaches the
reward stops being a monitoring input and becomes an optimisation target.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Final

from astra.kernel.errors import InvariantViolationError

__all__ = ["PERMITTED_FIELDS", "TrainingSignal", "assert_signal_excludes_core_b"]

PERMITTED_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "lane_deviation_m",
        "longitudinal_acceleration_mps2",
        "speed_mps",
        "collided",
        "progress_m",
    }
)
"""Every quantity Core-A's reward and constraint computation may read.

The list is short on purpose. Each entry is a fact about the vehicle's own
motion, observable without reference to any safety component, and each maps to
one of the three constraints in the training formulation: C1 lane deviation, C2
longitudinal acceleration, C3 collision.
"""

_FORBIDDEN_SUBSTRINGS: Final[tuple[str, ...]] = (
    "veto",
    "verdict",
    "gate",
    "shield",
    "failsafe",
    "fail_safe",
    "trust",
    "conformal",
    "quantile",
    "nonconformity",
    "non_conformity",
    "alpha",
)
"""Fragments that mark a field as describing a Core-B artefact.

A blunt instrument, and deliberately so: it is a tripwire for the plausible
mistake -- someone adding ``recent_veto_rate`` or ``gate_margin`` to the reward
because it made training converge faster -- not a proof of absence. The
structural guarantee is :data:`PERMITTED_FIELDS`; this is the check that fires
with a message explaining *why* rather than only that a set comparison failed.
"""


@dataclass(frozen=True, slots=True)
class TrainingSignal:
    """One step's worth of what Core-A may optimise against.

    Frozen and slotted, so no field can be attached at runtime. A mutable signal
    would let a caller decorate it with a Core-B observable between construction
    and use, which is exactly the path this type exists to close.

    Attributes:
        lane_deviation_m: Lateral distance from the lane centre. Constraint C1.
        longitudinal_acceleration_mps2: Signed longitudinal acceleration.
            Constraint C2 bounds its magnitude.
        speed_mps: Current speed, for the reward's progress term.
        collided: Whether a collision occurred on this step. Constraint C3
            requires the rate to be zero.
        progress_m: Distance advanced along the route since the last step.
    """

    lane_deviation_m: float
    longitudinal_acceleration_mps2: float
    speed_mps: float
    collided: bool
    progress_m: float


def assert_signal_excludes_core_b() -> None:
    """Verify that the training signal names no Core-B artefact (SI-6).

    Called from the composition root at start-up as well as from the test suite,
    so a build that somehow shipped a widened signal still refuses to start a
    run rather than training against its own safety monitor.

    Raises:
        InvariantViolationError: If :class:`TrainingSignal` carries a field
            outside :data:`PERMITTED_FIELDS`, or one whose name contains a
            fragment naming a Core-B concept.
    """
    declared = {field.name for field in fields(TrainingSignal)}

    extra = declared - PERMITTED_FIELDS
    if extra:
        message = (
            f"the Core-A training signal declares {sorted(extra)}, which is outside the "
            f"permitted set. SI-6: rewarding a low veto rate trains the proposer to avoid "
            f"detection rather than to be safe, and the optimiser cannot tell those apart"
        )
        raise InvariantViolationError(message, context={"unexpected": sorted(extra)})

    offending = sorted(
        name
        for name in declared
        if any(fragment in name.lower() for fragment in _FORBIDDEN_SUBSTRINGS)
    )
    if offending:
        message = (
            f"the Core-A training signal declares {offending}, which names a Core-B "
            f"artefact. SI-6 forbids any Core-B observable from reaching the reward or "
            f"constraint computation, however it is spelled"
        )
        raise InvariantViolationError(message, context={"offending": offending})
