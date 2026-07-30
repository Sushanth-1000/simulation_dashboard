"""Architectural constants, and their agreement with the enumerations."""

from __future__ import annotations

import pytest

from astra.kernel import constants
from astra.kernel.constants import (
    ASTRA_LAYER_COUNT,
    AUDIT_SCHEMA_VERSION,
    CONFIG_SCHEMA_VERSION,
    CORE_B_GATE_COUNT,
    FAILSAFE_STATE_COUNT,
    FAST_STATE_DIMENSION,
    FAST_STATE_FIELDS,
    FEEDBACK_LOOP_COUNT,
    RCS_DIMENSION,
    RCS_FIELDS,
    SENSOR_MODALITY_COUNT,
    SLOW_STATE_DIMENSION,
    SLOW_STATE_FIELDS,
)
from astra.kernel.enums import FailSafeState, FeedbackLoop, GateId, LayerId, SensorModality

# --------------------------------------------------------------------------- #
# Cardinality constants must agree with the enumerations they describe
# --------------------------------------------------------------------------- #


def test_layer_count_matches_the_layer_enumeration() -> None:
    assert len(LayerId) == ASTRA_LAYER_COUNT


def test_gate_count_matches_the_gate_enumeration() -> None:
    assert len(GateId) == CORE_B_GATE_COUNT


def test_feedback_loop_count_matches_the_feedback_loop_enumeration() -> None:
    assert len(FeedbackLoop) == FEEDBACK_LOOP_COUNT


def test_failsafe_state_count_matches_the_failsafe_state_enumeration() -> None:
    assert len(FailSafeState) == FAILSAFE_STATE_COUNT


def test_sensor_modality_count_matches_the_sensor_modality_enumeration() -> None:
    assert len(SensorModality) == SENSOR_MODALITY_COUNT


@pytest.mark.parametrize(
    ("constant", "expected"),
    [
        (ASTRA_LAYER_COUNT, 9),
        (CORE_B_GATE_COUNT, 3),
        (FEEDBACK_LOOP_COUNT, 4),
        (FAILSAFE_STATE_COUNT, 4),
        (SENSOR_MODALITY_COUNT, 5),
    ],
)
def test_documented_cardinalities_are_pinned_to_their_literal_values(
    constant: int, expected: int
) -> None:
    assert constant == expected


@pytest.mark.parametrize(
    "constant",
    [
        ASTRA_LAYER_COUNT,
        CORE_B_GATE_COUNT,
        FEEDBACK_LOOP_COUNT,
        FAILSAFE_STATE_COUNT,
        SENSOR_MODALITY_COUNT,
    ],
)
def test_every_cardinality_is_a_positive_int_and_not_a_bool(constant: int) -> None:
    assert isinstance(constant, int)
    assert not isinstance(constant, bool)
    assert constant > 0


# --------------------------------------------------------------------------- #
# State vector layouts: dimensions are derived from the field tuples
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("fields", "dimension"),
    [
        (FAST_STATE_FIELDS, FAST_STATE_DIMENSION),
        (SLOW_STATE_FIELDS, SLOW_STATE_DIMENSION),
        (RCS_FIELDS, RCS_DIMENSION),
    ],
)
def test_each_declared_dimension_equals_the_length_of_its_field_tuple(
    fields: tuple[str, ...], dimension: int
) -> None:
    assert dimension == len(fields)


@pytest.mark.parametrize(
    ("dimension", "expected"),
    [
        (FAST_STATE_DIMENSION, 5),
        (SLOW_STATE_DIMENSION, 3),
        (RCS_DIMENSION, 5),
    ],
)
def test_state_vector_dimensions_are_pinned_to_their_documented_values(
    dimension: int, expected: int
) -> None:
    assert dimension == expected


@pytest.mark.parametrize("fields", [FAST_STATE_FIELDS, SLOW_STATE_FIELDS, RCS_FIELDS])
def test_field_layouts_are_immutable_tuples(fields: tuple[str, ...]) -> None:
    assert isinstance(fields, tuple)


@pytest.mark.parametrize("fields", [FAST_STATE_FIELDS, SLOW_STATE_FIELDS, RCS_FIELDS])
def test_field_names_are_unique_within_a_layout(fields: tuple[str, ...]) -> None:
    assert len(set(fields)) == len(fields)


@pytest.mark.parametrize("fields", [FAST_STATE_FIELDS, SLOW_STATE_FIELDS, RCS_FIELDS])
def test_field_names_are_non_empty_lower_snake_case_identifiers(fields: tuple[str, ...]) -> None:
    assert all(name and name.isidentifier() and name == name.lower() for name in fields)


def test_fast_state_ordering_is_the_documented_px_py_v_psi_alat_layout() -> None:
    assert FAST_STATE_FIELDS == (
        "position_x",
        "position_y",
        "speed",
        "heading",
        "lateral_acceleration",
    )


def test_slow_state_ordering_is_the_documented_degradation_layout() -> None:
    assert SLOW_STATE_FIELDS == (
        "road_friction_coefficient",
        "tyre_wear_index",
        "sensor_health_score",
    )


def test_runtime_context_signature_ordering_is_the_documented_layout() -> None:
    assert RCS_FIELDS == (
        "visibility",
        "ego_speed",
        "traffic_dynamicity",
        "sensor_reliability",
        "road_complexity",
    )


def test_the_fast_and_slow_state_layouts_share_no_field_name() -> None:
    assert not set(FAST_STATE_FIELDS) & set(SLOW_STATE_FIELDS)


def test_the_fast_state_supplies_the_lateral_acceleration_the_shield_bounds() -> None:
    assert "lateral_acceleration" in FAST_STATE_FIELDS


# --------------------------------------------------------------------------- #
# Schema versions
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        (AUDIT_SCHEMA_VERSION, 1),
        (CONFIG_SCHEMA_VERSION, 1),
    ],
)
def test_schema_versions_start_at_one(version: int, expected: int) -> None:
    assert version == expected


@pytest.mark.parametrize("version", [AUDIT_SCHEMA_VERSION, CONFIG_SCHEMA_VERSION])
def test_schema_versions_are_positive_ints(version: int) -> None:
    assert isinstance(version, int)
    assert not isinstance(version, bool)
    assert version >= 1


# --------------------------------------------------------------------------- #
# No operating point leaked into the constants module
# --------------------------------------------------------------------------- #


def test_no_threshold_style_name_is_exported_from_the_constants_module() -> None:
    forbidden = ("THRESHOLD", "EPSILON", "THETA", "TAU", "GAMMA", "DELTA", "SPEED_CAP")
    assert not [name for name in constants.__all__ if any(term in name for term in forbidden)]


def test_the_public_surface_is_exactly_what_dunder_all_declares() -> None:
    assert sorted(constants.__all__) == list(constants.__all__)
    assert all(hasattr(constants, name) for name in constants.__all__)
