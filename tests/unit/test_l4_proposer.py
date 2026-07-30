"""Unit tests for L4, the Core-A constrained-MDP proposer."""

from __future__ import annotations

import math
from dataclasses import fields
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from astra.layers.l4_proposer import signal as signal_module

if TYPE_CHECKING:
    from collections.abc import Sequence

from astra.contracts.actuation import ActuationSpace, CommandOrigin
from astra.contracts.assurance import TrustAssessment
from astra.contracts.estimation import FastStateEstimate
from astra.kernel.enums import ContextClass, LayerId
from astra.kernel.errors import ConfigurationError, InvariantViolationError, SafetyPathError
from astra.kernel.identifiers import ComponentId, TickId
from astra.kernel.matrix import SymmetricMatrix
from astra.kernel.time import Instant, ManualClock, Timeline
from astra.kernel.units import Probability
from astra.layers.l4_proposer.constraints import (
    COLLISION_BUDGET,
    ConstraintBudget,
    LagrangianDual,
    constraint_costs,
)
from astra.layers.l4_proposer.proposer import CmdpProposer, Policy
from astra.layers.l4_proposer.signal import (
    PERMITTED_FIELDS,
    TrainingSignal,
    assert_signal_excludes_core_b,
)
from astra.ports.pipeline import CommandProposer

AT = Instant(1_000, Timeline.MANUAL)


class _StubPolicy:
    """A deterministic policy, so every path is exercised without a trained model."""

    def __init__(self, values: tuple[float, ...]) -> None:
        self.values = values
        self.seen: list[tuple[float, ...]] = []

    def act(self, observation: Sequence[float]) -> Sequence[float]:
        self.seen.append(tuple(observation))
        return self.values


def _state(mean: tuple[float, ...] = (0.0, 0.0, 15.0, 0.1, 0.5)) -> FastStateEstimate:
    return FastStateEstimate(
        tick=TickId(1),
        valid_at=AT,
        mean=mean,
        covariance=SymmetricMatrix.from_diagonal([1.0, 1.0, 0.25, 0.1, 0.5]),
    )


def _trust(index: float = 0.9) -> TrustAssessment:
    return TrustAssessment(
        tick=TickId(1),
        trust_index=Probability(index),
        context_class=ContextClass.HIGHWAY_CLEAR,
        class_conditional_quantile=0.5,
        coverage_target=Probability(0.95),
        calibration_sample_count=500,
    )


def _proposer(space: ActuationSpace, values: tuple[float, ...]) -> CmdpProposer:
    return CmdpProposer(
        policy=_StubPolicy(values),
        space=space,
        component=ComponentId(LayerId.L4_CORE_A_CMDP),
        clock=ManualClock(Instant(0, Timeline.MANUAL)),
    )


# --------------------------------------------------------------------------- #
# SI-6 -- the invariant this layer makes mechanical
# --------------------------------------------------------------------------- #


def test_the_training_signal_declares_only_permitted_fields() -> None:
    # SI-6's enforcement was REVIEW until this test existed. Rewarding a low
    # veto rate trains the proposer to avoid detection rather than to be safe,
    # and the optimiser cannot tell those apart.
    declared = {field.name for field in fields(TrainingSignal)}

    assert declared == PERMITTED_FIELDS


def test_the_training_signal_names_no_core_b_artefact() -> None:
    assert_signal_excludes_core_b()


def test_the_permitted_set_contains_nothing_describing_a_gate() -> None:
    forbidden = ("veto", "verdict", "gate", "shield", "failsafe", "trust", "conformal")

    for name in PERMITTED_FIELDS:
        assert not any(fragment in name.lower() for fragment in forbidden)


def test_the_guard_rejects_a_widened_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    # Simulates the plausible mistake: somebody adds `recent_veto_rate` to the
    # reward because it made training converge faster.
    monkeypatch.setattr(
        signal_module, "fields", lambda _: [SimpleNamespace(name="recent_veto_rate")]
    )

    with pytest.raises(InvariantViolationError, match="SI-6"):
        signal_module.assert_signal_excludes_core_b()


def test_the_guard_still_fires_if_the_permitted_set_was_widened_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Defence in depth: somebody who edits both the record *and* the permitted
    # set still trips the substring check, which exists precisely because the
    # first line of defence is one edit away from being switched off.
    monkeypatch.setattr(signal_module, "PERMITTED_FIELDS", frozenset({"recent_veto_rate"}))
    monkeypatch.setattr(
        signal_module, "fields", lambda _: [SimpleNamespace(name="recent_veto_rate")]
    )

    with pytest.raises(InvariantViolationError, match="Core-B artefact"):
        signal_module.assert_signal_excludes_core_b()


def test_the_training_signal_is_frozen_and_slotted() -> None:
    # A mutable signal could be decorated with a Core-B observable between
    # construction and use, which is the path this type exists to close.
    signal = TrainingSignal(
        lane_deviation_m=0.1,
        longitudinal_acceleration_mps2=1.0,
        speed_mps=15.0,
        collided=False,
        progress_m=0.75,
    )

    # Rebinding a declared field raises FrozenInstanceError; attaching an
    # undeclared one raises TypeError rather than AttributeError, because
    # `slots=True` recreates the class and leaves the generated `__setattr__`'s
    # `super()` call referring to the original. The exception type is a CPython
    # detail; what matters is that neither assignment can succeed.
    with pytest.raises((AttributeError, TypeError)):
        signal.lane_deviation_m = 0.2  # type: ignore[misc]
    with pytest.raises((AttributeError, TypeError)):
        signal.recent_veto_rate = 0.3  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- #
# Constraint costs
# --------------------------------------------------------------------------- #


def _signal(**overrides: float | bool) -> TrainingSignal:
    base: dict[str, float | bool] = {
        "lane_deviation_m": 0.0,
        "longitudinal_acceleration_mps2": 0.0,
        "speed_mps": 15.0,
        "collided": False,
        "progress_m": 0.75,
    }
    base.update(overrides)
    return TrainingSignal(**base)  # type: ignore[arg-type]


BUDGET = ConstraintBudget(lane_deviation_limit_m=0.5, longitudinal_acceleration_limit_mps2=3.0)


def test_a_step_inside_every_limit_costs_nothing() -> None:
    assert constraint_costs(_signal(lane_deviation_m=0.4), BUDGET) == (0.0, 0.0, 0.0)


def test_lane_deviation_cost_is_the_excess_over_the_limit() -> None:
    c1, _, _ = constraint_costs(_signal(lane_deviation_m=1.2), BUDGET)

    assert c1 == pytest.approx(0.7)


def test_lane_deviation_cost_is_on_the_absolute_value() -> None:
    left, _, _ = constraint_costs(_signal(lane_deviation_m=-1.2), BUDGET)
    right, _, _ = constraint_costs(_signal(lane_deviation_m=1.2), BUDGET)

    assert left == pytest.approx(right)


def test_harsh_braking_is_constrained_exactly_as_harsh_acceleration() -> None:
    _, braking, _ = constraint_costs(_signal(longitudinal_acceleration_mps2=-5.0), BUDGET)
    _, accelerating, _ = constraint_costs(_signal(longitudinal_acceleration_mps2=5.0), BUDGET)

    assert braking == pytest.approx(accelerating) == pytest.approx(2.0)


def test_a_collision_costs_one_and_the_budget_is_zero() -> None:
    _, _, c3 = constraint_costs(_signal(collided=True), BUDGET)

    assert c3 == 1.0
    assert COLLISION_BUDGET == 0.0


@pytest.mark.parametrize("limit", [0.0, -1.0, math.nan, math.inf])
def test_an_unsatisfiable_constraint_budget_is_refused(limit: float) -> None:
    with pytest.raises(ConfigurationError):
        ConstraintBudget(lane_deviation_limit_m=limit, longitudinal_acceleration_limit_mps2=3.0)


# --------------------------------------------------------------------------- #
# The PID dual variable
# --------------------------------------------------------------------------- #


def test_the_multiplier_starts_at_zero_so_an_unviolated_constraint_costs_nothing() -> None:
    assert LagrangianDual(learning_rate=0.1).value == 0.0


def test_violating_the_constraint_raises_the_multiplier() -> None:
    dual = LagrangianDual(learning_rate=0.1)

    dual.update(realised_cost=2.0, budget=0.0)

    assert dual.value == pytest.approx(0.2)


def test_the_multiplier_is_projected_onto_the_non_negative_reals() -> None:
    # A negative multiplier would turn the constraint into a bonus.
    dual = LagrangianDual(learning_rate=1.0)

    dual.update(realised_cost=0.0, budget=10.0)

    assert dual.value == 0.0


def test_satisfying_the_constraint_relaxes_a_raised_multiplier() -> None:
    dual = LagrangianDual(learning_rate=0.1)
    dual.update(realised_cost=10.0, budget=0.0)
    raised = dual.value

    dual.update(realised_cost=0.0, budget=1.0)

    assert dual.value < raised


def test_the_integral_term_punishes_a_small_persistent_violation() -> None:
    # Proportional-only would leave a steady-state offset: a violation small
    # enough to sit forever without the multiplier catching up.
    proportional = LagrangianDual(learning_rate=0.1)
    with_integral = LagrangianDual(learning_rate=0.1, integral_gain=0.05)

    for _ in range(10):
        proportional.update(realised_cost=0.1, budget=0.0)
        with_integral.update(realised_cost=0.1, budget=0.0)

    assert with_integral.value > proportional.value


def test_the_derivative_term_responds_to_a_worsening_trend() -> None:
    plain = LagrangianDual(learning_rate=0.1)
    damped = LagrangianDual(learning_rate=0.1, derivative_gain=0.5)

    for cost in (0.1, 0.5, 1.5):
        plain.update(realised_cost=cost, budget=0.0)
        damped.update(realised_cost=cost, budget=0.0)

    assert damped.value > plain.value


def test_the_first_update_has_no_derivative_history_to_use() -> None:
    plain = LagrangianDual(learning_rate=0.1)
    damped = LagrangianDual(learning_rate=0.1, derivative_gain=10.0)

    plain.update(realised_cost=1.0, budget=0.0)
    damped.update(realised_cost=1.0, budget=0.0)

    assert plain.value == pytest.approx(damped.value)


@pytest.mark.parametrize("gain", [-0.1, math.nan, math.inf])
def test_a_negative_or_non_finite_gain_is_refused(gain: float) -> None:
    with pytest.raises(ConfigurationError):
        LagrangianDual(learning_rate=gain)


@pytest.mark.parametrize("bad", [math.nan, math.inf])
def test_a_non_finite_dual_update_is_refused(bad: float) -> None:
    # A NaN multiplier propagates into every subsequent reward and disables the
    # constraint without raising anything.
    dual = LagrangianDual(learning_rate=0.1)

    with pytest.raises(ConfigurationError):
        dual.update(realised_cost=bad, budget=0.0)


def test_the_penalty_is_the_multiplier_times_the_total_cost() -> None:
    dual = LagrangianDual(learning_rate=1.0)
    dual.update(realised_cost=2.0, budget=0.0)

    assert dual.penalty((0.5, 0.25, 0.0)) == pytest.approx(1.5)


# --------------------------------------------------------------------------- #
# The proposer
# --------------------------------------------------------------------------- #


def test_the_proposer_satisfies_the_command_proposer_port(
    actuation_space: ActuationSpace,
) -> None:
    assert isinstance(_proposer(actuation_space, (0.4, 0.1)), CommandProposer)


def test_a_proposal_carries_the_l4_source_and_the_learned_origin(
    actuation_space: ActuationSpace,
) -> None:
    proposal = _proposer(actuation_space, (0.4, 0.1)).propose(
        tick=TickId(7), state=_state(), trust=_trust()
    )

    assert proposal.tick == TickId(7)
    assert proposal.source.layer is LayerId.L4_CORE_A_CMDP
    assert proposal.origin is CommandOrigin.PROPOSED
    assert proposal.command.values == (0.4, 0.1)


def test_the_trust_index_reaches_the_policy_as_a_monitoring_input(
    actuation_space: ActuationSpace,
) -> None:
    # Permitted: SI-4 keeps the Trust Index out of Core-B's verdict, not out of
    # Core-A's observation. It is excluded from the *training signal*, not here.
    policy = _StubPolicy((0.4, 0.1))
    proposer = CmdpProposer(
        policy=policy,
        space=actuation_space,
        component=ComponentId(LayerId.L4_CORE_A_CMDP),
        clock=ManualClock(Instant(0, Timeline.MANUAL)),
    )

    proposer.propose(tick=TickId(1), state=_state(), trust=_trust(0.42))

    assert policy.seen[0][-1] == pytest.approx(0.42)


def test_an_inadmissible_proposal_is_passed_through_rather_than_clamped(
    actuation_space: ActuationSpace,
) -> None:
    # Silently clamping would hide a misbehaving policy behind a correct-looking
    # command. Catching it is what the gates are for.
    proposal = _proposer(actuation_space, (5.0, -9.0)).propose(
        tick=TickId(1), state=_state(), trust=_trust()
    )

    assert proposal.command.values == (5.0, -9.0)
    assert not proposal.command.is_admissible()


def test_the_proposer_rejects_a_component_that_is_not_l4(
    actuation_space: ActuationSpace, twin_component: ComponentId
) -> None:
    with pytest.raises(ConfigurationError, match="L4"):
        CmdpProposer(
            policy=_StubPolicy((0.4, 0.1)),
            space=actuation_space,
            component=twin_component,
            clock=ManualClock(Instant(0, Timeline.MANUAL)),
        )


def test_a_policy_returning_the_wrong_width_fails_closed(
    actuation_space: ActuationSpace,
) -> None:
    with pytest.raises(SafetyPathError, match="channels"):
        _proposer(actuation_space, (0.4, 0.1, 0.2)).propose(
            tick=TickId(1), state=_state(), trust=_trust()
        )


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_a_non_finite_proposal_fails_closed(actuation_space: ActuationSpace, bad: float) -> None:
    # A NaN command defeats every bound comparison in Core-B rather than
    # failing it, so it must not leave Core-A.
    with pytest.raises(SafetyPathError) as raised:
        _proposer(actuation_space, (0.4, bad)).propose(
            tick=TickId(1), state=_state(), trust=_trust()
        )

    assert raised.value.context["source"] == "proposal"


def test_a_non_finite_state_fails_closed_before_the_policy_runs(
    actuation_space: ActuationSpace,
) -> None:
    policy = _StubPolicy((0.4, 0.1))
    proposer = CmdpProposer(
        policy=policy,
        space=actuation_space,
        component=ComponentId(LayerId.L4_CORE_A_CMDP),
        clock=ManualClock(Instant(0, Timeline.MANUAL)),
    )

    with pytest.raises(SafetyPathError):
        proposer.propose(
            tick=TickId(1), state=_state((0.0, 0.0, math.nan, 0.1, 0.5)), trust=_trust()
        )

    assert policy.seen == []


def test_the_stub_policy_satisfies_the_policy_protocol() -> None:
    assert isinstance(_StubPolicy((0.1,)), Policy)
