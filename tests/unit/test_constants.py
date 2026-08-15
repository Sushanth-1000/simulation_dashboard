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
        # Audit v2: ADR-0016 widened the gate-verdict vocabulary with ABSTAIN.
        # Audit v3: the decision record carries `fast_innovation`, the one
        # quantity in it that can disagree with the state estimate. It was
        # always computed and never archived, which is how OD-9 came to be
        # unanswerable from the evidence log.
        # Audit v4: the record carries `ablation`, naming which layers were
        # disarmed. The one boundary where an old reader is *dangerously*
        # wrong rather than merely poorer: a v3 reader sees an ablated run's
        # records as a governed run's, because every other field is identical
        # by construction -- that is what an ablation is.
        # Audit v5: every record carries `previous_digest`, making the log a
        # hash chain and therefore tamper-evident rather than merely
        # integrity-checked -- N-10, and the cheapest item in the threat
        # model.
        # Audit v6: the fail-safe snapshot carries `integrity_counter`. The
        # machine now escalates on two independent counters -- sustained refusal
        # and sustained sensor unhealth -- and the state alone no longer says
        # which (ADR-0024, OD-9). A v5 archive showing NOMINAL through a sensor
        # fault is *correct about the machine that wrote it* and must not be
        # compared against a v6 archive as the same system.
        # Audit v7: the arbitration decision carries the `signature` RCM
        # actually decided on. It was computed every cold-path evaluation,
        # searched the knowledge base with, and archived nowhere -- so a record
        # could say SAFE_EXPLORATION and could not say what context produced it
        # (OD-14). Third time this shape has appeared, after v3 and v5.
        # Audit v8: the snapshot's `integrity_counter` reaches the *record*. v6
        # put it on the snapshot and stopped there, so the archive carried
        # ADR-0024's conclusion and none of its evidence (OD-16). Found by the
        # explainer rather than by a test, which is why the explainer exists.
        # Audit v9: the fail-safe snapshot carries `withdrawn_capabilities`.
        # ADR-0029 gave the machine a second *axis*: `state` records how bad
        # things were getting, this records what was broken, and the two are
        # independent -- a v9 row can read NOMINAL with lane changes withdrawn.
        # A v8 archive cannot express that, and a missing list there means
        # nobody asked rather than nothing was withdrawn.
        # Audit v10: the snapshot carries `sensor_decay` and
        # `sensors_needing_service`. Every other number in the record resets when
        # the trouble passes; measured, that makes an intermittent fault
        # invisible -- a camera dark on alternate frames for a full minute held
        # the integrity counter at 1 and the posture at NOMINAL (E-135, OD-21).
        # A v9 archive of a fleet cannot be mined for sensor wear at all, and
        # absence of the field there means nobody was counting.
        # Pinned rather than merely bounded, so that a schema change has to be a
        # decision someone made here as well as there. This pin has now fired
        # seven times for that reason and did its job every time.
        (AUDIT_SCHEMA_VERSION, 10),
        (CONFIG_SCHEMA_VERSION, 1),
    ],
)
def test_schema_versions_are_the_pinned_values(version: int, expected: int) -> None:
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
