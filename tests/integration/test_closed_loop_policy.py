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

import pytest

from astra.layers.l4_proposer.learned import LearnedPolicy
from training.closed_loop import CORPUS, TWIN, drive_closed_loop

POLICY = Path("var/policy/synthetic.pt")
TICKS = 300

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


def test_the_learned_policy_holds_the_lane_better_than_the_placeholder(
    learned: object, placeholder: object
) -> None:
    # Not a safety claim -- a sanity check that training did something. A
    # learned policy that drove worse than a deterministic controller would mean
    # the pipeline was ignoring it, which has happened and was not obvious.
    assert learned.mean_absolute_deviation_m < placeholder.mean_absolute_deviation_m  # type: ignore[attr-defined]


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
