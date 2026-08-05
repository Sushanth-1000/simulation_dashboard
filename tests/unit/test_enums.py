"""The canonical vocabulary, and the fail-closed aggregation built on it."""

from __future__ import annotations

import itertools
import json

import pytest

from astra.kernel.enums import (
    ArbitrationOutcome,
    ContextClass,
    EventSeverity,
    ExecutionDomain,
    FailSafeState,
    FeedbackLoop,
    GateId,
    LayerId,
    SensorModality,
    StreamHealth,
    TimingDomain,
    Verdict,
)

_ALL_ENUMS = [
    ArbitrationOutcome,
    ContextClass,
    EventSeverity,
    ExecutionDomain,
    FailSafeState,
    FeedbackLoop,
    GateId,
    LayerId,
    SensorModality,
    StreamHealth,
    TimingDomain,
    Verdict,
]

# --------------------------------------------------------------------------- #
# Verdict.merge -- separation invariant SI-3, fail-closed aggregation
# --------------------------------------------------------------------------- #


def test_merge_of_empty_verdict_set_is_veto() -> None:
    assert Verdict.merge([]) is Verdict.VETO


def test_merge_of_an_exhausted_iterator_is_veto_not_pass() -> None:
    assert Verdict.merge(iter(())) is Verdict.VETO


def test_merge_of_all_pass_is_pass() -> None:
    assert Verdict.merge([Verdict.PASS, Verdict.PASS, Verdict.PASS]) is Verdict.PASS


def test_merge_of_a_single_pass_is_pass() -> None:
    assert Verdict.merge([Verdict.PASS]) is Verdict.PASS


def test_merge_of_a_single_veto_is_veto() -> None:
    assert Verdict.merge([Verdict.VETO]) is Verdict.VETO


@pytest.mark.parametrize(
    "verdicts",
    [
        [Verdict.VETO, Verdict.PASS, Verdict.PASS],
        [Verdict.PASS, Verdict.VETO, Verdict.PASS],
        [Verdict.PASS, Verdict.PASS, Verdict.VETO],
        [Verdict.VETO, Verdict.VETO, Verdict.VETO],
    ],
)
def test_a_single_veto_survives_every_pass_regardless_of_position(
    verdicts: list[Verdict],
) -> None:
    assert Verdict.merge(verdicts) is Verdict.VETO


def test_merge_is_not_a_majority_vote() -> None:
    outnumbered_veto = [Verdict.PASS] * 99 + [Verdict.VETO]
    assert Verdict.merge(outnumbered_veto) is Verdict.VETO


def test_merge_accepts_any_iterable_including_a_generator() -> None:
    assert Verdict.merge(v for v in (Verdict.PASS, Verdict.PASS)) is Verdict.PASS
    assert Verdict.merge(v for v in (Verdict.PASS, Verdict.VETO)) is Verdict.VETO


def test_merge_is_order_independent() -> None:
    forward = Verdict.merge([Verdict.PASS, Verdict.VETO])
    backward = Verdict.merge([Verdict.VETO, Verdict.PASS])
    assert forward is backward is Verdict.VETO


def test_merging_the_result_of_a_merge_is_stable() -> None:
    once = Verdict.merge([Verdict.PASS, Verdict.VETO])
    assert Verdict.merge([once]) is once


# --------------------------------------------------------------------------- #
# Abstention (ADR-0016) -- withdrawing from the judgement, never clearing it
# --------------------------------------------------------------------------- #


def test_merge_of_all_abstentions_is_veto_exactly_as_an_empty_set_is() -> None:
    # THE test for this feature. An abstention removes a gate from the
    # aggregation; if every gate withdraws, nothing judged the command, and a
    # command nothing judged has not been cleared. Returning PASS here would let
    # a gate clear a command by declining to look at it, which is the fail-open
    # mode SI-3 exists to prevent -- reached by a new route.
    assert Verdict.merge([Verdict.ABSTAIN]) is Verdict.VETO
    assert Verdict.merge([Verdict.ABSTAIN, Verdict.ABSTAIN, Verdict.ABSTAIN]) is Verdict.VETO
    assert Verdict.merge([Verdict.ABSTAIN] * 3) is Verdict.merge([])


def test_an_abstention_does_not_block_a_command_the_others_cleared() -> None:
    # The other half: an abstention is not a veto either. One gate having no
    # basis to judge must not stop the two that do.
    assert Verdict.merge([Verdict.PASS, Verdict.ABSTAIN]) is Verdict.PASS
    assert Verdict.merge([Verdict.ABSTAIN, Verdict.PASS, Verdict.PASS]) is Verdict.PASS


def test_an_abstention_cannot_rescue_a_vetoed_command() -> None:
    assert Verdict.merge([Verdict.VETO, Verdict.ABSTAIN]) is Verdict.VETO
    assert Verdict.merge([Verdict.ABSTAIN, Verdict.VETO, Verdict.PASS]) is Verdict.VETO


@pytest.mark.parametrize(
    "verdicts",
    [
        [Verdict.ABSTAIN, Verdict.PASS],
        [Verdict.PASS, Verdict.ABSTAIN],
        [Verdict.ABSTAIN, Verdict.VETO],
        [Verdict.VETO, Verdict.ABSTAIN],
    ],
)
def test_merge_stays_order_independent_with_abstentions(verdicts: list[Verdict]) -> None:
    assert Verdict.merge(verdicts) is Verdict.merge(list(reversed(verdicts)))


# --------------------------------------------------------------------------- #
# Verdict.is_blocking
# --------------------------------------------------------------------------- #


def test_veto_is_blocking() -> None:
    assert Verdict.VETO.is_blocking is True


def test_pass_is_not_blocking() -> None:
    assert Verdict.PASS.is_blocking is False


def test_exactly_one_verdict_is_blocking() -> None:
    assert [verdict for verdict in Verdict if verdict.is_blocking] == [Verdict.VETO]


def test_verdict_has_exactly_three_members() -> None:
    # Two judgements and one refusal to judge. ADR-0016 added ABSTAIN; the count
    # is pinned because a fourth value would be a change to what a gate is
    # allowed to say, which is an architectural decision and not a tidy-up.
    assert len(Verdict) == 3


def test_only_an_abstention_declines_to_participate() -> None:
    assert Verdict.PASS.participates
    assert Verdict.VETO.participates
    assert not Verdict.ABSTAIN.participates


# --------------------------------------------------------------------------- #
# LayerId
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("layer", "ordinal"),
    [
        (LayerId.L1_SENSOR_BUS, 1),
        (LayerId.L2_DUAL_RATE_UKF, 2),
        (LayerId.L3_CONFORMAL_TRUST, 3),
        (LayerId.L4_CORE_A_CMDP, 4),
        (LayerId.L5_PINN_TWIN, 5),
        (LayerId.L6_MPC_ICP_GATE, 6),
        (LayerId.L7_HARD_SAFETY_SHIELD, 7),
        (LayerId.L8_FAILSAFE_FSM, 8),
        (LayerId.L9_RCM, 9),
    ],
)
def test_layer_ordinal_is_the_one_based_number_in_the_member_name(
    layer: LayerId, ordinal: int
) -> None:
    assert layer.ordinal == ordinal


def test_layer_ordinals_are_the_contiguous_range_one_to_nine() -> None:
    assert sorted(layer.ordinal for layer in LayerId) == list(range(1, 10))


def test_layer_declaration_order_matches_ordinal_order() -> None:
    assert [layer.ordinal for layer in LayerId] == list(range(1, 10))


@pytest.mark.parametrize(
    ("layer", "domain"),
    [
        (LayerId.L1_SENSOR_BUS, ExecutionDomain.SHARED),
        (LayerId.L2_DUAL_RATE_UKF, ExecutionDomain.SHARED),
        (LayerId.L3_CONFORMAL_TRUST, ExecutionDomain.SHARED),
        (LayerId.L4_CORE_A_CMDP, ExecutionDomain.CORE_A),
        (LayerId.L5_PINN_TWIN, ExecutionDomain.CORE_B),
        (LayerId.L6_MPC_ICP_GATE, ExecutionDomain.CORE_B),
        (LayerId.L7_HARD_SAFETY_SHIELD, ExecutionDomain.CORE_B),
        (LayerId.L8_FAILSAFE_FSM, ExecutionDomain.CORE_B),
        (LayerId.L9_RCM, ExecutionDomain.ARBITRATOR),
    ],
)
def test_execution_domain_maps_all_nine_layers(layer: LayerId, domain: ExecutionDomain) -> None:
    assert layer.execution_domain is domain


def test_every_layer_has_an_execution_domain() -> None:
    assert all(isinstance(layer.execution_domain, ExecutionDomain) for layer in LayerId)


def test_exactly_one_layer_is_the_untrusted_proposer() -> None:
    core_a = [layer for layer in LayerId if layer.execution_domain is ExecutionDomain.CORE_A]
    assert core_a == [LayerId.L4_CORE_A_CMDP]


def test_exactly_one_layer_is_the_arbitrator() -> None:
    arbitrators = [
        layer for layer in LayerId if layer.execution_domain is ExecutionDomain.ARBITRATOR
    ]
    assert arbitrators == [LayerId.L9_RCM]


def test_the_safety_island_holds_the_four_core_b_layers() -> None:
    core_b = [layer for layer in LayerId if layer.execution_domain is ExecutionDomain.CORE_B]
    assert core_b == [
        LayerId.L5_PINN_TWIN,
        LayerId.L6_MPC_ICP_GATE,
        LayerId.L7_HARD_SAFETY_SHIELD,
        LayerId.L8_FAILSAFE_FSM,
    ]


def test_every_execution_domain_owns_at_least_one_layer() -> None:
    owned = {layer.execution_domain for layer in LayerId}
    assert owned == set(ExecutionDomain)


# --------------------------------------------------------------------------- #
# FailSafeState
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("state", "rank"),
    [
        (FailSafeState.NOMINAL, 0),
        (FailSafeState.DEGRADED, 1),
        (FailSafeState.LIMP, 2),
        (FailSafeState.HALT, 3),
    ],
)
def test_failsafe_severity_rank_is_zero_for_nominal_through_three_for_halt(
    state: FailSafeState, rank: int
) -> None:
    assert state.severity_rank == rank


def test_failsafe_severity_ranks_are_strictly_increasing_in_declaration_order() -> None:
    ranks = [state.severity_rank for state in FailSafeState]
    assert all(earlier < later for earlier, later in itertools.pairwise(ranks))


def test_halt_outranks_every_other_failsafe_state() -> None:
    assert all(
        FailSafeState.HALT.severity_rank > state.severity_rank
        for state in FailSafeState
        if state is not FailSafeState.HALT
    )


def test_every_failsafe_state_has_a_distinct_rank() -> None:
    ranks = [state.severity_rank for state in FailSafeState]
    assert len(set(ranks)) == len(ranks)


# --------------------------------------------------------------------------- #
# ContextClass
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("context", "certified"),
    [
        (ContextClass.HIGHWAY_CLEAR, True),
        (ContextClass.URBAN_CLEAR, True),
        (ContextClass.RAIN_NIGHT, True),
        (ContextClass.DEGRADED_SENSOR, True),
        (ContextClass.UNCLASSIFIED, False),
    ],
)
def test_only_unclassified_is_not_certifiable(context: ContextClass, certified: bool) -> None:
    assert context.is_certified is certified


def test_exactly_one_context_class_is_uncertifiable() -> None:
    uncertified = [context for context in ContextClass if not context.is_certified]
    assert uncertified == [ContextClass.UNCLASSIFIED]


def test_no_tunnel_context_class_is_declared() -> None:
    assert not any("TUNNEL" in context.name for context in ContextClass)


# --------------------------------------------------------------------------- #
# FeedbackLoop
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("loop", "relevant"),
    [
        (FeedbackLoop.FB1_UKF_REANCHOR, True),
        (FeedbackLoop.FB2_PINN_ADAPT, True),
        (FeedbackLoop.FB3_TRUST_RECALIBRATE, True),
        (FeedbackLoop.FB4_SIMULATOR_SYNC, False),
    ],
)
def test_only_the_simulator_sync_loop_has_no_deployment_counterpart(
    loop: FeedbackLoop, relevant: bool
) -> None:
    assert loop.is_deployment_relevant is relevant


def test_three_of_the_four_feedback_loops_survive_into_deployment() -> None:
    deployed = [loop for loop in FeedbackLoop if loop.is_deployment_relevant]
    assert len(deployed) == 3


def test_feedback_loop_declaration_order_is_the_bring_up_order() -> None:
    assert [loop.name[:3] for loop in FeedbackLoop] == ["FB1", "FB2", "FB3", "FB4"]


# --------------------------------------------------------------------------- #
# Serialisation and hygiene, shared by every enumeration
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("enumeration", _ALL_ENUMS)
def test_every_enum_member_serialises_to_its_own_name_without_a_custom_encoder(
    enumeration: type[FailSafeState],
) -> None:
    members = list(enumeration)
    assert json.loads(json.dumps(members)) == [member.name for member in members]


@pytest.mark.parametrize("enumeration", _ALL_ENUMS)
def test_every_enum_value_equals_its_member_name(enumeration: type[FailSafeState]) -> None:
    assert all(member.value == member.name for member in enumeration)


@pytest.mark.parametrize("enumeration", _ALL_ENUMS)
def test_every_enum_round_trips_through_its_string_value(
    enumeration: type[FailSafeState],
) -> None:
    assert all(enumeration(member.value) is member for member in enumeration)


@pytest.mark.parametrize("enumeration", _ALL_ENUMS)
def test_every_enum_has_unique_values(enumeration: type[FailSafeState]) -> None:
    values = [member.value for member in enumeration]
    assert len(set(values)) == len(values)


def test_str_enum_members_compare_equal_to_their_string_value() -> None:
    assert Verdict.VETO == "VETO"
    assert GateId.DETERMINISTIC == "DETERMINISTIC"


@pytest.mark.parametrize(
    ("enumeration", "count"),
    [
        (LayerId, 9),
        (ExecutionDomain, 4),
        (Verdict, 3),
        (GateId, 3),
        (FailSafeState, 4),
        (ContextClass, 5),
        (SensorModality, 5),
        (StreamHealth, 4),
        (TimingDomain, 2),
        (ArbitrationOutcome, 5),
        (FeedbackLoop, 4),
        (EventSeverity, 5),
    ],
)
def test_enumeration_membership_counts_are_pinned(
    enumeration: type[FailSafeState], count: int
) -> None:
    assert len(enumeration) == count


def test_a_stale_stream_and_a_lying_stream_are_distinct_health_states() -> None:
    assert len({StreamHealth.DEGRADED, StreamHealth.FAULTED}) == 2
