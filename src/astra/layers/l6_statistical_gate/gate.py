"""L6 -- the statistical gate, and the direction the paper's wording gets wrong.

The score
---------
    ``alpha = |pi_prop - pi_hat| / sigma(x)``   with   ``sigma(x) = sqrt(P_f[control dim])``

The numerator is how far the untrusted proposal departs from what the twin
expects. The denominator is the filter's own uncertainty about the dimension
that departure acts on, so the same absolute departure is scored as ordinary
when the filter is unsure and as anomalous when it is confident. That coupling
between state uncertainty and the acceptance band is the second of the paper's
listed contributions, and it is one line of code.

Which way "tighten epsilon" goes
---------------------------------
This is the trap in this module and it is worth stating plainly, because the
natural reading of the source material implements it backwards.

The conformal acceptance region is ``{score <= q_{1-epsilon}}``. A *smaller*
epsilon means higher coverage, a higher quantile, and therefore a **larger**
acceptance region. So reducing epsilon makes the gate more permissive.

The papers say the gate "tightens epsilon" under covariate shift and that it
"gets stricter immediately". Those two statements are only consistent if
"tighten" means *raise* epsilon: less coverage, a lower quantile, a smaller
acceptance region, a stricter gate.

Implementing the phrase literally -- reducing epsilon on detected shift -- would
make the gate more permissive at exactly the moment the world stopped matching
the calibration data. Nothing would raise. Coverage would still be reported as
achieved, because it would be: the guarantee would hold at the new, weaker
level. This module therefore multiplies epsilon *upward* on shift, and the
setting is named for what it does rather than for what the paper called it.

Why this gate can fail when the others do not
----------------------------------------------
Conformal coverage assumes exchangeability between calibration and runtime data.
An adversarial perturbation violates that by construction -- it is chosen to be
unlike the calibration set. So this gate is the one that a deliberate attack can
defeat, and it is why there is more than one gate. Its counterpart property is
the one the validation plan is built around: an FGSM perturbation that is
kinematically plausible and inside every hard bound is invisible to L7a and L7b
and visible only here.

The uncalibrated case
---------------------
A class with too few scores has no finite conformal threshold. This gate vetoes
in that case rather than passing, with its own reason code, because a gate that
cannot make a statistical claim must not report that the proposal satisfied one.
In a running system L9 substitutes the nearest available calibration table
before this is reached, which is what keeps the tunnel scenario moving.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Final

from astra.contracts.assurance import GateVerdict
from astra.kernel.enums import GateId, LayerId, Verdict
from astra.kernel.errors import SafetyPathError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from astra.contracts.actuation import PredictedCommand, ProposedCommand
    from astra.contracts.estimation import FastStateEstimate
    from astra.kernel.enums import ContextClass
    from astra.kernel.identifiers import TickId
    from astra.layers.l3_trust.mondrian import MondrianCalibration
    from astra.layers.l3_trust.trust import ContextClassifier
    from astra.layers.l6_statistical_gate.mmd import MmdShiftDetector

__all__ = ["REASON_CODES", "IcpStatisticalGate", "non_conformity_score"]

REASON_NOMINAL: Final = "NOMINAL"
REASON_SCORE_ABOVE_QUANTILE: Final = "SCORE_EXCEEDS_CONFORMAL_QUANTILE"
REASON_UNCALIBRATED: Final = "CONTEXT_NOT_CALIBRATED"
REASON_INPUT_NOT_FINITE: Final = "INPUT_NOT_FINITE"

REASON_CODES: Final[tuple[str, ...]] = (
    REASON_NOMINAL,
    REASON_SCORE_ABOVE_QUANTILE,
    REASON_UNCALIBRATED,
    REASON_INPUT_NOT_FINITE,
)
"""Every reason code this gate can emit. Part of the evidence schema."""

CONTROL_DIMENSION: Final = "lateral_acceleration"
"""The state dimension whose variance normalises the score.

Named rather than indexed. ``FastStateEstimate.variance_of`` resolves it from
the canonical field order, so reordering the state vector cannot silently
repoint the normalisation term at a different physical quantity -- which would
still produce plausible numbers.
"""

_MINIMUM_SIGMA: Final = 1e-6
"""Floor on the normalisation term.

A variance at or below this means the filter claims near-perfect certainty about
the control dimension. Dividing by it produces an enormous score -- arithmetically
a VETO, which is the right answer, but by way of an overflow rather than a
decision. The floor makes the veto explicit and keeps the number in the evidence
log finite and readable.
"""


def non_conformity_score(
    *, proposed: Sequence[float], predicted: Sequence[float], variance: float
) -> tuple[float, float, float]:
    """Return ``(score, departure, sigma)`` for one proposal against one prediction.

    Extracted from :meth:`IcpStatisticalGate.evaluate` so that anything wanting
    to know what the gate *would* have said computes it with the gate's own
    arithmetic rather than a copy. The specific thing that motivated it was
    measuring FB2 in shadow: a shadow score computed by a reimplementation would
    be evidence about the reimplementation.

    Args:
        proposed: The untrusted proposal's command vector.
        predicted: The twin's prediction.
        variance: ``P_f`` at the control dimension.

    Returns:
        The score, the raw Euclidean departure, and the normalisation term. The
        last two are returned because they are what makes a score readable in
        the evidence log -- a score alone cannot be told apart from a large
        departure and a large sigma.
    """
    departure = math.dist(proposed, predicted)
    sigma = math.sqrt(max(variance, _MINIMUM_SIGMA))
    return departure / sigma, departure, sigma


class IcpStatisticalGate:
    """L6. Satisfies :class:`~astra.ports.pipeline.StatisticalGate`.

    Holds calibration, a classifier, and the shift detector. It deliberately
    does *not* hold or accept a
    :class:`~astra.contracts.assurance.TrustAssessment`: SI-4 forbids the Trust
    Index from participating in Core-B's verdict, and the surest way to honour
    that is to have no parameter through which it could arrive. The calibration
    *scores* are shared with L3 because they are data; the Trust Index derived
    from them is not.
    """

    __slots__ = ("_calibration", "_classifier", "_detector", "_epsilon", "_shift_multiplier")

    def __init__(
        self,
        *,
        calibration: MondrianCalibration,
        classifier: ContextClassifier,
        detector: MmdShiftDetector,
        significance_epsilon: float,
        shift_epsilon_multiplier: float,
    ) -> None:
        """Build the gate.

        Args:
            calibration: The Mondrian calibration windows.
            classifier: Supplied by the adapter, as L3's is.
            detector: The covariate-shift detector.
            significance_epsilon: The nominal significance level.
            shift_epsilon_multiplier: Factor applied to epsilon when shift is
                declared. Must be at least 1: see the module docstring for why
                a value below 1 would loosen the gate under shift rather than
                tightening it.

        Raises:
            SafetyPathError: If the multiplier is below 1, or if either value is
                non-finite, or if the resulting epsilon would leave ``(0, 1)``.
        """
        if not math.isfinite(shift_epsilon_multiplier) or shift_epsilon_multiplier < 1.0:
            message = (
                f"the shift epsilon multiplier must be at least 1, got "
                f"{shift_epsilon_multiplier}; a value below 1 raises the conformal "
                f"quantile and widens the acceptance region, making the gate more "
                f"permissive at exactly the moment covariate shift was detected"
            )
            raise SafetyPathError(
                message,
                layer=LayerId.L6_MPC_ICP_GATE,
                context={"multiplier": str(shift_epsilon_multiplier)},
            )
        if not math.isfinite(significance_epsilon) or not (0.0 < significance_epsilon < 1.0):
            message = (
                f"the significance level must lie strictly inside (0, 1), got "
                f"{significance_epsilon}"
            )
            raise SafetyPathError(
                message,
                layer=LayerId.L6_MPC_ICP_GATE,
                context={"epsilon": str(significance_epsilon)},
            )
        self._calibration = calibration
        self._classifier = classifier
        self._detector = detector
        self._epsilon = significance_epsilon
        self._shift_multiplier = shift_epsilon_multiplier

    def effective_epsilon(self) -> float:
        """Return the significance level in force for this tick.

        Returns:
            The nominal epsilon, or the shifted one when the detector has fired.
            Capped strictly below 1: an epsilon of 1 would set the quantile to
            the smallest observed score and veto essentially everything, which
            is a fail-safe posture the FSM should reach by counting vetoes
            rather than one the gate should adopt unilaterally.
        """
        if not self._detector.has_shifted():
            return self._epsilon
        return min(self._epsilon * self._shift_multiplier, 0.999)

    def observe_innovation(self, magnitude: float) -> None:
        """Feed the shift detector one innovation magnitude.

        Args:
            magnitude: The Mahalanobis distance for this tick.
        """
        self._detector.observe(magnitude)

    def quantile_for(self, context: ContextClass) -> float:
        """Return the conformal quantile this gate would threshold against.

        Exposed so that anything measuring what the gate *would* do reads the
        gate's own number instead of recomputing it from the calibration and the
        epsilon -- the same reasoning as
        :func:`non_conformity_score`. ``math.inf`` for a class with too few
        samples to certify, which is a VETO rather than an error.

        Args:
            context: The Mondrian class.

        Returns:
            The quantile, possibly infinite.
        """
        return self._calibration.quantile(context, self.effective_epsilon())

    def recalibrate(self, *, score: float, context: ContextClass) -> None:
        """Fold a realised non-conformity score into this gate's own window.

        Feedback loop FB3, L6's half, and the one the roadmap's phrase "online
        Mondrian requantilisation" most naturally describes: the acceptance
        threshold tracks the scores the *deployed* proposer actually produces
        rather than the ones whatever proposer generated the corpus produced.
        E-20 measured that gap at 1.18 against 2.43 for HIGHWAY_CLEAR, so it is
        not a small correction.

        **Unwired, deliberately.** Requantilising on a self-generated
        distribution is self-referential by construction: the threshold follows
        the proposer, so a proposer that degrades slowly takes the threshold with
        it and is never anomalous relative to itself. Whether that matters at
        this operating point is measured in shadow before this is given
        authority, exactly as FB2 was -- and FB2 is why that is now the rule.

        Args:
            score: The realised non-conformity score for the executed tick.
            context: The Mondrian class it was observed in.
        """
        if not math.isfinite(score) or score < 0.0:
            # The cold path must not take down a tick already decided, and a
            # corrupt value admitted here would silently move every future
            # threshold.
            return
        self._calibration.observe(context, score)

    def evaluate(
        self,
        *,
        tick: TickId,
        proposal: ProposedCommand,
        prediction: PredictedCommand,
        state: FastStateEstimate,
    ) -> GateVerdict:
        """Score the proposal against the class-conditional conformal band.

        Args:
            tick: The control tick.
            proposal: The untrusted proposed command.
            prediction: The twin's prediction.
            state: The fast estimate, supplying ``sigma(x)`` from ``P_f``.

        Returns:
            A verdict tagged :attr:`~astra.kernel.enums.GateId.STATISTICAL`.

        Raises:
            SafetyPathError: If the two commands are vectors over
                different-sized spaces, or if any input is non-finite. NaN
                defeats the comparison against the quantile rather than failing
                it, which reads as a PASS.
        """
        proposed = proposal.command.values
        predicted = prediction.command.values
        if len(proposed) != len(predicted):
            message = (
                f"the proposal has {len(proposed)} channels and the prediction has "
                f"{len(predicted)}; a departure measured across a dimension mismatch "
                f"is a number about no particular vehicle"
            )
            raise SafetyPathError(
                message,
                layer=LayerId.L6_MPC_ICP_GATE,
                context={
                    "tick": tick.value,
                    "proposed": len(proposed),
                    "predicted": len(predicted),
                },
            )

        variance = state.variance_of(CONTROL_DIMENSION)
        self._require_finite(tick, (*proposed, *predicted, variance))

        score, departure, sigma = non_conformity_score(
            proposed=proposed, predicted=predicted, variance=variance
        )

        context = self._classifier.classify(state=state, innovation=None)
        epsilon = self.effective_epsilon()
        quantile = self._calibration.quantile(context, epsilon)
        discrepancy = self._detector.discrepancy()

        evidence: tuple[tuple[str, float], ...] = (
            ("non_conformity_score", score),
            ("departure", departure),
            ("sigma", sigma),
            ("conformal_quantile", quantile if math.isfinite(quantile) else -1.0),
            ("effective_epsilon", epsilon),
            ("mmd_discrepancy", discrepancy),
            ("calibration_samples", float(self._calibration.sample_count(context))),
        )

        if math.isinf(quantile):
            # No finite threshold exists for this class. A gate that cannot make
            # a statistical claim must not report that the proposal satisfied
            # one -- and, by ADR-0016, must not report that it violated one
            # either. Both are claims about a distribution this gate has no
            # sample of. It abstains, and the aggregate falls to the two gates
            # whose bounds do not depend on calibration; if neither of those
            # judged either, `Verdict.merge` fails closed exactly as it does for
            # an empty verdict set.
            #
            # The quantile is logged as -1 above because the evidence schema
            # carries floats and an infinity would not round-trip. The
            # calibration sample count is in the evidence too, which is what
            # makes this abstention checkable after the fact rather than taken
            # on trust.
            return GateVerdict(
                tick=tick,
                gate=GateId.STATISTICAL,
                verdict=Verdict.ABSTAIN,
                reason_code=REASON_UNCALIBRATED,
                evidence=evidence,
            )
        if score > quantile:
            return self._veto(tick, REASON_SCORE_ABOVE_QUANTILE, evidence)
        return GateVerdict(
            tick=tick,
            gate=GateId.STATISTICAL,
            verdict=Verdict.PASS,
            reason_code=REASON_NOMINAL,
            evidence=evidence,
        )

    @staticmethod
    def _veto(
        tick: TickId, reason_code: str, evidence: tuple[tuple[str, float], ...]
    ) -> GateVerdict:
        """Build a vetoing verdict.

        Args:
            tick: The control tick.
            reason_code: Why the gate rejected the proposal.
            evidence: The computed quantities.

        Returns:
            The verdict.
        """
        return GateVerdict(
            tick=tick,
            gate=GateId.STATISTICAL,
            verdict=Verdict.VETO,
            reason_code=reason_code,
            evidence=evidence,
        )

    @staticmethod
    def _require_finite(tick: TickId, values: tuple[float, ...]) -> None:
        """Refuse to score a non-finite input.

        Args:
            tick: The control tick.
            values: Every quantity the score is computed from.

        Raises:
            SafetyPathError: If any value is NaN or infinite.
        """
        offenders = [index for index, value in enumerate(values) if not math.isfinite(value)]
        if offenders:
            message = (
                f"the statistical gate cannot score a non-finite input at indices "
                f"{offenders}; NaN defeats the comparison against the conformal quantile "
                f"rather than failing it, so this tick fails closed"
            )
            raise SafetyPathError(
                message,
                layer=LayerId.L6_MPC_ICP_GATE,
                context={
                    "tick": tick.value,
                    "indices": offenders,
                    "reason": REASON_INPUT_NOT_FINITE,
                },
            )
