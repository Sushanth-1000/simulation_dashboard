"""L3 -- the conformal Trust Module.

What the Trust Index is, and what it is not
--------------------------------------------
``TI = 1 - F_hat_k(alpha)`` is the proportion of calibration scores for this
context class that are at least as extreme as the current one. High means the
situation resembles what was calibrated; low means it does not.

It is not a probability that the command is safe, and nothing in the system
treats it as one. By SI-4 it never reaches Core-B's verdict: it routes to L4 as
a monitoring signal and to L9 as a routing input. The reason is that a gate
consulting the Trust Index would make its verdict depend on a quantity derived
from the same calibration data the gate itself is scored against, and the two
would fail together.

Why the context classifier is injected
----------------------------------------
Deciding that the vehicle is in ``RAIN_NIGHT`` rather than ``HIGHWAY_CLEAR``
requires knowing about weather and lighting, which are not in the state vector
and which SI-1 forbids this layer from reading off the sensors. The classifier
is therefore supplied by the adapter, exactly as ``MeasurementExtractor`` is for
L2. The core reasons about "the class the classifier returned" and never about
what makes a class.

The uncalibrated case, and a contract that cannot express it
--------------------------------------------------------------
When a class holds too few scores, there is no finite conformal threshold and
:func:`~astra.layers.l3_trust.quantile.conformal_quantile` correctly returns
infinity. :class:`~astra.contracts.assurance.TrustAssessment` cannot carry that:
``class_conditional_quantile`` is validated with ``require_non_negative``, which
rejects a non-finite value.

The quantile is therefore reported as ``0.0`` in that case, which is the
fail-closed reading -- a threshold of zero rejects every non-zero score -- and
matches the project's standing posture that the absence of a verdict is a VETO.
The information is not lost: ``calibration_sample_count`` is recorded on every
assessment, and a reader can recover the distinction exactly by comparing it
against :func:`~astra.layers.l3_trust.quantile.minimum_samples_for`. The helper
:meth:`ConformalTrustModule.is_calibrated` does that comparison.

This is a real limitation of the contract rather than a property of the
mathematics, and it is recorded as such. An explicit ``is_calibrated`` field on
``TrustAssessment`` would say it directly, at the cost of an audit schema
version. Worth doing before the evidence pack is assembled, not before then.

In practice the uncalibrated case should not reach the gate during a run: L9
supplies the nearest available calibration table when no class matches, which is
what keeps the tunnel scenario moving rather than halting. The fail-closed
encoding here is the backstop for when it does.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from astra.contracts.assurance import TrustAssessment
from astra.kernel.enums import ContextClass, LayerId
from astra.kernel.errors import ConfigurationError
from astra.kernel.units import Probability
from astra.layers.l3_trust.mondrian import MondrianCalibration
from astra.layers.l3_trust.quantile import minimum_samples_for

if TYPE_CHECKING:
    from astra.contracts.estimation import FastStateEstimate, InnovationRecord
    from astra.kernel.identifiers import TickId

__all__ = ["ConformalTrustModule", "ContextClassifier"]


@runtime_checkable
class ContextClassifier(Protocol):
    """Maps a situation to its Mondrian class.

    Structural, and supplied by the adapter. Deciding that conditions are
    ``RAIN_NIGHT`` needs weather and lighting, which are not in the state vector
    and which SI-1 keeps out of this layer.
    """

    def classify(
        self, *, state: FastStateEstimate, innovation: InnovationRecord | None
    ) -> ContextClass:
        """Return the operational context class for this tick.

        Args:
            state: The current fast state estimate.
            innovation: The latest innovation record, if the filter has run.

        Returns:
            The class to condition on. ``UNCLASSIFIED`` when no certified class
            matches -- which is a legitimate answer, not a failure.
        """
        ...


class ConformalTrustModule:
    """L3. Satisfies :class:`~astra.ports.pipeline.TrustEstimator`.

    Holds the Mondrian calibration windows and the injected classifier. The hot
    path reads; feedback loop FB3 writes.
    """

    __slots__ = ("_calibration", "_classifier", "_epsilon", "_last_context")

    def __init__(
        self,
        *,
        classifier: ContextClassifier,
        calibration: MondrianCalibration,
        coverage_level: float,
    ) -> None:
        """Build the Trust Module.

        Args:
            classifier: Supplied by the adapter.
            calibration: The per-class calibration windows.
            coverage_level: ``1 - epsilon``, the coverage this module targets.

        Raises:
            ConfigurationError: If the coverage level is not strictly inside
                ``(0, 1)``. At 1 the significance level is zero, which makes
                every threshold infinite forever; at 0 the gate accepts
                everything.
        """
        if not math.isfinite(coverage_level) or not (0.0 < coverage_level < 1.0):
            message = (
                f"the coverage level must lie strictly inside (0, 1), got "
                f"{coverage_level}; at 1 every conformal threshold is infinite for "
                f"every sample count and at 0 the gate accepts everything"
            )
            raise ConfigurationError(
                message,
                layer=LayerId.L3_CONFORMAL_TRUST,
                context={"coverage_level": str(coverage_level)},
            )
        self._classifier = classifier
        self._calibration = calibration
        self._epsilon = 1.0 - coverage_level
        self._last_context: ContextClass = ContextClass.UNCLASSIFIED

    @property
    def epsilon(self) -> float:
        """Return the significance level this module targets."""
        return self._epsilon

    def is_calibrated(self, context: ContextClass) -> bool:
        """Return whether a class holds enough scores for a finite threshold.

        The distinction ``TrustAssessment`` cannot carry directly. A caller that
        needs to tell "uncalibrated" from "calibrated with a threshold of zero"
        asks here, or derives the same answer from the recorded sample count.

        Args:
            context: The class to check.

        Returns:
            ``True`` if the conformal quantile for this class is finite.
        """
        return self._calibration.sample_count(context) >= minimum_samples_for(self._epsilon)

    def assess(
        self,
        *,
        tick: TickId,
        state: FastStateEstimate,
        innovation: InnovationRecord | None,
    ) -> TrustAssessment:
        """Estimate how typical the current situation is for its context class.

        Args:
            tick: The control tick.
            state: The current fast state estimate.
            innovation: The latest innovation record, if the filter has run.

        Returns:
            The Trust Index with the class, quantile and sample count that
            produced it. An uncalibrated class yields a Trust Index of zero and
            a reported quantile of zero -- see the module docstring for why the
            second is the fail-closed encoding of an infinite threshold rather
            than a real threshold.
        """
        context = self._classifier.classify(state=state, innovation=innovation)
        self._last_context = context

        score = self._current_score(innovation)
        trust = 1.0 - self._calibration.cdf(context, score)
        quantile = self._calibration.quantile(context, self._epsilon)

        return TrustAssessment(
            tick=tick,
            trust_index=Probability(trust),
            context_class=context,
            # Infinity cannot be carried by the contract. Zero is the
            # fail-closed reading, and `calibration_sample_count` below is what
            # lets a reader tell the two apart.
            class_conditional_quantile=0.0 if math.isinf(quantile) else quantile,
            coverage_target=Probability(1.0 - self._epsilon),
            calibration_sample_count=self._calibration.sample_count(context),
        )

    def recalibrate(self, *, non_conformity_score: float, was_correct: bool) -> None:
        """Fold an executed outcome back into the calibration windows (FB3).

        Args:
            non_conformity_score: The realised score for the executed command.
            was_correct: Whether the outcome matched the prediction within the
                certified tolerance. Recorded by the caller in the evidence log;
                it does not gate the update, because a conformal calibration set
                must contain the scores that actually occurred. Filtering it to
                the outcomes that went well would bias the quantile downward and
                produce a guarantee about a distribution the vehicle does not
                drive in.
        """
        del was_correct  # see the docstring: filtering would bias the quantile
        if not math.isfinite(non_conformity_score) or non_conformity_score < 0.0:
            # The cold path must not take down a tick that has already been
            # decided. A corrupt score is dropped rather than admitted, because
            # admitting it would silently move every future threshold.
            return
        self._calibration.observe(self._last_context, non_conformity_score)

    @staticmethod
    def _current_score(innovation: InnovationRecord | None) -> float:
        """Return the non-conformity score for this tick.

        Before L6 exists, the physics-grounded signal available is the filter's
        innovation: the Mahalanobis distance between what the sensors said and
        what the model expected. It is the same quantity the covariate-shift
        detector consumes, and it is genuinely a measure of how unusual the
        present situation is.

        Args:
            innovation: The latest innovation record, if the filter has run.

        No finiteness guard here, deliberately.
        :class:`~astra.contracts.estimation.InnovationRecord` validates the
        distance at construction, so a non-finite one is unrepresentable rather
        than merely unlikely. Re-checking it would add a branch that no input
        can reach, which reads to the next person as though the case were
        possible and the contract unreliable.

        Args:
            innovation: The latest innovation record, if the filter has run.

        Returns:
            The Mahalanobis distance, or ``0.0`` before the first update. Zero
            is the least surprising score, which gives maximum trust -- correct
            for a tick where nothing has yet contradicted the model.
        """
        if innovation is None:
            return 0.0
        return float(innovation.mahalanobis_distance)
