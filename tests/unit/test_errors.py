"""The exception hierarchy and its fail-closed disposition policy."""

from __future__ import annotations

import json
from typing import ClassVar

import pytest

from astra.kernel.enums import EventSeverity, LayerId
from astra.kernel.errors import (
    AdapterError,
    AstraError,
    ConfigurationError,
    ContractViolationError,
    DimensionMismatchError,
    InvariantViolationError,
    NonFiniteValueError,
    RangeViolationError,
    SafetyDisposition,
    SafetyPathError,
    SchemaVersionError,
    TimingBudgetExceededError,
)

_MESSAGE = "boom"
_LONGER_MESSAGE = "the pipeline stalled"

_ALL_ERROR_CLASSES: list[type[AstraError]] = [
    AstraError,
    ConfigurationError,
    SchemaVersionError,
    ContractViolationError,
    RangeViolationError,
    NonFiniteValueError,
    DimensionMismatchError,
    SafetyPathError,
    TimingBudgetExceededError,
    InvariantViolationError,
    AdapterError,
]

_DISPOSITION_POLICY: list[tuple[type[AstraError], str, SafetyDisposition, EventSeverity]] = [
    (AstraError, "ASTRA-000", SafetyDisposition.FAIL_FAST, EventSeverity.SAFETY_CRITICAL),
    (
        ConfigurationError,
        "ASTRA-CFG-001",
        SafetyDisposition.FAIL_FAST,
        EventSeverity.SAFETY_CRITICAL,
    ),
    (
        SchemaVersionError,
        "ASTRA-CFG-002",
        SafetyDisposition.FAIL_FAST,
        EventSeverity.SAFETY_CRITICAL,
    ),
    (
        ContractViolationError,
        "ASTRA-CTR-001",
        SafetyDisposition.FAIL_CLOSED,
        EventSeverity.SAFETY_RELEVANT,
    ),
    (
        RangeViolationError,
        "ASTRA-CTR-002",
        SafetyDisposition.FAIL_CLOSED,
        EventSeverity.SAFETY_RELEVANT,
    ),
    (
        NonFiniteValueError,
        "ASTRA-CTR-003",
        SafetyDisposition.FAIL_CLOSED,
        EventSeverity.SAFETY_RELEVANT,
    ),
    (
        DimensionMismatchError,
        "ASTRA-CTR-004",
        SafetyDisposition.FAIL_CLOSED,
        EventSeverity.SAFETY_RELEVANT,
    ),
    (
        SafetyPathError,
        "ASTRA-SAF-001",
        SafetyDisposition.FAIL_CLOSED,
        EventSeverity.SAFETY_RELEVANT,
    ),
    (
        TimingBudgetExceededError,
        "ASTRA-SAF-002",
        SafetyDisposition.FAIL_CLOSED,
        EventSeverity.SAFETY_CRITICAL,
    ),
    (
        InvariantViolationError,
        "ASTRA-INV-001",
        SafetyDisposition.FAIL_FAST,
        EventSeverity.SAFETY_CRITICAL,
    ),
    (AdapterError, "ASTRA-ADP-001", SafetyDisposition.FAIL_OPERATIONAL, EventSeverity.WARNING),
]

_POLICY_IDS = [entry[0].__name__ for entry in _DISPOSITION_POLICY]
_CODE_BY_CLASS = [(entry[0], entry[1]) for entry in _DISPOSITION_POLICY]


def _class_name(error_class: type[AstraError]) -> str:
    return error_class.__name__


def _raise_type_error() -> None:
    message = "a genuine programming error, not a modelled failure"
    raise TypeError(message)


# --------------------------------------------------------------------------- #
# The disposition policy, class by class
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("error_class", "code", "disposition", "severity"), _DISPOSITION_POLICY, ids=_POLICY_IDS
)
def test_each_error_class_declares_its_documented_code_disposition_and_severity(
    error_class: type[AstraError],
    code: str,
    disposition: SafetyDisposition,
    severity: EventSeverity,
) -> None:
    assert error_class.code == code
    assert error_class.disposition is disposition
    assert error_class.severity is severity


@pytest.mark.parametrize(
    ("error_class", "code", "disposition", "severity"), _DISPOSITION_POLICY, ids=_POLICY_IDS
)
def test_the_class_level_policy_is_visible_on_a_raised_instance(
    error_class: type[AstraError],
    code: str,
    disposition: SafetyDisposition,
    severity: EventSeverity,
) -> None:
    with pytest.raises(error_class) as excinfo:
        raise error_class(_MESSAGE)
    assert excinfo.value.code == code
    assert excinfo.value.disposition is disposition
    assert excinfo.value.severity is severity


def test_every_error_code_is_unique_so_audit_records_stay_greppable() -> None:
    codes = [error_class.code for error_class in _ALL_ERROR_CLASSES]
    assert len(set(codes)) == len(codes)


def test_no_data_contract_error_fails_fast_because_one_bad_frame_must_not_stop_the_loop() -> None:
    contract_errors = [
        ContractViolationError,
        RangeViolationError,
        NonFiniteValueError,
        DimensionMismatchError,
    ]
    assert all(
        error_class.disposition is SafetyDisposition.FAIL_CLOSED for error_class in contract_errors
    )


def test_a_timing_overrun_is_fail_closed_because_a_late_verdict_is_not_a_verdict() -> None:
    assert TimingBudgetExceededError.disposition is SafetyDisposition.FAIL_CLOSED


def test_an_invariant_breach_is_fail_fast_because_no_graduated_response_applies() -> None:
    assert InvariantViolationError.disposition is SafetyDisposition.FAIL_FAST


def test_only_the_adapter_error_defaults_to_fail_operational() -> None:
    operational = [
        error_class
        for error_class in _ALL_ERROR_CLASSES
        if error_class.disposition is SafetyDisposition.FAIL_OPERATIONAL
    ]
    assert operational == [AdapterError]


def test_a_safety_path_adapter_may_override_the_disposition_to_fail_closed() -> None:
    class SensorAdapterError(AdapterError):
        code: ClassVar[str] = "ASTRA-ADP-999"
        disposition: ClassVar[SafetyDisposition] = SafetyDisposition.FAIL_CLOSED
        severity: ClassVar[EventSeverity] = EventSeverity.SAFETY_RELEVANT

    assert SensorAdapterError.disposition is SafetyDisposition.FAIL_CLOSED
    assert issubclass(SensorAdapterError, AdapterError)
    assert SensorAdapterError(_MESSAGE).to_audit_fields()["disposition"] == "FAIL_CLOSED"


def test_safety_disposition_has_exactly_three_members() -> None:
    assert len(SafetyDisposition) == 3


# --------------------------------------------------------------------------- #
# Hierarchy
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("error_class", _ALL_ERROR_CLASSES, ids=_class_name)
def test_every_astra_error_derives_from_the_common_base(error_class: type[AstraError]) -> None:
    assert issubclass(error_class, AstraError)


def test_the_base_derives_directly_from_exception() -> None:
    assert issubclass(AstraError, Exception)
    assert AstraError.__bases__ == (Exception,)


@pytest.mark.parametrize(
    ("child", "parent"),
    [
        (SchemaVersionError, ConfigurationError),
        (RangeViolationError, ContractViolationError),
        (NonFiniteValueError, ContractViolationError),
        (DimensionMismatchError, ContractViolationError),
        (TimingBudgetExceededError, SafetyPathError),
    ],
)
def test_specialised_errors_sit_under_the_right_parent(
    child: type[AstraError], parent: type[AstraError]
) -> None:
    assert issubclass(child, parent)


@pytest.mark.parametrize(
    "error_class", [RangeViolationError, NonFiniteValueError, DimensionMismatchError]
)
def test_catching_contract_violation_catches_every_data_contract_error(
    error_class: type[AstraError],
) -> None:
    with pytest.raises(ContractViolationError):
        raise error_class(_MESSAGE)


def test_a_contract_error_and_a_safety_path_error_are_siblings_not_ancestors() -> None:
    assert not issubclass(ContractViolationError, SafetyPathError)
    assert not issubclass(SafetyPathError, ContractViolationError)


def test_catching_astra_error_leaves_genuine_programming_errors_to_propagate() -> None:
    with pytest.raises(TypeError):
        _raise_type_error()
    assert not issubclass(TypeError, AstraError)


# --------------------------------------------------------------------------- #
# __str__
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(("error_class", "code"), _CODE_BY_CLASS, ids=_POLICY_IDS)
def test_str_carries_the_stable_code_and_the_message(
    error_class: type[AstraError], code: str
) -> None:
    rendered = str(error_class(_LONGER_MESSAGE))
    assert rendered == f"[{code}] {_LONGER_MESSAGE}"
    assert code in rendered


def test_str_of_a_subclass_reports_the_subclass_code_not_the_parent_code() -> None:
    assert str(SchemaVersionError(_MESSAGE)).startswith("[ASTRA-CFG-002]")
    assert str(ConfigurationError(_MESSAGE)).startswith("[ASTRA-CFG-001]")


def test_the_message_attribute_survives_construction() -> None:
    error = ContractViolationError(_LONGER_MESSAGE)
    assert error.message == _LONGER_MESSAGE
    assert error.args == (_LONGER_MESSAGE,)


# --------------------------------------------------------------------------- #
# to_audit_fields
# --------------------------------------------------------------------------- #


def test_to_audit_fields_has_the_documented_key_set() -> None:
    fields = ContractViolationError(_MESSAGE).to_audit_fields()
    assert set(fields) == {
        "error_code",
        "error_type",
        "message",
        "disposition",
        "severity",
        "layer",
        "context",
    }


def test_to_audit_fields_reports_the_concrete_type_name() -> None:
    fields = NonFiniteValueError(_MESSAGE).to_audit_fields()
    assert fields["error_type"] == "NonFiniteValueError"
    assert fields["error_code"] == "ASTRA-CTR-003"
    assert fields["message"] == _MESSAGE


def test_to_audit_fields_renders_a_missing_layer_as_null() -> None:
    assert ContractViolationError(_MESSAGE).to_audit_fields()["layer"] is None


def test_to_audit_fields_renders_a_known_layer_as_its_string_value() -> None:
    error = SafetyPathError(_MESSAGE, layer=LayerId.L7_HARD_SAFETY_SHIELD)
    assert error.layer is LayerId.L7_HARD_SAFETY_SHIELD
    assert error.to_audit_fields()["layer"] == "L7_HARD_SAFETY_SHIELD"


def test_to_audit_fields_defaults_the_context_to_an_empty_mapping() -> None:
    assert ContractViolationError(_MESSAGE).to_audit_fields()["context"] == {}


def test_an_explicitly_empty_context_is_treated_as_no_context() -> None:
    assert ContractViolationError(_MESSAGE, context={}).context == {}


def test_to_audit_fields_carries_supplied_context_through() -> None:
    error = RangeViolationError(_MESSAGE, context={"field": "trust_index", "value": 1.4})
    assert error.to_audit_fields()["context"] == {"field": "trust_index", "value": 1.4}


def test_the_context_is_copied_so_a_later_caller_mutation_cannot_rewrite_the_record() -> None:
    supplied = {"field": "trust_index"}
    error = RangeViolationError(_MESSAGE, context=supplied)
    supplied["field"] = "tampered"
    assert error.context == {"field": "trust_index"}


@pytest.mark.parametrize("error_class", _ALL_ERROR_CLASSES, ids=_class_name)
def test_to_audit_fields_is_json_serialisable_for_every_error_class(
    error_class: type[AstraError],
) -> None:
    error = error_class(
        _MESSAGE,
        layer=LayerId.L9_RCM,
        context={"index": 3, "value": 1.5, "flag": True, "note": "x", "missing": None},
    )
    decoded = json.loads(json.dumps(error.to_audit_fields()))
    assert decoded["error_code"] == error_class.code
    assert decoded["layer"] == "L9_RCM"
    assert decoded["context"]["missing"] is None


def test_the_json_encoded_disposition_and_severity_are_plain_strings() -> None:
    decoded = json.loads(json.dumps(AdapterError(_MESSAGE).to_audit_fields()))
    assert decoded["disposition"] == "FAIL_OPERATIONAL"
    assert decoded["severity"] == "WARNING"
    assert isinstance(decoded["disposition"], str)
