"""The learned policy driving the real pipeline, with the loop closed.

Why the loop being closed is the whole point
----------------------------------------------
Under an open-loop harness -- one that publishes a fixed sensor payload every
tick regardless of what the vehicle was commanded to do -- L7b's jerk check
compares each proposal against a lateral acceleration pinned at zero. Every
non-zero proposal is then a jerk violation, and the measured veto rate is a
property of the harness. Measured that way the first trained policy scored 100%.
Closed-loop, on the same checkpoint, it is a single tick in four hundred.

That is recorded here rather than quietly fixed because the same mistake is
available to anyone who writes the next scenario.

What these tests assert
------------------------
That a genuinely learned policy is admissible on the modelled platform and that
the architecture's availability claim survives contact with one. They do not
assert a gate accuracy figure: the plant, the twin and the calibration corpus
all descend from the same kinematic equations, so there is no distribution shift
here for the statistical gate to be right or wrong about.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from astra.layers.l4_proposer.learned import LearnedPolicy
from training.closed_loop import CORPUS, TWIN, drive_closed_loop
from training.environment import EnvironmentSpec, SyntheticDrivingEnv

POLICY = Path("var/policy/synthetic.pt")
TICKS = 1000
"""Long enough to contain the startup transient *and* some steady state.

At 300 -- the value used until 2 August -- the run was entirely transient. The
plant resets up to 1 m off the lane centre, the policy corrects, and the
correction exceeds L7b's jerk bound until the rate limiter of ADR-0017 walks the
achieved lateral acceleration in over about twenty ticks. Measuring a veto *rate*
across only those ticks reports the transient as though it were the run.
"""

# The band the policy must hold around the reference speed, as a fraction of it.
# Generous on purpose: this is not a control-quality bar, it is the difference
# between a vehicle that drives and one that does not. The first checkpoint to
# reach a soak run came to a complete stop by step 250 of a 500-step episode and
# passed every test in this file, because none of them looked at speed.
SPEED_BAND = 0.35

pytestmark = pytest.mark.skipif(
    not (TWIN.exists() and CORPUS.exists() and POLICY.exists()),
    reason=(
        "needs a trained twin, a calibration corpus and a trained policy:\n"
        "  python training/train_twin.py --out var/twin/synthetic.pt\n"
        "  python training/generate_calibration.py --out var/calibration/synthetic.json\n"
        "  python -m training.train_policy --out var/policy/synthetic.pt"
    ),
)


@pytest.fixture(scope="module")
def learned() -> object:
    """Return one closed-loop run of the trained policy."""
    return drive_closed_loop(policy=LearnedPolicy.load(POLICY), ticks=TICKS)


@pytest.fixture(scope="module")
def placeholder() -> object:
    """Return one closed-loop run of the deterministic placeholder."""
    return drive_closed_loop(policy=None, ticks=TICKS)


def _drive_the_plant_directly(steps: int) -> list[float]:
    """Run the checkpoint in its own training environment and return the speeds.

    No pipeline, no gates, no fallback: just the policy and the plant it was
    fitted to. If the vehicle stops here, nothing downstream can be blamed for
    it, and every measurement taken through the pipeline is a measurement of
    that.
    """
    spec = EnvironmentSpec()
    policy = LearnedPolicy.load(POLICY)
    plant = SyntheticDrivingEnv(spec)
    plant.reset(seed=20260731)
    lower = np.asarray(spec.channel_lower, dtype=np.float64)
    upper = np.asarray(spec.channel_upper, dtype=np.float64)
    speeds: list[float] = []

    for _ in range(steps):
        raw = (*(float(value) for value in plant._state), 1.0)
        command = np.asarray([float(value) for value in policy.act(raw)], dtype=np.float64)
        plant.step((2.0 * (command - lower) / (upper - lower) - 1.0).astype(np.float32))
        speeds.append(float(plant._state[2]))
    return speeds


# --------------------------------------------------------------------------- #
# The vehicle has to keep moving, which nothing here used to check
# --------------------------------------------------------------------------- #


def test_the_learned_policy_holds_speed_in_its_own_environment() -> None:
    # Every other test in this file passed while the policy brought the vehicle
    # to a complete stop, because they all measure lane deviation and veto
    # rates. A proposer that cannot hold speed makes the whole pipeline
    # measurement meaningless: the state leaves the region every calibration
    # profile covers, so the knowledge base matches nothing and bounded safe
    # exploration engages for ever. See docs/SOAK_REPORT.md.
    spec = EnvironmentSpec()
    speeds = _drive_the_plant_directly(spec.episode_steps)

    assert speeds[-1] == pytest.approx(spec.reference_speed_mps, rel=SPEED_BAND)


def test_the_learned_policy_does_not_coast_to_a_halt() -> None:
    # The sharper form of the test above, and the one that fails loudest. A
    # stationary vehicle satisfies the lane-deviation assertions perfectly.
    spec = EnvironmentSpec()
    speeds = _drive_the_plant_directly(spec.episode_steps)

    assert min(speeds[spec.episode_steps // 2 :]) > 1.0


def test_the_vehicle_is_still_moving_at_the_end_of_a_closed_loop_run(learned: object) -> None:
    # The same property through the pipeline. It can fail here while passing
    # above -- a veto sequence that hands control to the fallback changes what
    # drives -- so both are worth having.
    assert learned.final_speed_mps > 1.0  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- #
# The architecture's availability claim, against a learned proposer
# --------------------------------------------------------------------------- #


def test_every_tick_issues_a_command_even_while_the_proposer_is_vetoed(learned: object) -> None:
    # The headline claim, and the first time it has been tested against a
    # component that can actually be wrong. A vetoed proposal does not stop the
    # vehicle; L9 issues the fallback and the drive continues.
    assert learned.issued == TICKS  # type: ignore[attr-defined]
    assert learned.vetoed > 0, "no veto occurred, so this proved nothing"  # type: ignore[attr-defined]


def test_the_learned_policy_is_physically_admissible_on_the_modelled_platform(
    learned: object,
) -> None:
    # C1--C3 contain no term bounding the lateral command's rate while L7b
    # enforces one, so this is not guaranteed by training and has to be measured.
    # It holds because of the action-rate term in the objective; remove that and
    # this test fails, which is the point of having it.
    jerk_vetoes = learned.reasons["PHYSICAL:LATERAL_JERK_EXCEEDS_LIMIT"]  # type: ignore[attr-defined]

    assert jerk_vetoes / TICKS < 0.05


# --------------------------------------------------------------------------- #
# The learned policy against the scaffolding it replaces
# --------------------------------------------------------------------------- #


def test_the_calibrated_proposer_is_typical_of_its_own_calibration(learned: object) -> None:
    # What replaced "the learned policy holds the lane better than the
    # placeholder". That comparison became meaningless once the corpus was
    # harvested from the deployed policy rather than the placeholder: the
    # placeholder is then off-distribution, is vetoed on 299 of 300 ticks, and
    # the fallback -- not the placeholder -- is what the learned policy would be
    # measured against. It held the lane 4% better, which said nothing about
    # either policy.
    #
    # This is the stronger claim the matched corpus makes available. A conformal
    # gate calibrated on a proposer should find that proposer unremarkable;
    # before the corpus was matched, the same policy was vetoed on 41% of ticks
    # by a threshold harvested from a different one.
    assert learned.vetoed <= TICKS * 0.05  # type: ignore[attr-defined]


def test_the_statistical_gate_still_discriminates_between_proposers(
    placeholder: object,
) -> None:
    # The control, and the reason the test above is not circular. A gate that
    # accepted its own proposer *because* it accepts everything would prove
    # nothing; this asserts it rejects a different one. Calibrating on the
    # deployed policy means L6 detects departures from that policy's own typical
    # behaviour -- which is what inductive conformal prediction is -- and the
    # absolute bounds that catch bad driving whatever produced it are L7a's and
    # L7b's job, not this gate's.
    assert placeholder.vetoed > TICKS * 0.5  # type: ignore[attr-defined]


def test_the_learned_policy_holds_the_lane(learned: object) -> None:
    # The lane-quality half of the old assertion, kept as an absolute bound
    # rather than a comparison against a controller that is no longer driving.
    assert learned.mean_absolute_deviation_m < 0.5  # type: ignore[attr-defined]


def test_the_vehicle_converges_on_the_lane_centre_and_stays_there(learned: object) -> None:
    # The assertion that would have caught the finding of 2 August, and the one
    # nothing in this file previously made. Lateral position was not measured by
    # any sensor, so the filter dead-reckoned it, the estimate sat at zero while
    # the plant drifted 2 m off a lane 1.75 m wide, and **no gate objected** --
    # a 0.00 veto rate and a Trust Index of exactly 1.00 the whole way out.
    #
    # A mean over the run would not have caught it either: the drift is slow and
    # the early ticks are near zero. What catches it is where the vehicle ends
    # up.
    assert learned.final_absolute_deviation_m < 0.05  # type: ignore[attr-defined]


def test_both_policies_keep_the_vehicle_moving(placeholder: object) -> None:
    assert placeholder.issued == TICKS  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- #
# Determinism
# --------------------------------------------------------------------------- #


def test_a_closed_loop_run_is_reproducible() -> None:
    # The evidence log is only evidence if the run behind it can be reproduced.
    # Inference is deterministic and the clock is injected, so two runs at the
    # same seed must agree exactly.
    first = drive_closed_loop(policy=LearnedPolicy.load(POLICY), ticks=60, seed=11)
    second = drive_closed_loop(policy=LearnedPolicy.load(POLICY), ticks=60, seed=11)

    assert first.vetoed == second.vetoed
    assert first.reasons == second.reasons
    assert first.mean_absolute_deviation_m == pytest.approx(second.mean_absolute_deviation_m)


def test_a_different_seed_produces_a_different_drive() -> None:
    # The control for the test above: without it, "reproducible" would also be
    # satisfied by a harness that ignored its seed entirely.
    first = drive_closed_loop(policy=LearnedPolicy.load(POLICY), ticks=60, seed=11)
    other = drive_closed_loop(policy=LearnedPolicy.load(POLICY), ticks=60, seed=12)

    assert first.mean_absolute_deviation_m != pytest.approx(other.mean_absolute_deviation_m)
