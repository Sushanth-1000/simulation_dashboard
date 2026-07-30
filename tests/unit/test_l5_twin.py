"""Unit tests for the L5 physics-informed digital twin."""

from __future__ import annotations

import math

import pytest
import torch

from astra.config.schema import TwinSettings
from astra.contracts.actuation import ActuationSpace, ControlCommand
from astra.contracts.estimation import FastStateEstimate
from astra.kernel.enums import LayerId
from astra.kernel.errors import ConfigurationError, SafetyPathError
from astra.kernel.identifiers import ComponentId, TickId
from astra.kernel.matrix import SymmetricMatrix
from astra.kernel.time import Instant, ManualClock, Timeline
from astra.kernel.units import Seconds
from astra.layers.l5_twin.network import (
    FEATURE_DIMENSION,
    TwinNetwork,
    physics_residual,
    state_features,
)
from astra.layers.l5_twin.twin import PhysicsInformedTwin
from astra.ports.pipeline import DynamicsPredictor

# A nominal fast state: [px, py, v, psi, a_lat].
NOMINAL: tuple[float, ...] = (10.0, 20.0, 15.0, 0.3, 1.2)


def _settings(**overrides: object) -> TwinSettings:
    base: dict[str, object] = {
        "physics_weight": 1.0,
        "ewc_lambda": 10.0,
        # Two entries, to match the two-channel `actuation_space` fixture.
        "control_effectiveness": [0.0, 120.0],
        "hidden_width": 8,
        "adaptation_buffer": 4,
        "adaptation_steps": 10,
        "fisher_sample_count": 6,
        "seed": 7,
    }
    base.update(overrides)
    return TwinSettings(**base)  # type: ignore[arg-type]


def _state(mean: tuple[float, ...], tick_value: int = 42) -> FastStateEstimate:
    return FastStateEstimate(
        tick=TickId(tick_value),
        valid_at=Instant(1_000, Timeline.MANUAL),
        mean=mean,
        covariance=SymmetricMatrix.from_diagonal([1.0, 1.0, 0.25, 0.1, 0.5]),
    )


def _twin(
    space: ActuationSpace, component: ComponentId, **overrides: object
) -> PhysicsInformedTwin:
    return PhysicsInformedTwin(
        settings=_settings(**overrides),
        space=space,
        component=component,
        clock=ManualClock(Instant(0, Timeline.MANUAL)),
    )


# --------------------------------------------------------------------------- #
# Construction
# --------------------------------------------------------------------------- #


def test_the_twin_satisfies_the_dynamics_predictor_port(
    actuation_space: ActuationSpace, twin_component: ComponentId
) -> None:
    assert isinstance(_twin(actuation_space, twin_component), DynamicsPredictor)


def test_twin_rejects_a_component_that_is_not_l5(
    actuation_space: ActuationSpace, proposer_component: ComponentId
) -> None:
    with pytest.raises(ConfigurationError, match="L5"):
        _twin(actuation_space, proposer_component)


def test_twin_rejects_effectiveness_row_of_the_wrong_length(
    actuation_space: ActuationSpace, twin_component: ComponentId
) -> None:
    # The space has two channels; three entries describe a different platform.
    with pytest.raises(ConfigurationError, match="control_effectiveness"):
        _twin(actuation_space, twin_component, control_effectiveness=[0.0, 0.0, 120.0])


def test_effectiveness_row_may_not_be_empty() -> None:
    with pytest.raises(ValueError, match="at least one channel"):
        _settings(control_effectiveness=[])


def test_effectiveness_row_may_not_contain_a_non_finite_entry() -> None:
    with pytest.raises(ValueError, match="finite"):
        _settings(control_effectiveness=[0.0, math.nan])


# --------------------------------------------------------------------------- #
# Prediction
# --------------------------------------------------------------------------- #


def test_predict_returns_a_command_in_the_configured_space(
    actuation_space: ActuationSpace, twin_component: ComponentId
) -> None:
    twin = _twin(actuation_space, twin_component)

    prediction = twin.predict(tick=TickId(42), state=_state(NOMINAL))

    assert prediction.tick == TickId(42)
    assert prediction.source.layer is LayerId.L5_PINN_TWIN
    assert prediction.command.space is actuation_space
    assert len(prediction.command.values) == actuation_space.dimension
    assert all(math.isfinite(value) for value in prediction.command.values)


def test_prediction_is_pure_so_replay_reproduces_it(
    actuation_space: ActuationSpace, twin_component: ComponentId
) -> None:
    # Two calls with the same state must agree: the twin holds no per-tick
    # counter that could make the second call differ from the first.
    twin = _twin(actuation_space, twin_component)

    first = twin.predict(tick=TickId(1), state=_state(NOMINAL))
    second = twin.predict(tick=TickId(1), state=_state(NOMINAL))

    assert first.command.values == second.command.values


def test_same_seed_gives_two_twins_the_same_prediction(
    actuation_space: ActuationSpace, twin_component: ComponentId
) -> None:
    # A-5: replay compares byte-for-byte, so weight initialisation is seeded.
    left = _twin(actuation_space, twin_component, seed=99)
    right = _twin(actuation_space, twin_component, seed=99)

    assert left.predict(tick=TickId(3), state=_state(NOMINAL)).command.values == pytest.approx(
        right.predict(tick=TickId(3), state=_state(NOMINAL)).command.values
    )


def test_different_seeds_give_different_twins(
    actuation_space: ActuationSpace, twin_component: ComponentId
) -> None:
    left = _twin(actuation_space, twin_component, seed=1)
    right = _twin(actuation_space, twin_component, seed=2)

    assert left.predict(tick=TickId(3), state=_state(NOMINAL)).command.values != pytest.approx(
        right.predict(tick=TickId(3), state=_state(NOMINAL)).command.values
    )


def test_prediction_timestamp_comes_from_the_injected_clock(
    actuation_space: ActuationSpace, twin_component: ComponentId
) -> None:
    clock = ManualClock(Instant(0, Timeline.MANUAL))
    twin = PhysicsInformedTwin(
        settings=_settings(), space=actuation_space, component=twin_component, clock=clock
    )
    clock.advance(Seconds(0.05))

    prediction = twin.predict(tick=TickId(1), state=_state(NOMINAL))

    assert prediction.predicted_at == Instant(50_000_000, Timeline.MANUAL)


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_a_non_finite_state_fails_closed_rather_than_predicting(
    actuation_space: ActuationSpace, twin_component: ComponentId, bad: float
) -> None:
    # NaN would make the ICP comparison against the quantile false, which the
    # gate reads as PASS. This must raise, not return.
    twin = _twin(actuation_space, twin_component)
    corrupt = (10.0, 20.0, bad, 0.3, 1.2)

    with pytest.raises(SafetyPathError) as raised:
        twin.predict(tick=TickId(42), state=_state(corrupt))

    assert raised.value.context["source"] == "state"
    assert raised.value.context["indices"] == [2]


def test_a_non_finite_network_output_fails_closed(
    actuation_space: ActuationSpace, twin_component: ComponentId
) -> None:
    twin = _twin(actuation_space, twin_component)
    with torch.no_grad():
        twin._network.output.bias.fill_(math.nan)

    with pytest.raises(SafetyPathError) as raised:
        twin.predict(tick=TickId(42), state=_state(NOMINAL))

    assert raised.value.context["source"] == "prediction"


# --------------------------------------------------------------------------- #
# Adaptation -- feedback loop FB2
# --------------------------------------------------------------------------- #


def test_adapt_does_not_update_before_the_buffer_fills(
    actuation_space: ActuationSpace, twin_component: ComponentId
) -> None:
    twin = _twin(actuation_space, twin_component, adaptation_buffer=4)
    before = twin.predict(tick=TickId(1), state=_state(NOMINAL)).command.values
    command = ControlCommand(space=actuation_space, values=(0.4, 0.1))

    for _ in range(3):
        twin.adapt(applied=command, measured=_state(NOMINAL))

    after = twin.predict(tick=TickId(2), state=_state(NOMINAL)).command.values
    assert after == before


def test_adapt_updates_once_the_buffer_fills(
    actuation_space: ActuationSpace, twin_component: ComponentId
) -> None:
    twin = _twin(actuation_space, twin_component, adaptation_buffer=4, ewc_lambda=0.0)
    before = twin.predict(tick=TickId(1), state=_state(NOMINAL)).command.values
    command = ControlCommand(space=actuation_space, values=(0.9, -0.4))

    for _ in range(4):
        twin.adapt(applied=command, measured=_state(NOMINAL))

    after = twin.predict(tick=TickId(2), state=_state(NOMINAL)).command.values
    assert after != pytest.approx(before)


def test_adaptation_leaves_the_hidden_layer_untouched(
    actuation_space: ActuationSpace, twin_component: ComponentId
) -> None:
    # Only the output layer may move. The hidden layer carries the physics
    # representation and is what EWC exists to protect.
    twin = _twin(actuation_space, twin_component, adaptation_buffer=2, ewc_lambda=0.0)
    hidden_before = twin._network.hidden.weight.detach().clone()
    command = ControlCommand(space=actuation_space, values=(0.9, -0.4))

    for _ in range(2):
        twin.adapt(applied=command, measured=_state(NOMINAL))

    assert torch.equal(twin._network.hidden.weight, hidden_before)


def test_hidden_layer_is_trainable_again_after_adaptation(
    actuation_space: ActuationSpace, twin_component: ComponentId
) -> None:
    twin = _twin(actuation_space, twin_component, adaptation_buffer=2, ewc_lambda=0.0)
    command = ControlCommand(space=actuation_space, values=(0.9, -0.4))

    for _ in range(2):
        twin.adapt(applied=command, measured=_state(NOMINAL))

    assert all(p.requires_grad for p in twin._network.hidden.parameters())


def test_a_non_finite_sample_is_discarded_rather_than_raising(
    actuation_space: ActuationSpace, twin_component: ComponentId
) -> None:
    # The cold path must not take down a tick that has already been decided.
    twin = _twin(actuation_space, twin_component, adaptation_buffer=2)
    command = ControlCommand(space=actuation_space, values=(0.4, 0.1))

    twin.adapt(applied=command, measured=_state((10.0, 20.0, math.nan, 0.3, 1.2)))

    assert twin._buffer == []


def test_a_non_finite_command_is_also_discarded(
    actuation_space: ActuationSpace, twin_component: ComponentId
) -> None:
    twin = _twin(actuation_space, twin_component, adaptation_buffer=2)
    # ControlCommand rejects non-finite values, so the guard is exercised
    # through a command whose channel value is finite but whose state is not.
    twin.adapt(
        applied=ControlCommand(space=actuation_space, values=(0.4, 0.1)),
        measured=_state((10.0, 20.0, 15.0, math.inf, 1.2)),
    )

    assert twin._buffer == []


def test_history_is_bounded_by_the_fisher_sample_count(
    actuation_space: ActuationSpace, twin_component: ComponentId
) -> None:
    twin = _twin(actuation_space, twin_component, adaptation_buffer=100, fisher_sample_count=3)
    command = ControlCommand(space=actuation_space, values=(0.4, 0.1))

    for _ in range(10):
        twin.adapt(applied=command, measured=_state(NOMINAL))

    assert len(twin._history) == 3


def test_the_first_consolidation_has_no_anchor_to_hold_it(
    actuation_space: ActuationSpace, twin_component: ComponentId
) -> None:
    # Nothing has been learned yet, so there is nothing to forget: the penalty
    # must be inert on the first update regardless of how large lambda is.
    twin = _twin(actuation_space, twin_component, adaptation_buffer=4, ewc_lambda=1e9)
    command = ControlCommand(space=actuation_space, values=(0.9, -0.4))

    assert twin._anchor == {}
    for _ in range(4):
        twin.adapt(applied=command, measured=_state(NOMINAL))

    assert twin._anchor != {}


def test_the_elastic_penalty_can_resist_movement_once_an_anchor_exists(
    actuation_space: ActuationSpace, twin_component: ComponentId
) -> None:
    # This checks the *mechanism*, not the operating point. Twelve samples at a
    # buffer of four gives three consolidations; the anchor is established by
    # the first, so the second and third are the ones the penalty constrains.
    #
    # A very large lambda is needed to see the effect, and that is itself worth
    # recording: gradients are norm-clipped, and immediately after re-anchoring
    # `(theta - theta_anchor)` is near zero, so the penalty's contribution is
    # small next to the data and physics terms until it has something to pull
    # against. Whether the *configured* lambda prevents forgetting on real
    # dynamics is RK-5, and only the catastrophic-forgetting test in Phase 7
    # can answer it.
    command = ControlCommand(space=actuation_space, values=(0.9, -0.4))

    def parameter_movement(ewc_lambda: float) -> float:
        twin = _twin(actuation_space, twin_component, adaptation_buffer=4, ewc_lambda=ewc_lambda)
        start = torch.cat([p.detach().flatten().clone() for p in twin._network.output.parameters()])
        for _ in range(12):
            twin.adapt(applied=command, measured=_state(NOMINAL))
        end = torch.cat([p.detach().flatten() for p in twin._network.output.parameters()])
        return float(torch.linalg.vector_norm(end - start))

    assert parameter_movement(1e12) < parameter_movement(0.0)


def test_a_divergent_update_is_rolled_back_rather_than_kept(
    actuation_space: ActuationSpace, twin_component: ComponentId
) -> None:
    # An absurd lambda drives the output layer to infinity within a few steps.
    # A twin holding NaN weights does not fail loudly, it predicts NaN -- which
    # the statistical gate compares against its quantile and reads as a PASS.
    # Adaptation is the cold path, so the update is abandoned instead.
    twin = _twin(actuation_space, twin_component, adaptation_buffer=4, ewc_lambda=1e30)
    command = ControlCommand(space=actuation_space, values=(0.9, -0.4))

    for _ in range(12):
        twin.adapt(applied=command, measured=_state(NOMINAL))

    prediction = twin.predict(tick=TickId(9), state=_state(NOMINAL))
    assert all(math.isfinite(value) for value in prediction.command.values)


# --------------------------------------------------------------------------- #
# The network and its physics residual
# --------------------------------------------------------------------------- #


def test_state_features_drop_position_and_split_heading() -> None:
    features = state_features(
        (11.0, 22.0, 15.0, 0.0, 1.2), speed_index=2, heading_index=3, lateral_index=4
    )

    assert len(features) == FEATURE_DIMENSION
    assert features == pytest.approx((15.0, 0.0, 1.0, 1.2))


def test_heading_features_are_continuous_across_the_pi_boundary() -> None:
    # psi = +pi and psi = -pi are the same heading. Feeding psi raw would put a
    # 2*pi discontinuity in the middle of the input space.
    just_below = state_features(
        (0.0, 0.0, 10.0, math.pi - 1e-9, 0.0), speed_index=2, heading_index=3, lateral_index=4
    )
    just_above = state_features(
        (0.0, 0.0, 10.0, -math.pi + 1e-9, 0.0), speed_index=2, heading_index=3, lateral_index=4
    )

    assert just_below == pytest.approx(just_above, abs=1e-6)


def test_physics_residual_is_zero_when_the_command_explains_the_acceleration() -> None:
    commands = torch.tensor([[0.0, 0.5]])
    effectiveness = torch.tensor([0.0, 120.0])
    lateral = torch.tensor([60.0])  # 0.5 * 120

    assert float(physics_residual(commands, lateral, effectiveness)) == pytest.approx(0.0)


def test_physics_residual_grows_with_the_inconsistency() -> None:
    commands = torch.tensor([[0.0, 0.5]])
    effectiveness = torch.tensor([0.0, 120.0])

    near = float(physics_residual(commands, torch.tensor([59.0]), effectiveness))
    far = float(physics_residual(commands, torch.tensor([10.0]), effectiveness))

    assert far > near > 0.0


def test_physics_residual_is_differentiable() -> None:
    # The PINN loss needs a gradient through this term; a residual that detached
    # would silently train an ordinary regressor.
    commands = torch.tensor([[0.0, 0.5]], requires_grad=True)
    residual = physics_residual(commands, torch.tensor([10.0]), torch.tensor([0.0, 120.0]))
    residual.backward()  # type: ignore[no-untyped-call]

    assert commands.grad is not None
    assert float(commands.grad.abs().sum()) > 0.0


def test_network_maps_feature_rows_to_command_rows() -> None:
    torch.manual_seed(0)
    network = TwinNetwork(hidden_width=8, command_dimension=3)

    output = network(torch.zeros((5, FEATURE_DIMENSION)))

    assert output.shape == (5, 3)
