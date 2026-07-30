"""Mondrian conditioning: one calibration bucket per operational context.

Why conditioning matters here
------------------------------
A single pooled calibration set gives *marginal* coverage: the guarantee holds
on average across every context the vehicle has driven in. That average is
almost useless in a safety argument, because it can be satisfied by
over-covering the common case and under-covering the rare one -- and the rare
one is the whole reason the system exists.

Highway-clear will dominate any realistic corpus. Pooled, its residuals set the
threshold, and rain-night proposals get judged against a distribution they were
never drawn from. Mondrian conditioning splits the calibration set by context
class so the guarantee holds *per class*, which is what the paper's Equation 2
states and what the validation plan measures.

The rolling window
-------------------
Each class keeps a bounded window of its most recent scores. Bounded for two
reasons: an unbounded set grows without limit over a long drive, and -- more
importantly -- conformal prediction assumes exchangeability, which a set
spanning the whole history violates the moment conditions change. A window is
the crude but honest way to keep the calibration set roughly contemporaneous
with what is being scored.

The window size is a genuine trade-off, not a tuning detail: too short and the
quantile is noisy, too long and it describes conditions the vehicle has left.
UNCLASSIFIED is a real class
-----------------------------
:attr:`~astra.kernel.enums.ContextClass.UNCLASSIFIED` gets a bucket like any
other, and it will usually be empty. That is deliberate. The tunnel scenario
exists precisely because no certified class matches, and the correct behaviour
there is an infinite threshold and a Trust Index of zero -- which routes the
tick to bounded safe exploration rather than to a rejection the system cannot
justify.
"""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

from astra.kernel.enums import ContextClass, LayerId
from astra.kernel.errors import ConfigurationError
from astra.layers.l3_trust.quantile import conformal_quantile, empirical_cdf

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["MondrianCalibration"]


class MondrianCalibration:
    """A bounded calibration window per operational context class.

    Cold-path state: it is written by feedback loop FB3 as executed outcomes
    arrive, and read once per tick. Nothing here allocates on the hot path
    beyond the read itself.
    """

    __slots__ = ("_buckets", "_window")

    def __init__(self, *, window: int) -> None:
        """Build an empty calibration set.

        Args:
            window: How many recent scores each class retains.

        Raises:
            ConfigurationError: If the window is not positive. A zero window
                keeps no calibration data, which makes every threshold infinite
                and the gate permanently inert -- a system that looks calibrated
                while rejecting nothing.
        """
        if window < 1:
            message = (
                f"the Mondrian calibration window must be at least 1, got {window}; "
                f"a zero window retains no scores, so every threshold is infinite and "
                f"the statistical gate can never reject anything"
            )
            raise ConfigurationError(
                message, layer=LayerId.L3_CONFORMAL_TRUST, context={"window": window}
            )
        self._window = window
        self._buckets: dict[ContextClass, deque[float]] = {
            context: deque(maxlen=window) for context in ContextClass
        }

    def observe(self, context: ContextClass, score: float) -> None:
        """Record one non-conformity score against its context class.

        Feedback loop FB3. Called with the realised score of an executed
        command, so the quantiles track what the vehicle actually did rather
        than remaining frozen at the offline distribution.

        Args:
            context: The Mondrian class the score belongs to.
            score: The realised non-conformity score.
        """
        self._buckets[context].append(score)

    def scores(self, context: ContextClass) -> tuple[float, ...]:
        """Return the retained scores for one class.

        Args:
            context: The class to read.

        Returns:
            The scores, oldest first.
        """
        return tuple(self._buckets[context])

    def sample_count(self, context: ContextClass) -> int:
        """Return how many scores back this class's quantile.

        Args:
            context: The class to read.

        Returns:
            The number of retained scores. Recorded on every assessment so a
            reviewer can see when a quantile rested on too little data.
        """
        return len(self._buckets[context])

    def quantile(self, context: ContextClass, epsilon: float) -> float:
        """Return the class-conditional conformal threshold.

        Args:
            context: The class to read.
            epsilon: The significance level.

        Returns:
            The conformal quantile, or ``math.inf`` when the class holds too
            few scores to support the guarantee.
        """
        return conformal_quantile(self.scores(context), epsilon)

    def cdf(self, context: ContextClass, score: float) -> float:
        """Return the class-conditional empirical CDF at a score.

        Args:
            context: The class to read.
            score: The score to evaluate at.

        Returns:
            ``F_hat_k(score)``.
        """
        return empirical_cdf(self.scores(context), score)

    def seed(self, context: ContextClass, scores: Sequence[float]) -> None:
        """Load offline calibration scores for one class.

        Used to install the corpus collected before a run. Kept distinct from
        :meth:`observe` so that the audit log can distinguish a quantile derived
        from certified offline calibration from one that has drifted under FB3.

        Args:
            context: The class to seed.
            scores: The offline calibration scores.
        """
        for score in scores:
            self._buckets[context].append(score)
