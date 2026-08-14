"""Does a second sensor actually carry information the first one cannot?

Why this file is short and structural
---------------------------------------
The measurement lives in ``benchmarks/redundancy.py`` and takes about a minute
to run, so these tests do not re-run it. They pin the three properties that make
the measurement *mean* something, each of which would be easy to break silently
while the numbers kept looking plausible:

**The residual is invariant to where the vehicle actually is.** ``reading_i -
median`` cancels the truth term exactly, so the statistic measures sensor
disagreement and nothing else. If it did not, a monitor would fire on a
manoeuvre and be reported as detecting a fault -- which is the failure mode the
cross-channel candidate actually had (E-106).

**The channels are dissimilar.** Identical sigmas would model identical sensors,
and identical sensors fail identically: two devices from one batch drift the
same way at the same temperature. Redundancy that shares a failure mode is
redundancy that is not there.

**Three channels, not two.** With two, a disagreement says something is wrong
and cannot say which one is lying. Three is the smallest number that permits a
median, and the median is what makes the faulted channel identifiable rather
than merely detectable.
"""

from __future__ import annotations

import random
import statistics

import pytest

from astra.kernel.enums import SensorModality
from benchmarks.redundancy import CHANNELS, SIGMAS, _readings


def residuals(readings: dict[SensorModality, float]) -> dict[SensorModality, float]:
    """Return each channel's absolute residual against the median."""
    median = statistics.median(readings.values())
    return {channel: abs(reading - median) for channel, reading in readings.items()}


# --------------------------------------------------------------------------- #
# The property that makes the statistic meaningful
# --------------------------------------------------------------------------- #


def test_the_residual_does_not_depend_on_where_the_vehicle_is() -> None:
    """Truth cancels, so this cannot fire on a manoeuvre.

    ``reading_i = truth + noise_i + offset_i`` and the median carries the same
    truth term, so the difference is a function of the noise and the fault
    alone. That is what distinguishes this from the cross-channel candidate,
    which measured a *quantity* rather than a *disagreement* and consequently
    fired on a large correction (E-106).

    **The cancellation is algebraic and the arithmetic is floating point**, so
    the two agree to about 5e-17 rather than bit-for-bit: ``7.5 + noise`` and
    ``0.0 + noise`` round differently in the last place, and the median inherits
    it. Asserted with a tolerance far tighter than any signal this monitor could
    care about -- the smallest fault it must see is 0.01 m -- and stated rather
    than hidden behind a loose ``approx``.
    """
    on_centre = _readings(0.0, generator=random.Random(1), faulted=None, offset=0.0)
    far_off = _readings(7.5, generator=random.Random(1), faulted=None, offset=0.0)

    left = residuals(on_centre)
    right = residuals(far_off)

    for channel in CHANNELS:
        assert left[channel] == pytest.approx(right[channel], abs=1e-12)


def test_a_fault_on_one_channel_moves_that_channel_furthest() -> None:
    # Identifiability, not just detectability: the largest residual must name
    # the liar. With two channels this test could not exist.
    readings = _readings(0.0, generator=random.Random(7), faulted=SensorModality.GPS, offset=2.0)

    worst = max(residuals(readings), key=lambda channel: residuals(readings)[channel])

    assert worst is SensorModality.GPS


def test_no_fault_leaves_every_residual_inside_the_noise() -> None:
    generator = random.Random(11)
    widest = max(SIGMAS.values())

    for _ in range(200):
        found = residuals(_readings(0.0, generator=generator, faulted=None, offset=0.0))
        assert max(found.values()) < 6.0 * widest


# --------------------------------------------------------------------------- #
# The properties that make the redundancy real rather than nominal
# --------------------------------------------------------------------------- #


def test_the_channels_are_dissimilar() -> None:
    # Identical sigmas model identical sensors, and identical sensors share a
    # failure mode. Common-mode failure is exactly what dissimilarity buys
    # protection against, so equal sigmas would be redundancy in name only.
    assert len(set(SIGMAS.values())) == len(SIGMAS)


def test_there_are_at_least_three_channels() -> None:
    # Two channels detect a disagreement and cannot attribute it. Three is the
    # smallest number that permits a median, and the median is what makes
    # `test_a_fault_on_one_channel_moves_that_channel_furthest` possible.
    minimum_for_a_median = 3

    assert len(CHANNELS) >= minimum_for_a_median


def test_every_channel_has_a_sigma() -> None:
    assert set(CHANNELS) == set(SIGMAS)


def test_the_channels_are_distinct_modalities() -> None:
    # A duplicate would be one sensor counted twice, which is the arithmetic
    # form of the defect this whole measurement exists to answer: five
    # modalities carrying one measurement (OD-15).
    assert len(set(CHANNELS)) == len(CHANNELS)
