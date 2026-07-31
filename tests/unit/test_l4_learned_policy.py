"""The trained policy: its feature map, its action map, and how it refuses to load.

The properties worth testing here are not "the network computes the right
numbers" -- it is a learned function and there is no right answer to check
against. They are the ones whose violation is *silent*: a checkpoint loaded with
the wrong scales, an architecture mismatch absorbed by a permissive load, an
action map that clamps away the very proposals the gates exist to catch.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

import pytest
import torch

from astra.kernel.errors import ConfigurationError, RangeViolationError
from astra.layers.l4_proposer.learned import LearnedPolicy, PolicyCheckpoint
from astra.layers.l4_proposer.network import (
    POLICY_FEATURE_COUNT,
    PolicyNetwork,
    command_from_normalised,
    policy_features,
)

if TYPE_CHECKING:
    from pathlib import Path

LANE_HALF_WIDTH = 1.75
REFERENCE_SPEED = 13.0
LATERAL_LIMIT = 3.0
LOWER = (0.0, 0.0, -0.5)
UPPER = (1.0, 1.0, 0.5)


def _payload(**overrides: object) -> dict[str, Any]:
    network = PolicyNetwork(command_dimension=3)
    payload: dict[str, Any] = {
        "weights": network.state_dict(),
        "command_dimension": 3,
        "lane_half_width_m": LANE_HALF_WIDTH,
        "reference_speed_mps": REFERENCE_SPEED,
        "lateral_acceleration_limit_mps2": LATERAL_LIMIT,
        "channel_lower": LOWER,
        "channel_upper": UPPER,
    }
    payload.update(overrides)
    return payload


def _features(observation: tuple[float, ...]) -> tuple[float, ...]:
    return policy_features(
        observation,
        lane_half_width_m=LANE_HALF_WIDTH,
        reference_speed_mps=REFERENCE_SPEED,
        lateral_acceleration_limit_mps2=LATERAL_LIMIT,
    )


# --------------------------------------------------------------------------- #
# The feature map
# --------------------------------------------------------------------------- #


def test_longitudinal_position_does_not_reach_the_network() -> None:
    # The reason the feature map exists. `px` grows without bound along a route,
    # and a network that sees it learns the training route rather than the task.
    near = _features((0.0, 0.4, 13.0, 0.02, 0.5, 0.9))
    far = _features((9_999.0, 0.4, 13.0, 0.02, 0.5, 0.9))

    assert near == far


def test_the_feature_vector_has_the_width_the_network_expects() -> None:
    assert len(_features((0.0, 0.0, 13.0, 0.0, 0.0, 1.0))) == POLICY_FEATURE_COUNT


def test_heading_is_presented_without_a_wrap_discontinuity() -> None:
    # sin/cos rather than the raw angle. Feeding psi directly would present the
    # network with a jump of 2*pi between two headings a hair apart.
    just_below = _features((0.0, 0.0, 13.0, math.pi - 1e-9, 0.0, 1.0))
    just_above = _features((0.0, 0.0, 13.0, -math.pi + 1e-9, 0.0, 1.0))

    assert just_below[2] == pytest.approx(just_above[2], abs=1e-6)
    assert just_below[3] == pytest.approx(just_above[3], abs=1e-6)


def test_the_speed_feature_is_zero_at_the_reference_speed() -> None:
    assert _features((0.0, 0.0, REFERENCE_SPEED, 0.0, 0.0, 1.0))[1] == pytest.approx(0.0)


# --------------------------------------------------------------------------- #
# The action map
# --------------------------------------------------------------------------- #


def test_the_normalised_extremes_map_to_the_channel_bounds() -> None:
    assert command_from_normalised((-1.0, -1.0, -1.0), lower=LOWER, upper=UPPER) == pytest.approx(
        LOWER
    )
    assert command_from_normalised((1.0, 1.0, 1.0), lower=LOWER, upper=UPPER) == pytest.approx(
        UPPER
    )


def test_an_out_of_range_action_maps_to_an_out_of_envelope_command() -> None:
    # Load-bearing. Core-A is the untrusted component; a proposer that could not
    # physically express an inadmissible command would make every gate
    # downstream untestable, and a clamp here would do exactly that.
    steer = command_from_normalised((0.0, 0.0, 3.0), lower=LOWER, upper=UPPER)[2]

    assert steer > UPPER[2]


# --------------------------------------------------------------------------- #
# Loading refuses what it cannot verify
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "missing",
    ["weights", "lane_half_width_m", "reference_speed_mps", "channel_lower", "channel_upper"],
)
def test_a_checkpoint_missing_any_scale_is_refused(missing: str) -> None:
    # The failure this prevents is silent: a policy fed features on a different
    # scale from the ones it learned returns plausible commands computed from
    # misscaled inputs, and it reads as poor tuning rather than a loading bug.
    payload = _payload()
    del payload[missing]

    with pytest.raises(ConfigurationError, match="missing"):
        PolicyCheckpoint(payload)


def test_a_non_positive_normaliser_is_refused() -> None:
    with pytest.raises(RangeViolationError):
        PolicyCheckpoint(_payload(reference_speed_mps=0.0))


def test_channel_bounds_that_do_not_match_the_command_width_are_refused() -> None:
    with pytest.raises(ConfigurationError, match="do not match"):
        PolicyCheckpoint(_payload(channel_lower=(0.0, 0.0)))


def test_degenerate_channel_bounds_are_refused() -> None:
    # Every normalised action would map to the same command, so the policy would
    # look like a constant controller rather than a broken checkpoint.
    with pytest.raises(ConfigurationError, match="ordered"):
        PolicyCheckpoint(_payload(channel_lower=(0.0, 0.0, 0.5)))


def test_weights_that_do_not_fit_the_architecture_are_refused() -> None:
    # `strict=True`. A permissive load leaves the unmatched layers at their
    # random initialisation, and a partly-random actor still returns commands.
    payload = _payload()
    payload["weights"] = {
        key: value for key, value in payload["weights"].items() if "head" not in key
    }

    with pytest.raises(ConfigurationError, match="does not fit"):
        LearnedPolicy(PolicyCheckpoint(payload))


def test_loading_an_absent_checkpoint_names_the_command_that_produces_one(
    tmp_path: Path,
) -> None:
    with pytest.raises(ConfigurationError, match="train_policy"):
        LearnedPolicy.load(tmp_path / "absent.pt")


def test_a_checkpoint_that_is_not_a_mapping_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "wrong.pt"
    torch.save(torch.zeros(3), path)

    with pytest.raises(ConfigurationError, match="not a mapping"):
        LearnedPolicy.load(path)


# --------------------------------------------------------------------------- #
# Inference
# --------------------------------------------------------------------------- #


def test_the_policy_returns_one_value_per_channel() -> None:
    policy = LearnedPolicy(PolicyCheckpoint(_payload()))

    assert len(policy.act((0.0, 0.3, 12.0, 0.01, 0.2, 0.9))) == len(LOWER)


def test_inference_is_deterministic() -> None:
    # Exploration belongs to training. A stochastic proposer would make the
    # evidence log non-reproducible for reasons unrelated to the vehicle's
    # situation, and replay would stop being a check on anything.
    policy = LearnedPolicy(PolicyCheckpoint(_payload()))
    observation = (0.0, 0.3, 12.0, 0.01, 0.2, 0.9)

    assert policy.act(observation) == policy.act(observation)


def test_a_round_trip_through_a_file_preserves_the_policy(tmp_path: Path) -> None:
    payload = _payload()
    path = tmp_path / "policy.pt"
    torch.save(payload, path)
    observation = (0.0, -0.6, 11.0, -0.03, 0.4, 0.7)

    direct = LearnedPolicy(PolicyCheckpoint(payload)).act(observation)
    loaded = LearnedPolicy.load(path).act(observation)

    assert loaded == pytest.approx(direct)
