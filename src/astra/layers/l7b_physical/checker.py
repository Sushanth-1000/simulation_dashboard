"""L7b -- the physical gate, and why it is not the shield with extra steps.

The question this gate asks
--------------------------
Not *"is the vehicle outside its envelope?"* -- that is L7a's question, and L7a
answers it from the state alone. This gate asks *"can the vehicle actually do
what is being asked, in the time available?"*

The distinction is the whole reason both exist. A command can sit comfortably
inside every hard bound and still be physically impossible to execute, because
reaching it would require a step change in lateral acceleration that no tyre can
transmit. And a command can be perfectly executable and still be forbidden,
because the road is icy. Neither gate subsumes the other.

Both bounds are therefore *rate* limits, never magnitude limits. Adding a
magnitude bound here would duplicate L7a and quietly collapse two of the three
gates into one, which is precisely the failure the architecture is built to
avoid -- and it would do so invisibly, because both gates would still return
verdicts and the dashboard would still show three lit paths.

The two bounds
--------------
**1. Lateral jerk.** ``|a_prop - a_now| / dt <= jerk_max``

Tyres and suspension transfer force through deflection, which takes time. A
proposal demanding an instantaneous change in lateral acceleration is asking for
something the vehicle cannot deliver regardless of grip, speed or legality. This
bound fails when the proposer asks for the impossible.

**2. Model divergence.** ``|a_prop - a_twin| <= admissible_divergence``

The twin predicts the command the modelled physics expects. Where the proposal
implies a lateral acceleration far from the twin's, one of the two is wrong
about the vehicle. This is the term through which *twin drift* becomes this
gate's failure mode -- and having a distinct failure mode is what earns the gate
its place. L7a fails when the state estimate is wrong; L6 fails when
exchangeability is violated; L7b fails when the model has drifted beyond what
elastic weight consolidation could correct.

Why this is not the statistical gate either
--------------------------------------------
L6 computes ``|pi_prop - pi_hat| / sigma(x)`` and compares it to a conformal
quantile. The comparison here uses the same two commands and is still a
different test: it is in metres per second squared against a physical limit, not
in standard deviations against a learned threshold. L6 asks *"is this
statistically surprising?"*; L7b asks *"is this physically reachable?"* A command
can be one without being the other, which is exactly the case the adversarial
validation scenario is designed to produce.

Why the proposal is read here and not in L7a
---------------------------------------------
This gate does evaluate the proposed command -- it has to, because the question
is about a demanded change. L7a deliberately does not. That asymmetry is
deliberate rather than an inconsistency: the deterministic gate's authority
comes from depending on as little as possible, and a bound evaluated purely on
the state cannot be defeated by a malformed command.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Final

from astra.contracts.assurance import GateVerdict
from astra.kernel.enums import GateId, LayerId, Verdict
from astra.kernel.errors import SafetyPathError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from astra.config.schema import PhysicalGateSettings
    from astra.contracts.actuation import PredictedCommand, ProposedCommand
    from astra.contracts.estimation import FastStateEstimate
    from astra.kernel.identifiers import TickId
    from astra.kernel.units import Seconds

__all__ = ["REASON_CODES", "PhysicalAdmissibilityGate"]

REASON_NOMINAL: Final = "NOMINAL"
REASON_LATERAL_JERK: Final = "LATERAL_JERK_EXCEEDS_LIMIT"
REASON_MODEL_DIVERGENCE: Final = "PROPOSAL_DIVERGES_FROM_TWIN"
REASON_INPUT_NOT_FINITE: Final = "INPUT_NOT_FINITE"

REASON_CODES: Final[tuple[str, ...]] = (
    REASON_NOMINAL,
    REASON_LATERAL_JERK,
    REASON_MODEL_DIVERGENCE,
    REASON_INPUT_NOT_FINITE,
)
"""Every reason code this gate can emit. Part of the evidence schema."""

_ERROR_LAYER: Final = LayerId.L5_PINN_TWIN
"""The layer this gate's failures are attributed to in the evidence log.

There is no ``LayerId.L7B``. The pipeline has exactly nine numbered layers and
the architecture tests assert that count against
:data:`~astra.kernel.constants.ASTRA_LAYER_COUNT`, so inventing a tenth to name a
sub-gate would break the cardinality the numbering exists to fix.

L5 is the correct attribution rather than a convenient one: this gate's verdict
is a function of the twin's prediction, its distinctive failure mode *is* twin
drift, and :attr:`~astra.kernel.enums.GateId.PHYSICAL` is already documented as
belonging to "L5/L7b". A failure here is a statement about the model, and the
evidence log should say so.
"""


class PhysicalAdmissibilityGate:
    """L7b. Satisfies :class:`~astra.ports.pipeline.PhysicalAdmissibilityChecker`.

    Stateless, like the shield: it holds configuration, the control
    effectiveness of the platform and the tick period, and derives everything
    else from its arguments. A gate that accumulated state between ticks could
    be walked into a permissive mode by a crafted sequence.
    """

    __slots__ = ("_effectiveness", "_settings", "_tick_period")

    def __init__(
        self,
        *,
        settings: PhysicalGateSettings,
        control_effectiveness: Sequence[float],
        tick_period: Seconds,
    ) -> None:
        """Build the gate for one platform.

        Args:
            settings: The two rate bounds.
            control_effectiveness: Row mapping a command vector to the lateral
                acceleration it produces, in the actuation space's channel
                order. The same platform characterisation the twin is given, and
                configured for the same reason: it is a fact about one vehicle,
                and naming a channel here would put that vehicle inside the core
                (NFR5).
            tick_period: The control period, used to turn a demanded change in
                acceleration into a jerk.
        """
        self._settings = settings
        self._effectiveness = tuple(control_effectiveness)
        self._tick_period = float(tick_period)

    def evaluate(
        self,
        *,
        tick: TickId,
        proposal: ProposedCommand,
        prediction: PredictedCommand,
        state: FastStateEstimate,
    ) -> GateVerdict:
        """Judge whether the proposal is physically reachable from the state.

        Args:
            tick: The control tick.
            proposal: The untrusted proposed command.
            prediction: The twin's prediction for this tick.
            state: The current fast state estimate.

        Returns:
            A verdict tagged :attr:`~astra.kernel.enums.GateId.PHYSICAL`,
            carrying every computed quantity as evidence -- including on a PASS,
            so an analyst can read the margin the vehicle actually had.

        Raises:
            SafetyPathError: If any input is non-finite, or if the proposal and
                the prediction are vectors over different-sized spaces. Both
                fail closed. A NaN would defeat every comparison below rather
                than failing it, which reads as PASS.
        """
        proposed = proposal.command.values
        predicted = prediction.command.values
        self._require_matching_dimensions(tick, proposed, predicted)

        current = float(state.lateral_acceleration)
        self._require_finite(tick, (*proposed, *predicted, current))

        implied = self._implied_lateral_acceleration(proposed)
        expected = self._implied_lateral_acceleration(predicted)
        jerk = abs(implied - current) / self._tick_period
        divergence = abs(implied - expected)

        jerk_limit = self._settings.max_lateral_jerk
        divergence_limit = float(self._settings.admissible_divergence)

        evidence: tuple[tuple[str, float], ...] = (
            ("proposed_lateral_acceleration_mps2", implied),
            ("twin_lateral_acceleration_mps2", expected),
            ("current_lateral_acceleration_mps2", current),
            ("demanded_jerk_mps3", jerk),
            ("max_lateral_jerk_mps3", jerk_limit),
            ("model_divergence_mps2", divergence),
            ("admissible_divergence_mps2", divergence_limit),
        )

        # Jerk first: a proposal the vehicle physically cannot execute is a
        # worse fault than one that merely disagrees with the model, and the
        # reason code reported should name the more fundamental problem.
        if jerk > jerk_limit:
            return self._veto(tick, REASON_LATERAL_JERK, evidence)
        if divergence > divergence_limit:
            return self._veto(tick, REASON_MODEL_DIVERGENCE, evidence)
        return GateVerdict(
            tick=tick,
            gate=GateId.PHYSICAL,
            verdict=Verdict.PASS,
            reason_code=REASON_NOMINAL,
            evidence=evidence,
        )

    def _implied_lateral_acceleration(self, command: Sequence[float]) -> float:
        """Return the lateral acceleration a command vector produces.

        Args:
            command: The command vector, aligned to the actuation space order.

        Returns:
            ``B . command`` in metres per second squared.
        """
        return sum(gain * value for gain, value in zip(self._effectiveness, command, strict=True))

    @staticmethod
    def _veto(
        tick: TickId, reason_code: str, evidence: tuple[tuple[str, float], ...]
    ) -> GateVerdict:
        """Build a vetoing verdict.

        Args:
            tick: The control tick.
            reason_code: Which bound was breached.
            evidence: The computed quantities.

        Returns:
            The verdict.
        """
        return GateVerdict(
            tick=tick,
            gate=GateId.PHYSICAL,
            verdict=Verdict.VETO,
            reason_code=reason_code,
            evidence=evidence,
        )

    def _require_matching_dimensions(
        self, tick: TickId, proposed: Sequence[float], predicted: Sequence[float]
    ) -> None:
        """Refuse to compare commands from differently-shaped spaces.

        Args:
            tick: The control tick.
            proposed: The proposed command vector.
            predicted: The predicted command vector.

        Raises:
            SafetyPathError: If either vector's length differs from the
                configured control-effectiveness row. Comparing a command from
                one platform against a row from another produces a plausible
                number for the wrong vehicle, which is worse than an error.
        """
        expected = len(self._effectiveness)
        if len(proposed) != expected or len(predicted) != expected:
            message = (
                f"the physical gate is configured for a {expected}-channel platform but "
                f"was given a {len(proposed)}-channel proposal and a "
                f"{len(predicted)}-channel prediction; scoring across a dimension "
                f"mismatch would produce a plausible number for the wrong vehicle"
            )
            raise SafetyPathError(
                message,
                layer=_ERROR_LAYER,
                context={
                    "tick": tick.value,
                    "expected": expected,
                    "proposed": len(proposed),
                    "predicted": len(predicted),
                },
            )

    @staticmethod
    def _require_finite(tick: TickId, values: Sequence[float]) -> None:
        """Refuse to judge a non-finite input.

        Args:
            tick: The control tick.
            values: Every quantity the bounds will be computed from.

        Raises:
            SafetyPathError: If any value is NaN or infinite. ``nan > limit`` is
                ``False``, so a NaN would satisfy both bounds and be reported as
                a PASS -- a fail-open in a gate.
        """
        offenders = [index for index, value in enumerate(values) if not math.isfinite(value)]
        if offenders:
            message = (
                f"the physical gate cannot judge a non-finite input at indices "
                f"{offenders}; NaN defeats both bound comparisons rather than failing "
                f"them, so this tick fails closed rather than silently passing"
            )
            raise SafetyPathError(
                message,
                layer=_ERROR_LAYER,
                context={
                    "tick": tick.value,
                    "indices": offenders,
                    "reason": REASON_INPUT_NOT_FINITE,
                },
            )
