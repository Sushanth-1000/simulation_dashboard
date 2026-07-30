"""Unit tests for the actuation contracts, including separation invariant SI-7."""

from __future__ import annotations

import pytest

from astra.contracts.actuation import (
    ActuationChannel,
    ActuationSpace,
    CommandOrigin,
    ControlCommand,
    IssuedCommand,
    PredictedCommand,
    ProposedCommand,
)
from astra.kernel.enums import LayerId
from astra.kernel.errors import (
    ContractViolationError,
    DimensionMismatchError,
    InvariantViolationError,
    NonFiniteValueError,
)
from astra.kernel.identifiers import ComponentId, TickId
from astra.kernel.time import Instant

# --------------------------------------------------------------------------- #
# ActuationChannel
# --------------------------------------------------------------------------- #


def test_actuation_channel_contains_values_at_and_inside_its_inclusive_bounds() -> None:
    channel = ActuationChannel(name="steer", lower=-0.5, upper=0.5, unit="rad")

    assert channel.contains(-0.5)
    assert channel.contains(0.0)
    assert channel.contains(0.5)


def test_actuation_channel_does_not_contain_values_outside_its_bounds() -> None:
    channel = ActuationChannel(name="steer", lower=-0.5, upper=0.5, unit="rad")

    assert not channel.contains(-0.500_001)
    assert not channel.contains(0.500_001)


def test_actuation_channel_never_contains_a_nan_so_it_cannot_pass_a_bounds_check() -> None:
    channel = ActuationChannel(name="throttle", lower=0.0, upper=1.0, unit="1")

    assert not channel.contains(float("nan"))


def test_actuation_channel_clamp_confines_values_to_the_interval() -> None:
    channel = ActuationChannel(name="steer", lower=-0.5, upper=0.5, unit="rad")

    assert channel.clamp(2.0) == 0.5
    assert channel.clamp(-2.0) == -0.5
    assert channel.clamp(0.1) == 0.1


def test_actuation_channel_clamp_of_a_nan_raises_rather_than_producing_a_bound() -> None:
    channel = ActuationChannel(name="steer", lower=-0.5, upper=0.5, unit="rad")

    with pytest.raises(NonFiniteValueError):
        channel.clamp(float("nan"))


def test_actuation_channel_with_an_empty_name_raises_contract_violation() -> None:
    with pytest.raises(ContractViolationError):
        ActuationChannel(name="", lower=0.0, upper=1.0, unit="1")


def test_actuation_channel_with_lower_above_upper_raises_contract_violation() -> None:
    with pytest.raises(ContractViolationError) as raised:
        ActuationChannel(name="brake", lower=1.0, upper=0.0, unit="1")

    assert raised.value.context["channel"] == "brake"


def test_actuation_channel_with_a_degenerate_but_valid_interval_is_accepted() -> None:
    channel = ActuationChannel(name="gear", lower=1.0, upper=1.0, unit="1")

    assert channel.contains(1.0)
    assert channel.clamp(5.0) == 1.0


def test_actuation_channel_with_an_infinite_bound_raises_non_finite_value() -> None:
    with pytest.raises(NonFiniteValueError):
        ActuationChannel(name="throttle", lower=0.0, upper=float("inf"), unit="1")


# --------------------------------------------------------------------------- #
# ActuationSpace
# --------------------------------------------------------------------------- #


def test_actuation_space_exposes_its_dimension_and_canonical_channel_names(
    actuation_space: ActuationSpace,
) -> None:
    assert actuation_space.dimension == 2
    assert actuation_space.names == ("throttle", "steer")


def test_actuation_space_with_no_channels_raises_contract_violation() -> None:
    with pytest.raises(ContractViolationError):
        ActuationSpace(())


def test_actuation_space_with_duplicate_channel_names_raises_contract_violation() -> None:
    with pytest.raises(ContractViolationError) as raised:
        ActuationSpace(
            (
                ActuationChannel(name="steer", lower=-0.5, upper=0.5, unit="rad"),
                ActuationChannel(name="steer", lower=-1.0, upper=1.0, unit="rad"),
            )
        )

    assert raised.value.context["names"] == ["steer", "steer"]


def test_actuation_space_channel_lookup_returns_the_named_channel(
    actuation_space: ActuationSpace,
) -> None:
    channel = actuation_space.channel("steer")

    assert channel.unit == "rad"
    assert channel.lower == -0.5


def test_actuation_space_channel_lookup_of_an_unknown_name_raises_contract_violation(
    actuation_space: ActuationSpace,
) -> None:
    with pytest.raises(ContractViolationError) as raised:
        actuation_space.channel("brake")

    assert raised.value.context["known"] == ["throttle", "steer"]


def test_actuation_space_contains_accepts_an_in_bounds_vector(
    actuation_space: ActuationSpace,
) -> None:
    assert actuation_space.contains((0.5, 0.1))


def test_actuation_space_contains_rejects_an_out_of_bounds_component(
    actuation_space: ActuationSpace,
) -> None:
    assert not actuation_space.contains((0.5, 0.9))


def test_actuation_space_contains_rejects_a_vector_of_the_wrong_length(
    actuation_space: ActuationSpace,
) -> None:
    assert not actuation_space.contains((0.5,))
    assert not actuation_space.contains((0.5, 0.1, 0.0))


def test_actuation_space_clamp_confines_every_component_to_its_own_channel(
    actuation_space: ActuationSpace,
) -> None:
    assert actuation_space.clamp((5.0, -3.0)) == (1.0, -0.5)


def test_actuation_space_clamp_of_a_wrong_length_vector_raises_dimension_mismatch(
    actuation_space: ActuationSpace,
) -> None:
    with pytest.raises(DimensionMismatchError):
        actuation_space.clamp((0.5,))


# --------------------------------------------------------------------------- #
# ControlCommand
# --------------------------------------------------------------------------- #


def test_control_command_allows_an_inadmissible_vector_so_the_shield_can_catch_it(
    actuation_space: ActuationSpace,
) -> None:
    command = ControlCommand(space=actuation_space, values=(3.0, -2.0))

    assert command.values == (3.0, -2.0)
    assert not command.is_admissible()


def test_control_command_reports_an_in_bounds_vector_as_admissible(
    actuation_space: ActuationSpace,
) -> None:
    command = ControlCommand(space=actuation_space, values=(0.4, 0.2))

    assert command.is_admissible()


def test_control_command_with_the_wrong_dimension_raises_dimension_mismatch(
    actuation_space: ActuationSpace,
) -> None:
    with pytest.raises(DimensionMismatchError):
        ControlCommand(space=actuation_space, values=(0.4,))


def test_control_command_with_a_nan_component_raises_non_finite_value(
    actuation_space: ActuationSpace,
) -> None:
    with pytest.raises(NonFiniteValueError):
        ControlCommand(space=actuation_space, values=(float("nan"), 0.0))


def test_control_command_with_an_infinite_component_raises_non_finite_value(
    actuation_space: ActuationSpace,
) -> None:
    with pytest.raises(NonFiniteValueError):
        ControlCommand(space=actuation_space, values=(0.0, float("-inf")))


def test_control_command_value_of_returns_the_component_for_a_named_channel(
    actuation_space: ActuationSpace,
) -> None:
    command = ControlCommand(space=actuation_space, values=(0.4, -0.2))

    assert command.value_of("throttle") == 0.4
    assert command.value_of("steer") == -0.2


def test_control_command_value_of_an_unknown_channel_raises_contract_violation(
    actuation_space: ActuationSpace,
) -> None:
    command = ControlCommand(space=actuation_space, values=(0.4, -0.2))

    with pytest.raises(ContractViolationError) as raised:
        command.value_of("brake")

    assert raised.value.context["name"] == "brake"


def test_control_command_clamped_returns_an_admissible_copy_leaving_the_original(
    actuation_space: ActuationSpace,
) -> None:
    command = ControlCommand(space=actuation_space, values=(3.0, -2.0))

    clamped = command.clamped()

    assert clamped.values == (1.0, -0.5)
    assert clamped.is_admissible()
    assert command.values == (3.0, -2.0)


def test_control_command_normalises_a_list_of_values_into_an_immutable_tuple(
    actuation_space: ActuationSpace,
) -> None:
    mutable = [0.4, 0.2]
    command = ControlCommand(space=actuation_space, values=mutable)  # type: ignore[arg-type]
    mutable[0] = 99.0

    assert isinstance(command.values, tuple)
    assert command.values == (0.4, 0.2)


# --------------------------------------------------------------------------- #
# ProposedCommand and PredictedCommand -- provenance
# --------------------------------------------------------------------------- #


def test_proposed_command_from_the_l4_proposer_is_accepted(
    tick: TickId,
    now: Instant,
    actuation_space: ActuationSpace,
    proposer_component: ComponentId,
) -> None:
    proposal = ProposedCommand(
        tick=tick,
        proposed_at=now,
        command=ControlCommand(space=actuation_space, values=(0.4, 0.2)),
        origin=CommandOrigin.PROPOSED,
        source=proposer_component,
    )

    assert proposal.source is proposer_component


def test_proposed_command_may_carry_an_inadmissible_vector_for_the_gates_to_veto(
    tick: TickId,
    now: Instant,
    actuation_space: ActuationSpace,
    proposer_component: ComponentId,
) -> None:
    proposal = ProposedCommand(
        tick=tick,
        proposed_at=now,
        command=ControlCommand(space=actuation_space, values=(9.0, 9.0)),
        origin=CommandOrigin.PROPOSED,
        source=proposer_component,
    )

    assert not proposal.command.is_admissible()


def test_proposed_command_from_a_non_l4_source_raises_contract_violation(
    tick: TickId,
    now: Instant,
    actuation_space: ActuationSpace,
    twin_component: ComponentId,
) -> None:
    with pytest.raises(ContractViolationError) as raised:
        ProposedCommand(
            tick=tick,
            proposed_at=now,
            command=ControlCommand(space=actuation_space, values=(0.4, 0.2)),
            origin=CommandOrigin.PROPOSED,
            source=twin_component,
        )

    assert raised.value.layer is LayerId.L5_PINN_TWIN


def test_predicted_command_from_the_l5_twin_is_accepted(
    tick: TickId,
    now: Instant,
    actuation_space: ActuationSpace,
    twin_component: ComponentId,
) -> None:
    prediction = PredictedCommand(
        tick=tick,
        predicted_at=now,
        command=ControlCommand(space=actuation_space, values=(0.4, 0.2)),
        source=twin_component,
    )

    assert prediction.source is twin_component


def test_predicted_command_from_a_non_l5_source_raises_contract_violation(
    tick: TickId,
    now: Instant,
    actuation_space: ActuationSpace,
    proposer_component: ComponentId,
) -> None:
    with pytest.raises(ContractViolationError) as raised:
        PredictedCommand(
            tick=tick,
            predicted_at=now,
            command=ControlCommand(space=actuation_space, values=(0.4, 0.2)),
            source=proposer_component,
        )

    assert raised.value.layer is LayerId.L4_CORE_A_CMDP


# --------------------------------------------------------------------------- #
# IssuedCommand -- SI-7, sole actuation authority
# --------------------------------------------------------------------------- #


def test_issued_command_from_the_l9_arbitrator_is_accepted(
    tick: TickId,
    now: Instant,
    actuation_space: ActuationSpace,
    rcm_component: ComponentId,
) -> None:
    issued = IssuedCommand(
        tick=tick,
        issued_at=now,
        command=ControlCommand(space=actuation_space, values=(0.4, 0.2)),
        origin=CommandOrigin.PROPOSED,
        issuer=rcm_component,
    )

    assert issued.issuer.layer is LayerId.L9_RCM


def test_issued_command_from_a_non_l9_component_violates_si7(
    tick: TickId,
    now: Instant,
    actuation_space: ActuationSpace,
    proposer_component: ComponentId,
) -> None:
    with pytest.raises(InvariantViolationError) as raised:
        IssuedCommand(
            tick=tick,
            issued_at=now,
            command=ControlCommand(space=actuation_space, values=(0.4, 0.2)),
            origin=CommandOrigin.PROPOSED,
            issuer=proposer_component,
        )

    assert "SI-7" in raised.value.message
    assert raised.value.context["issuer"] == "L4_CORE_A_CMDP/primary"


def test_issued_command_from_a_core_b_gate_component_violates_si7(
    tick: TickId,
    now: Instant,
    actuation_space: ActuationSpace,
) -> None:
    shield = ComponentId(LayerId.L7_HARD_SAFETY_SHIELD)

    with pytest.raises(InvariantViolationError):
        IssuedCommand(
            tick=tick,
            issued_at=now,
            command=ControlCommand(space=actuation_space, values=(0.4, 0.2)),
            origin=CommandOrigin.FALLBACK_PID,
            issuer=shield,
        )


def test_issued_command_accepts_a_shadow_instance_of_the_l9_arbitrator(
    tick: TickId,
    now: Instant,
    actuation_space: ActuationSpace,
) -> None:
    shadow = ComponentId(LayerId.L9_RCM, instance="shadow")

    issued = IssuedCommand(
        tick=tick,
        issued_at=now,
        command=ControlCommand(space=actuation_space, values=(0.4, 0.2)),
        origin=CommandOrigin.EXPLORATION_BOUNDED,
        issuer=shadow,
    )

    assert str(issued.issuer) == "L9_RCM/shadow"


def test_issued_command_with_an_out_of_bounds_command_raises_contract_violation(
    tick: TickId,
    now: Instant,
    actuation_space: ActuationSpace,
    rcm_component: ComponentId,
) -> None:
    with pytest.raises(ContractViolationError) as raised:
        IssuedCommand(
            tick=tick,
            issued_at=now,
            command=ControlCommand(space=actuation_space, values=(1.5, 0.0)),
            origin=CommandOrigin.PROPOSED,
            issuer=rcm_component,
        )

    assert raised.value.context["values"] == [1.5, 0.0]


def test_issued_command_rejects_a_bad_issuer_before_it_inspects_the_command(
    tick: TickId,
    now: Instant,
    actuation_space: ActuationSpace,
    proposer_component: ComponentId,
) -> None:
    with pytest.raises(InvariantViolationError):
        IssuedCommand(
            tick=tick,
            issued_at=now,
            command=ControlCommand(space=actuation_space, values=(1.5, 0.0)),
            origin=CommandOrigin.PROPOSED,
            issuer=proposer_component,
        )


def test_clamping_an_inadmissible_command_makes_it_issuable(
    tick: TickId,
    now: Instant,
    actuation_space: ActuationSpace,
    rcm_component: ComponentId,
) -> None:
    proposed = ControlCommand(space=actuation_space, values=(1.5, -3.0))

    issued = IssuedCommand(
        tick=tick,
        issued_at=now,
        command=proposed.clamped(),
        origin=CommandOrigin.SPEED_CAPPED,
        issuer=rcm_component,
    )

    assert issued.command.values == (1.0, -0.5)
