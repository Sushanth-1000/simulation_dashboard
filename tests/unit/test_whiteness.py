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
    _MINIMUM_LIVE_TICKS,
    ArmReading,
    Whiteness,
    _longest_run,
    _majority_fraction,
    _row_is_live,
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


# --------------------------------------------------------------------------- #
# Liveness: which ticks may be measured at all
# --------------------------------------------------------------------------- #
# These exist because the *first* version of this guard was wrong, and wrong in
# the direction that produces silence rather than a bad number: it read the
# run's final speed, so an arm whose fail-safe correctly brought the vehicle to
# rest was refused as though the policy had never driven. The benchmark produced
# nothing at all until 16 August 2026 and no test would have noticed.


def test_a_tick_is_live_only_when_a_command_moved_the_vehicle() -> None:
    assert _row_is_live(was_issued=True, speed_mps=12.0)


def test_a_vetoed_tick_is_not_live_however_fast_the_vehicle_is() -> None:
    # E-107's mechanism is the proposer closing the loop on a corrupted
    # estimate. A command that reaches no actuator cannot do that, and coasting
    # is not the loop being closed.
    assert not _row_is_live(was_issued=False, speed_mps=12.0)


def test_a_stationary_tick_is_not_live_however_the_command_was_issued() -> None:
    # The 7.35x retraction in one line: a stopped vehicle has no lateral
    # dynamics for the estimate to be wrong about, so its residual keeps a bias
    # that a moving vehicle would absorb.
    assert not _row_is_live(was_issued=True, speed_mps=0.0)


def test_liveness_is_per_tick_so_a_correct_safety_stop_keeps_its_earlier_ticks() -> None:
    """The defect this guard was narrowed to fix, stated as a property.

    Under an IMU dropout the fail-safe brings the vehicle to rest part way
    through the window. Those ticks are dead and the ones before the stop are
    not. A rule that read the *run's* final speed threw away both.
    """
    moving_then_stopped = [(True, 12.0)] * 41 + [(True, 0.0)] * 159

    live = [
        _row_is_live(was_issued=issued, speed_mps=speed) for issued, speed in moving_then_stopped
    ]

    assert sum(live) == 41, "the ticks before the stop are measurable"
    assert live[0], "the vehicle was driving when the window opened"
    assert not live[-1], "and stopped before it closed"


def test_an_arm_below_the_floor_is_thin_rather_than_quoted() -> None:
    def arm(live: int) -> ArmReading:
        return ArmReading(
            arm="imu_dropout",
            components=(
                Whiteness(
                    component="position_y",
                    mean_sigmas=0.0,
                    peak_cusum=0.0,
                    detected_at=None,
                    longest_run=0,
                    majority_sign_fraction=0.0,
                ),
            ),
            live_samples=live,
        )

    assert arm(_MINIMUM_LIVE_TICKS - 1).thin
    assert not arm(_MINIMUM_LIVE_TICKS).thin
