"""L9's cold path: finding a calibration profile, and refusing to.

Where this runs
---------------
The cold path, on a millisecond-to-second timescale, never inside a tick. SI-8
depends on that separation: the Mahalanobis search below is O(profiles) and the
hot path must not wait for it. Nothing in this module is called by
:meth:`~astra.ports.pipeline.CalibrationArbiter.issue`.

The order of operations is the safety argument
------------------------------------------------
Distance, then **gates**, then score. Not distance-then-score-then-gates, which
would produce the same answer in the common case and a much worse one in the
case that matters.

A profile with an expired certificate, or certified for a different platform, or
with a documented critical failure in the field, is not a *low-scoring*
candidate. It is not a candidate. Scoring it first and hoping the weights push
it down means a sufficiently close centroid can outvote an expired signature,
and the arithmetic that lets that happen is invisible in the result: the chosen
profile just looks like the nearest one.

So the gates are applied as filters before any score exists, and
:func:`~astra.contracts.governance.is_candidate_admissible` applies validity as
a second hard conjunction afterwards. Two independent chances to refuse, neither
of which a weight can overrule.

Why similarity is Mahalanobis and not Euclidean
------------------------------------------------
The five RCS components are not comparable quantities. Visibility and sensor
reliability move over different ranges and with different natural spread, and a
Euclidean distance would let whichever component happens to vary most dominate
the match. Each profile carries its own certified covariance, so the distance is
measured in units of that profile's own observed variation: "how unusual is this
situation *for this profile*" rather than "how far away is it in an arbitrary
coordinate system".

The distance is computed through the covariance's Cholesky factor rather than by
inverting it. Inverting a near-singular covariance produces enormous finite
numbers rather than an error, and a profile whose covariance has collapsed would
then appear to match everything.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from astra.contracts.governance import is_candidate_admissible
from astra.kernel.enums import LayerId
from astra.kernel.errors import SafetyPathError

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from astra.contracts.governance import CalibrationProfile, RuntimeContextSignature

__all__ = [
    "ScoredCandidate",
    "SearchWeights",
    "mahalanobis_distance",
    "rejects",
    "score_candidates",
]

_UNIT_SIMILARITY_SCALE: Final = 1.0
"""Distance at which similarity has fallen to one half.

Turns an unbounded distance into a bounded similarity through
``sim = 1 / (1 + d)``. A bounded similarity is what lets the weighted sum in
``T(c)`` mean anything: an unbounded term would let one very close profile
dominate every other consideration including field history.
"""


@dataclass(frozen=True, slots=True)
class SearchWeights:
    """The four weights of ``T(c) = w1*sim + w2*val + w3*hist - w4*risk``.

    Fixed at certification time, per the paper. They are a frozen record rather
    than four loose floats so that a call site cannot silently pass them in the
    wrong order -- an error that would still produce a plausible ranking.

    Attributes:
        similarity: ``w1``, on the inverse-normalised Mahalanobis distance.
        validation: ``w2``, on the fraction of the certification suite passed.
        history: ``w3``, on the field track record.
        risk: ``w4``, subtracted, on the cost of transitioning to this profile.
    """

    similarity: float
    validation: float
    history: float
    risk: float


@dataclass(frozen=True, slots=True)
class ScoredCandidate:
    """One profile that passed every mandatory gate, with its score.

    Attributes:
        profile: The candidate profile.
        distance: Mahalanobis distance from the current signature.
        similarity: The bounded similarity derived from that distance.
        trust_score: ``T(c)``.
        is_valid: ``val(c) == 1``, the hard validity conjunct.
    """

    profile: CalibrationProfile
    distance: float
    similarity: float
    trust_score: float
    is_valid: bool

    def is_admissible(self, threshold: float) -> bool:
        """Return whether this candidate may be committed.

        Args:
            threshold: The admissibility threshold ``tau``.

        Returns:
            ``True`` only if valid *and* scoring at or above the threshold.
        """
        return is_candidate_admissible(
            trust_score=self.trust_score, threshold=threshold, is_valid=self.is_valid
        )


def mahalanobis_distance(
    signature: Sequence[float], centroid: Sequence[float], covariance: object
) -> float:
    """Return the Mahalanobis distance from a signature to a profile's centroid.

    Computed by forward substitution through the covariance's Cholesky factor.
    Inverting the covariance instead would turn a collapsed one into enormous
    finite numbers rather than a refusal, and a profile whose covariance has
    collapsed would then appear to match everything.

    Args:
        signature: The current RCS as a bare vector.
        centroid: The profile's certified centroid.
        covariance: The profile's certified covariance. Typed loosely to keep
            this function usable from the contracts' own tests without a
            circular import; it must expose ``cholesky_factor`` and
            ``dimension``.

    Returns:
        The distance, always non-negative.

    Raises:
        SafetyPathError: If the dimensions disagree, or if the covariance is not
            positive definite. The second is not a numerical inconvenience: a
            covariance that admits no Cholesky factor does not describe a
            probability distribution, so any distance derived from it would be a
            plausible number about nothing.
    """
    if len(signature) != len(centroid):
        message = (
            f"the signature has {len(signature)} components and the centroid has "
            f"{len(centroid)}; a distance across a dimension mismatch is a number "
            f"about no particular context"
        )
        raise SafetyPathError(
            message,
            layer=LayerId.L9_RCM,
            context={"signature": len(signature), "centroid": len(centroid)},
        )

    factor = covariance.cholesky_factor()  # type: ignore[attr-defined]
    if factor is None:
        message = (
            "the profile's covariance is not positive definite, so it admits no "
            "Cholesky factor and describes no probability distribution; a distance "
            "computed from it would be a plausible number about nothing"
        )
        raise SafetyPathError(message, layer=LayerId.L9_RCM)

    delta = [float(a) - float(b) for a, b in zip(signature, centroid, strict=True)]
    # Forward substitution through the packed lower triangle: the entry at row
    # `i`, column `j <= i` lives at index i*(i+1)//2 + j.
    solved: list[float] = []
    for row in range(len(delta)):
        total = delta[row]
        for column in range(row):
            total -= factor[row * (row + 1) // 2 + column] * solved[column]
        diagonal = factor[row * (row + 1) // 2 + row]
        solved.append(total / diagonal)
    return math.sqrt(sum(value * value for value in solved))


def rejects(profile: CalibrationProfile, *, platform: str, now: datetime) -> str | None:
    """Return why a profile fails a mandatory gate, or ``None`` if it passes.

    The three gates the paper names, applied as filters before any score is
    computed. Each is a veto rather than a penalty: none of them can be
    outweighed by a close centroid.

    Args:
        profile: The candidate.
        platform: The platform identifier the running system is certified for.
        now: The current time, injected rather than read, so that expiry is
            testable and replayable.

    Returns:
        A stable reason string for the evidence log, or ``None`` when the
        profile is eligible to be scored.
    """
    if profile.expires_at <= now:
        return "EXPIRED_SIGNATURE"
    if profile.platform != platform:
        return "PLATFORM_MISMATCH"
    if profile.field_history.has_critical_failure_history:
        return "CRITICAL_FAILURE_HISTORY"
    return None


def score_candidates(
    *,
    signature: RuntimeContextSignature,
    profiles: Sequence[CalibrationProfile],
    weights: SearchWeights,
    platform: str,
    now: datetime,
    active_profile_context: object = None,
) -> tuple[tuple[ScoredCandidate, ...], tuple[tuple[str, str], ...]]:
    """Search the knowledge base and score every eligible profile.

    Args:
        signature: The current runtime context signature.
        profiles: The knowledge base.
        weights: The four certified weights.
        platform: The platform the running system is certified for.
        now: The current time, for the expiry gate.
        active_profile_context: The context class of the currently active
            profile, if any. Switching between classes costs more than staying
            within one, and that cost is the ``risk`` term.

    Returns:
        ``(candidates, rejections)``. Candidates are sorted best-first by
        ``T(c)``. Rejections pair each rejected profile's identifier with the
        gate it failed, so the evidence log records *why* the knowledge base
        came up empty rather than only that it did -- which is the difference
        between a diagnosable tunnel scenario and a mysterious one.
    """
    vector = signature.as_vector()
    candidates: list[ScoredCandidate] = []
    rejections: list[tuple[str, str]] = []

    for profile in profiles:
        reason = rejects(profile, platform=platform, now=now)
        if reason is not None:
            rejections.append((str(profile.profile_id), reason))
            continue

        distance = mahalanobis_distance(vector, profile.centroid, profile.covariance)
        similarity = _UNIT_SIMILARITY_SCALE / (_UNIT_SIMILARITY_SCALE + distance)
        validation = float(profile.validation_fraction)
        history = _history_score(profile)
        risk = 0.0 if profile.context_class is active_profile_context else 1.0

        trust_score = (
            weights.similarity * similarity
            + weights.validation * validation
            + weights.history * history
            - weights.risk * risk
        )
        candidates.append(
            ScoredCandidate(
                profile=profile,
                distance=distance,
                similarity=similarity,
                trust_score=trust_score,
                # val(c) is the profile's binary certification verdict, not the
                # fraction of its corpus held out for validation. Reading the
                # fraction here instead made every correctly-certified profile
                # -- one holding out a sensible 20% -- permanently inadmissible,
                # so the knowledge base could never return a candidate and
                # bounded safe exploration engaged in every context.
                #
                # The hard-conjunct reasoning still stands: a profile that
                # passed 99% of its suite is not 99% admissible.
                is_valid=profile.validation_passed,
            )
        )

    candidates.sort(key=lambda candidate: candidate.trust_score, reverse=True)
    return tuple(candidates), tuple(rejections)


def _history_score(profile: CalibrationProfile) -> float:
    """Return a bounded field-track-record term for ``T(c)``.

    A profile with no deployments scores zero rather than one. An unproven
    profile is not a good one, and defaulting an unknown to its best possible
    value is how an unvalidated candidate wins a ranking.

    Args:
        profile: The candidate.

    Returns:
        A value in ``[0, 1]`` rising with deployments and saturating, so that a
        long history cannot dominate similarity and validity.
    """
    deployments = profile.field_history.deployments
    if deployments <= 0:
        return 0.0
    return deployments / (deployments + 10.0)
