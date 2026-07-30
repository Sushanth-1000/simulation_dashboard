"""Unit tests for the one-way Core-A to Core-B channel."""

from __future__ import annotations

import queue

import pytest

from astra.contracts.actuation import (
    ActuationChannel,
    ActuationSpace,
    CommandOrigin,
    ControlCommand,
    ProposedCommand,
)
from astra.kernel.enums import ExecutionDomain, LayerId
from astra.kernel.errors import InvariantViolationError
from astra.kernel.identifiers import ComponentId, TickId
from astra.kernel.time import Instant, Timeline
from astra.runtime.channels import (
    DEFAULT_CAPACITY,
    ProposalReader,
    ProposalWriter,
    guard_core_a_isolation,
    guard_proposal_origin,
    open_proposal_channel,
)

SPACE = ActuationSpace((ActuationChannel("throttle", 0.0, 1.0, "1"),))
CORE_A_LAYERS = tuple(
    layer for layer in LayerId if layer.execution_domain is ExecutionDomain.CORE_A
)
NON_CORE_A_LAYERS = tuple(
    layer for layer in LayerId if layer.execution_domain is not ExecutionDomain.CORE_A
)


def _proposal(tick: int) -> ProposedCommand:
    return ProposedCommand(
        tick=TickId(tick),
        proposed_at=Instant(tick, Timeline.MANUAL),
        command=ControlCommand(SPACE, (0.5,)),
        origin=CommandOrigin.PROPOSED,
        source=ComponentId(LayerId.L4_CORE_A_CMDP),
    )


def _public_members(obj: object) -> set[str]:
    return {name for name in dir(obj) if not name.startswith("_")}


# --------------------------------------------------------------------------- #
# SI-5 by construction
# --------------------------------------------------------------------------- #


def test_the_writer_has_no_method_that_could_return_a_core_b_artefact() -> None:
    # This is the enforcement, so it is tested directly. Core-A holds this
    # object; there is no method on it through which a verdict, an FSM state or
    # a calibration table could come back.
    writer, _reader = open_proposal_channel()

    assert _public_members(writer) == {"send", "pending"}


def test_the_reader_has_no_method_that_could_write_back_to_core_a() -> None:
    _writer, reader = open_proposal_channel()

    assert _public_members(reader) == {"receive", "drain"}


def test_neither_endpoint_exposes_the_underlying_queue() -> None:
    # A caller that could obtain the queue could hand the same object to both
    # cores and reintroduce the bidirectional path the pair exists to remove.
    writer, reader = open_proposal_channel()

    for endpoint in (writer, reader):
        for name in _public_members(endpoint):
            assert not isinstance(getattr(endpoint, name), queue.Queue)


def test_the_two_endpoints_are_distinct_types() -> None:
    writer, reader = open_proposal_channel()

    # The two are unrelated classes, not a base and a subclass: mypy rejects
    # `isinstance(writer, ProposalReader)` as statically impossible, which is a
    # stronger guarantee than a runtime check could give.
    assert isinstance(writer, ProposalWriter)
    assert isinstance(reader, ProposalReader)
    assert ProposalWriter not in ProposalReader.__mro__


# --------------------------------------------------------------------------- #
# Delivery
# --------------------------------------------------------------------------- #


def test_a_sent_proposal_arrives_unchanged() -> None:
    writer, reader = open_proposal_channel()
    sent = _proposal(7)

    assert writer.send(sent) is True

    assert reader.receive() == sent


def test_receiving_from_an_empty_channel_returns_none() -> None:
    # A legitimate outcome, not an error: no proposal means nothing to
    # validate, an empty verdict set, and therefore a VETO.
    _writer, reader = open_proposal_channel()

    assert reader.receive() is None


def test_proposals_are_delivered_in_the_order_they_were_sent() -> None:
    writer, reader = open_proposal_channel()
    for tick in range(3):
        writer.send(_proposal(tick))

    delivered = [reader.receive(), reader.receive(), reader.receive()]

    assert [proposal.tick.value for proposal in delivered if proposal is not None] == [0, 1, 2]


def test_pending_reflects_how_many_proposals_are_undelivered() -> None:
    writer, reader = open_proposal_channel()

    assert writer.pending == 0
    writer.send(_proposal(0))
    writer.send(_proposal(1))
    assert writer.pending == 2
    reader.receive()
    assert writer.pending == 1


# --------------------------------------------------------------------------- #
# Bounded, and non-blocking when full
# --------------------------------------------------------------------------- #


def test_sending_into_a_full_channel_returns_false_instead_of_blocking() -> None:
    # This test completing at all is the proof that it does not block. A
    # blocking send would hang here rather than fail, and Core-A's tick would be
    # held hostage by a stalled Core-B.
    writer, _reader = open_proposal_channel(capacity=2)
    assert writer.send(_proposal(0)) is True
    assert writer.send(_proposal(1)) is True

    assert writer.send(_proposal(2)) is False


def test_a_full_channel_recovers_once_core_b_consumes() -> None:
    writer, reader = open_proposal_channel(capacity=1)
    writer.send(_proposal(0))
    assert writer.send(_proposal(1)) is False

    reader.receive()

    assert writer.send(_proposal(1)) is True


def test_the_default_capacity_is_small_so_a_stall_does_not_become_stale_commands() -> None:
    # A deep queue would convert a Core-B stall into a burst of stale commands
    # rather than into the VETOs it should produce. At 20 Hz the fifth queued
    # proposal already describes a world 250 ms old.
    assert DEFAULT_CAPACITY <= 8


@pytest.mark.parametrize("capacity", [0, -1, -100])
def test_a_non_positive_capacity_is_refused(capacity: int) -> None:
    # A zero-capacity channel drops every proposal, so Core-B would validate
    # nothing and every tick would VETO -- a system that looks fail-safe while
    # being entirely non-functional.
    with pytest.raises(InvariantViolationError):
        open_proposal_channel(capacity)


# --------------------------------------------------------------------------- #
# drain: take the newest, discard the stale
# --------------------------------------------------------------------------- #


def test_drain_returns_the_newest_proposal_and_discards_the_rest() -> None:
    writer, reader = open_proposal_channel()
    for tick in (10, 11, 12):
        writer.send(_proposal(tick))

    newest = reader.drain()

    assert newest is not None
    assert newest.tick.value == 12
    assert writer.pending == 0


def test_drain_on_an_empty_channel_returns_none() -> None:
    _writer, reader = open_proposal_channel()

    assert reader.drain() is None


def test_drain_of_a_single_proposal_returns_it() -> None:
    writer, reader = open_proposal_channel()
    writer.send(_proposal(4))

    drained = reader.drain()

    assert drained is not None
    assert drained.tick.value == 4


# --------------------------------------------------------------------------- #
# guard_core_a_isolation
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("layer", CORE_A_LAYERS)
def test_a_core_a_component_may_not_read_a_core_b_artefact(layer: LayerId) -> None:
    with pytest.raises(InvariantViolationError) as raised:
        guard_core_a_isolation(ComponentId(layer), "verdict")

    assert "SI-5" in str(raised.value)
    assert raised.value.context["artefact"] == "verdict"


@pytest.mark.parametrize("layer", NON_CORE_A_LAYERS)
def test_every_component_outside_core_a_may_read_a_verdict(layer: LayerId) -> None:
    guard_core_a_isolation(ComponentId(layer), "verdict")  # must not raise


@pytest.mark.parametrize(
    "artefact", ["verdict", "failsafe_state", "calibration_table", "quantile_table"]
)
def test_the_isolation_guard_names_the_artefact_it_refused(artefact: str) -> None:
    with pytest.raises(InvariantViolationError) as raised:
        guard_core_a_isolation(ComponentId(LayerId.L4_CORE_A_CMDP), artefact)

    assert artefact in str(raised.value)


def test_the_isolation_guard_covers_a_shadow_instance_too() -> None:
    with pytest.raises(InvariantViolationError):
        guard_core_a_isolation(ComponentId(LayerId.L4_CORE_A_CMDP, instance="shadow"), "verdict")


# --------------------------------------------------------------------------- #
# guard_proposal_origin
# --------------------------------------------------------------------------- #


def test_the_core_a_proposer_may_write_a_proposal() -> None:
    guard_proposal_origin(ComponentId(LayerId.L4_CORE_A_CMDP))  # must not raise


@pytest.mark.parametrize(
    "layer", [layer for layer in LayerId if layer is not LayerId.L4_CORE_A_CMDP]
)
def test_no_other_layer_may_write_a_proposal(layer: LayerId) -> None:
    # A proposal from inside Core-B would make the safety verdict a
    # self-assessment.
    with pytest.raises(InvariantViolationError) as raised:
        guard_proposal_origin(ComponentId(layer))

    assert "SI-5" in str(raised.value)
    assert raised.value.layer is layer


def test_the_origin_guard_records_the_offending_component() -> None:
    with pytest.raises(InvariantViolationError) as raised:
        guard_proposal_origin(ComponentId(LayerId.L7_HARD_SAFETY_SHIELD))

    assert raised.value.context["source"] == "L7_HARD_SAFETY_SHIELD/primary"


# --------------------------------------------------------------------------- #
# The guards agree with the domain map
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("layer", list(LayerId))
def test_the_isolation_guard_agrees_with_the_declared_execution_domain(layer: LayerId) -> None:
    # The expectation is derived from the domain map rather than hardcoded, so
    # moving a layer between domains updates this test automatically instead of
    # leaving it asserting a stale answer.
    is_core_a = layer.execution_domain is ExecutionDomain.CORE_A

    if is_core_a:
        with pytest.raises(InvariantViolationError):
            guard_core_a_isolation(ComponentId(layer), "verdict")
    else:
        guard_core_a_isolation(ComponentId(layer), "verdict")
