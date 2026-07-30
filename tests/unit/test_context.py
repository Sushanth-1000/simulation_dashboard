"""Unit tests for the run/tick/component correlation context and event sequencing."""

from __future__ import annotations

import pytest

from astra.kernel.enums import LayerId
from astra.kernel.errors import InvariantViolationError
from astra.kernel.identifiers import ComponentId, RunId, TickId
from astra.observability.context import (
    current_component,
    current_run,
    current_tick,
    next_event_id,
    run_scope,
    tick_scope,
)

SHADOW = ComponentId(LayerId.L9_RCM, "shadow")
PRIMARY = ComponentId(LayerId.L9_RCM)
TWIN = ComponentId(LayerId.L5_PINN_TWIN)


# --------------------------------------------------------------------------- #
# Outside every scope
# --------------------------------------------------------------------------- #


def test_the_current_run_is_none_outside_a_run_scope() -> None:
    assert current_run() is None


def test_the_current_tick_is_none_outside_a_tick_scope() -> None:
    assert current_tick() is None


def test_the_current_component_is_none_when_nothing_bound_it() -> None:
    assert current_component() is None


# --------------------------------------------------------------------------- #
# run_scope
# --------------------------------------------------------------------------- #


def test_a_run_scope_binds_the_run_for_the_duration_of_the_block(run: RunId) -> None:
    with run_scope(run) as bound:
        assert bound is run
        assert current_run() == run


def test_a_run_scope_restores_the_absence_of_a_run_on_exit(run: RunId) -> None:
    with run_scope(run):
        pass

    assert current_run() is None


def test_a_run_scope_restores_the_previous_run_exactly(run: RunId) -> None:
    outer = RunId("run-outer0001")

    with run_scope(outer):
        with run_scope(run):
            assert current_run() == run
        assert current_run() == outer

    assert current_run() is None


def test_a_run_scope_restores_the_run_even_when_the_block_raises(run: RunId) -> None:
    with pytest.raises(ZeroDivisionError), run_scope(run):
        raise ZeroDivisionError

    assert current_run() is None


def test_a_run_scope_binds_a_component_when_one_is_supplied(run: RunId) -> None:
    with run_scope(run, PRIMARY):
        assert current_component() == PRIMARY

    assert current_component() is None


def test_a_run_scope_without_a_component_leaves_the_component_untouched(run: RunId) -> None:
    with run_scope(RunId("run-outer0001"), TWIN), run_scope(run):
        assert current_component() == TWIN


# --------------------------------------------------------------------------- #
# tick_scope
# --------------------------------------------------------------------------- #


def test_a_tick_scope_binds_the_tick_for_the_duration_of_the_block(
    run: RunId, tick: TickId
) -> None:
    with run_scope(run), tick_scope(tick) as bound:
        assert bound is tick
        assert current_tick() == tick


def test_a_tick_scope_restores_the_absence_of_a_tick_on_exit(run: RunId, tick: TickId) -> None:
    with run_scope(run):
        with tick_scope(tick):
            pass
        assert current_tick() is None


def test_sequential_tick_scopes_each_restore_the_previous_tick(run: RunId) -> None:
    first = TickId(1)
    second = TickId(2)

    with run_scope(run):
        with tick_scope(first):
            assert current_tick() == first
        with tick_scope(second):
            assert current_tick() == second
        assert current_tick() is None


def test_a_nested_tick_scope_restores_the_enclosing_tick_exactly(run: RunId) -> None:
    outer = TickId(7)
    inner = TickId(8)

    with run_scope(run), tick_scope(outer):
        with tick_scope(inner):
            assert current_tick() == inner
        assert current_tick() == outer


def test_a_tick_scope_restores_the_tick_even_when_the_block_raises(
    run: RunId, tick: TickId
) -> None:
    with run_scope(run):
        with pytest.raises(ZeroDivisionError), tick_scope(tick):
            raise ZeroDivisionError
        assert current_tick() is None


def test_a_tick_scope_entered_outside_a_run_scope_raises_an_invariant_violation(
    tick: TickId,
) -> None:
    with pytest.raises(InvariantViolationError) as raised, tick_scope(tick):
        pass  # pragma: no cover - the scope never opens

    assert raised.value.context["tick"] == tick.value


def test_a_tick_scope_entered_after_its_run_scope_closed_raises(run: RunId, tick: TickId) -> None:
    with run_scope(run):
        pass

    with pytest.raises(InvariantViolationError), tick_scope(tick):
        pass  # pragma: no cover - the scope never opens


def test_a_tick_scope_binds_the_shadow_component_so_its_records_are_distinguishable(
    run: RunId, tick: TickId
) -> None:
    with run_scope(run, PRIMARY):
        with tick_scope(tick, SHADOW):
            assert current_component() == SHADOW
            assert str(current_component()) == "L9_RCM/shadow"
        assert current_component() == PRIMARY


# --------------------------------------------------------------------------- #
# next_event_id
# --------------------------------------------------------------------------- #


def test_next_event_id_outside_every_scope_raises_an_invariant_violation() -> None:
    with pytest.raises(InvariantViolationError) as raised:
        next_event_id()

    assert raised.value.context == {"has_run": False, "has_tick": False}


def test_next_event_id_inside_a_run_but_outside_a_tick_raises(run: RunId) -> None:
    with run_scope(run), pytest.raises(InvariantViolationError) as raised:
        next_event_id()

    assert raised.value.context == {"has_run": True, "has_tick": False}


def test_next_event_id_after_the_tick_scope_closed_raises(run: RunId, tick: TickId) -> None:
    with run_scope(run):
        with tick_scope(tick):
            next_event_id()
        with pytest.raises(InvariantViolationError):
            next_event_id()


def test_the_event_sequence_starts_at_zero_and_increments_within_a_tick(
    run: RunId, tick: TickId
) -> None:
    with run_scope(run), tick_scope(tick):
        sequences = [next_event_id().sequence for _ in range(4)]

    assert sequences == [0, 1, 2, 3]


def test_the_event_sequence_resets_at_the_next_tick(run: RunId) -> None:
    with run_scope(run):
        with tick_scope(TickId(1)):
            first = [next_event_id().sequence for _ in range(3)]
        with tick_scope(TickId(2)):
            second = [next_event_id().sequence for _ in range(3)]

    assert first == [0, 1, 2]
    assert second == [0, 1, 2]


def test_an_event_identifier_carries_the_run_and_tick_in_scope(run: RunId, tick: TickId) -> None:
    with run_scope(run), tick_scope(tick):
        event_id = next_event_id()

    assert event_id.run == run
    assert event_id.tick == tick
    assert str(event_id) == f"{run}:{tick}:0000"


def test_a_nested_tick_scope_gets_its_own_sequence_and_the_outer_one_survives(
    run: RunId,
) -> None:
    with run_scope(run), tick_scope(TickId(1)):
        assert next_event_id().sequence == 0
        with tick_scope(TickId(2)):
            assert next_event_id().sequence == 0
            assert next_event_id().sequence == 1
        assert next_event_id().sequence == 1


def test_two_identical_scope_sequences_produce_identical_event_identifiers(run: RunId) -> None:
    def replay() -> list[str]:
        with run_scope(run), tick_scope(TickId(4200)):
            return [str(next_event_id()) for _ in range(3)]

    assert replay() == replay()
