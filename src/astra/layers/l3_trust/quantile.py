r"""The conformal quantile, and the two ways it is usually got wrong.

This module is small and it is the most correctness-critical code in the
project after the filter. Risk RK-2 says so in as many words: a subtly wrong
conformal implementation gives a *silently invalid* coverage guarantee. Nothing
raises, no test that only checks types fails, the gate keeps returning verdicts,
and the central claim of the architecture is quietly false.

Mistake one: using the ordinary empirical quantile
---------------------------------------------------
The finite-sample conformal guarantee is

    ``Pr(y in C(x)) >= 1 - epsilon``

and it holds only if the threshold is the :math:`\lceil (n+1)(1-\epsilon)\rceil`-th
smallest calibration score. The ``+1`` is not a rounding preference. It accounts
for the test point itself joining the calibration set under exchangeability, and
dropping it -- taking the plain :math:`\lceil n(1-\epsilon)\rceil`-th score --
produces a threshold that is too small and a predictor that *under-covers*.

The error is largest exactly where it is least affordable: with few calibration
samples. At n = 20 and epsilon = 0.05 the correct index is 20 and the naive one
is 19, which is the difference between a guarantee and an approximation.

Mistake two: clamping when the index runs past the data
---------------------------------------------------------
When :math:`\lceil (n+1)(1-\epsilon)\rceil > n` there is no finite threshold that
can support the guarantee, and the honest answer is :math:`+\infty` -- the
prediction set is everything and the gate cannot reject anything yet. At
epsilon = 0.05 that is every n below 19.

The tempting implementation returns ``max(scores)`` instead, because an infinity
is awkward downstream. That single line converts "I do not have enough
calibration data to make this promise" into "here is a threshold", and the
resulting gate rejects proposals on the authority of a guarantee it does not
have. It is the exact failure RK-2 describes, and it is why this function
returns ``math.inf`` and the caller is required to deal with it.

The Trust Module handles that case by reporting a Trust Index of zero with the
sample count attached, so an analyst reading the evidence log can see that the
class was not yet calibrated rather than inferring that the situation was
untrustworthy.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from astra.kernel.enums import LayerId
from astra.kernel.errors import ContractViolationError

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["conformal_quantile", "empirical_cdf", "minimum_samples_for"]


def minimum_samples_for(epsilon: float) -> int:
    """Return the smallest calibration count that admits a finite threshold.

    Args:
        epsilon: The significance level.

    Returns:
        The smallest ``n`` for which ``ceil((n+1)(1-epsilon)) <= n``. Below this
        the conformal quantile is ``+inf`` and no proposal can be rejected on
        conformal grounds.

    Raises:
        ContractViolationError: If ``epsilon`` is outside ``(0, 1)``.
    """
    _require_epsilon(epsilon)
    # ceil((n+1)(1-e)) <= n  <=>  n >= (1-e)/e for the smallest integer n.
    return max(1, math.ceil((1.0 - epsilon) / epsilon))


def conformal_quantile(scores: Sequence[float], epsilon: float) -> float:
    r"""Return the conformal threshold for a set of calibration scores.

    Args:
        scores: The calibration non-conformity scores for one Mondrian class.
            Order is irrelevant; the function sorts internally.
        epsilon: The significance level. The guarantee produced is
            ``1 - epsilon`` coverage.

    Returns:
        The :math:`\lceil (n+1)(1-\epsilon)\rceil`-th smallest score, or
        ``math.inf`` when that index exceeds ``n``. An infinite threshold means
        the class has too little calibration data to support the guarantee at
        this significance level -- it is a real answer, not an error, and the
        caller must not substitute the largest observed score for it.

    Raises:
        ContractViolationError: If ``epsilon`` is outside ``(0, 1)``, or if any
            score is non-finite. A NaN would sort unpredictably and could land
            anywhere in the ordering, producing a plausible threshold from a
            corrupt sample.
    """
    _require_epsilon(epsilon)
    for index, score in enumerate(scores):
        if not math.isfinite(score):
            message = (
                f"calibration score at index {index} is {score}; a non-finite score sorts "
                f"unpredictably and would produce a plausible-looking threshold from a "
                f"corrupt sample"
            )
            raise ContractViolationError(
                message,
                layer=LayerId.L3_CONFORMAL_TRUST,
                context={"index": index, "score": str(score)},
            )

    count = len(scores)
    if count == 0:
        return math.inf

    # The +1 accounts for the test point joining the calibration set under
    # exchangeability. Dropping it under-covers.
    rank = math.ceil((count + 1) * (1.0 - epsilon))
    if rank > count:
        return math.inf
    return sorted(scores)[rank - 1]


def empirical_cdf(scores: Sequence[float], value: float) -> float:
    """Return the empirical CDF of a score set evaluated at a value.

    This is ``F_hat_k`` in ``TI = 1 - F_hat_k(alpha)``. The Trust Index is
    therefore the proportion of calibration scores at least as extreme as the
    current one: high when the situation resembles what was calibrated, low when
    it does not.

    Args:
        scores: The calibration scores for one Mondrian class.
        value: The score to evaluate at.

    Returns:
        The fraction of scores less than or equal to ``value``, in ``[0, 1]``.
        An empty set returns ``1.0``, which drives the Trust Index to zero --
        the correct posture for a class nothing is known about.

    Raises:
        ContractViolationError: If ``value`` is non-finite.
    """
    if not math.isfinite(value):
        message = (
            f"cannot evaluate the empirical CDF at {value}; a non-finite score would "
            f"produce a Trust Index that is neither high nor low but arbitrary"
        )
        raise ContractViolationError(
            message, layer=LayerId.L3_CONFORMAL_TRUST, context={"value": str(value)}
        )
    if not scores:
        return 1.0
    return sum(1 for score in scores if score <= value) / len(scores)


def _require_epsilon(epsilon: float) -> None:
    """Validate a significance level.

    Args:
        epsilon: The significance level.

    Raises:
        ContractViolationError: If it is not finite or not strictly inside
            ``(0, 1)``. At zero the guarantee demands an infinite threshold
            forever; at one it demands nothing at all.
    """
    if not math.isfinite(epsilon) or not (0.0 < epsilon < 1.0):
        message = (
            f"the significance level must lie strictly inside (0, 1), got {epsilon}; "
            f"at 0 the conformal threshold is infinite for every sample count and at 1 "
            f"the gate accepts everything"
        )
        raise ContractViolationError(
            message, layer=LayerId.L3_CONFORMAL_TRUST, context={"epsilon": str(epsilon)}
        )
