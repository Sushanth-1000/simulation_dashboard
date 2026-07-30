"""Typed identifiers: validation, determinism and canonical rendering."""

from __future__ import annotations

import pytest

from astra.kernel.enums import LayerId
from astra.kernel.errors import ContractViolationError
from astra.kernel.identifiers import ComponentId, EventId, ProfileId, RunId, TickId

# --------------------------------------------------------------------------- #
# RunId
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "value",
    [
        "abc",
        "run-testfixture01",
        "run_2026_07_29",
        "a00",
        "0ab",
        "a" * 64,
        "9" + "-" * 63,
    ],
)
def test_run_id_accepts_a_lower_case_slug_of_three_to_sixty_four_characters(value: str) -> None:
    assert RunId(value).value == value


@pytest.mark.parametrize(
    "value",
    [
        "",
        "a",
        "ab",
        "a" * 65,
        "RUN-1",
        "run 1",
        "-run",
        "_run",
        "run.1",
        "run/1",
        "rün-1",
    ],
)
def test_run_id_rejects_anything_that_is_not_a_valid_slug(value: str) -> None:
    with pytest.raises(ContractViolationError):
        RunId(value)


def test_a_rejected_run_id_reports_the_offending_value_in_its_audit_context() -> None:
    with pytest.raises(ContractViolationError) as excinfo:
        RunId("NOPE")
    assert excinfo.value.context == {"value": "NOPE"}
    assert excinfo.value.code == "ASTRA-CTR-001"


def test_generate_produces_a_valid_run_prefixed_identifier() -> None:
    generated = RunId.generate()
    assert generated.value.startswith("run-")
    assert len(generated.value) == len("run-") + 16
    assert RunId(generated.value) == generated


def test_generate_is_the_one_deliberately_non_deterministic_identifier() -> None:
    assert RunId.generate() != RunId.generate()


def test_run_id_str_is_the_raw_slug() -> None:
    assert str(RunId("run-abc")) == "run-abc"


def test_run_id_is_frozen_and_hashable() -> None:
    run = RunId("run-abc")
    assert hash(run) == hash(RunId("run-abc"))
    with pytest.raises(AttributeError):
        run.value = "other"  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# TickId
# --------------------------------------------------------------------------- #


def test_tick_origin_is_zero() -> None:
    assert TickId.origin() == TickId(0)
    assert TickId.ORIGIN == 0
    assert TickId.origin().value == 0


def test_next_returns_the_following_tick_without_mutating_the_original() -> None:
    tick = TickId(41)
    following = tick.next()
    assert following == TickId(42)
    assert tick == TickId(41)


def test_repeated_next_walks_the_tick_sequence() -> None:
    tick = TickId.origin()
    for _ in range(5):
        tick = tick.next()
    assert tick == TickId(5)


def test_tick_ids_order_by_their_numeric_value() -> None:
    assert TickId(1) < TickId(2)
    assert TickId(2) > TickId(1)
    assert TickId(2) <= TickId(2)
    assert TickId(2) >= TickId(2)


def test_a_list_of_tick_ids_sorts_chronologically() -> None:
    unordered = [TickId(9), TickId(0), TickId(4)]
    assert sorted(unordered) == [TickId(0), TickId(4), TickId(9)]


@pytest.mark.parametrize("value", [-1, -42, -1_000_000])
def test_tick_id_rejects_a_negative_tick_number(value: int) -> None:
    with pytest.raises(ContractViolationError) as excinfo:
        TickId(value)
    assert excinfo.value.context == {"value": value}


@pytest.mark.parametrize("value", [True, False])
def test_tick_id_rejects_a_bool_even_though_bool_is_a_subclass_of_int(value: bool) -> None:
    with pytest.raises(ContractViolationError):
        TickId(value)


@pytest.mark.parametrize("value", [1.0, "4", None, 2.5])
def test_tick_id_rejects_a_non_integer_from_a_deserialised_record(value: object) -> None:
    with pytest.raises(ContractViolationError):
        TickId(value)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("value", "rendered"),
    [
        (0, "000000000"),
        (42, "000000042"),
        (4200, "000004200"),
        (999_999_999, "999999999"),
        (1_000_000_000, "1000000000"),
    ],
)
def test_tick_id_str_is_zero_padded_to_nine_digits_for_stable_log_alignment(
    value: int, rendered: str
) -> None:
    assert str(TickId(value)) == rendered


def test_tick_ids_of_equal_value_are_equal_and_hash_alike() -> None:
    assert TickId(7) == TickId(7)
    assert len({TickId(7), TickId(7)}) == 1


# --------------------------------------------------------------------------- #
# ProfileId
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "text",
    ["rain_night@v2", "highway_clear@v1", "abc@v999", "urban_clear@v10"],
)
def test_profile_id_parse_round_trips_through_its_canonical_form(text: str) -> None:
    assert str(ProfileId.parse(text)) == text


def test_profile_id_parse_extracts_the_name_and_version() -> None:
    profile = ProfileId.parse("rain_night@v2")
    assert profile.name == "rain_night"
    assert profile.version == 2


def test_profile_id_str_is_the_canonical_name_at_v_version_form() -> None:
    assert str(ProfileId(name="highway_clear", version=3)) == "highway_clear@v3"


@pytest.mark.parametrize(
    "text",
    ["rain_night", "rain_night@2", "rain_night@v", "rain_night@vx", "@v1", "rain_night@v2.1"],
)
def test_profile_id_parse_rejects_text_not_in_name_at_v_number_form(text: str) -> None:
    with pytest.raises(ContractViolationError):
        ProfileId.parse(text)


def test_a_rejected_parse_reports_the_offending_text_in_its_audit_context() -> None:
    with pytest.raises(ContractViolationError) as excinfo:
        ProfileId.parse("rain_night")
    assert excinfo.value.context == {"text": "rain_night"}


@pytest.mark.parametrize(
    "name",
    ["", "ab", "Highway", "1highway", "_highway", "highway-clear", "highway clear", "a" * 49],
)
def test_profile_id_rejects_a_malformed_family_name(name: str) -> None:
    with pytest.raises(ContractViolationError):
        ProfileId(name=name, version=1)


@pytest.mark.parametrize("name", ["abc", "a" * 48, "highway_clear", "a1_2"])
def test_profile_id_accepts_a_well_formed_family_name(name: str) -> None:
    assert ProfileId(name=name, version=1).name == name


@pytest.mark.parametrize("version", [0, -1, -100])
def test_profile_id_rejects_a_version_below_one(version: int) -> None:
    with pytest.raises(ContractViolationError) as excinfo:
        ProfileId(name="highway_clear", version=version)
    assert excinfo.value.context == {"version": version}


@pytest.mark.parametrize("version", [True, False])
def test_profile_id_rejects_a_bool_version(version: bool) -> None:
    with pytest.raises(ContractViolationError):
        ProfileId(name="highway_clear", version=version)


@pytest.mark.parametrize("version", [1.0, "2", None])
def test_profile_id_rejects_a_non_integer_version_from_a_calibration_file(
    version: object,
) -> None:
    with pytest.raises(ContractViolationError):
        ProfileId(name="highway_clear", version=version)  # type: ignore[arg-type]


def test_two_versions_of_the_same_profile_family_are_distinct_identities() -> None:
    assert ProfileId("highway_clear", 1) != ProfileId("highway_clear", 2)


# --------------------------------------------------------------------------- #
# ComponentId
# --------------------------------------------------------------------------- #


def test_component_instance_defaults_to_primary() -> None:
    assert ComponentId(LayerId.L9_RCM).instance == "primary"


def test_component_str_is_the_canonical_layer_slash_instance_form() -> None:
    assert str(ComponentId(LayerId.L9_RCM, "shadow")) == "L9_RCM/shadow"
    assert str(ComponentId(LayerId.L4_CORE_A_CMDP)) == "L4_CORE_A_CMDP/primary"


def test_the_active_and_shadow_calibration_tables_are_distinguishable() -> None:
    active = ComponentId(LayerId.L9_RCM, "primary")
    shadow = ComponentId(LayerId.L9_RCM, "shadow")
    assert active != shadow
    assert str(active) != str(shadow)


def test_component_rejects_an_empty_instance_discriminator() -> None:
    with pytest.raises(ContractViolationError) as excinfo:
        ComponentId(LayerId.L9_RCM, "")
    assert excinfo.value.context == {"instance": ""}


def test_component_rejects_an_instance_discriminator_over_thirty_two_characters() -> None:
    with pytest.raises(ContractViolationError):
        ComponentId(LayerId.L9_RCM, "x" * 33)


def test_component_accepts_an_instance_discriminator_of_exactly_thirty_two_characters() -> None:
    assert ComponentId(LayerId.L9_RCM, "x" * 32).instance == "x" * 32


def test_component_ids_are_hashable_so_they_can_key_a_registry() -> None:
    registry = {ComponentId(LayerId.L1_SENSOR_BUS): "bus"}
    assert registry[ComponentId(LayerId.L1_SENSOR_BUS, "primary")] == "bus"


# --------------------------------------------------------------------------- #
# EventId
# --------------------------------------------------------------------------- #


def test_event_id_is_a_pure_function_of_run_tick_and_sequence(run: RunId, tick: TickId) -> None:
    assert EventId(run, tick, 3) == EventId(run, tick, 3)


def test_two_replays_of_the_same_run_produce_identical_event_identities() -> None:
    first = EventId(RunId("run-abc"), TickId(4200), 3)
    second = EventId(RunId("run-abc"), TickId(4200), 3)
    assert first == second
    assert str(first) == str(second)
    assert hash(first) == hash(second)


def test_event_ids_differing_in_any_component_are_distinct(run: RunId, tick: TickId) -> None:
    base = EventId(run, tick, 0)
    assert base != EventId(RunId("run-other"), tick, 0)
    assert base != EventId(run, tick.next(), 0)
    assert base != EventId(run, tick, 1)


def test_event_sort_key_is_run_then_tick_then_sequence(run: RunId, tick: TickId) -> None:
    assert EventId(run, tick, 3).sort_key == (run.value, tick.value, 3)


def test_sorting_events_of_one_run_by_sort_key_is_chronological(run: RunId) -> None:
    events = [
        EventId(run, TickId(2), 0),
        EventId(run, TickId(1), 5),
        EventId(run, TickId(1), 0),
    ]
    assert [event.sort_key for event in sorted(events, key=lambda e: e.sort_key)] == [
        (run.value, 1, 0),
        (run.value, 1, 5),
        (run.value, 2, 0),
    ]


def test_event_ids_are_deliberately_not_directly_orderable(run: RunId, tick: TickId) -> None:
    with pytest.raises(TypeError):
        _ = EventId(run, tick, 0) < EventId(run, tick, 1)  # type: ignore[operator]


def test_event_str_is_the_canonical_run_colon_tick_colon_sequence_form() -> None:
    event = EventId(RunId("run-1a2b3c"), TickId(4200), 3)
    assert str(event) == "run-1a2b3c:000004200:0003"


def test_event_sequence_is_zero_padded_to_four_digits() -> None:
    assert str(EventId(RunId("run-abc"), TickId(0), 0)).endswith(":0000")
    assert str(EventId(RunId("run-abc"), TickId(0), 12345)).endswith(":12345")


@pytest.mark.parametrize("sequence", [-1, -7])
def test_event_id_rejects_a_negative_intra_tick_sequence(run: RunId, sequence: int) -> None:
    with pytest.raises(ContractViolationError) as excinfo:
        EventId(run, TickId(0), sequence)
    assert excinfo.value.context == {"sequence": sequence}


def test_event_id_accepts_a_zero_sequence_as_the_first_event_of_a_tick(run: RunId) -> None:
    assert EventId(run, TickId(0), 0).sequence == 0
