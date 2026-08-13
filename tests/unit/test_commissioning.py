"""Does the commissioning certificate say what actually happened?

Why this file exists
---------------------
A commissioning certificate is a document an integrator acts on. Every defect
this project has filed against a *document* -- OD-2, OD-7, and the four-week
staleness in `SEPARATION_INVARIANTS.md` -- was a case of an artefact asserting
something the system did not do. A certificate is the highest-consequence
document the repository produces, so its verdict rules are asserted here rather
than trusted.

The three verdicts are tested against their boundaries, not their middles: a
run that halts, a run that stops, a run that leaves the corridor, a run that
matched nothing, and -- the one that was wrong on the first attempt -- a run
that matched *something* and spent almost all of its time in exploration
anyway.
"""

from __future__ import annotations

from astra.kernel.enums import ContextClass, FailSafeState
from benchmarks.commissioning import _CERTIFIED_HOLD, CONTEXTS, _judge

CORRIDOR = 1.75
TICKS = 400


def judge(
    *,
    matched: bool = True,
    exploring: int = 0,
    ticks: int = TICKS,
    worst: FailSafeState = FailSafeState.NOMINAL,
    final_speed: float = 12.0,
    max_deviation: float = 0.2,
) -> tuple[str, str]:
    """Judge a run, defaulting every field to a healthy certified one."""
    return _judge(
        matched=matched,
        exploring=exploring,
        ticks=ticks,
        worst=worst,
        final_speed=final_speed,
        max_deviation=max_deviation,
        corridor=CORRIDOR,
    )


# --------------------------------------------------------------------------- #
# UNFIT, and it must win over everything else
# --------------------------------------------------------------------------- #


def test_a_halted_run_is_unfit() -> None:
    verdict, reason = judge(worst=FailSafeState.HALT)

    assert verdict == "UNFIT"
    assert "HALT" in reason


def test_a_stopped_run_is_unfit_even_without_halting() -> None:
    # LIMP caps speed hard and exploration caps it too, so a slow vehicle is not
    # by itself a failure -- but a stationary one is, however it got there.
    verdict, _ = judge(final_speed=0.0)

    assert verdict == "UNFIT"


def test_leaving_the_corridor_is_unfit() -> None:
    verdict, reason = judge(max_deviation=CORRIDOR + 0.01)

    assert verdict == "UNFIT"
    assert "corridor" in reason


def test_a_halt_is_reported_over_a_corridor_departure() -> None:
    # Both are true on the same run. A certificate that reported whichever check
    # ran first would be non-deterministic in its explanation while being right
    # in its verdict, which is worse than being wrong in a stated way.
    _, reason = judge(worst=FailSafeState.HALT, max_deviation=99.0, final_speed=0.0)

    assert "HALT" in reason


def test_unfit_wins_over_a_perfectly_held_profile() -> None:
    verdict, _ = judge(matched=True, exploring=0, worst=FailSafeState.HALT)

    assert verdict == "UNFIT"


# --------------------------------------------------------------------------- #
# BOUNDED -- the verdict that must not be collapsed into a failure
# --------------------------------------------------------------------------- #


def test_no_profile_matched_is_bounded_not_unfit() -> None:
    # The architecture's distinguishing behaviour. Reporting this as a failure
    # would throw away the whole selling point: the vehicle is safe here, and it
    # is not calibrated here, and those are different sentences.
    verdict, reason = judge(matched=False, exploring=TICKS)

    assert verdict == "BOUNDED"
    assert "exploration envelope" in reason


def test_a_profile_that_matched_but_barely_held_is_bounded() -> None:
    """The rule that was wrong on the first run, and the platform that found it.

    With weaker brakes and 20% less steering bite, ``urban_clear`` matched on
    some ticks and spent **360 of 400 in exploration** -- and the first version
    of this rule reported it CERTIFIED, because it asked only whether a profile
    had *ever* matched.

    A context where the vehicle is inside the narrowed envelope for nine ticks
    in ten is a context it is not calibrated for, whatever happened on the
    tenth.
    """
    verdict, reason = judge(matched=True, exploring=360, ticks=400)

    assert verdict == "BOUNDED"
    assert "360" in reason or "40 of 400" in reason


def test_the_hold_threshold_is_a_majority() -> None:
    just_under = int(TICKS * _CERTIFIED_HOLD) + 1
    just_over = int(TICKS * _CERTIFIED_HOLD) - 1

    assert judge(exploring=just_under)[0] == "BOUNDED"
    assert judge(exploring=just_over)[0] == "CERTIFIED"


# --------------------------------------------------------------------------- #
# CERTIFIED
# --------------------------------------------------------------------------- #


def test_a_profile_held_throughout_is_certified() -> None:
    verdict, reason = judge(matched=True, exploring=0)

    assert verdict == "CERTIFIED"
    assert "throughout" in reason


def test_a_certified_verdict_still_explains_itself() -> None:
    # A certificate that only explains its failures leaves a reader unable to
    # check its successes.
    _, reason = judge(matched=True, exploring=10)

    assert "10" in reason


# --------------------------------------------------------------------------- #
# The context set
# --------------------------------------------------------------------------- #


def test_every_seeded_profile_has_a_context_to_commission_in() -> None:
    # A commissioning run that silently skipped a profile would certify a subset
    # and present it as the whole.
    covered = {context.expects for context in CONTEXTS if context.expects is not None}

    assert covered == set(ContextClass) - {ContextClass.UNCLASSIFIED}


def test_one_context_is_deliberately_uncertified() -> None:
    # The control arm. `seed_profiles` omits a tunnel on purpose, and a platform
    # that cannot produce BOUNDED there has lost the architecture's
    # distinguishing behaviour -- which a certificate listing only passes would
    # never reveal.
    uncovered = [context for context in CONTEXTS if context.expects is None]

    assert len(uncovered) == 1
    assert uncovered[0].name == "tunnel"


def test_every_supplied_component_is_a_probability() -> None:
    for context in CONTEXTS:
        for component in context.supplied:
            assert 0.0 <= component <= 1.0
