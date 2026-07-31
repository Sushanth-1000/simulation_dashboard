"""Unit tests for the assurance contracts, including SI-3 and SI-4."""

from __future__ import annotations

import dataclasses

import pytest

from astra.contracts.assurance import FailSafeSnapshot, GateVerdict, SafetyVerdict, TrustAssessment
from astra.kernel.enums import ContextClass, FailSafeState, GateId, Verdict
from astra.kernel.errors import (
    ContractViolationError,
    NonFiniteValueError,
    RangeViolationError,
)
from astra.kernel.identifiers import TickId
from astra.kernel.units import MetresPerSecond, Probability, Seconds


def _gate_verdict(tick: TickId, gate: GateId, verdict: Verdict) -> GateVerdict:
    return GateVerdict(
        tick=tick,
        gate=gate,
        verdict=verdict,
        reason_code="NOMINAL" if verdict is Verdict.PASS else "BOUND_BREACHED",
    )


# --------------------------------------------------------------------------- #
# TrustAssessment
# --------------------------------------------------------------------------- #


def test_trust_assessment_accepts_a_well_formed_assessment(tick: TickId) -> None:
    assessment = TrustAssessment(
        tick=tick,
        trust_index=Probability(0.87),
        context_class=ContextClass.HIGHWAY_CLEAR,
        class_conditional_quantile=1.42,
        coverage_target=Probability(0.9),
        calibration_sample_count=512,
        is_calibrated=True,
    )

    assert assessment.trust_index == 0.87
    assert assessment.context_class.is_certified


def test_trust_assessment_with_a_trust_index_above_one_raises_range_violation(
    tick: TickId,
) -> None:
    with pytest.raises(RangeViolationError):
        TrustAssessment(
            tick=tick,
            trust_index=Probability(1.5),
            context_class=ContextClass.HIGHWAY_CLEAR,
            class_conditional_quantile=1.0,
            coverage_target=Probability(0.9),
            calibration_sample_count=1,
            is_calibrated=True,
        )


def test_trust_assessment_with_a_negative_trust_index_raises_range_violation(
    tick: TickId,
) -> None:
    with pytest.raises(RangeViolationError):
        TrustAssessment(
            tick=tick,
            trust_index=Probability(-0.01),
            context_class=ContextClass.URBAN_CLEAR,
            class_conditional_quantile=1.0,
            coverage_target=Probability(0.9),
            calibration_sample_count=1,
            is_calibrated=True,
        )


def test_trust_assessment_with_a_coverage_target_above_one_raises_range_violation(
    tick: TickId,
) -> None:
    with pytest.raises(RangeViolationError):
        TrustAssessment(
            tick=tick,
            trust_index=Probability(0.5),
            context_class=ContextClass.RAIN_NIGHT,
            class_conditional_quantile=1.0,
            coverage_target=Probability(1.01),
            calibration_sample_count=1,
            is_calibrated=True,
        )


def test_trust_assessment_with_a_nan_quantile_raises_non_finite_value(tick: TickId) -> None:
    with pytest.raises(NonFiniteValueError):
        TrustAssessment(
            tick=tick,
            trust_index=Probability(0.5),
            context_class=ContextClass.RAIN_NIGHT,
            class_conditional_quantile=float("nan"),
            coverage_target=Probability(0.9),
            calibration_sample_count=1,
            is_calibrated=True,
        )


def test_trust_assessment_with_a_negative_quantile_raises_range_violation(tick: TickId) -> None:
    with pytest.raises(RangeViolationError):
        TrustAssessment(
            tick=tick,
            trust_index=Probability(0.5),
            context_class=ContextClass.DEGRADED_SENSOR,
            class_conditional_quantile=-1.0,
            coverage_target=Probability(0.9),
            calibration_sample_count=1,
            is_calibrated=True,
        )


def test_trust_assessment_with_a_negative_sample_count_raises_contract_violation(
    tick: TickId,
) -> None:
    with pytest.raises(ContractViolationError) as raised:
        TrustAssessment(
            tick=tick,
            trust_index=Probability(0.5),
            context_class=ContextClass.UNCLASSIFIED,
            class_conditional_quantile=1.0,
            coverage_target=Probability(0.9),
            calibration_sample_count=-1,
            is_calibrated=True,
        )

    assert raised.value.context["count"] == -1


def test_trust_assessment_accepts_a_zero_sample_count_as_a_recordable_fact(tick: TickId) -> None:
    assessment = TrustAssessment(
        tick=tick,
        trust_index=Probability(0.0),
        context_class=ContextClass.UNCLASSIFIED,
        class_conditional_quantile=0.0,
        coverage_target=Probability(1.0),
        calibration_sample_count=0,
        is_calibrated=True,
    )

    assert assessment.calibration_sample_count == 0


# --------------------------------------------------------------------------- #
# GateVerdict
# --------------------------------------------------------------------------- #


def test_gate_verdict_with_an_empty_reason_code_raises_contract_violation(tick: TickId) -> None:
    with pytest.raises(ContractViolationError) as raised:
        GateVerdict(tick=tick, gate=GateId.STATISTICAL, verdict=Verdict.PASS, reason_code="")

    assert raised.value.context["gate"] == "STATISTICAL"


def test_gate_verdict_with_a_nan_evidence_value_raises_non_finite_value(tick: TickId) -> None:
    with pytest.raises(NonFiniteValueError):
        GateVerdict(
            tick=tick,
            gate=GateId.STATISTICAL,
            verdict=Verdict.PASS,
            reason_code="NOMINAL",
            evidence=(("alpha", float("nan")),),
        )


def test_gate_verdict_with_an_infinite_evidence_value_raises_non_finite_value(
    tick: TickId,
) -> None:
    with pytest.raises(NonFiniteValueError):
        GateVerdict(
            tick=tick,
            gate=GateId.PHYSICAL,
            verdict=Verdict.VETO,
            reason_code="PHYSICS_VIOLATED",
            evidence=(("residual", float("inf")),),
        )


def test_gate_verdict_with_a_negative_evaluation_duration_raises_range_violation(
    tick: TickId,
) -> None:
    with pytest.raises(RangeViolationError):
        GateVerdict(
            tick=tick,
            gate=GateId.DETERMINISTIC,
            verdict=Verdict.PASS,
            reason_code="NOMINAL",
            evaluation_duration=Seconds(-0.001),
        )


def test_gate_verdict_evidence_map_returns_a_fresh_detached_dictionary(tick: TickId) -> None:
    verdict = GateVerdict(
        tick=tick,
        gate=GateId.STATISTICAL,
        verdict=Verdict.VETO,
        reason_code="ALPHA_ABOVE_QUANTILE",
        evidence=(("alpha", 2.5), ("quantile", 1.4)),
        evaluation_duration=Seconds(0.002),
    )

    mapping = verdict.evidence_map()
    mapping["alpha"] = 0.0

    assert verdict.evidence_map() == {"alpha": 2.5, "quantile": 1.4}


def test_gate_verdict_defaults_to_no_evidence_and_no_duration(tick: TickId) -> None:
    verdict = GateVerdict(
        tick=tick, gate=GateId.DETERMINISTIC, verdict=Verdict.PASS, reason_code="NOMINAL"
    )

    assert verdict.evidence == ()
    assert verdict.evaluation_duration is None
    assert verdict.evidence_map() == {}


# --------------------------------------------------------------------------- #
# SafetyVerdict -- SI-3, unconditional veto
# --------------------------------------------------------------------------- #


def test_safety_verdict_aggregate_is_pass_when_every_gate_passed(tick: TickId) -> None:
    verdict = SafetyVerdict(
        tick=tick,
        gate_verdicts=tuple(_gate_verdict(tick, gate, Verdict.PASS) for gate in GateId),
    )

    assert verdict.aggregate is Verdict.PASS
    assert not verdict.is_blocking


def test_safety_verdict_with_two_passes_and_one_veto_aggregates_to_veto_under_si3(
    tick: TickId,
) -> None:
    verdict = SafetyVerdict(
        tick=tick,
        gate_verdicts=(
            _gate_verdict(tick, GateId.STATISTICAL, Verdict.PASS),
            _gate_verdict(tick, GateId.PHYSICAL, Verdict.PASS),
            _gate_verdict(tick, GateId.DETERMINISTIC, Verdict.VETO),
        ),
    )

    assert verdict.aggregate is Verdict.VETO
    assert verdict.is_blocking


def test_safety_verdict_veto_survives_however_many_passes_accompany_it_under_si3(
    tick: TickId,
) -> None:
    single_veto = SafetyVerdict(
        tick=tick, gate_verdicts=(_gate_verdict(tick, GateId.DETERMINISTIC, Verdict.VETO),)
    )
    veto_with_one_pass = SafetyVerdict(
        tick=tick,
        gate_verdicts=(
            _gate_verdict(tick, GateId.DETERMINISTIC, Verdict.VETO),
            _gate_verdict(tick, GateId.STATISTICAL, Verdict.PASS),
        ),
    )
    veto_with_two_passes = SafetyVerdict(
        tick=tick,
        gate_verdicts=(
            _gate_verdict(tick, GateId.DETERMINISTIC, Verdict.VETO),
            _gate_verdict(tick, GateId.STATISTICAL, Verdict.PASS),
            _gate_verdict(tick, GateId.PHYSICAL, Verdict.PASS),
        ),
    )

    assert single_veto.aggregate is Verdict.VETO
    assert veto_with_one_pass.aggregate is Verdict.VETO
    assert veto_with_two_passes.aggregate is Verdict.VETO


def test_safety_verdict_with_no_gate_verdicts_aggregates_to_veto_under_si3(
    tick: TickId,
) -> None:
    verdict = SafetyVerdict(tick=tick, gate_verdicts=())

    assert verdict.aggregate is Verdict.VETO
    assert verdict.is_blocking


def test_safety_verdict_aggregate_is_independent_of_the_order_of_the_gate_verdicts(
    tick: TickId,
) -> None:
    forwards = SafetyVerdict(
        tick=tick,
        gate_verdicts=(
            _gate_verdict(tick, GateId.STATISTICAL, Verdict.VETO),
            _gate_verdict(tick, GateId.PHYSICAL, Verdict.PASS),
        ),
    )
    backwards = SafetyVerdict(
        tick=tick,
        gate_verdicts=(
            _gate_verdict(tick, GateId.PHYSICAL, Verdict.PASS),
            _gate_verdict(tick, GateId.STATISTICAL, Verdict.VETO),
        ),
    )

    assert forwards.aggregate is backwards.aggregate


# --------------------------------------------------------------------------- #
# SafetyVerdict -- SI-4, trust isolation
# --------------------------------------------------------------------------- #


def test_safety_verdict_declares_no_trust_field_under_si4() -> None:
    field_names = {field.name for field in dataclasses.fields(SafetyVerdict)}

    assert field_names == {"tick", "gate_verdicts"}
    assert not {name for name in field_names if "trust" in name.lower()}


def test_safety_verdict_slots_leave_no_room_for_a_trust_index_under_si4() -> None:
    slots = set(SafetyVerdict.__slots__)

    assert slots == {"tick", "gate_verdicts"}
    assert not {name for name in slots if "trust" in name.lower()}


def test_safety_verdict_cannot_be_constructed_with_a_trust_index_under_si4(tick: TickId) -> None:
    with pytest.raises(TypeError):
        SafetyVerdict(tick=tick, gate_verdicts=(), trust_index=0.99)  # type: ignore[call-arg]


def test_safety_verdict_cannot_be_given_a_trust_index_after_construction_under_si4(
    tick: TickId,
) -> None:
    verdict = SafetyVerdict(
        tick=tick, gate_verdicts=(_gate_verdict(tick, GateId.STATISTICAL, Verdict.PASS),)
    )

    # A frozen, slotted record has nowhere to put a Trust Index: the assignment
    # is refused rather than silently creating an attribute.
    with pytest.raises(TypeError):
        verdict.trust_index = 0.99  # type: ignore[attr-defined]

    assert not hasattr(verdict, "trust_index")


def test_safety_verdict_declared_fields_are_immutable_after_construction(tick: TickId) -> None:
    verdict = SafetyVerdict(tick=tick, gate_verdicts=())

    with pytest.raises(dataclasses.FrozenInstanceError):
        verdict.tick = TickId(99)  # type: ignore[misc]


def test_safety_verdict_has_no_attribute_resembling_a_trust_index_under_si4(
    tick: TickId,
) -> None:
    verdict = SafetyVerdict(tick=tick, gate_verdicts=())

    assert not [name for name in dir(verdict) if "trust" in name.lower()]


# --------------------------------------------------------------------------- #
# SafetyVerdict -- structure and reporting
# --------------------------------------------------------------------------- #


def test_safety_verdict_with_the_same_gate_twice_raises_contract_violation(tick: TickId) -> None:
    with pytest.raises(ContractViolationError) as raised:
        SafetyVerdict(
            tick=tick,
            gate_verdicts=(
                _gate_verdict(tick, GateId.STATISTICAL, Verdict.PASS),
                _gate_verdict(tick, GateId.STATISTICAL, Verdict.VETO),
            ),
        )

    assert raised.value.context["gates"] == ["STATISTICAL", "STATISTICAL"]


def test_vetoing_gates_returns_the_stable_canonical_gate_declaration_order(tick: TickId) -> None:
    verdict = SafetyVerdict(
        tick=tick,
        gate_verdicts=(
            _gate_verdict(tick, GateId.DETERMINISTIC, Verdict.VETO),
            _gate_verdict(tick, GateId.PHYSICAL, Verdict.VETO),
            _gate_verdict(tick, GateId.STATISTICAL, Verdict.VETO),
        ),
    )

    assert verdict.vetoing_gates == (GateId.STATISTICAL, GateId.PHYSICAL, GateId.DETERMINISTIC)


def test_vetoing_gates_order_does_not_depend_on_construction_order(tick: TickId) -> None:
    forwards = SafetyVerdict(
        tick=tick,
        gate_verdicts=(
            _gate_verdict(tick, GateId.STATISTICAL, Verdict.VETO),
            _gate_verdict(tick, GateId.DETERMINISTIC, Verdict.VETO),
        ),
    )
    backwards = SafetyVerdict(
        tick=tick,
        gate_verdicts=(
            _gate_verdict(tick, GateId.DETERMINISTIC, Verdict.VETO),
            _gate_verdict(tick, GateId.STATISTICAL, Verdict.VETO),
        ),
    )

    assert forwards.vetoing_gates == backwards.vetoing_gates
    assert forwards.vetoing_gates == (GateId.STATISTICAL, GateId.DETERMINISTIC)


def test_vetoing_gates_excludes_gates_that_passed(tick: TickId) -> None:
    verdict = SafetyVerdict(
        tick=tick,
        gate_verdicts=(
            _gate_verdict(tick, GateId.STATISTICAL, Verdict.PASS),
            _gate_verdict(tick, GateId.PHYSICAL, Verdict.VETO),
        ),
    )

    assert verdict.vetoing_gates == (GateId.PHYSICAL,)


def test_vetoing_gates_is_empty_when_nothing_vetoed(tick: TickId) -> None:
    verdict = SafetyVerdict(
        tick=tick, gate_verdicts=(_gate_verdict(tick, GateId.PHYSICAL, Verdict.PASS),)
    )

    assert verdict.vetoing_gates == ()


# --------------------------------------------------------------------------- #
# FailSafeSnapshot
# --------------------------------------------------------------------------- #


def test_failsafe_snapshot_defaults_to_a_permissive_nominal_posture(tick: TickId) -> None:
    snapshot = FailSafeSnapshot(tick=tick, state=FailSafeState.NOMINAL, ood_counter=0)

    assert snapshot.speed_cap is None
    assert snapshot.lane_change_permitted
    assert not snapshot.human_intervention_requested


def test_failsafe_snapshot_with_a_negative_ood_counter_raises_contract_violation(
    tick: TickId,
) -> None:
    with pytest.raises(ContractViolationError) as raised:
        FailSafeSnapshot(tick=tick, state=FailSafeState.NOMINAL, ood_counter=-1)

    assert raised.value.context["ood_counter"] == -1


def test_failsafe_snapshot_with_a_negative_speed_cap_raises_range_violation(tick: TickId) -> None:
    with pytest.raises(RangeViolationError):
        FailSafeSnapshot(
            tick=tick,
            state=FailSafeState.LIMP,
            ood_counter=7,
            speed_cap=MetresPerSecond(-1.0),
        )


def test_failsafe_snapshot_with_a_nan_speed_cap_raises_non_finite_value(tick: TickId) -> None:
    with pytest.raises(NonFiniteValueError):
        FailSafeSnapshot(
            tick=tick,
            state=FailSafeState.LIMP,
            ood_counter=7,
            speed_cap=MetresPerSecond(float("nan")),
        )


def test_failsafe_snapshot_accepts_a_zero_speed_cap_for_a_halted_vehicle(tick: TickId) -> None:
    snapshot = FailSafeSnapshot(
        tick=tick,
        state=FailSafeState.HALT,
        ood_counter=12,
        speed_cap=MetresPerSecond(0.0),
        lane_change_permitted=False,
        human_intervention_requested=True,
    )

    assert snapshot.speed_cap == 0.0
    assert snapshot.state.severity_rank == 3
