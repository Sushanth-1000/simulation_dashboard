"""The statistics behind the fifth candidate against the slow drift.

Why this file exists at all
----------------------------
`benchmarks/whiteness.py` broke a claim this project had made and carried into
its register, its module docstrings and its case for Phase 7: E-107's *"a
self-consistent lie slower than the sensor noise cannot be distinguished from
truth by any function of a single sensor chain."* The measurement that broke it
turns on a handful of small pure functions, so those functions had better be
right.

The near miss these tests pin
-------------------------------
At the textbook slack ``k = 0.5`` the detector reports **1.21x** separation and
would have been filed as a fifth refutation — strengthening a claim that is
false. The drift's mean offset is 0.242 sigma, the slack absorbed all of it, and
only sweeping ``k`` revealed that separation begins at 0.20 and reaches 7.35x at
0.10 (E-140).

:func:`test_slack_absorbs_a_bias_smaller_than_itself` is that near miss as an
assertion. It is not a curiosity: it is the arithmetic reason a CUSUM can be
mistuned into silence, and anyone changing ``CUSUM_SLACK`` should have to read
it.
"""

from __future__ import annotations

import math
import random

import pytest

from benchmarks.whiteness import (
    _longest_run,
    _majority_fraction,
    _standard_deviation,
    cusum,
)


def white(count: int, *, seed: int = 20260815) -> list[float]:
    """Return a zero-mean, serially uncorrelated sequence."""
    generator = random.Random(seed)
    return [generator.gauss(0.0, 1.0) for _ in range(count)]


def biased(count: int, *, offset: float, seed: int = 20260815) -> list[float]:
    """Return a white sequence with a constant offset added."""
    return [sample + offset for sample in white(count, seed=seed)]


# --------------------------------------------------------------------------- #
# CUSUM
# --------------------------------------------------------------------------- #


def test_a_white_sequence_does_not_accumulate_the_way_a_biased_one_does() -> None:
    """The property the whole detector rests on, stated as the ratio it is.

    A white CUSUM is not *flat* — it random-walks, and its peak grows slowly
    with the sequence length, which is why the benchmark reports a clean arm
    beside every faulted one instead of assuming zero. What must hold is
    **separation**, and that is what the report and this test both measure.
    """
    clean, _ = cusum(white(400), slack=0.1, threshold=math.inf)
    biased_peak, _ = cusum(biased(400, offset=0.3), slack=0.1, threshold=math.inf)
    assert biased_peak > clean * 3, "the bar E-94 could not clear on any window"


def test_a_biased_sequence_accumulates_without_any_sample_being_extreme() -> None:
    """The whole point: no single sample is anomalous and the sum is.

    The offset here is 0.3 sigma. Every sample sits comfortably inside any
    per-tick band — which is exactly what E-53 measured and reported as silence
    — and the sequence still separates.
    """
    samples = biased(400, offset=0.3)
    assert max(abs(sample) for sample in samples) < 5.0, "no sample is individually extreme"

    peak, detected = cusum(samples, slack=0.1, threshold=5.0)
    assert detected is not None
    assert peak > 20.0


def test_slack_absorbs_a_bias_smaller_than_itself() -> None:
    """The near miss, as an assertion. Read the module docstring.

    A slack of 0.5 against an offset of 0.242 leaves nothing to accumulate, so
    the detector reports silence on a fault it can see perfectly well at a
    smaller slack. This is why a detector is not refuted until its free
    parameter has been swept.
    """
    samples = biased(200, offset=0.242)

    absorbed, _ = cusum(samples, slack=0.5, threshold=math.inf)
    found, _ = cusum(samples, slack=0.1, threshold=math.inf)

    # Same data, same statistic, one constant apart. On the real residual this
    # was 3.55 against 32.75; the ratio is what matters, not the magnitudes.
    assert found > absorbed * 3

    clean = cusum(white(200), slack=0.5, threshold=math.inf)[0]
    assert absorbed < clean * 2, "at the textbook slack it is indistinguishable from noise"


def test_the_cusum_is_two_sided() -> None:
    """A sensor drifting the other way must not be invisible.

    A one-sided CUSUM would halve the detector's coverage in a way nothing in
    the report would reveal, because the fault study only drifts upward.
    """
    peak, detected = cusum(biased(400, offset=-0.3), slack=0.1, threshold=5.0)
    assert detected is not None
    assert peak > 20.0


def test_detection_is_the_first_crossing_not_the_peak() -> None:
    """The reported tick must be when a monitor would have acted."""
    samples = [0.0] * 50 + [1.0] * 200
    _, detected = cusum(samples, slack=0.5, threshold=5.0)
    assert detected is not None
    assert 50 <= detected <= 61, "0.5 net per sample needs ten samples to clear five"


def test_an_unreachable_threshold_reports_no_detection_and_a_real_peak() -> None:
    """The sweep relies on this: peak with `threshold=inf` and no alarm."""
    peak, detected = cusum(biased(400, offset=0.3), slack=0.1, threshold=math.inf)
    assert detected is None
    assert peak > 20.0


def test_an_empty_sequence_is_flat_rather_than_an_error() -> None:
    """An arm that produced no corrected update is silent, not a crash."""
    assert cusum([], slack=0.5, threshold=5.0) == (0.0, None)


# --------------------------------------------------------------------------- #
# The supporting statistics
# --------------------------------------------------------------------------- #


def test_a_white_sequence_has_short_sign_runs() -> None:
    """About log2(N) for a fair coin, which is what makes a long run evidence."""
    assert _longest_run(white(1000)) < 20


def test_a_constant_sign_sequence_runs_to_its_length() -> None:
    assert _longest_run([1.0] * 200) == 200


def test_a_run_is_broken_by_a_sign_change_and_by_a_zero() -> None:
    """A zero has no sign, so counting it as either would overstate persistence."""
    assert _longest_run([1.0, 1.0, -1.0, -1.0, -1.0]) == 3
    assert _longest_run([1.0, 1.0, 0.0, 1.0, 1.0]) == 2


def test_the_majority_fraction_is_a_half_for_a_fair_coin() -> None:
    assert _majority_fraction(white(2000)) == pytest.approx(0.5, abs=0.05)


def test_the_majority_fraction_is_one_when_every_sign_agrees() -> None:
    assert _majority_fraction([1.0] * 100) == 1.0
    assert _majority_fraction([]) == 0.0


def test_a_degenerate_spread_does_not_become_a_divisor_of_zero() -> None:
    """Otherwise the normalisation would manufacture a detection out of arithmetic.

    A component that never moves — a stuck channel, or one the extractor does
    not fill — would divide every later arm by ~0 and report enormous
    separation on noise.
    """
    assert _standard_deviation([2.0] * 100) == 1.0
    assert _standard_deviation([]) == 1.0
    assert _standard_deviation([1.0]) == 1.0


def test_the_standard_deviation_is_the_sample_estimate() -> None:
    assert _standard_deviation([2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]) == pytest.approx(
        2.13809, abs=1e-4
    )
