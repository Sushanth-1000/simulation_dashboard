"""The separation invariant catalogue and its two runtime guards."""

from __future__ import annotations

import pytest

from astra.invariants.catalogue import (
    SEPARATION_INVARIANTS,
    EnforcementKind,
    SeparationInvariant,
    guard_actuation_authority,
    guard_verdict_aggregation,
    invariant,
)
from astra.kernel.enums import LayerId, Verdict
from astra.kernel.errors import InvariantViolationError
from astra.kernel.identifiers import ComponentId

_EXPECTED_IDENTIFIERS = tuple(f"SI-{number}" for number in range(1, 11))

# --------------------------------------------------------------------------- #
# The catalogue is complete and well formed
# --------------------------------------------------------------------------- #


def test_the_catalogue_declares_exactly_ten_invariants() -> None:
    assert len(SEPARATION_INVARIANTS) == 10


def test_the_catalogue_declares_si_1_through_si_10_in_order() -> None:
    identifiers = tuple(entry.identifier for entry in SEPARATION_INVARIANTS)
    assert identifiers == _EXPECTED_IDENTIFIERS


def test_no_identifier_is_declared_twice() -> None:
    identifiers = [entry.identifier for entry in SEPARATION_INVARIANTS]
    assert len(identifiers) == len(set(identifiers))


@pytest.mark.parametrize("entry", SEPARATION_INVARIANTS, ids=lambda e: e.identifier)
@pytest.mark.parametrize("field", ["statement", "rationale", "consequence", "mechanism"])
def test_every_invariant_carries_a_non_empty_prose_field(
    entry: SeparationInvariant, field: str
) -> None:
    value = getattr(entry, field)
    assert isinstance(value, str)
    assert value.strip()


@pytest.mark.parametrize("entry", SEPARATION_INVARIANTS, ids=lambda e: e.identifier)
def test_every_invariant_has_a_non_empty_title(entry: SeparationInvariant) -> None:
    assert entry.title.strip()


@pytest.mark.parametrize("entry", SEPARATION_INVARIANTS, ids=lambda e: e.identifier)
def test_mechanical_enforcement_is_false_exactly_for_review_only_invariants(
    entry: SeparationInvariant,
) -> None:
    assert entry.is_mechanically_enforced is (entry.enforcement is not EnforcementKind.REVIEW)


@pytest.mark.parametrize(
    "kind",
    [EnforcementKind.STATIC, EnforcementKind.RUNTIME, EnforcementKind.TEST],
)
def test_every_non_review_enforcement_kind_counts_as_mechanical(kind: EnforcementKind) -> None:
    entry = SeparationInvariant(
        identifier="SI-0",
        title="probe",
        statement="s",
        rationale="r",
        consequence="c",
        enforcement=kind,
        mechanism="m",
    )
    assert entry.is_mechanically_enforced


def test_a_review_only_invariant_does_not_claim_mechanical_enforcement() -> None:
    entry = SeparationInvariant(
        identifier="SI-0",
        title="probe",
        statement="s",
        rationale="r",
        consequence="c",
        enforcement=EnforcementKind.REVIEW,
        mechanism="m",
    )
    assert entry.is_mechanically_enforced is False


# --------------------------------------------------------------------------- #
# Lookup
# --------------------------------------------------------------------------- #


def test_looking_up_si_3_returns_the_unconditional_veto_invariant() -> None:
    entry = invariant("SI-3")
    assert entry.identifier == "SI-3"
    assert entry.title == "Unconditional veto"
    assert entry.enforcement is EnforcementKind.RUNTIME


@pytest.mark.parametrize("identifier", _EXPECTED_IDENTIFIERS)
def test_every_declared_identifier_is_retrievable(identifier: str) -> None:
    assert invariant(identifier).identifier == identifier


def test_looking_up_an_undeclared_identifier_raises_key_error() -> None:
    with pytest.raises(KeyError):
        invariant("SI-99")


def test_the_lookup_error_names_the_identifier_that_was_asked_for() -> None:
    with pytest.raises(KeyError) as excinfo:
        invariant("SI-99")
    assert "SI-99" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# SI-3: guard_verdict_aggregation
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "components",
    [
        (Verdict.PASS,),
        (Verdict.PASS, Verdict.PASS),
        (Verdict.PASS, Verdict.PASS, Verdict.PASS),
    ],
)
def test_an_all_pass_aggregation_reported_as_pass_is_accepted_silently(
    components: tuple[Verdict, ...],
) -> None:
    guard_verdict_aggregation(Verdict.PASS, components)  # must not raise


@pytest.mark.parametrize(
    "components",
    [
        (Verdict.VETO,),
        (Verdict.PASS, Verdict.VETO),
        (Verdict.VETO, Verdict.PASS, Verdict.PASS),
        (Verdict.VETO, Verdict.VETO),
        (),
    ],
)
def test_an_aggregation_containing_a_veto_reported_as_veto_is_accepted_silently(
    components: tuple[Verdict, ...],
) -> None:
    guard_verdict_aggregation(Verdict.VETO, components)  # must not raise


@pytest.mark.parametrize(
    "components",
    [
        (Verdict.VETO,),
        (Verdict.PASS, Verdict.VETO),
        (Verdict.VETO, Verdict.PASS),
        (Verdict.PASS, Verdict.PASS, Verdict.VETO),
        (Verdict.VETO, Verdict.VETO),
    ],
)
def test_a_pass_aggregate_over_components_containing_a_veto_is_an_invariant_violation(
    components: tuple[Verdict, ...],
) -> None:
    with pytest.raises(InvariantViolationError):
        guard_verdict_aggregation(Verdict.PASS, components)


def test_an_empty_component_set_reported_as_pass_is_an_invariant_violation() -> None:
    with pytest.raises(InvariantViolationError):
        guard_verdict_aggregation(Verdict.PASS, ())


def test_a_veto_aggregate_over_all_pass_components_is_also_reported() -> None:
    with pytest.raises(InvariantViolationError):
        guard_verdict_aggregation(Verdict.VETO, (Verdict.PASS, Verdict.PASS))


def test_the_aggregation_violation_names_si_3_and_carries_the_components() -> None:
    with pytest.raises(InvariantViolationError) as excinfo:
        guard_verdict_aggregation(Verdict.PASS, (Verdict.PASS, Verdict.VETO))
    assert "SI-3" in str(excinfo.value)
    assert excinfo.value.context["aggregate"] == "PASS"
    assert excinfo.value.context["expected"] == "VETO"
    assert excinfo.value.context["components"] == ["PASS", "VETO"]


def test_the_guard_accepts_a_one_shot_iterator_of_components() -> None:
    guard_verdict_aggregation(Verdict.VETO, iter((Verdict.PASS, Verdict.VETO)))  # must not raise


# --------------------------------------------------------------------------- #
# SI-7: guard_actuation_authority
# --------------------------------------------------------------------------- #


def test_an_l9_component_may_issue_an_actuator_command() -> None:
    guard_actuation_authority(ComponentId(LayerId.L9_RCM))  # must not raise


def test_a_named_l9_instance_may_also_issue_an_actuator_command() -> None:
    guard_actuation_authority(ComponentId(LayerId.L9_RCM, instance="primary"))  # must not raise


@pytest.mark.parametrize(
    "layer",
    [layer for layer in LayerId if layer is not LayerId.L9_RCM],
    ids=lambda layer: layer.value,
)
def test_no_layer_other_than_l9_may_issue_an_actuator_command(layer: LayerId) -> None:
    with pytest.raises(InvariantViolationError):
        guard_actuation_authority(ComponentId(layer))


def test_the_authority_violation_names_si_7_and_the_offending_layer() -> None:
    with pytest.raises(InvariantViolationError) as excinfo:
        guard_actuation_authority(ComponentId(LayerId.L4_CORE_A_CMDP))
    assert "SI-7" in str(excinfo.value)
    assert excinfo.value.layer is LayerId.L4_CORE_A_CMDP
    assert "L4_CORE_A_CMDP" in excinfo.value.context["issuer"]
