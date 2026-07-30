"""Tests for the twin's checkpoint round-trip and weights digest."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pytest
import torch

from astra.config.schema import TwinSettings
from astra.kernel.errors import ConfigurationError
from astra.kernel.identifiers import TickId
from astra.kernel.matrix import SymmetricMatrix
from astra.kernel.time import Instant, ManualClock, Timeline
from astra.layers.l5_twin.twin import PhysicsInformedTwin

if TYPE_CHECKING:
    from pathlib import Path

    from astra.contracts.actuation import ActuationSpace
    from astra.kernel.identifiers import ComponentId

from astra.contracts.actuation import ControlCommand
from astra.contracts.estimation import FastStateEstimate

NOMINAL: tuple[float, ...] = (10.0, 20.0, 15.0, 0.3, 1.2)


def _settings(**overrides: object) -> TwinSettings:
    base: dict[str, object] = {
        "physics_weight": 1.0,
        "ewc_lambda": 10.0,
        "control_effectiveness": [0.0, 120.0],
        "hidden_width": 8,
        "adaptation_buffer": 4,
        "adaptation_steps": 10,
        "fisher_sample_count": 6,
        "seed": 7,
    }
    base.update(overrides)
    return TwinSettings(**base)  # type: ignore[arg-type]


def _state() -> FastStateEstimate:
    return FastStateEstimate(
        tick=TickId(42),
        valid_at=Instant(1_000, Timeline.MANUAL),
        mean=NOMINAL,
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


def test_the_digest_is_stable_for_unchanged_weights(
    actuation_space: ActuationSpace, twin_component: ComponentId
) -> None:
    twin = _twin(actuation_space, twin_component)

    assert twin.weights_digest == twin.weights_digest


def test_two_twins_with_the_same_seed_share_a_digest(
    actuation_space: ActuationSpace, twin_component: ComponentId
) -> None:
    left = _twin(actuation_space, twin_component, seed=11)
    right = _twin(actuation_space, twin_component, seed=11)

    assert left.weights_digest == right.weights_digest


def test_different_seeds_give_different_digests(
    actuation_space: ActuationSpace, twin_component: ComponentId
) -> None:
    left = _twin(actuation_space, twin_component, seed=1)
    right = _twin(actuation_space, twin_component, seed=2)

    assert left.weights_digest != right.weights_digest


def test_the_digest_moves_when_adaptation_moves_the_twin(
    actuation_space: ActuationSpace, twin_component: ComponentId
) -> None:
    # The point of recording it: FB2 changes the model during a run, so a
    # verdict is only traceable if the record says which model produced it.
    twin = _twin(actuation_space, twin_component, adaptation_buffer=2, ewc_lambda=0.0)
    before = twin.weights_digest
    command = ControlCommand(space=actuation_space, values=(0.9, -0.4))

    for _ in range(2):
        twin.adapt(applied=command, measured=_state())

    assert twin.weights_digest != before


def test_a_checkpoint_round_trips(
    actuation_space: ActuationSpace, twin_component: ComponentId, tmp_path: Path
) -> None:
    trained = _twin(actuation_space, twin_component, seed=5)
    with torch.no_grad():
        trained._network.output.bias.fill_(0.25)
    expected = trained.predict(tick=TickId(1), state=_state()).command.values
    path = tmp_path / "nested" / "twin.pt"
    trained.save_checkpoint(path)

    fresh = _twin(actuation_space, twin_component, seed=999)
    assert fresh.predict(tick=TickId(1), state=_state()).command.values != pytest.approx(expected)

    fresh.load_checkpoint(path)

    assert fresh.predict(tick=TickId(1), state=_state()).command.values == pytest.approx(expected)
    assert fresh.weights_digest == trained.weights_digest


def test_saving_creates_missing_parent_directories(
    actuation_space: ActuationSpace, twin_component: ComponentId, tmp_path: Path
) -> None:
    path = tmp_path / "a" / "b" / "c" / "twin.pt"

    _twin(actuation_space, twin_component).save_checkpoint(path)

    assert path.is_file()


def test_a_checkpoint_from_a_different_architecture_is_refused(
    actuation_space: ActuationSpace, twin_component: ComponentId, tmp_path: Path
) -> None:
    # A checkpoint trained for a different actuation space or hidden width would
    # leave a twin predicting confidently from half-trained weights.
    wide = _twin(actuation_space, twin_component, hidden_width=64)
    path = tmp_path / "wide.pt"
    wide.save_checkpoint(path)

    narrow = _twin(actuation_space, twin_component, hidden_width=8)

    with pytest.raises(ConfigurationError, match="architecture"):
        narrow.load_checkpoint(path)


def test_a_loaded_twin_is_left_in_evaluation_mode(
    actuation_space: ActuationSpace, twin_component: ComponentId, tmp_path: Path
) -> None:
    path = tmp_path / "twin.pt"
    _twin(actuation_space, twin_component).save_checkpoint(path)

    fresh = _twin(actuation_space, twin_component)
    fresh.load_checkpoint(path)

    assert not fresh._network.training
    assert all(
        math.isfinite(v) for v in fresh.predict(tick=TickId(1), state=_state()).command.values
    )
