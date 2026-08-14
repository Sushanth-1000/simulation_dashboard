"""Audit contracts: the evidence records that make a run certifiable.

NFR8 makes the audit log a certification artefact, not a debugging aid: every
veto, Trust Index, FSM transition and calibration switch must be recorded so a
run can be reconstructed and defended after the fact. Three records carry that
weight.

* :class:`AuditEvent` is the atomic log entry. Its payload is validated to be
  JSON-serialisable *at construction*, so an event that could not become
  evidence fails when it is built, not when the log is written.

* :class:`DecisionRecord` is the explainability unit (finding R-7): for one
  tick it ties together frame health, state estimate, Trust Index, the
  proposal, the twin's prediction, every gate verdict, the FSM snapshot, the
  arbitration decision, the issued command and the configuration hash under
  which all of it happened. It answers "why did the vehicle do that, on what
  evidence, under which calibration" without any model-internal attribution.

* :class:`ExecutionOutcome` closes the loop: the command actually applied, what
  was measured afterwards, and which feedback loops that outcome feeds.

Round-trip guarantee
--------------------
The audit sink writes each record as one JSON line and offline tools read those
lines back as JSON. The property that matters is therefore that a record's
rendered payload is *stable* through serialisation: parsing the JSON and
re-serialising it yields byte-identical output. :meth:`DecisionRecord.to_json`
produces that payload, and it is built from ordered dictionaries of JSON scalars
only -- no sets, no mappings with non-string keys -- so the guarantee holds by
construction rather than by hope.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from astra.kernel.constants import AUDIT_SCHEMA_VERSION
from astra.kernel.enums import EventSeverity, FeedbackLoop
from astra.kernel.errors import ContractViolationError
from astra.kernel.validation import require_finite

if TYPE_CHECKING:
    from astra.contracts.actuation import (
        ControlCommand,
        IssuedCommand,
        PredictedCommand,
        ProposedCommand,
    )
    from astra.contracts.assurance import (
        FailSafeSnapshot,
        GateVerdict,
        SafetyVerdict,
        TrustAssessment,
    )
    from astra.contracts.estimation import FastStateEstimate
    from astra.contracts.governance import ArbitrationDecision
    from astra.kernel.enums import SensorModality, StreamHealth
    from astra.kernel.identifiers import EventId, RunId, TickId
    from astra.kernel.time import Instant

__all__ = [
    "AuditEvent",
    "DecisionRecord",
    "ExecutionOutcome",
    "JsonValue",
]

type JsonValue = bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"] | None
"""The value space of a JSON document. Every rendered audit payload is one."""


def _render_instant(instant: Instant) -> dict[str, JsonValue]:
    """Render an instant as a timeline-tagged nanosecond offset."""
    return {"nanoseconds": instant.nanoseconds, "timeline": instant.timeline.value}


def _render_command(command: ControlCommand) -> dict[str, JsonValue]:
    """Render a control command as a channel-name-keyed mapping of values."""
    return dict(zip(command.space.names, command.values, strict=True))


def _render_fast_state(estimate: FastStateEstimate) -> dict[str, JsonValue]:
    """Render the fast state estimate: mean, covariance and validity instant."""
    return {
        "valid_at": _render_instant(estimate.valid_at),
        "mean": list(estimate.mean),
        "covariance": [list(row) for row in estimate.covariance.to_rows()],
    }


def _render_trust(trust: TrustAssessment) -> dict[str, JsonValue]:
    """Render the trust assessment."""
    return {
        "trust_index": float(trust.trust_index),
        "context_class": trust.context_class.value,
        "class_conditional_quantile": trust.class_conditional_quantile,
        "coverage_target": float(trust.coverage_target),
        "calibration_sample_count": trust.calibration_sample_count,
        "is_calibrated": trust.is_calibrated,
    }


def _render_gate_verdict(gate_verdict: GateVerdict) -> dict[str, JsonValue]:
    """Render a single gate verdict with its evidence."""
    rendered: dict[str, JsonValue] = {
        "gate": gate_verdict.gate.value,
        "verdict": gate_verdict.verdict.value,
        "reason_code": gate_verdict.reason_code,
        "evidence": dict(gate_verdict.evidence),
    }
    if gate_verdict.evaluation_duration is not None:
        rendered["evaluation_duration_s"] = float(gate_verdict.evaluation_duration)
    return rendered


def _render_safety_verdict(verdict: SafetyVerdict) -> dict[str, JsonValue]:
    """Render the safety verdict: the aggregate, the vetoing gates and each verdict."""
    return {
        "aggregate": verdict.aggregate.value,
        "vetoing_gates": [gate.value for gate in verdict.vetoing_gates],
        "gate_verdicts": [
            _render_gate_verdict(gate_verdict) for gate_verdict in verdict.gate_verdicts
        ],
    }


def _render_failsafe(snapshot: FailSafeSnapshot) -> dict[str, JsonValue]:
    """Render the fail-safe FSM snapshot."""
    return {
        "state": snapshot.state.value,
        "ood_counter": snapshot.ood_counter,
        # Added at schema 8. ADR-0024 gave the machine two counters and argued
        # that they must be reported separately, because "the gates refused
        # forty commands" and "a sensor was dark for forty ticks" need different
        # responses and one integer cannot say which happened. The field was put
        # on the snapshot and **not on the record**, so the archive carried the
        # argument's conclusion and none of its evidence (OD-16).
        "integrity_counter": snapshot.integrity_counter,
        "speed_cap_mps": None if snapshot.speed_cap is None else float(snapshot.speed_cap),
        "lane_change_permitted": snapshot.lane_change_permitted,
        "human_intervention_requested": snapshot.human_intervention_requested,
        # Added at schema 9, ADR-0029. The second axis: `state` records how bad
        # things were getting, this records what was broken. A row carrying only
        # the first cannot answer the question a technician actually opens the
        # log with -- "which function did the vehicle stop offering, and when?"
        #
        # An empty list is ambiguous by construction and the snapshot's docstring
        # says so: it means either nothing was withdrawn or the profile declared
        # no capabilities. The active profile disambiguates, and the run manifest
        # already records which profile was loaded.
        "withdrawn_capabilities": list(snapshot.withdrawn_capabilities),
    }


def _render_arbitration(decision: ArbitrationDecision) -> dict[str, JsonValue]:
    """Render the arbitration decision."""
    return {
        "outcome": decision.outcome.value,
        "active_profile": str(decision.active_profile),
        "candidate_profile": (
            None if decision.candidate_profile is None else str(decision.candidate_profile)
        ),
        "trust_score": decision.trust_score,
        "calibration_divergence_index": (
            None
            if decision.calibration_divergence_index is None
            else float(decision.calibration_divergence_index)
        ),
        # The context the decision was taken about. Rendered as a bare vector
        # ordered per RCS_FIELDS rather than as named keys, because the ordering
        # is already fixed by contract -- a profile's stored centroid is a bare
        # vector too, and a reader that pairs them must use the same order.
        "signature": (
            None
            if decision.signature is None
            else [float(component) for component in decision.signature.components]
        ),
    }


def _render_proposal(proposal: ProposedCommand) -> dict[str, JsonValue]:
    """Render the proposed command."""
    return {
        "command": _render_command(proposal.command),
        "origin": proposal.origin.value,
        "source": str(proposal.source),
        "admissible": proposal.command.is_admissible(),
    }


def _render_prediction(prediction: PredictedCommand) -> dict[str, JsonValue]:
    """Render the twin's prediction."""
    return {
        "command": _render_command(prediction.command),
        "source": str(prediction.source),
        "predicted_at": _render_instant(prediction.predicted_at),
        "admissible": prediction.command.is_admissible(),
    }


def _render_issued(issued: IssuedCommand) -> dict[str, JsonValue]:
    """Render the issued command."""
    return {
        "command": _render_command(issued.command),
        "origin": issued.origin.value,
        "issuer": str(issued.issuer),
        "issued_at": _render_instant(issued.issued_at),
    }


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """One atomic entry in the audit log.

    The payload is snapshotted through JSON at construction. This does two jobs
    at once: it proves the payload is serialisable before the event claims to be
    evidence, and it detaches the stored copy from the caller's dictionary so a
    later mutation cannot rewrite history.

    Attributes:
        event_id: The deterministic ``run:tick:sequence`` identity.
        severity: The safety severity of the event.
        kind: A stable, greppable event kind, e.g. ``"fsm_transition"``.
        payload: JSON-serialisable structured detail. Snapshotted at
            construction.
    """

    event_id: EventId
    severity: EventSeverity
    kind: str
    payload: dict[str, JsonValue]

    def __post_init__(self) -> None:
        """Validate the kind and snapshot the payload through JSON.

        Raises:
            ContractViolationError: If the kind is empty, or the payload is not
                JSON-serialisable.
        """
        if not self.kind:
            message = "an audit event must carry a non-empty kind"
            raise ContractViolationError(message)
        try:
            snapshot: dict[str, JsonValue] = json.loads(json.dumps(self.payload))
        except (TypeError, ValueError) as error:
            message = "audit event payload must be JSON-serialisable"
            raise ContractViolationError(
                message, context={"kind": self.kind, "error": str(error)}
            ) from error
        object.__setattr__(self, "payload", snapshot)

    def to_payload(self) -> dict[str, JsonValue]:
        """Render the event as a JSON-serialisable dictionary.

        Returns:
            An ordered mapping carrying the schema version, identity, severity,
            kind and detail, suitable for writing directly as a JSONL line.
        """
        return {
            "schema_version": AUDIT_SCHEMA_VERSION,
            "event_id": str(self.event_id),
            "run": self.event_id.run.value,
            "tick": self.event_id.tick.value,
            "sequence": self.event_id.sequence,
            "severity": self.severity.value,
            "kind": self.kind,
            "payload": self.payload,
        }


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    """The full, joinable account of what the pipeline decided in one tick.

    Every field except the identity trio and the configuration hash is optional,
    because a tick can end early: a fail-closed VETO can be reached before a
    proposal is scored, and the record must still faithfully show how far the
    pipeline got. An absent field means "this stage did not run this tick", which
    is itself evidence.

    Attributes:
        run: The run this tick belongs to.
        tick: The tick.
        config_hash: The hash of the frozen configuration in force, so every
            number in the record is attributable to a specific operating point.
        frame_health: Per-modality health of the fused sensor frame, as ordered
            pairs for deterministic rendering.
        fast_state: The UKF fast state estimate.
        fast_innovation: ``||nu_t||`` under the innovation covariance for this
            tick's fast update, or ``None`` if no update ran.

            **The one quantity in the record that can disagree with the
            estimate.** Everything else here is derived from the state the
            filter settled on; this is how far the measurement was from what
            the filter expected before it settled. The pipeline has always
            computed it -- L6's rolling covariate-shift window is fed from it
            and L3's Trust Index is computed from it -- and until 9 August 2026
            it reached the evidence log through neither. An auditor could read
            every record of a run and not recover the signal both gates were
            reasoning about.

            Added while measuring OD-9, where the question *"could anything in
            Core-B have seen this fault?"* could not be answered from the
            archive.
        trust: The Trust Module assessment.
        proposal: The untrusted proposed command.
        prediction: The digital twin's one-step prediction. Two gates score
            against it, so a verdict cannot be reproduced from the record
            without it.
        twin_weights_digest: Which twin produced that prediction. The
            counterpart of ``config_hash``: the twin is not a fixed thing --
            it ships as a checkpoint and FB2 moves it mid-run -- so a record
            that named only the configuration would answer "under which
            operating point" but not "under which model".
        prediction_admissible: Whether the twin's prediction was itself
            admissible. Retained from before L5 existed, when the full
            prediction could not be recorded; it is now derivable from
            ``prediction`` and is kept only because removing a field from an
            evidence schema is a schema-version change, not a tidy-up.
        safety_verdict: Core-B's combined verdict.
        failsafe: The fail-safe FSM snapshot.
        arbitration: RCM's arbitration decision.
        issued: The command actually issued, if one was.
        ablation: Which layers were disarmed for this run, as
            :meth:`~astra.runtime.ablation.AblationProfile.render` produces
            them, or ``"NONE"`` for a governed run.

            **Stamped on every tick, and that is the point.** An ablation study
            produces evidence that looks exactly like a governed run's --
            verdicts, reason codes, a fail-safe trace -- and the difference is
            invisible unless the record carries it. A configuration file
            elsewhere is not enough: evidence outlives the configuration that
            produced it, and a certification artefact describing a system that
            was not running is the failure this field exists to prevent
            (ADR-0021).
    """

    run: RunId
    tick: TickId
    config_hash: str
    frame_health: tuple[tuple[SensorModality, StreamHealth], ...] = ()
    fast_state: FastStateEstimate | None = None
    fast_innovation: float | None = None
    trust: TrustAssessment | None = None
    proposal: ProposedCommand | None = None
    prediction: PredictedCommand | None = None
    twin_weights_digest: str | None = None
    prediction_admissible: bool | None = None
    safety_verdict: SafetyVerdict | None = None
    failsafe: FailSafeSnapshot | None = None
    arbitration: ArbitrationDecision | None = None
    issued: IssuedCommand | None = None
    ablation: str = "NONE"

    def __post_init__(self) -> None:
        """Validate the configuration hash and the frame-health keys.

        Raises:
            ContractViolationError: If the configuration hash is empty, or a
                modality appears twice in the frame-health pairs.
        """
        if not self.config_hash:
            message = "a decision record must carry the configuration hash it ran under"
            raise ContractViolationError(message)
        modalities = [modality for modality, _ in self.frame_health]
        if len(modalities) != len(set(modalities)):
            message = "frame health must carry at most one entry per modality"
            raise ContractViolationError(
                message, context={"modalities": [modality.value for modality in modalities]}
            )

    def to_payload(self) -> dict[str, JsonValue]:
        """Render the record as a deterministic, JSON-serialisable dictionary.

        Optional stages that did not run are rendered as ``null`` rather than
        omitted, so every record from a run has the same key set and the
        evidence archive is a rectangle, not a ragged join.

        Returns:
            The full decision payload.
        """
        return {
            "schema_version": AUDIT_SCHEMA_VERSION,
            "run": self.run.value,
            "tick": self.tick.value,
            "config_hash": self.config_hash,
            "frame_health": {
                modality.value: health.value for modality, health in self.frame_health
            },
            "fast_state": None if self.fast_state is None else _render_fast_state(self.fast_state),
            "fast_innovation": self.fast_innovation,
            "trust": None if self.trust is None else _render_trust(self.trust),
            "proposal": None if self.proposal is None else _render_proposal(self.proposal),
            "prediction": (
                None if self.prediction is None else _render_prediction(self.prediction)
            ),
            "twin_weights_digest": self.twin_weights_digest,
            "prediction_admissible": self.prediction_admissible,
            "safety_verdict": (
                None if self.safety_verdict is None else _render_safety_verdict(self.safety_verdict)
            ),
            "failsafe": None if self.failsafe is None else _render_failsafe(self.failsafe),
            "arbitration": (
                None if self.arbitration is None else _render_arbitration(self.arbitration)
            ),
            "issued": None if self.issued is None else _render_issued(self.issued),
            "ablation": self.ablation,
        }

    def to_json(self) -> str:
        """Serialise the record to a compact, stable JSON string.

        The exact form the audit sink writes. Using fixed separators and no key
        sorting -- the payload is already built in a fixed order -- makes the
        output byte-stable, so re-serialising a parsed record reproduces it.

        Returns:
            A single-line JSON document.
        """
        return json.dumps(self.to_payload(), separators=(",", ":"), ensure_ascii=False)


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    """What actually happened after a command was applied, and where it feeds back.

    The input to the feedback loops. It pairs the issued command with the
    measured result and names which loops consume that result -- FB1 re-anchors
    the UKF on the *applied* command, FB2 adapts the twin on the measured
    outcome, FB3 recalibrates trust. Recording the destination set makes the
    feedback wiring auditable rather than implicit.

    Attributes:
        tick: The control tick whose command was applied.
        applied: The command that was issued and applied.
        measured: Named measured quantities observed after application, as
            ordered pairs for deterministic rendering.
        feeds: The feedback loops this outcome is routed to.
    """

    tick: TickId
    applied: IssuedCommand
    measured: tuple[tuple[str, float], ...] = ()
    feeds: frozenset[FeedbackLoop] = frozenset()

    def __post_init__(self) -> None:
        """Validate the measured quantities and the feedback destinations.

        Raises:
            ContractViolationError: If a measured quantity name repeats.
            NonFiniteValueError: If a measured value is not finite.
        """
        names = [name for name, _ in self.measured]
        if len(names) != len(set(names)):
            message = "a measured outcome must carry at most one value per name"
            raise ContractViolationError(message, context={"names": names})
        for name, value in self.measured:
            require_finite(value, name=f"measured.{name}")

    def to_payload(self) -> dict[str, JsonValue]:
        """Render the outcome as a JSON-serialisable dictionary.

        Returns:
            The outcome payload, with feedback loops rendered in canonical order.
        """
        return {
            "schema_version": AUDIT_SCHEMA_VERSION,
            "tick": self.tick.value,
            "applied": _render_issued(self.applied),
            "measured": dict(self.measured),
            "feeds": [loop.value for loop in FeedbackLoop if loop in self.feeds],
        }
