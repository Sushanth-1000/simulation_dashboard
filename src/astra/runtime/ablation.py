"""Switching a gate off for a study, without ever making a gate optional.

The problem this solves
------------------------
The ablation study (P3.4) has to run the pipeline with L6, L7a and L7b disabled
in turn and re-measure. All three are **required constructor parameters** of
:class:`~astra.runtime.pipeline.GovernancePipeline`, and that requirement is
load-bearing rather than incidental: a pipeline that could be constructed
without a statistical gate is the single most dangerous defect this codebase
could carry, because it would fail *silently and in the flattering direction*.
Every audit row would still be written. Every verdict would still read
``PASS``. Nothing would record that the gate which accepted was absent.

That is the exact shape of OD-2 — a fail-safe speed cap recorded on every capped
tick that reached no actuator — and of OD-7, and this project has now been
bitten three times by mechanisms that fail by making the evidence look better.

The decision, from ADR-0021
-----------------------------
**An ablation neutralises a gate. It never removes one.**

The parameters stay required, and an ablated run supplies a *transparent*
gate: a subtype that runs, is evaluated, emits a verdict, and appears in the
audit log exactly as its parent would — but cannot block. Because they are
subtypes, the declared parameter type is satisfied without being widened.
**There is no ``| None`` anywhere, and a pipeline with no gate stays
unconstructible rather than merely discouraged.**

That is the same move SI-5 already makes for the one-way core channel, where
the wrong direction is a type error rather than a convention. This project's
standing preference is the type system wherever the type system will do the
work, and here it will.

What a transparent gate is not
--------------------------------
It is **not** a gate that is skipped. It runs, it costs the same tick budget,
and it writes a verdict carrying :data:`ABLATED_REASON_CODE`, so the evidence
from an ablated run says on every row that the gate was present and disarmed.
An ablation therefore measures a gate's **authority**, not its presence.

The consequence, stated because it is a real limitation: this cannot measure
what a layer *costs* in compute. ``benchmarks/latency.py`` already times each
stage individually against its own budget (E-10), which is the better
instrument for that question anyway — subtracting two whole-pipeline latencies
to infer one stage's cost is a difference of two noisy numbers, while the
benchmark measures the stage directly. The ablation answers *what does this
gate catch*; the latency benchmark answers *what does it cost*. Neither was
ever the right tool for the other's question.

Three guards, weakest last
----------------------------
1. **The required parameter is never relaxed.** Structural, and the only one of
   the three that cannot be circumvented by a mistake somewhere else.
2. **The profile is stamped into every** :class:`~astra.contracts.audit.DecisionRecord`.
   A run measured under an ablation is self-identifying in its own evidence,
   permanently and per tick, so it can never later be mistaken for a governed
   run. That failure would turn a certification artefact into a description of
   a system that was not running.
3. **Any non-empty profile is refused outside the measurement environments.**
   ``development`` and ``simulation`` only -- never ``certification``.
   Defence in depth, and deliberately the weakest of the three: it is a
   runtime check on a construction-time property.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, ClassVar, override

from astra.contracts.assurance import GateVerdict
from astra.kernel.enums import GateId, Verdict
from astra.kernel.errors import ConfigurationError
from astra.layers.l6_statistical_gate.gate import IcpStatisticalGate
from astra.layers.l7_shield.shield import HardSafetyShield
from astra.layers.l7b_physical.checker import PhysicalAdmissibilityGate

if TYPE_CHECKING:
    from astra.contracts.actuation import PredictedCommand, ProposedCommand
    from astra.contracts.estimation import FastStateEstimate, SlowStateEstimate
    from astra.kernel.identifiers import TickId

__all__ = [
    "ABLATED_REASON_CODE",
    "ABLATION_ENVIRONMENTS",
    "AblationProfile",
    "TransparentPhysicalGate",
    "TransparentShield",
    "TransparentStatisticalGate",
    "require_ablation_is_permitted",
]

ABLATED_REASON_CODE = "GATE_ABLATED_FOR_STUDY"
"""The reason code every transparent gate returns.

Distinct from any reason a real gate can produce, and greppable. A verdict
carrying this code is a statement that the gate ran and was disarmed -- never
that it looked and found nothing.
"""

ABLATION_ENVIRONMENTS = frozenset({"development", "simulation"})
"""The environments in which a non-empty profile may be assembled.

**This admitted ``development`` alone until the study was first run**, and the
correction is worth recording rather than quietly making. Forcing the ablation
into ``development`` would have measured it at that environment's deliberately
twitchy operating point -- OOD thresholds of 3/6/10 against simulation's
10/30/100 -- so every ablated run would have differed from its control in the
disarmed gate *and* in a tenfold tighter escalation threshold. Two variables,
one measurement, and no way to attribute the outcome to either.

That is the confound C-0 in the credibility matrix already records once, and a
guard that forces it is a worse guard than one that admits the environment
measurements are actually taken in.

``certification`` is not here and must not be added. The point of the rule is
that an ablated pipeline never reaches a context whose evidence is offered as
an assurance argument.
"""


@dataclass(frozen=True, slots=True)
class AblationProfile:
    """Which layers are disarmed for a study.

    Attributes:
        statistical_gate: Disarm L6, the ICP statistical gate.
        physical_gate: Disarm L7b, physical admissibility.
        shield: Disarm L7a, the hard safety shield.

    Note:
        FB2 and FB3 are deliberately absent. Neither has ever been wired, so
        "FB2 off" *is* the shipped configuration and ablating it would measure
        nothing. The comparison those rows want is against FB2 and FB3 **on**,
        which was never available and which the shadow harness measured instead
        -- a stronger result, because it changed no verdict (E-39, E-40).
    """

    statistical_gate: bool = False
    physical_gate: bool = False
    shield: bool = False

    NONE: ClassVar[AblationProfile]
    """The profile of a governed run. The default everywhere."""

    @property
    def is_empty(self) -> bool:
        """Return whether nothing is disarmed."""
        return not (self.statistical_gate or self.physical_gate or self.shield)

    @property
    def disabled(self) -> tuple[str, ...]:
        """Return the disarmed layers, in a stable order."""
        return tuple(
            name
            for name, off in (
                ("statistical_gate", self.statistical_gate),
                ("physical_gate", self.physical_gate),
                ("shield", self.shield),
            )
            if off
        )

    def render(self) -> str:
        """Return the stable string stamped into every decision record.

        ``"NONE"`` for a governed run, so the field is never empty and a reader
        can tell "not ablated" from "field missing".

        Returns:
            ``"NONE"``, or the disarmed layer names joined by ``+``.
        """
        return "+".join(self.disabled) if self.disabled else "NONE"

    def without(self, layer: str) -> AblationProfile:
        """Return this profile with one more layer disarmed.

        Args:
            layer: One of ``statistical_gate``, ``physical_gate``, ``shield``.

        Returns:
            The new profile.

        Raises:
            ValueError: If the layer is not one this profile can disarm.
        """
        if layer not in {"statistical_gate", "physical_gate", "shield"}:
            message = f"{layer!r} is not an ablatable layer"
            raise ValueError(message)
        return replace(self, **{layer: True})


AblationProfile.NONE = AblationProfile()


def require_ablation_is_permitted(profile: AblationProfile, *, environment: str) -> None:
    """Refuse a non-empty profile outside the development environment.

    The third and weakest of ADR-0021's guards -- a runtime check on a
    construction-time property. It exists so that a configuration mistake is
    loud, not because the guarantee rests on it: the guarantee is that the gate
    parameters were never made optional in the first place.

    Args:
        profile: The requested ablation.
        environment: The resolved configuration environment.

    Raises:
        ConfigurationError: If anything is disarmed outside
            :data:`ABLATION_ENVIRONMENTS`.
    """
    if profile.is_empty or environment in ABLATION_ENVIRONMENTS:
        return
    permitted = ", ".join(sorted(ABLATION_ENVIRONMENTS))
    message = (
        f"refusing to disarm {profile.render()} in the {environment!r} environment; "
        f"ablation is permitted only in: {permitted}"
    )
    raise ConfigurationError(message, context={"ablation": profile.render()})


def _ablated(tick: TickId, gate: GateId) -> GateVerdict:
    """Return the PASS verdict a disarmed gate emits.

    Args:
        tick: The control tick.
        gate: Which gate was disarmed.

    Returns:
        A passing verdict carrying :data:`ABLATED_REASON_CODE`.
    """
    return GateVerdict(tick=tick, gate=gate, verdict=Verdict.PASS, reason_code=ABLATED_REASON_CODE)


class TransparentStatisticalGate(IcpStatisticalGate):
    """L6, present and disarmed.

    A subtype rather than a replacement, so the pipeline's declared parameter
    type is satisfied without being widened. It still observes innovations --
    the rolling covariate-shift window keeps filling, so the run's evidence
    still shows what the gate *would* have been reasoning about.
    """

    __slots__ = ()

    @override
    def evaluate(
        self,
        *,
        tick: TickId,
        proposal: ProposedCommand,
        prediction: PredictedCommand,
        state: FastStateEstimate,
    ) -> GateVerdict:
        """Return a passing verdict without scoring the proposal.

        Args:
            tick: The control tick.
            proposal: The untrusted proposed command. Not read.
            prediction: The twin's prediction. Not read.
            state: The fast state estimate. Not read.

        Returns:
            A PASS carrying :data:`ABLATED_REASON_CODE`.
        """
        del proposal, prediction, state
        return _ablated(tick, GateId.STATISTICAL)


class TransparentPhysicalGate(PhysicalAdmissibilityGate):
    """L7b, present and disarmed."""

    __slots__ = ()

    @override
    def evaluate(
        self,
        *,
        tick: TickId,
        proposal: ProposedCommand,
        prediction: PredictedCommand,
        state: FastStateEstimate,
    ) -> GateVerdict:
        """Return a passing verdict without checking admissibility.

        Args:
            tick: The control tick.
            proposal: The untrusted proposed command. Not read.
            prediction: The twin's prediction. Not read.
            state: The fast state estimate. Not read.

        Returns:
            A PASS carrying :data:`ABLATED_REASON_CODE`.
        """
        del proposal, prediction, state
        return _ablated(tick, GateId.PHYSICAL)


class TransparentShield(HardSafetyShield):
    """L7a, present and disarmed.

    The one with unconditional veto authority in a governed run, and therefore
    the one whose ablation most needs to be visible in the evidence rather than
    inferable from a configuration file.
    """

    __slots__ = ()

    @override
    def evaluate(
        self,
        *,
        tick: TickId,
        proposal: ProposedCommand,
        state: FastStateEstimate,
        degradation: SlowStateEstimate,
    ) -> GateVerdict:
        """Return a passing verdict without checking any hard bound.

        Args:
            tick: The control tick.
            proposal: The untrusted proposed command. Not read.
            state: The fast state estimate. Not read.
            degradation: The slow state estimate. Not read.

        Returns:
            A PASS carrying :data:`ABLATED_REASON_CODE`.
        """
        del proposal, state, degradation
        return _ablated(tick, GateId.DETERMINISTIC)
