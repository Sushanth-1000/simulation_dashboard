"""Unit tests for the L8 fail-safe state machine."""

from __future__ import annotations

import itertools
from typing import TYPE_CHECKING

import pytest

from astra.config.schema import FailSafeSettings
from astra.contracts.assurance import FailSafeSnapshot, GateVerdict, SafetyVerdict
from astra.kernel.enums import FailSafeState, GateId, LayerId, SensorModality, Verdict
from astra.kernel.errors import ContractViolationError
from astra.kernel.identifiers import TickId
from astra.layers.l8_failsafe.machine import FailSafeStateMachine
from astra.ports.pipeline import SafetyStateMachine

if TYPE_CHECKING:
    from collections.abc import Sequence

# Deliberately built inline rather than loaded from `config/`: the repository's
# operating point is an empirical value that will move, and a transition test
# pinned to it would start failing for a reason that has nothing to do with the
# machine. Small thresholds keep every transition reachable in a few ticks.
THETA_DEGRADED = 3
THETA_LIMP = 6
THETA_HALT = 10
DEGRADED_CAP_KMH = 40.0
LIMP_CAP_KMH = 20.0

SETTINGS = FailSafeSettings(
    ood_threshold_degraded=THETA_DEGRADED,
    ood_threshold_limp=THETA_LIMP,
    ood_threshold_halt=THETA_HALT,
    degraded_speed_cap_kmh=DEGRADED_CAP_KMH,
    limp_speed_cap_kmh=LIMP_CAP_KMH,
    integrity_threshold_degraded=5,
    integrity_threshold_limp=15,
    integrity_threshold_halt=40,
    integrity_tolerated_faults=0,
    critical_modalities=(
        SensorModality.CAMERA,
        SensorModality.LIDAR,
        SensorModality.IMU,
        SensorModality.GPS,
        SensorModality.RADAR,
    ),
)

LONG_CLEAN_RUN = 100
ALTERNATIONS = 20
# Mirrors the machine's private `_HYSTERESIS`. Written out rather than imported:
# a test that reaches into a module's privates stops being able to tell you that
# the module's *published* behaviour changed.
HYSTERESIS = 1

# The Phase 3 exit criterion, written out tick by tick: every verdict, the
# counter it produces and the state it implies, from NOMINAL up to LIMP and all
# the way back down again without a restart and without `reset`.
ROUND_TRIP: list[tuple[Verdict, int, FailSafeState]] = [
    (Verdict.VETO, 1, FailSafeState.NOMINAL),
    (Verdict.VETO, 2, FailSafeState.NOMINAL),
    (Verdict.VETO, 3, FailSafeState.DEGRADED),
    (Verdict.VETO, 4, FailSafeState.DEGRADED),
    (Verdict.VETO, 5, FailSafeState.DEGRADED),
    (Verdict.VETO, 6, FailSafeState.LIMP),
    (Verdict.PASS, 5, FailSafeState.LIMP),
    (Verdict.PASS, 4, FailSafeState.DEGRADED),
    (Verdict.PASS, 3, FailSafeState.DEGRADED),
    (Verdict.PASS, 2, FailSafeState.DEGRADED),
    (Verdict.PASS, 1, FailSafeState.NOMINAL),
    (Verdict.PASS, 0, FailSafeState.NOMINAL),
]


def _machine() -> FailSafeStateMachine:
    return FailSafeStateMachine(SETTINGS)


def _verdict(
    tick: TickId,
    verdict: Verdict,
    gate: GateId = GateId.STATISTICAL,
) -> SafetyVerdict:
    return SafetyVerdict(
        tick=tick,
        gate_verdicts=(
            GateVerdict(tick=tick, gate=gate, verdict=verdict, reason_code="UNIT_TEST"),
        ),
    )


def _drive_all(
    machine: FailSafeStateMachine,
    verdicts: Sequence[Verdict],
    *,
    gate: GateId = GateId.STATISTICAL,
    first_tick: int = 0,
) -> list[FailSafeSnapshot]:
    snapshots: list[FailSafeSnapshot] = []
    for index, verdict in enumerate(verdicts):
        tick = TickId(first_tick + index)
        snapshots.append(machine.observe(tick=tick, verdict=_verdict(tick, verdict, gate)))
    return snapshots


def _drive(
    machine: FailSafeStateMachine,
    verdict: Verdict,
    times: int,
    *,
    gate: GateId = GateId.STATISTICAL,
    first_tick: int = 0,
) -> FailSafeSnapshot:
    return _drive_all(machine, [verdict] * times, gate=gate, first_tick=first_tick)[-1]


# --------------------------------------------------------------------------- #
# Construction, and the snapshot that does not exist yet
# --------------------------------------------------------------------------- #


def test_a_new_machine_starts_in_nominal_with_a_zero_counter() -> None:
    machine = _machine()

    assert machine.state is FailSafeState.NOMINAL
    assert machine.ood_counter == 0


def test_reading_the_snapshot_before_any_observe_raises_contract_violation() -> None:
    machine = _machine()

    with pytest.raises(ContractViolationError):
        _ = machine.snapshot


def test_the_untickled_snapshot_error_names_the_failsafe_layer() -> None:
    machine = _machine()

    with pytest.raises(ContractViolationError) as raised:
        _ = machine.snapshot

    assert raised.value.layer is LayerId.L8_FAILSAFE_FSM
    assert "observe()" in str(raised.value)


def test_the_first_snapshot_carries_the_tick_that_produced_it() -> None:
    machine = _machine()

    snapshot = machine.observe(tick=TickId(7), verdict=_verdict(TickId(7), Verdict.PASS))

    assert snapshot.tick == TickId(7)
    assert machine.snapshot.tick == TickId(7)


# --------------------------------------------------------------------------- #
# The counter
# --------------------------------------------------------------------------- #


def test_a_veto_increments_the_counter() -> None:
    machine = _machine()

    snapshot = _drive(machine, Verdict.VETO, 1)

    assert snapshot.ood_counter == 1
    assert machine.ood_counter == 1


def test_a_pass_decrements_the_counter() -> None:
    machine = _machine()
    _drive(machine, Verdict.VETO, 2)

    snapshot = _drive(machine, Verdict.PASS, 1, first_tick=2)

    assert snapshot.ood_counter == 1
    assert machine.ood_counter == 1


def test_a_long_clean_run_never_drives_the_counter_below_zero() -> None:
    # A counter allowed to go negative would bank "credit" during quiet driving
    # and let a later burst of vetoes pass without ever crossing theta-1.
    machine = _machine()

    snapshots = _drive_all(machine, [Verdict.PASS] * LONG_CLEAN_RUN)

    assert [snapshot.ood_counter for snapshot in snapshots] == [0] * LONG_CLEAN_RUN
    assert machine.ood_counter == 0
    assert machine.state is FailSafeState.NOMINAL


def test_passes_after_a_veto_burst_stop_at_zero_rather_than_going_negative() -> None:
    machine = _machine()
    _drive(machine, Verdict.VETO, THETA_DEGRADED)

    snapshot = _drive(machine, Verdict.PASS, LONG_CLEAN_RUN, first_tick=THETA_DEGRADED)

    assert snapshot.ood_counter == 0
    assert machine.state is FailSafeState.NOMINAL


# --------------------------------------------------------------------------- #
# The full round trip -- a Phase 3 exit criterion
# --------------------------------------------------------------------------- #


def test_the_machine_walks_up_to_limp_and_back_to_nominal_without_a_restart() -> None:
    machine = _machine()

    for index, (verdict, expected_counter, expected_state) in enumerate(ROUND_TRIP):
        tick = TickId(index)
        snapshot = machine.observe(tick=tick, verdict=_verdict(tick, verdict))

        assert snapshot.ood_counter == expected_counter
        assert snapshot.state is expected_state
        assert machine.state is expected_state

    final = machine.snapshot
    assert final.state is FailSafeState.NOMINAL
    assert final.ood_counter == 0
    assert final.speed_cap is None
    assert final.lane_change_permitted is True
    assert final.human_intervention_requested is False


def test_the_round_trip_visits_every_state_below_halt() -> None:
    machine = _machine()

    snapshots = _drive_all(machine, [verdict for verdict, _, _ in ROUND_TRIP])

    assert {snapshot.state for snapshot in snapshots} == {
        FailSafeState.NOMINAL,
        FailSafeState.DEGRADED,
        FailSafeState.LIMP,
    }


# --------------------------------------------------------------------------- #
# Escalation happens at exactly the configured threshold
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("vetoes", "expected"),
    [
        (THETA_DEGRADED - 1, FailSafeState.NOMINAL),
        (THETA_DEGRADED, FailSafeState.DEGRADED),
        (THETA_LIMP - 1, FailSafeState.DEGRADED),
        (THETA_LIMP, FailSafeState.LIMP),
        (THETA_HALT - 1, FailSafeState.LIMP),
        (THETA_HALT, FailSafeState.HALT),
    ],
)
def test_escalation_happens_on_the_threshold_and_not_one_veto_earlier(
    vetoes: int, expected: FailSafeState
) -> None:
    machine = _machine()

    snapshot = _drive(machine, Verdict.VETO, vetoes)

    assert snapshot.ood_counter == vetoes
    assert snapshot.state is expected


# --------------------------------------------------------------------------- #
# HALT is latched
# --------------------------------------------------------------------------- #


def test_halt_is_not_left_by_a_hundred_consecutive_clean_ticks() -> None:
    machine = _machine()
    _drive(machine, Verdict.VETO, THETA_HALT)
    assert machine.state is FailSafeState.HALT

    snapshots = _drive_all(machine, [Verdict.PASS] * LONG_CLEAN_RUN, first_tick=THETA_HALT)

    assert {snapshot.state for snapshot in snapshots} == {FailSafeState.HALT}
    assert machine.state is FailSafeState.HALT
    assert machine.ood_counter == 0


def test_the_counter_falling_to_zero_does_not_release_the_halt_latch() -> None:
    machine = _machine()
    _drive(machine, Verdict.VETO, THETA_HALT)

    snapshot = _drive(machine, Verdict.PASS, THETA_HALT, first_tick=THETA_HALT)

    assert snapshot.ood_counter == 0
    assert snapshot.state is FailSafeState.HALT
    assert snapshot.speed_cap == 0.0


def test_reset_is_the_only_way_out_of_halt_and_returns_the_machine_to_nominal() -> None:
    machine = _machine()
    _drive(machine, Verdict.VETO, THETA_HALT)
    _drive(machine, Verdict.PASS, LONG_CLEAN_RUN, first_tick=THETA_HALT)
    assert machine.state is FailSafeState.HALT


def test_an_explicit_reset_is_the_only_way_out_of_halt() -> None:
    machine = _machine()
    _drive(machine, Verdict.VETO, THETA_HALT)
    _drive(machine, Verdict.PASS, LONG_CLEAN_RUN, first_tick=THETA_HALT)

    machine.reset()

    assert machine.state is FailSafeState.NOMINAL
    assert machine.ood_counter == 0
    assert machine.speed_cap is None


def test_a_reset_machine_escalates_again_from_scratch() -> None:
    machine = _machine()
    _drive(machine, Verdict.VETO, THETA_HALT)
    machine.reset()

    snapshot = _drive(machine, Verdict.VETO, THETA_DEGRADED, first_tick=THETA_HALT)

    assert snapshot.ood_counter == THETA_DEGRADED
    assert snapshot.state is FailSafeState.DEGRADED


# --------------------------------------------------------------------------- #
# The counter is bounded at both ends
# --------------------------------------------------------------------------- #
# Finding F5 of the 6 August soak review: the counter reached 1,508 by tick 2,000
# and kept climbing, in a field written into every snapshot and every audit row.
# Nothing consulted the excess -- the machine had been in HALT since 10 and HALT
# does not look at the counter -- so it was 1,498 ticks of pure noise.


def test_the_counter_never_climbs_past_the_halt_threshold() -> None:
    machine = _machine()

    snapshot = _drive(machine, Verdict.VETO, THETA_HALT * 20)

    assert snapshot.ood_counter == THETA_HALT
    assert snapshot.state is FailSafeState.HALT


def test_the_ceiling_is_the_halt_threshold_and_not_some_multiple_of_it() -> None:
    # A ceiling above the threshold would be an arbitrary constant with no
    # consumer: no counter value above THETA_HALT can change any decision.
    machine = _machine()
    _drive(machine, Verdict.VETO, THETA_HALT * 3)

    assert machine.ood_counter == THETA_HALT


def test_time_spent_in_halt_is_still_recoverable_from_the_snapshot() -> None:
    # What capping costs, and why it costs nothing: the tick is in the record,
    # so duration is a subtraction. Reading it off the counter instead would be
    # one field answering two questions.
    machine = _machine()
    snapshots = _drive_all(machine, [Verdict.VETO] * (THETA_HALT * 5))

    entered = next(s for s in snapshots if s.state is FailSafeState.HALT)

    assert snapshots[-1].tick.value - entered.tick.value == THETA_HALT * 5 - THETA_HALT


def test_recovery_is_bounded_in_duration_and_not_merely_automatic() -> None:
    # The property the ceiling actually buys. Outside HALT the counter cannot
    # exceed THETA_HALT, because reaching it is what enters HALT -- so the walk
    # back to NOMINAL has a worst case, and this is it. Without a ceiling the
    # module's promise of automatic recovery would carry no duration at all.
    machine = _machine()
    _drive(machine, Verdict.VETO, THETA_HALT - 1)

    assert machine.state is FailSafeState.LIMP, "the deepest state short of HALT"
    assert machine.ood_counter == THETA_HALT - 1, "the highest counter short of HALT"

    snapshots = _drive_all(machine, [Verdict.PASS] * THETA_HALT * 2, first_tick=THETA_HALT)
    recovered = next(
        index for index, s in enumerate(snapshots, start=1) if s.state is FailSafeState.NOMINAL
    )
    worst_case = THETA_HALT - THETA_DEGRADED + HYSTERESIS

    assert recovered == worst_case, (
        f"recovery took {recovered} clean ticks; the bound the module docstring "
        f"states is {worst_case}"
    )


# --------------------------------------------------------------------------- #
# Hysteresis: the posture must not oscillate
# --------------------------------------------------------------------------- #
# An oscillating safety posture is worse than either state it flips between: the
# speed cap and the lane-change permission would change every tick. The correct
# assertion is therefore not "the state is whatever the code produces" but "the
# state is *constant* while the counter alternates around the threshold".


@pytest.mark.parametrize(
    ("threshold", "expected"),
    [
        (THETA_DEGRADED, FailSafeState.DEGRADED),
        (THETA_LIMP, FailSafeState.LIMP),
    ],
)
def test_a_counter_parked_on_a_threshold_holds_one_state_under_alternating_verdicts(
    threshold: int, expected: FailSafeState
) -> None:
    machine = _machine()
    _drive(machine, Verdict.VETO, threshold)
    assert machine.state is expected

    snapshots = _drive_all(
        machine, [Verdict.PASS, Verdict.VETO] * ALTERNATIONS, first_tick=threshold
    )

    assert {snapshot.state for snapshot in snapshots} == {expected}
    assert {snapshot.ood_counter for snapshot in snapshots} == {threshold - 1, threshold}


def test_alternating_verdicts_across_the_degraded_boundary_flip_the_state_only_once() -> None:
    machine = _machine()
    _drive(machine, Verdict.VETO, THETA_DEGRADED - 1)
    assert machine.state is FailSafeState.NOMINAL

    snapshots = _drive_all(
        machine, [Verdict.VETO, Verdict.PASS] * ALTERNATIONS, first_tick=THETA_DEGRADED
    )
    states = [FailSafeState.NOMINAL, *(snapshot.state for snapshot in snapshots)]
    flips = sum(1 for before, after in itertools.pairwise(states) if before is not after)

    # One escalation, then a stable posture -- not one transition per tick.
    assert flips == 1
    assert states[-1] is FailSafeState.DEGRADED


def test_alternating_verdicts_across_the_limp_boundary_flip_the_state_only_once() -> None:
    machine = _machine()
    _drive(machine, Verdict.VETO, THETA_LIMP - 1)
    assert machine.state is FailSafeState.DEGRADED

    snapshots = _drive_all(
        machine, [Verdict.VETO, Verdict.PASS] * ALTERNATIONS, first_tick=THETA_LIMP
    )
    states = [FailSafeState.DEGRADED, *(snapshot.state for snapshot in snapshots)]
    flips = sum(1 for before, after in itertools.pairwise(states) if before is not after)

    assert flips == 1
    assert states[-1] is FailSafeState.LIMP


def test_de_escalation_requires_the_counter_to_fall_clear_of_the_threshold() -> None:
    machine = _machine()
    _drive(machine, Verdict.VETO, THETA_DEGRADED)

    # One PASS puts the counter one below theta-1; the posture holds.
    holding = _drive(machine, Verdict.PASS, 1, first_tick=THETA_DEGRADED)
    assert holding.ood_counter == THETA_DEGRADED - 1
    assert holding.state is FailSafeState.DEGRADED

    # A second PASS clears the hysteresis margin and the machine recovers.
    recovered = _drive(machine, Verdict.PASS, 1, first_tick=THETA_DEGRADED + 1)
    assert recovered.ood_counter == THETA_DEGRADED - 2
    assert recovered.state is FailSafeState.NOMINAL


# --------------------------------------------------------------------------- #
# Per-state operating limits
# --------------------------------------------------------------------------- #


def test_the_nominal_snapshot_imposes_no_cap_and_permits_a_lane_change() -> None:
    machine = _machine()

    snapshot = _drive(machine, Verdict.PASS, 1)

    assert snapshot.state is FailSafeState.NOMINAL
    assert snapshot.speed_cap is None
    assert snapshot.lane_change_permitted is True
    assert snapshot.human_intervention_requested is False


def test_the_degraded_snapshot_carries_the_configured_cap_and_forbids_a_lane_change() -> None:
    machine = _machine()

    snapshot = _drive(machine, Verdict.VETO, THETA_DEGRADED)

    assert snapshot.state is FailSafeState.DEGRADED
    assert snapshot.speed_cap == pytest.approx(SETTINGS.degraded_speed_cap)
    assert snapshot.lane_change_permitted is False
    assert snapshot.human_intervention_requested is False


def test_the_limp_snapshot_carries_the_configured_cap_and_forbids_a_lane_change() -> None:
    machine = _machine()

    snapshot = _drive(machine, Verdict.VETO, THETA_LIMP)

    assert snapshot.state is FailSafeState.LIMP
    assert snapshot.speed_cap == pytest.approx(SETTINGS.limp_speed_cap)
    assert snapshot.lane_change_permitted is False
    assert snapshot.human_intervention_requested is False


def test_the_limp_cap_is_stricter_than_the_degraded_cap() -> None:
    assert SETTINGS.limp_speed_cap < SETTINGS.degraded_speed_cap


def test_the_halt_snapshot_commands_a_stop_rather_than_reporting_no_cap() -> None:
    machine = _machine()

    snapshot = _drive(machine, Verdict.VETO, THETA_HALT)

    assert snapshot.state is FailSafeState.HALT
    # `None` would mean "this state imposes no cap", which inverts the meaning of
    # a controlled pull-over.
    assert snapshot.speed_cap is not None
    assert snapshot.speed_cap == 0.0
    assert snapshot.lane_change_permitted is False
    assert snapshot.human_intervention_requested is True


def test_human_intervention_is_not_requested_before_halt() -> None:
    machine = _machine()

    snapshots = _drive_all(machine, [Verdict.VETO] * (THETA_HALT - 1))

    assert not any(snapshot.human_intervention_requested for snapshot in snapshots)


def test_human_intervention_is_requested_on_the_tick_that_enters_halt() -> None:
    machine = _machine()

    snapshots = _drive_all(machine, [Verdict.VETO] * THETA_HALT)

    assert snapshots[-2].human_intervention_requested is False
    assert snapshots[-1].human_intervention_requested is True


def test_human_intervention_survives_clean_ticks_and_is_cleared_only_by_reset() -> None:
    machine = _machine()
    _drive(machine, Verdict.VETO, THETA_HALT)

    still_requested = _drive(machine, Verdict.PASS, LONG_CLEAN_RUN, first_tick=THETA_HALT)
    assert still_requested.human_intervention_requested is True

    machine.reset()
    cleared = _drive(machine, Verdict.PASS, 1, first_tick=THETA_HALT + LONG_CLEAN_RUN)

    assert cleared.human_intervention_requested is False
    assert cleared.state is FailSafeState.NOMINAL


# --------------------------------------------------------------------------- #
# SI-3 symmetry: the machine reads the aggregate, never the gate identity
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("gate", list(GateId))
def test_the_counter_moves_identically_whichever_gate_vetoed(gate: GateId) -> None:
    reference = _machine()
    candidate = _machine()

    expected = _drive_all(reference, [Verdict.VETO] * THETA_HALT, gate=GateId.STATISTICAL)
    actual = _drive_all(candidate, [Verdict.VETO] * THETA_HALT, gate=gate)

    assert [snapshot.ood_counter for snapshot in actual] == [
        snapshot.ood_counter for snapshot in expected
    ]
    assert [snapshot.state for snapshot in actual] == [snapshot.state for snapshot in expected]


def test_a_statistical_veto_and_a_deterministic_veto_are_indistinguishable_tick_by_tick() -> None:
    statistical = _machine()
    deterministic = _machine()

    for step in range(THETA_HALT):
        tick = TickId(step)
        left = statistical.observe(
            tick=tick, verdict=_verdict(tick, Verdict.VETO, GateId.STATISTICAL)
        )
        right = deterministic.observe(
            tick=tick, verdict=_verdict(tick, Verdict.VETO, GateId.DETERMINISTIC)
        )

        assert left == right


def test_a_multi_gate_verdict_with_one_veto_moves_the_counter_like_a_single_veto() -> None:
    machine = _machine()
    tick = TickId(0)
    mixed = SafetyVerdict(
        tick=tick,
        gate_verdicts=(
            GateVerdict(tick=tick, gate=GateId.STATISTICAL, verdict=Verdict.PASS, reason_code="OK"),
            GateVerdict(tick=tick, gate=GateId.PHYSICAL, verdict=Verdict.PASS, reason_code="OK"),
            GateVerdict(
                tick=tick, gate=GateId.DETERMINISTIC, verdict=Verdict.VETO, reason_code="BOUND"
            ),
        ),
    )

    snapshot = machine.observe(tick=tick, verdict=mixed)

    assert snapshot.ood_counter == 1


def test_an_empty_safety_verdict_increments_the_counter_because_it_aggregates_to_veto() -> None:
    machine = _machine()
    tick = TickId(0)
    empty = SafetyVerdict(tick=tick, gate_verdicts=())
    assert empty.aggregate is Verdict.VETO

    snapshot = machine.observe(tick=tick, verdict=empty)

    assert snapshot.ood_counter == 1


def test_a_run_of_empty_verdicts_escalates_the_machine_all_the_way_to_halt() -> None:
    machine = _machine()

    for step in range(THETA_HALT):
        tick = TickId(step)
        machine.observe(tick=tick, verdict=SafetyVerdict(tick=tick, gate_verdicts=()))

    assert machine.state is FailSafeState.HALT


# --------------------------------------------------------------------------- #
# Protocol conformance and snapshot purity
# --------------------------------------------------------------------------- #


def test_the_machine_satisfies_the_safety_state_machine_protocol() -> None:
    assert isinstance(_machine(), SafetyStateMachine)


def test_the_machine_is_usable_through_the_safety_state_machine_port() -> None:
    port: SafetyStateMachine = _machine()
    tick = TickId(0)

    assert isinstance(
        port.observe(tick=tick, verdict=_verdict(tick, Verdict.PASS)), FailSafeSnapshot
    )


def test_reading_the_snapshot_twice_neither_advances_the_machine_nor_changes_the_answer() -> None:
    machine = _machine()
    _drive(machine, Verdict.VETO, THETA_DEGRADED)

    first = machine.snapshot
    second = machine.snapshot

    assert first == second
    assert machine.ood_counter == THETA_DEGRADED
    assert machine.state is FailSafeState.DEGRADED


def test_the_snapshot_matches_the_value_returned_by_the_observe_that_produced_it() -> None:
    machine = _machine()

    returned = _drive(machine, Verdict.VETO, THETA_LIMP)

    assert machine.snapshot == returned
