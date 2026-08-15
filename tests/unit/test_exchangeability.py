"""The rendering rules behind the OD-8 re-measurement.

Why a thin sample gets its own rule
-------------------------------------
The first run of `benchmarks/exchangeability.py` printed **100% inside** for a
context with **one** live sample, in the same column as a genuine **0%** from
999. Both looked like fractions. One was a measurement and the other was a
coincidence with a percent sign on it, and nothing in the table said which.

A fraction from ``n=1`` is not a weaker measurement of the same thing — it is a
different kind of thing. :func:`render` now says ``n=1`` and *"too few to
judge"*, and the verdict paragraph ignores those contexts entirely rather than
counting them toward or against the conclusion.

That is the same failure this session hit twice at larger scale: a number
assembled correctly from an observation nobody checked was adequate.
"""

from __future__ import annotations

from benchmarks.exchangeability import Comparison, render


def comparison(
    *,
    context: str = "URBAN_CLEAR",
    live_count: int = 999,
    live_low: float = 3.36,
    live_high: float = 3.41,
    corpus_low: float = 3.88,
    corpus_high: float = 5.43,
    inside: float = 0.0,
) -> Comparison:
    """Return one comparison, defaulting to the measured URBAN_CLEAR row."""
    return Comparison(
        context=context,
        corpus_count=1000,
        corpus_low=corpus_low,
        corpus_high=corpus_high,
        live_count=live_count,
        live_low=live_low,
        live_median=(live_low + live_high) / 2,
        live_high=live_high,
        inside=inside,
        overlaps=not (live_high < corpus_low or live_low > corpus_high),
    )


def test_a_disjoint_context_is_flagged_and_reported_as_standing() -> None:
    """The measured URBAN_CLEAR row: 999 samples, none inside, no overlap."""
    lines = render([comparison()])

    assert any("NO OVERLAP" in line for line in lines)
    assert any("OD-8 STANDS" in line for line in lines)


def test_a_thin_sample_is_not_reported_as_a_percentage() -> None:
    """The bug this file exists for. ``n=1`` is not ``100%``."""
    lines = render([comparison(context="DEGRADED_SENSOR", live_count=1, inside=1.0)])

    assert any("n=1" in line for line in lines)
    assert any("too few to judge" in line for line in lines)
    assert not any("100.0%" in line for line in lines)


def test_a_thin_sample_cannot_rescue_a_disjoint_verdict() -> None:
    """A one-sample context sitting inside must not dilute a real 0%.

    Both rows appear in the table -- suppressing the thin one would hide that
    the context exists -- but only the judged one reaches the conclusion.
    """
    lines = render(
        [
            comparison(),
            comparison(context="DEGRADED_SENSOR", live_count=1, inside=1.0, corpus_low=0.08),
        ]
    )

    assert any("DEGRADED_SENSOR" in line for line in lines), "still shown"
    assert any("OD-8 STANDS" in line for line in lines)
    assert any("1 context(s) have no overlap" in line for line in lines)


def test_a_thin_sample_cannot_manufacture_a_disjoint_verdict_either() -> None:
    """Symmetric: a single out-of-range sample must not read as a violation."""
    lines = render([comparison(live_count=2, inside=0.0)])

    assert any("too few to judge" in line for line in lines)
    assert not any("OD-8 STANDS" in line for line in lines)
    assert any("No context produced enough live samples" in line for line in lines)


def test_full_overlap_is_reported_with_its_own_caveat() -> None:
    """Passing is necessary and not sufficient, and the report has to say so.

    The corpus and the live loop share a plant, a twin and a policy. Agreement
    between them is agreement between two things this project wrote, and a
    reader who took it for coverage on real driving would be taking exactly the
    [M-syn] step the credibility matrix exists to prevent.
    """
    lines = render([comparison(live_low=4.0, live_high=5.0, inside=1.0)])

    assert not any("OD-8 STANDS" in line for line in lines)
    assert any("NOT sufficient" in line for line in lines)
    assert any("share a plant" in line for line in lines)
