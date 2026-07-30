"""Unit tests for the audit contracts: events, decision records and outcomes."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from astra.contracts.actuation import (
    ActuationSpace,
    CommandOrigin,
    ControlCommand,
    IssuedCommand,
    ProposedCommand,
)
from astra.contracts.assurance import FailSafeSnapshot, GateVerdict, SafetyVerdict, TrustAssessment
from astra.contracts.audit import AuditEvent, DecisionRecord, ExecutionOutcome
from astra.contracts.estimation import FastStateEstimate
from astra.contracts.governance import ArbitrationDecision
from astra.kernel.constants import AUDIT_SCHEMA_VERSION
from astra.kernel.enums import (
    ArbitrationOutcome,
    ContextClass,
    EventSeverity,
    FailSafeState,
    FeedbackLoop,
    GateId,
    SensorModality,
    StreamHealth,
    Verdict,
)
from astra.kernel.errors import ContractViolationError, NonFiniteValueError
from astra.kernel.identifiers import EventId, ProfileId, RunId, TickId
from astra.kernel.units import MetresPerSecond, Probability, Seconds

if TYPE_CHECKING:
    from astra.contracts.audit import JsonValue
    from astra.kernel.identifiers import ComponentId
    from astra.kernel.matrix import SymmetricMatrix
    from astra.kernel.time import Instant

CONFIG_HASH = "sha256:9f86d081884c7d65"

DECISION_RECORD_KEYS = (
    "schema_version",
    "run",
    "tick",
    "config_hash",
    "frame_health",
    "fast_state",
    "trust",
    "proposal",
    "prediction_admissible",
    "safety_verdict",
    "failsafe",
    "arbitration",
    "issued",
)


def _issued(
    tick: TickId,
    now: Instant,
    space: ActuationSpace,
    rcm: ComponentId,
) -> IssuedCommand:
    return IssuedCommand(
        tick=tick,
        issued_at=now,
        command=ControlCommand(space=space, values=(0.4, 0.2)),
        origin=CommandOrigin.PROPOSED,
        issuer=rcm,
    )


def _full_record(
    *,
    run: RunId,
    tick: TickId,
    now: Instant,
    space: ActuationSpace,
    rcm: ComponentId,
    proposer: ComponentId,
    covariance: SymmetricMatrix,
) -> DecisionRecord:
    return DecisionRecord(
        run=run,
        tick=tick,
        config_hash=CONFIG_HASH,
        frame_health=(
            (SensorModality.CAMERA, StreamHealth.HEALTHY),
            (SensorModality.LIDAR, StreamHealth.DEGRADED),
        ),
        fast_state=FastStateEstimate(
            tick=tick,
            valid_at=now,
            mean=(10.0, -2.0, 13.5, 0.25, 1.75),
            covariance=covariance,
        ),
        trust=TrustAssessment(
            tick=tick,
            trust_index=Probability(0.87),
            context_class=ContextClass.HIGHWAY_CLEAR,
            class_conditional_quantile=1.42,
            coverage_target=Probability(0.9),
            calibration_sample_count=512,
        ),
        proposal=ProposedCommand(
            tick=tick,
            proposed_at=now,
            command=ControlCommand(space=space, values=(0.4, 0.2)),
            origin=CommandOrigin.PROPOSED,
            source=proposer,
        ),
        prediction_admissible=True,
        safety_verdict=SafetyVerdict(
            tick=tick,
            gate_verdicts=(
                GateVerdict(
                    tick=tick,
                    gate=GateId.STATISTICAL,
                    verdict=Verdict.PASS,
                    reason_code="NOMINAL",
                    evidence=(("alpha", 0.3), ("quantile", 1.4)),
                    evaluation_duration=Seconds(0.0012),
                ),
                GateVerdict(
                    tick=tick,
                    gate=GateId.DETERMINISTIC,
                    verdict=Verdict.VETO,
                    reason_code="LATERAL_BOUND_BREACHED",
                ),
            ),
        ),
        failsafe=FailSafeSnapshot(
            tick=tick,
            state=FailSafeState.DEGRADED,
            ood_counter=3,
            speed_cap=MetresPerSecond(16.6),
            lane_change_permitted=False,
            human_intervention_requested=True,
        ),
        arbitration=ArbitrationDecision(
            tick=tick,
            outcome=ArbitrationOutcome.SHADOW_EXECUTION,
            active_profile=ProfileId(name="highway_clear", version=2),
            candidate_profile=ProfileId(name="rain_night", version=1),
            trust_score=0.71,
            calibration_divergence_index=Probability(0.04),
        ),
        issued=_issued(tick, now, space, rcm),
    )


# --------------------------------------------------------------------------- #
# AuditEvent
# --------------------------------------------------------------------------- #


def test_audit_event_with_an_empty_kind_raises_contract_violation(run: RunId, tick: TickId) -> None:
    with pytest.raises(ContractViolationError):
        AuditEvent(
            event_id=EventId(run=run, tick=tick, sequence=0),
            severity=EventSeverity.INFO,
            kind="",
            payload={},
        )


def test_audit_event_with_a_non_json_serialisable_payload_raises_contract_violation(
    run: RunId, tick: TickId
) -> None:
    payload: dict[str, JsonValue] = {"x": object()}  # type: ignore[dict-item]

    with pytest.raises(ContractViolationError) as raised:
        AuditEvent(
            event_id=EventId(run=run, tick=tick, sequence=0),
            severity=EventSeverity.WARNING,
            kind="fsm_transition",
            payload=payload,
        )

    assert raised.value.context["kind"] == "fsm_transition"


def test_audit_event_with_a_non_string_payload_key_raises_contract_violation(
    run: RunId, tick: TickId
) -> None:
    payload: dict[str, JsonValue] = {(1, 2): "tuple key"}  # type: ignore[dict-item]

    with pytest.raises(ContractViolationError):
        AuditEvent(
            event_id=EventId(run=run, tick=tick, sequence=1),
            severity=EventSeverity.WARNING,
            kind="bad_keys",
            payload=payload,
        )


def test_audit_event_snapshots_the_payload_so_later_caller_mutation_cannot_rewrite_history(
    run: RunId, tick: TickId
) -> None:
    nested: dict[str, JsonValue] = {"counter": 1}
    payload: dict[str, JsonValue] = {"nested": nested, "flag": True}

    event = AuditEvent(
        event_id=EventId(run=run, tick=tick, sequence=2),
        severity=EventSeverity.SAFETY_RELEVANT,
        kind="veto",
        payload=payload,
    )
    nested["counter"] = 99
    payload["added_later"] = "no"

    assert event.payload == {"nested": {"counter": 1}, "flag": True}


def test_audit_event_payload_is_a_distinct_object_from_the_caller_dictionary(
    run: RunId, tick: TickId
) -> None:
    payload: dict[str, JsonValue] = {"a": 1}

    event = AuditEvent(
        event_id=EventId(run=run, tick=tick, sequence=3),
        severity=EventSeverity.INFO,
        kind="tick_start",
        payload=payload,
    )

    assert event.payload is not payload
    assert event.payload == payload


def test_audit_event_to_payload_carries_the_schema_version_and_flattened_identity(
    run: RunId, tick: TickId
) -> None:
    event = AuditEvent(
        event_id=EventId(run=run, tick=tick, sequence=7),
        severity=EventSeverity.NOTICE,
        kind="calibration_switch",
        payload={"profile": "rain_night@v1"},
    )

    assert event.to_payload() == {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "event_id": f"{run}:{tick}:0007",
        "run": run.value,
        "tick": tick.value,
        "sequence": 7,
        "severity": "NOTICE",
        "kind": "calibration_switch",
        "payload": {"profile": "rain_night@v1"},
    }


def test_audit_event_payload_survives_a_json_round_trip(run: RunId, tick: TickId) -> None:
    event = AuditEvent(
        event_id=EventId(run=run, tick=tick, sequence=0),
        severity=EventSeverity.SAFETY_CRITICAL,
        kind="halt",
        payload={"reason": "bist_failure", "counter": 12, "caps": [1.0, 2.0], "cleared": None},
    )
    line = json.dumps(event.to_payload(), separators=(",", ":"), ensure_ascii=False)

    assert json.loads(line)["payload"] == event.payload


# --------------------------------------------------------------------------- #
# DecisionRecord -- validation
# --------------------------------------------------------------------------- #


def test_decision_record_with_an_empty_config_hash_raises_contract_violation(
    run: RunId, tick: TickId
) -> None:
    with pytest.raises(ContractViolationError):
        DecisionRecord(run=run, tick=tick, config_hash="")


def test_decision_record_with_a_duplicate_modality_in_frame_health_raises_contract_violation(
    run: RunId, tick: TickId
) -> None:
    with pytest.raises(ContractViolationError) as raised:
        DecisionRecord(
            run=run,
            tick=tick,
            config_hash=CONFIG_HASH,
            frame_health=(
                (SensorModality.CAMERA, StreamHealth.HEALTHY),
                (SensorModality.CAMERA, StreamHealth.DEGRADED),
            ),
        )

    assert raised.value.context["modalities"] == ["CAMERA", "CAMERA"]


# --------------------------------------------------------------------------- #
# DecisionRecord -- rectangular evidence
# --------------------------------------------------------------------------- #


def test_decision_record_with_every_optional_stage_absent_still_renders_every_key(
    run: RunId, tick: TickId
) -> None:
    record = DecisionRecord(run=run, tick=tick, config_hash=CONFIG_HASH)

    payload = record.to_payload()

    assert tuple(payload) == DECISION_RECORD_KEYS


def test_decision_record_renders_absent_stages_as_null_rather_than_omitting_them(
    run: RunId, tick: TickId
) -> None:
    record = DecisionRecord(run=run, tick=tick, config_hash=CONFIG_HASH)

    payload = record.to_payload()

    for key in (
        "fast_state",
        "trust",
        "proposal",
        "prediction_admissible",
        "safety_verdict",
        "failsafe",
        "arbitration",
        "issued",
    ):
        assert payload[key] is None
    assert payload["frame_health"] == {}


def test_a_full_and_an_empty_decision_record_share_exactly_the_same_key_set(
    *,
    run: RunId,
    tick: TickId,
    now: Instant,
    actuation_space: ActuationSpace,
    rcm_component: ComponentId,
    proposer_component: ComponentId,
    identity_covariance: SymmetricMatrix,
) -> None:
    empty = DecisionRecord(run=run, tick=tick, config_hash=CONFIG_HASH)
    full = _full_record(
        run=run,
        tick=tick,
        now=now,
        space=actuation_space,
        rcm=rcm_component,
        proposer=proposer_component,
        covariance=identity_covariance,
    )

    assert tuple(full.to_payload()) == tuple(empty.to_payload())


def test_decision_record_renders_each_stage_it_did_reach(
    *,
    run: RunId,
    tick: TickId,
    now: Instant,
    actuation_space: ActuationSpace,
    rcm_component: ComponentId,
    proposer_component: ComponentId,
    identity_covariance: SymmetricMatrix,
) -> None:
    payload = _full_record(
        run=run,
        tick=tick,
        now=now,
        space=actuation_space,
        rcm=rcm_component,
        proposer=proposer_component,
        covariance=identity_covariance,
    ).to_payload()

    assert payload["frame_health"] == {"CAMERA": "HEALTHY", "LIDAR": "DEGRADED"}
    assert payload["safety_verdict"] == {
        "aggregate": "VETO",
        "vetoing_gates": ["DETERMINISTIC"],
        "gate_verdicts": [
            {
                "gate": "STATISTICAL",
                "verdict": "PASS",
                "reason_code": "NOMINAL",
                "evidence": {"alpha": 0.3, "quantile": 1.4},
                "evaluation_duration_s": 0.0012,
            },
            {
                "gate": "DETERMINISTIC",
                "verdict": "VETO",
                "reason_code": "LATERAL_BOUND_BREACHED",
                "evidence": {},
            },
        ],
    }
    assert payload["issued"] == {
        "command": {"throttle": 0.4, "steer": 0.2},
        "origin": "PROPOSED",
        "issuer": "L9_RCM/primary",
        "issued_at": {"nanoseconds": now.nanoseconds, "timeline": now.timeline.value},
    }


# --------------------------------------------------------------------------- #
# DecisionRecord -- JSON round-trip stability
# --------------------------------------------------------------------------- #


def test_decision_record_to_json_is_byte_identical_after_a_parse_and_reserialise(
    *,
    run: RunId,
    tick: TickId,
    now: Instant,
    actuation_space: ActuationSpace,
    rcm_component: ComponentId,
    proposer_component: ComponentId,
    identity_covariance: SymmetricMatrix,
) -> None:
    rendered = _full_record(
        run=run,
        tick=tick,
        now=now,
        space=actuation_space,
        rcm=rcm_component,
        proposer=proposer_component,
        covariance=identity_covariance,
    ).to_json()

    reserialised = json.dumps(json.loads(rendered), separators=(",", ":"), ensure_ascii=False)

    assert reserialised == rendered


def test_an_empty_decision_record_to_json_is_byte_identical_after_a_round_trip(
    run: RunId, tick: TickId
) -> None:
    rendered = DecisionRecord(run=run, tick=tick, config_hash=CONFIG_HASH).to_json()

    reserialised = json.dumps(json.loads(rendered), separators=(",", ":"), ensure_ascii=False)

    assert reserialised == rendered


def test_decision_record_to_json_is_a_single_compact_line(run: RunId, tick: TickId) -> None:
    rendered = DecisionRecord(run=run, tick=tick, config_hash=CONFIG_HASH).to_json()

    assert "\n" not in rendered
    assert ", " not in rendered


def test_two_decision_records_built_from_equal_inputs_render_identical_json(
    *,
    run: RunId,
    tick: TickId,
    now: Instant,
    actuation_space: ActuationSpace,
    rcm_component: ComponentId,
    proposer_component: ComponentId,
    identity_covariance: SymmetricMatrix,
) -> None:
    first = _full_record(
        run=run,
        tick=tick,
        now=now,
        space=actuation_space,
        rcm=rcm_component,
        proposer=proposer_component,
        covariance=identity_covariance,
    )
    second = _full_record(
        run=run,
        tick=tick,
        now=now,
        space=actuation_space,
        rcm=rcm_component,
        proposer=proposer_component,
        covariance=identity_covariance,
    )

    assert first.to_json() == second.to_json()


# --------------------------------------------------------------------------- #
# ExecutionOutcome
# --------------------------------------------------------------------------- #


def test_execution_outcome_with_a_repeated_measured_name_raises_contract_violation(
    tick: TickId,
    now: Instant,
    actuation_space: ActuationSpace,
    rcm_component: ComponentId,
) -> None:
    with pytest.raises(ContractViolationError) as raised:
        ExecutionOutcome(
            tick=tick,
            applied=_issued(tick, now, actuation_space, rcm_component),
            measured=(("a_lat", 1.2), ("a_lat", 1.3)),
        )

    assert raised.value.context["names"] == ["a_lat", "a_lat"]


def test_execution_outcome_with_a_nan_measured_value_raises_non_finite_value(
    tick: TickId,
    now: Instant,
    actuation_space: ActuationSpace,
    rcm_component: ComponentId,
) -> None:
    with pytest.raises(NonFiniteValueError):
        ExecutionOutcome(
            tick=tick,
            applied=_issued(tick, now, actuation_space, rcm_component),
            measured=(("a_lat", float("nan")),),
        )


def test_execution_outcome_defaults_to_no_measurements_and_no_feedback_destinations(
    tick: TickId,
    now: Instant,
    actuation_space: ActuationSpace,
    rcm_component: ComponentId,
) -> None:
    outcome = ExecutionOutcome(
        tick=tick, applied=_issued(tick, now, actuation_space, rcm_component)
    )

    assert outcome.measured == ()
    assert outcome.to_payload()["feeds"] == []


def test_execution_outcome_to_payload_renders_feeds_in_canonical_loop_order(
    tick: TickId,
    now: Instant,
    actuation_space: ActuationSpace,
    rcm_component: ComponentId,
) -> None:
    outcome = ExecutionOutcome(
        tick=tick,
        applied=_issued(tick, now, actuation_space, rcm_component),
        measured=(("a_lat", 1.2), ("speed", 13.4)),
        feeds=frozenset(
            {
                FeedbackLoop.FB4_SIMULATOR_SYNC,
                FeedbackLoop.FB1_UKF_REANCHOR,
                FeedbackLoop.FB3_TRUST_RECALIBRATE,
            }
        ),
    )

    assert outcome.to_payload()["feeds"] == [
        "FB1_UKF_REANCHOR",
        "FB3_TRUST_RECALIBRATE",
        "FB4_SIMULATOR_SYNC",
    ]


def test_execution_outcome_to_payload_carries_the_applied_command_and_measurements(
    tick: TickId,
    now: Instant,
    actuation_space: ActuationSpace,
    rcm_component: ComponentId,
) -> None:
    outcome = ExecutionOutcome(
        tick=tick,
        applied=_issued(tick, now, actuation_space, rcm_component),
        measured=(("a_lat", 1.2), ("speed", 13.4)),
        feeds=frozenset({FeedbackLoop.FB2_PINN_ADAPT}),
    )

    payload = outcome.to_payload()

    assert payload["schema_version"] == AUDIT_SCHEMA_VERSION
    assert payload["tick"] == tick.value
    assert payload["measured"] == {"a_lat": 1.2, "speed": 13.4}
    assert payload["applied"] == {
        "command": {"throttle": 0.4, "steer": 0.2},
        "origin": "PROPOSED",
        "issuer": "L9_RCM/primary",
        "issued_at": {"nanoseconds": now.nanoseconds, "timeline": now.timeline.value},
    }


def test_execution_outcome_to_payload_is_json_serialisable_and_round_trip_stable(
    tick: TickId,
    now: Instant,
    actuation_space: ActuationSpace,
    rcm_component: ComponentId,
) -> None:
    outcome = ExecutionOutcome(
        tick=tick,
        applied=_issued(tick, now, actuation_space, rcm_component),
        measured=(("a_lat", 1.2),),
        feeds=frozenset({FeedbackLoop.FB1_UKF_REANCHOR}),
    )
    rendered = json.dumps(outcome.to_payload(), separators=(",", ":"), ensure_ascii=False)

    reserialised = json.dumps(json.loads(rendered), separators=(",", ":"), ensure_ascii=False)

    assert reserialised == rendered
