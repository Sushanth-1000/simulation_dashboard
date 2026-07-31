"""Maximum mean discrepancy over the rolling innovation distribution.

Why the innovation sequence rather than the feature space
-----------------------------------------------------------
Covariate shift is usually detected by comparing feature distributions, which
requires the detector to know what a feature is -- and in this architecture that
knowledge lives below SI-1's line. The innovation sequence is a better signal
anyway: it is the difference between what the sensors said and what the model
expected, so a change in its distribution means the world has stopped matching
the model. That is precisely the event the gate needs to hear about, and it is
physics-grounded rather than representational.

What MMD measures
-----------------
Given two samples, the squared maximum mean discrepancy under a kernel ``k`` is

    ``MMD^2 = E[k(x,x')] - 2 E[k(x,y)] + E[k(y,y')]``

which is zero when the two samples come from the same distribution and positive
when they do not. Using a Gaussian kernel makes it sensitive to differences in
shape, not only in mean -- an innovation distribution that keeps its average and
doubles its spread is exactly the kind of drift a mean test would miss and a
filter starting to lose the plot would produce.

The bandwidth is chosen by the median heuristic rather than configured. It is a
property of the data at hand rather than an operating point a safety engineer
could reason about, and a fixed bandwidth would make the detector's sensitivity
depend on the units the innovation happens to be expressed in.
"""

from __future__ import annotations

import math
import statistics
from collections import deque
from typing import TYPE_CHECKING, Final

from astra.kernel.enums import LayerId
from astra.kernel.errors import ConfigurationError

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["MINIMUM_WINDOW", "MmdShiftDetector", "median_bandwidth", "squared_mmd"]

MINIMUM_WINDOW: Final = 4
"""Smallest window the detector will accept.

The window is split in half for the comparison, so anything below four leaves a
half of fewer than two samples -- which is a point, not a distribution. An
architectural property of the mechanism rather than an operating point, so it
lives here rather than in configuration.
"""

_MINIMUM_PAIR: Final = 2
"""Fewest values from which a pairwise distance can be formed."""


def median_bandwidth(values: Sequence[float]) -> float:
    """Return the Gaussian kernel bandwidth by the median heuristic.

    Args:
        values: The pooled sample.

    Returns:
        The median pairwise absolute distance, or ``1.0`` when that median is
        zero or the sample is too small. Falling back to one keeps the kernel
        well-defined; a zero bandwidth would divide by zero and a
        near-zero one would make every pair look infinitely far apart.
    """
    if len(values) < _MINIMUM_PAIR:
        return 1.0
    distances = [
        abs(left - right) for index, left in enumerate(values) for right in values[index + 1 :]
    ]
    median = statistics.median(distances) if distances else 0.0
    return median if median > 0.0 else 1.0


def squared_mmd(left: Sequence[float], right: Sequence[float], bandwidth: float) -> float:
    """Return the biased squared MMD between two samples under a Gaussian kernel.

    The biased estimator is used deliberately: it includes the diagonal terms,
    which makes it non-negative for any input. The unbiased estimator can return
    a small negative value for identical distributions, and a detector whose
    "distance" is sometimes negative invites a comparison against a threshold
    that quietly never fires.

    Args:
        left: The first sample.
        right: The second sample.
        bandwidth: The Gaussian kernel bandwidth.

    Returns:
        ``MMD^2``, zero for identical samples and growing as they diverge. Two
        empty or single-element samples return ``0.0``: no evidence of shift is
        not evidence of no shift, and the caller reads the sample count.
    """
    if not left or not right:
        return 0.0

    def kernel(a: float, b: float) -> float:
        return math.exp(-((a - b) ** 2) / (2.0 * bandwidth * bandwidth))

    xx = sum(kernel(a, b) for a in left for b in left) / (len(left) ** 2)
    yy = sum(kernel(a, b) for a in right for b in right) / (len(right) ** 2)
    xy = sum(kernel(a, b) for a in left for b in right) / (len(left) * len(right))
    return xx - 2.0 * xy + yy


class MmdShiftDetector:
    """Watches a rolling innovation window for a change in distribution.

    Splits the window in half and compares the older half against the newer.
    Simple, and the simplicity is the point: a detector with its own learned
    model would need its own calibration, its own failure mode, and its own
    place in the safety argument.
    """

    __slots__ = ("_cached", "_threshold", "_values", "_window")

    def __init__(self, *, window: int, threshold: float) -> None:
        """Build the detector.

        Args:
            window: How many recent innovations to retain. Split in half for
                the comparison, so this must be at least four for either half
                to hold more than one sample.
            threshold: The squared-MMD value above which shift is declared.

        Raises:
            ConfigurationError: If the window is below four or the threshold is
                negative or non-finite. A negative threshold fires on every
                tick, since the biased estimator is never negative.
        """
        if window < MINIMUM_WINDOW:
            message = (
                f"the MMD window must be at least {MINIMUM_WINDOW}, got {window}; "
                f"the detector splits "
                f"the window in half and a half of fewer than two samples cannot "
                f"describe a distribution"
            )
            raise ConfigurationError(
                message, layer=LayerId.L6_MPC_ICP_GATE, context={"window": window}
            )
        if not math.isfinite(threshold) or threshold < 0.0:
            message = (
                f"the MMD threshold must be finite and non-negative, got {threshold}; "
                f"the biased estimator is never negative, so a negative threshold "
                f"declares covariate shift on every tick"
            )
            raise ConfigurationError(
                message,
                layer=LayerId.L6_MPC_ICP_GATE,
                context={"threshold": str(threshold)},
            )
        self._window = window
        self._threshold = threshold
        self._values: deque[float] = deque(maxlen=window)
        self._cached: float | None = None

    @property
    def sample_count(self) -> int:
        """Return how many innovations are currently retained."""
        return len(self._values)

    def observe(self, innovation: float) -> None:
        """Record one innovation magnitude.

        Args:
            innovation: The Mahalanobis distance for this tick. A non-finite
                value is dropped rather than admitted: it would poison the
                kernel and make the discrepancy meaningless for the whole
                window rather than for one sample.
        """
        if math.isfinite(innovation):
            self._values.append(innovation)
            self._cached = None

    def discrepancy(self) -> float:
        """Return the squared MMD between the older and newer halves.

        Memoised until the next :meth:`observe`. The discrepancy is a pure
        function of the retained window, so caching it returns the identical
        value rather than an approximation of it.

        The caching is not a micro-optimisation. The kernel is evaluated
        ``O(n^2)`` times in the window size, and the gate asks for the
        discrepancy twice per tick -- once through ``effective_epsilon`` to
        decide whether to tighten, and once directly to record it as evidence.
        Measured on the assembled pipeline, that second computation was the
        single largest cost in the whole tick.

        Returns:
            ``MMD^2``, or ``0.0`` before the window has filled enough to split.
        """
        if self._cached is not None:
            return self._cached
        if len(self._values) < self._window:
            self._cached = 0.0
            return 0.0
        half = len(self._values) // 2
        values = list(self._values)
        older, newer = values[:half], values[half:]
        self._cached = squared_mmd(older, newer, median_bandwidth(values))
        return self._cached

    def has_shifted(self) -> bool:
        """Return whether covariate shift is currently declared.

        Returns:
            ``True`` when the discrepancy exceeds the configured threshold.
            Always ``False`` until the window is full, because a comparison
            between two short halves is noise rather than evidence.
        """
        return self.discrepancy() > self._threshold
