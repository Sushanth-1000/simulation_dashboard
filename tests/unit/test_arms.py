"""The driven-arms benchmark: the estimator error, and the claim it carries.

Why the verdict is tested and not just the arithmetic
------------------------------------------------------
E-153's claim is not *"the error got smaller"*. It is that under redundancy the
biased arm and the healthy arm are **indistinguishable to four decimals** --
which is a far stronger statement, and one this tool must not make when it is
not true. So the interesting tests here are the two directions of that verdict:
it says "indistinguishable" only when the arms agree, and it says "the bias is
reaching the estimator" when they do not.

Importing the module also puts it under ``mypy --strict``: ``files = ["src",
"tests"]``, so a benchmark nobody imports is a benchmark whose types nobody
checks.
"""

from __future__ import annotations

from benchmarks.arms import ArmReading, render


def arm(
    *,
    single: bool,
    faulted: bool,
    deviation: float,
    peak: float = 0.13,
) -> ArmReading:
    """Return an arm with the fields the verdict reads."""
    return ArmReading(
        label=("single channel" if single else "redundant")
        + (" / 1 m bias" if faulted else " / clean"),
        single_channel=single,
        faulted=faulted,
        peak_estimator_error_m=peak,
        final_deviation_m=deviation,
        vetoed=1,
        final_speed_mps=12.09,
    )


def quartet(*, redundant_faulted: float) -> list[ArmReading]:
    """Return the four arms, with the one under test parameterised.

    The three fixed values are the measured ones: 0.1034 m single-channel clean,
    0.8387 m single-channel under a 1 m bias, 0.0168 m redundant clean.
    """
    return [
        arm(single=True, faulted=False, deviation=0.1034, peak=0.1993),
        arm(single=True, faulted=True, deviation=0.8387, peak=1.1805),
        arm(single=False, faulted=False, deviation=0.0168, peak=0.1323),
        arm(single=False, faulted=True, deviation=redundant_faulted, peak=0.1323),
    ]


def test_agreeing_redundant_arms_are_reported_as_indistinguishable() -> None:
    lines = render(quartet(redundant_faulted=0.0168), offset=1.0)

    assert any("INDISTINGUISHABLE" in line for line in lines)


def test_the_verdict_quotes_the_cost_of_going_without() -> None:
    # The claim is only interesting beside the alternative, so the text has to
    # carry the single-channel figures rather than leaving them in the table.
    lines = render(quartet(redundant_faulted=0.0168), offset=1.0)
    body = "\n".join(lines)

    assert "0.8387" in body
    assert "1.1805" in body


def test_disagreeing_redundant_arms_refuse_the_claim() -> None:
    """The direction that matters.

    A tool that only knows how to report success is a tool that will report
    success when the mechanism has broken.
    """
    lines = render(quartet(redundant_faulted=0.4000), offset=1.0)

    assert any("DIFFER" in line for line in lines)
    assert not any("INDISTINGUISHABLE" in line for line in lines)


def test_the_threshold_is_four_decimals_not_a_loose_tolerance() -> None:
    # 0.0168 against 0.0170 is a 2e-4 gap: visibly different at the precision
    # the claim is stated to, so it must not pass as agreement.
    lines = render(quartet(redundant_faulted=0.0170), offset=1.0)

    assert any("DIFFER" in line for line in lines)


def test_every_arm_appears_in_the_table() -> None:
    lines = render(quartet(redundant_faulted=0.0168), offset=1.0)
    body = "\n".join(lines)

    for label in ("single channel / clean", "single channel / 1 m bias", "redundant / clean"):
        assert label in body


def test_the_injected_offset_is_named_in_the_heading() -> None:
    # A table that does not say how big the lie was cannot be read later.
    lines = render(quartet(redundant_faulted=0.0168), offset=2.0)

    assert any("2 m lie" in line for line in lines)
