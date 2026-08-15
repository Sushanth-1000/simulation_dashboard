"""Building the ten layers, and the seed calibration they start from.

This is the only module that decides what a layer *is*. Everything else takes
layers as constructor arguments, because a component that could build its own
gate could build a different one than the configuration describes, and the
evidence log would then name an operating point that was not the one running.

The actuation space is the domain boundary
--------------------------------------------
:func:`automotive_actuation_space` is the single place where this codebase says
anything about vehicles. Three channels, their units and their bounds -- that is
the whole of the platform knowledge, and NFR5's domain-independence claim rests
on it staying that way. A different platform supplies a different space and no
layer changes.

Seed calibration, and what it is honestly worth
------------------------------------------------
Conformal prediction cannot promise anything without calibration data. With an
empty calibration set the quantile is correctly infinite and L6 vetoes every
tick as ``CONTEXT_NOT_CALIBRATED`` -- which is the right behaviour, and also a
pipeline that can never be observed doing anything else.

:func:`seed_calibration` fills that gap with scores drawn from the twin against
the synthetic vehicle. It is real calibration in the sense that the numbers come
from running the twin, and it is **not** certification data: the corpus comes
from synthetic dynamics, so the coverage it buys is coverage against a world the
twin already models. Phase 9's CARLA drives are what replace it.

The distinction matters because an uncalibrated gate and a
synthetically-calibrated gate fail differently. The first refuses everything and
is obviously broken. The second passes plausible commands and is only wrong about
situations the synthetic vehicle never produces -- which is exactly the class of
error a demo does not surface.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from astra.contracts.actuation import ActuationChannel, ActuationSpace
from astra.contracts.governance import CalibrationProfile, ProfileFieldHistory
from astra.kernel.constants import RCS_DIMENSION
from astra.kernel.enums import ContextClass, LayerId
from astra.kernel.errors import ConfigurationError, InvariantViolationError
from astra.kernel.identifiers import ComponentId, ProfileId
from astra.kernel.matrix import SymmetricMatrix
from astra.kernel.time import civil_plus_days
from astra.kernel.units import MetresPerSecond, Probability, Seconds
from astra.layers.l1_sensing.bus import SharedSensorBus
from astra.layers.l2_estimation.filter import DualRateUKF
from astra.layers.l2_estimation.measurement import IntegrityMonitor
from astra.layers.l3_trust.classifier import RuleBasedContextClassifier
from astra.layers.l3_trust.corpus import CalibrationCorpus
from astra.layers.l3_trust.mondrian import MondrianCalibration
from astra.layers.l3_trust.quantile import conformal_quantile
from astra.layers.l3_trust.trust import ConformalTrustModule
from astra.layers.l4_proposer.policies import KinematicPlaceholderPolicy
from astra.layers.l4_proposer.proposer import CmdpProposer
from astra.layers.l5_twin.twin import PhysicsInformedTwin
from astra.layers.l6_statistical_gate.gate import IcpStatisticalGate
from astra.layers.l6_statistical_gate.mmd import MmdShiftDetector
from astra.layers.l7_shield.shield import HardSafetyShield
from astra.layers.l7b_physical.checker import (
    REASON_LATERAL_JERK as PHYSICAL_REASON_LATERAL_JERK,
)
from astra.layers.l7b_physical.checker import PhysicalAdmissibilityGate
from astra.layers.l8_failsafe.machine import FailSafeStateMachine
from astra.layers.l9_rcm.arbiter import RuntimeCalibrationManager
from astra.layers.l9_rcm.fallback import ProportionalFallbackController
from astra.layers.l9_rcm.knowledge_base import SearchWeights
from astra.runtime.ablation import (
    AblationProfile,
    TransparentPhysicalGate,
    TransparentShield,
    TransparentStatisticalGate,
    require_ablation_is_permitted,
)
from astra.runtime.channels import open_proposal_channel
from astra.runtime.pipeline import ColdPathContext, GovernancePipeline

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime
    from pathlib import Path

    from astra.config.schema import AstraSettings
    from astra.kernel.identifiers import RunId
    from astra.kernel.time import Clock
    from astra.layers.l2_estimation.measurement import MeasurementExtractor
    from astra.layers.l4_proposer.proposer import Policy
    from astra.observability.audit import JsonlAuditSink
    from astra.ports.pipeline import CommandProjector

__all__ = [
    "AssembledPipeline",
    "AutomotiveCommandProjector",
    "ColdPathContext",
    "assemble_pipeline",
    "automotive_actuation_space",
    "seed_calibration",
    "seed_profiles",
    "verify_profiles",
]

# Channel positions within the automotive space. Named rather than written as
# literals at each use, because a reordering that missed one call site would
# route the throttle command into the steering channel and still type-check.
_MINIMUM_STEER_FOR_ESTIMATE: Final = 1e-3
"""Below this the ratio `a_lat / steer` is noise divided by a small number."""

THROTTLE_INDEX = 0
BRAKE_INDEX = 1
STEER_INDEX = 2

_PROFILE_VALIDITY_DAYS = 90.0
_QUANTILE_TABLE_EPSILONS: Final[tuple[float, ...]] = (0.20, 0.10, 0.05, 0.02, 0.01)
"""Significance levels the certified quantile table is tabulated at.

Descending epsilon gives an ascending threshold, which satisfies the
monotonicity SI-9 requires without needing a sort -- and a table that had to be
sorted to be monotonic would be hiding a generation bug.
"""
_PLACEHOLDER_QUANTILE_TABLE: Final[tuple[float, ...]] = (0.5, 1.0, 1.5, 2.0, 3.0)
"""Used when no corpus is available. Structurally valid; certifies nothing."""

_CERTIFIED_HISTORY: Final = ProfileFieldHistory(deployments=800, critical_failures=0)
"""Field history a seed profile is certified with.

Synthetic, and labelled as such: no profile in this repository has ever been
deployed. It exists because the trust score weights operational history at 0.2,
so a profile with none is unreachable above tau however well it matches -- and a
knowledge base that can never return a candidate makes bounded safe exploration
engage in every context, which is the tunnel scenario made meaningless by being
universal.
"""

_UNSIGNED: Final = "unsigned"
"""Placeholder checksum, replaced by the real digest before a profile escapes.

A profile carrying this string never leaves :func:`seed_profiles`: every one is
passed through ``with_checksum()`` on the way out. It exists only because
``CalibrationProfile`` refuses an empty checksum at construction, so the digest
cannot be computed until the record exists."""
_PLATFORM = "synthetic-prototype"
_STATIONARY: Final = MetresPerSecond(0.0)


def automotive_actuation_space() -> ActuationSpace:
    """Return the three-channel actuation space of a road vehicle.

    Returns:
        Throttle and brake as unit intervals, steering in radians. Steering is
        SI even though a human would write degrees: non-SI values are converted
        at the configuration boundary and never appear on an interface.
    """
    return ActuationSpace(
        (
            ActuationChannel(name="throttle", lower=0.0, upper=1.0, unit="1"),
            ActuationChannel(name="brake", lower=0.0, upper=1.0, unit="1"),
            ActuationChannel(name="steer", lower=-0.5, upper=0.5, unit="rad"),
        )
    )


@dataclass
class ControlEffectivenessEstimator:
    """Tracks the platform's steering effectiveness from measured response.

    Feedback loop FB2, as redefined by
    :doc:`ADR-0020 </adr/0020-fb2-estimates-control-effectiveness>`. It replaces
    an online network update whose only training labels were the proposer's own
    commands -- measured to collapse the non-conformity score 40% in a context
    where nothing changed, which is the statistical gate disarming itself.

    The relation is the one the twin, L7b and the projector already share:
    ``B . pi = a_lat``. Command a steering value, observe the lateral
    acceleration it produced, and the ratio is the effective ``B``. The target is
    therefore *measured physics* rather than the proposer's output, so no amount
    of adaptation can pull the reference toward the thing it judges. That is the
    property the network form could not have, at any penalty strength.

    It lives here rather than in L5 because ``B`` is a platform fact -- it is
    configuration precisely because NFR5 keeps vehicle knowledge out of the
    layers -- so the thing that estimates it belongs on the adapter's side of
    that boundary.

    Saturated samples are discarded, and that is not a refinement
    ------------------------------------------------------------
    A sample whose lateral acceleration is pinned at the platform's limit
    carries no information about ``B``: the response stopped tracking the
    command. Averaging it in reads the effectiveness *low*, and low is the
    dangerous direction -- an underestimated ``B`` makes the twin expect more
    steering than the vehicle needs, which shrinks the departure the
    non-conformity score is computed from.

    Measured on the synthetic plant, configured ``B`` 140.0, saturating beyond
    ``|steer| = 0.0214``: excluding saturated samples recovers **140.000** with
    zero spread; admitting them reads **116.0**, 17.1% low.

    Attributes:
        steering_index: Which actuation channel steers.
        configured: The configured effectiveness, returned until enough samples
            have accumulated to improve on it. A configured value is a
            characterisation someone signed off; an estimate from four samples
            is not, and preferring the latter would be a downgrade.
        saturation_limit: Magnitude of lateral acceleration at which the platform
            stops responding. A platform fact, supplied for the same reason
            ``configured`` is.
        window: Samples retained per context.
        minimum_samples: Samples required before the estimate is used at all.
    """

    steering_index: int
    configured: float
    saturation_limit: float
    window: int = 200
    minimum_samples: int = 20
    _samples: defaultdict[ContextClass, deque[float]] = field(
        default_factory=lambda: defaultdict(deque), init=False, repr=False
    )

    def __post_init__(self) -> None:
        """Validate the platform facts.

        Raises:
            ConfigurationError: If the configured effectiveness is not finite and
                non-zero, or the saturation limit is not positive. Both would
                make every estimate meaningless rather than merely wrong.
        """
        if not math.isfinite(self.configured) or self.configured == 0.0:
            message = f"control effectiveness must be finite and non-zero, got {self.configured}"
            raise ConfigurationError(message, layer=LayerId.L5_PINN_TWIN)
        if not math.isfinite(self.saturation_limit) or self.saturation_limit <= 0.0:
            message = (
                f"the saturation limit must be finite and positive, got "
                f"{self.saturation_limit}; without it every sample looks unsaturated"
            )
            raise ConfigurationError(message, layer=LayerId.L5_PINN_TWIN)

    def observe(
        self,
        *,
        command: Sequence[float],
        lateral_acceleration: float,
        context: ContextClass,
    ) -> None:
        """Record one executed outcome, if it says anything about ``B``.

        Args:
            command: The command actually applied.
            lateral_acceleration: The lateral acceleration measured after it.
            context: The Mondrian class it was observed in. Estimates are kept
                per context for the same reason the twin's heads are: a wet road
                and a dry one are different platforms as far as ``B`` goes.
        """
        steer = float(command[self.steering_index])
        if not math.isfinite(steer) or not math.isfinite(lateral_acceleration):
            return
        if abs(steer) < _MINIMUM_STEER_FOR_ESTIMATE:
            # Near zero the ratio is dominated by whatever noise is on the
            # acceleration, so the sample is noise amplified rather than signal.
            return
        if abs(lateral_acceleration) >= self.saturation_limit:
            return
        samples = self._samples[context]
        samples.append(lateral_acceleration / steer)
        while len(samples) > self.window:
            samples.popleft()

    def estimate(self, context: ContextClass) -> float:
        """Return the effectiveness to use for a context.

        Args:
            context: The Mondrian class.

        Returns:
            The median of the retained samples, or :attr:`configured` when too
            few have accumulated. Median rather than mean: one saturated sample
            that slipped through, or one outlier from a transient, should not
            move a number two gates depend on.
        """
        samples = self._samples.get(context)
        if samples is None or len(samples) < self.minimum_samples:
            return self.configured
        return statistics.median(samples)

    def sample_count(self, context: ContextClass) -> int:
        """Return how many usable samples a context has accumulated.

        Reported so a run can show whether an estimate is starved rather than
        merely stable -- a vehicle that corners hard spends its time saturated,
        which is exactly when the estimate is wanted.

        Args:
            context: The Mondrian class.

        Returns:
            The retained sample count.
        """
        samples = self._samples.get(context)
        return 0 if samples is None else len(samples)


@dataclass(frozen=True, slots=True)
class AutomotiveCommandProjector:
    """Turns a target lateral acceleration into a steering command.

    Satisfies :class:`~astra.ports.pipeline.CommandProjector` structurally. The
    second place in this codebase that says anything about vehicles, after
    :func:`automotive_actuation_space`, and it is here for the same reason: it
    is platform knowledge, and NFR5 keeps platform knowledge out of the layers.

    The model is the one the twin and L7b already share -- ``B . pi = a_lat``,
    lateral acceleration linear in the steering command through the control
    effectiveness. Inverting it is a division, and the only subtlety is that
    every other channel is carried through untouched: rate limiting adjusts the
    vehicle's path, never its speed.

    Attributes:
        steering_index: Which channel steers.
        effectiveness: Lateral acceleration produced per unit of that channel.
        throttle_index: Which channel drives.
        brake_index: Which channel brakes.
    """

    steering_index: int
    effectiveness: float
    throttle_index: int = THROTTLE_INDEX
    brake_index: int = BRAKE_INDEX

    def __post_init__(self) -> None:
        """Validate the effectiveness.

        Raises:
            ConfigurationError: If the effectiveness is zero or non-finite. A
                zero would make every target unreachable and the division
                undefined; silently returning the input instead would leave a
                rate limiter that never limits anything.
        """
        if not math.isfinite(self.effectiveness) or self.effectiveness == 0.0:
            message = (
                f"steering effectiveness must be finite and non-zero, got "
                f"{self.effectiveness}; a zero makes every lateral target unreachable"
            )
            raise ConfigurationError(message, layer=LayerId.L9_RCM)

    def with_lateral_acceleration(
        self, values: Sequence[float], target: float
    ) -> tuple[float, ...]:
        """Return the command that produces a target lateral acceleration.

        Args:
            values: The command vector to adjust, in actuation-space order.
            target: The lateral acceleration the result should imply, in m/s^2.

        Returns:
            The vector with only the steering channel changed.
        """
        steer = target / self.effectiveness
        return tuple(
            steer if index == self.steering_index else float(value)
            for index, value in enumerate(values)
        )

    def with_speed_cap(
        self, values: Sequence[float], *, current_speed: float, cap: float
    ) -> tuple[float, ...]:
        """Return the command with propulsion withdrawn if the cap is exceeded.

        Below the cap, unchanged: a cap is a ceiling, not a target. At or above
        it, throttle goes to zero and the brake goes full on. Full rather than
        proportional because this is a *fail-safe* posture, not a controller --
        proportional braking would need a gain, a gain is a tuning parameter,
        and a tuning parameter in the fail-safe path is a thing that can be set
        wrong. The FSM has already decided the situation warrants a cap; the
        cheapest correct response is to stop approaching it.

        Args:
            values: The command vector to adjust, in actuation-space order.
            current_speed: The vehicle's speed, in m/s.
            cap: The ceiling the fail-safe posture imposes, in m/s.

        Returns:
            The vector with the two longitudinal channels set, or unchanged.
        """
        if current_speed <= cap:
            return tuple(float(value) for value in values)
        return tuple(
            0.0
            if index == self.throttle_index
            else 1.0
            if index == self.brake_index
            else float(value)
            for index, value in enumerate(values)
        )


def _quantile_table(corpus: CalibrationCorpus | None, context: ContextClass) -> tuple[float, ...]:
    """Return a profile's certified quantile table.

    Derived from the corpus when one is available, so the table a profile
    certifies describes the same distribution the gate scores against. The
    fallback is a placeholder ladder, used only when no corpus exists -- and a
    profile carrying it certifies nothing.

    Args:
        corpus: The calibration corpus, if one was supplied.
        context: The class whose scores to draw from.

    Returns:
        A non-decreasing table, as SI-9 requires.
    """
    if corpus is None or corpus.sample_count(context) == 0:
        return _PLACEHOLDER_QUANTILE_TABLE
    scores = corpus.scores[context]
    return tuple(conformal_quantile(scores, epsilon) for epsilon in _QUANTILE_TABLE_EPSILONS)


def seed_profiles(
    *,
    now: datetime,
    max_speed: MetresPerSecond,
    corpus: CalibrationCorpus | None = None,
) -> tuple[CalibrationProfile, ...]:
    """Build the four seed calibration profiles.

    **There is deliberately no tunnel profile.** That omission is what makes the
    validation plan's tunnel scenario meaningful: with no admissible profile, L9
    must engage bounded safe exploration and keep the vehicle moving. A fifth
    profile added for tidiness would delete the project's most distinctive
    behaviour.

    Args:
        now: The current civil time, from the injected clock's ``wall_clock``.
        max_speed: The certified maximum speed for the highway profile. The
            others are derived as fractions of it.
        corpus: The calibration corpus each profile's quantile table is drawn
            from. ``None`` produces placeholder tables, which are structurally
            valid and certify nothing.

    Returns:
        The four certified profiles, in ``ContextClass`` declaration order.
    """
    certified = now
    expires = civil_plus_days(now, _PROFILE_VALIDITY_DAYS)

    specifications = (
        (ContextClass.HIGHWAY_CLEAR, (0.9, 0.8, 0.3, 0.95, 0.2), 1.0),
        (ContextClass.URBAN_CLEAR, (0.85, 0.35, 0.7, 0.95, 0.7), 0.45),
        (ContextClass.RAIN_NIGHT, (0.35, 0.5, 0.5, 0.7, 0.5), 0.6),
        (ContextClass.DEGRADED_SENSOR, (0.6, 0.4, 0.5, 0.35, 0.5), 0.4),
    )
    return tuple(
        CalibrationProfile(
            profile_id=ProfileId(name=context.value.lower(), version=1),
            context_class=context,
            centroid=centroid,
            covariance=SymmetricMatrix.from_diagonal([0.05] * RCS_DIMENSION),
            quantile_table=_quantile_table(corpus, context),
            coverage_level=Probability(0.95),
            # RCM's trust score is T(c) = w1*sim + w2*val + w3*hist - w4*risk,
            # and with tau = 0.7 a profile carrying no validation evidence and
            # no deployment history cannot reach the threshold *however well its
            # centroid matches* -- similarity alone is weighted 0.4. Seeding
            # them with no history made every context look like the tunnel,
            # which would have made the scenario meaningless by making it
            # universal.
            #
            # These are the numbers a genuinely certified profile would carry:
            # validated against most of its corpus, deployed extensively, never
            # failed critically.
            validation_fraction=Probability(0.9),
            validation_passed=True,
            max_speed=MetresPerSecond(float(max_speed) * fraction),
            # Placeholder; replaced immediately below by the real digest.
            checksum=_UNSIGNED,
            platform=_PLATFORM,
            certified_at=certified,
            expires_at=expires,
            field_history=_CERTIFIED_HISTORY,
        ).with_checksum()
        for context, centroid, fraction in specifications
    )


def seed_calibration(
    calibration: MondrianCalibration,
    *,
    scores_per_class: Sequence[float],
    classes: Sequence[ContextClass] = (
        ContextClass.HIGHWAY_CLEAR,
        ContextClass.URBAN_CLEAR,
        ContextClass.RAIN_NIGHT,
        ContextClass.DEGRADED_SENSOR,
    ),
) -> None:
    """Seed the Mondrian calibration so the conformal quantiles are finite.

    Without this every quantile is ``inf`` and L6 vetoes every tick as
    ``CONTEXT_NOT_CALIBRATED`` -- correct, and unobservable.

    Args:
        calibration: The calibration to seed.
        scores_per_class: Non-conformity scores to seed each class with.
        classes: Which classes to seed. ``UNCLASSIFIED`` is excluded on
            purpose: it is the class that means "no certified profile matches",
            and seeding it would let the system quietly treat an unrecognised
            context as calibrated.
    """
    for context in classes:
        calibration.seed(context, scores_per_class)


def verify_profiles(profiles: Sequence[CalibrationProfile]) -> None:
    """Refuse any profile whose contents no longer match its checksum (SI-9).

    The independent validation the invariant requires. It is deliberately
    performed here, in the composition root, rather than inside L9: a profile
    that fails this check must never reach the component that would activate it,
    and a check living inside that component would be the proposer validating
    its own proposal.

    Args:
        profiles: The profiles about to be handed to the arbitrator.

    Raises:
        InvariantViolationError: If any profile's digest does not match its
            contents. Not recoverable: a calibration table that has been altered
            since certification invalidates every threshold derived from it, and
            there is no safe subset to continue with.
    """
    tampered = [str(profile.profile_id) for profile in profiles if not profile.has_valid_checksum()]
    if tampered:
        message = (
            f"calibration profiles fail independent checksum validation: "
            f"{', '.join(tampered)}. A table altered since certification cannot "
            f"be activated (SI-9)"
        )
        raise InvariantViolationError(message, layer=LayerId.L9_RCM, context={"profiles": tampered})


@dataclass(frozen=True, slots=True)
class AssembledPipeline[PayloadT]:
    """A built pipeline and the pieces a caller still needs to reach.

    Attributes:
        pipeline: The tick loop.
        sensor_bus: L1, so a driver can publish readings into it.
        calibration: The **gate's** Mondrian calibration, over
            ``dist(proposal, twin) / sigma``, so a caller can seed or inspect it.
        trust_calibration: The **Trust Index's** calibration, over the filter's
            innovation magnitude. A second distribution rather than a second
            copy: L3 and L6 measure different quantities, and sharing one made
            the Trust Index return two distinct values in 4,001 ticks.
        fallback: The deterministic controller, so the driver can keep its error
            term current on every tick.
        space: The actuation space every command is a vector over.
    """

    pipeline: GovernancePipeline[PayloadT]
    sensor_bus: SharedSensorBus[PayloadT]
    calibration: MondrianCalibration
    trust_calibration: MondrianCalibration
    fallback: ProportionalFallbackController
    space: ActuationSpace


def assemble_pipeline[PayloadT](
    *,
    run: RunId,
    config_hash: str,
    settings: AstraSettings,
    clock: Clock,
    extractor: MeasurementExtractor[PayloadT],
    audit_sink: JsonlAuditSink,
    initial_speed: MetresPerSecond = _STATIONARY,
    twin_checkpoint: Path | None = None,
    shadow_fb2: bool = False,
    corpus: CalibrationCorpus | None = None,
    cold_path: ColdPathContext | None = None,
    policy: Policy | None = None,
    ablation: AblationProfile | None = None,
    environment: str = "unknown",
    integrity: IntegrityMonitor[PayloadT] | None = None,
    space: ActuationSpace | None = None,
    projector: CommandProjector | None = None,
) -> AssembledPipeline[PayloadT]:
    """Construct all ten layers and wire them into a pipeline.

    Args:
        run: The run identifier.
        config_hash: The frozen configuration's hash.
        settings: The validated settings.
        clock: The injected time source.
        space: The platform's actuation channels, their order and their bounds.
            **Adapter-supplied from 15 August 2026 (OD-11 wall 1, ADR-0034).**
            Defaults to :func:`automotive_actuation_space` — this composition
            root is automotive until a second platform exists, and pretending
            otherwise by making it required would break every caller to prove a
            point no adapter is yet making. What matters for NFR5 is that a
            different platform *can* supply one, which it now can.
        projector: Turns a target lateral acceleration back into a command.
            **Adapter-supplied from the same date (wall 2).** Defaults to
            :class:`AutomotiveCommandProjector`, which divides by a steering
            effectiveness — arithmetic a differential drive has no counterpart
            for, because it has no steering channel. That is precisely why it
            had to become injectable rather than better.
        extractor: Turns fused frames into measurements. Adapter-supplied.
        integrity: Cross-modality monitor, adapter-supplied and optional. The
            producer of ``StreamHealth.FAULTED``, which L1 reserves for a
            *lying* stream and cannot decide from freshness alone. ``None``
            leaves health exactly as L1 determines it (ADR-0026).
        audit_sink: Where decision records are written.
        initial_speed: The speed the filter starts from.
        shadow_fb2: Run the dormant feedback loops against state nothing reads,
            so a long run can measure what they would do before either is given
            authority. Builds a second twin for FB2 and a second Mondrian
            calibration for FB3. Off by default; see
            :meth:`~astra.runtime.pipeline.ControlPipeline._shadow`.
        twin_checkpoint: Trained twin weights. **Strongly recommended.** An
            untrained twin has random weights and predicts commands that are not
            merely inaccurate but physically absurd -- a lateral acceleration of
            13 g is a representative one -- so the physical gate vetoes every
            tick on model divergence and the statistical gate vetoes on the
            score that divergence produces. Both are behaving correctly; the
            pipeline is simply unusable. ``None`` is permitted so that the
            assembly can be exercised without a checkpoint, not because it is a
            sensible way to run.
        corpus: The calibration corpus. Seeds the Mondrian calibration and
            supplies every profile's quantile table. Without it the conformal
            quantiles are infinite and L6 vetoes every tick as
            ``CONTEXT_NOT_CALIBRATED`` -- correct, and unobservable.
        ablation: Which layers to disarm for a study. ``None`` -- the default
            -- is a governed run. A disarmed gate is still constructed,
            still evaluated and still writes a verdict; it simply cannot
            block, and every decision record says so. The gate parameters
            are never made optional (ADR-0021).
        environment: The resolved configuration environment, used only to
            refuse a non-empty ablation outside ``development``. Defence in
            depth behind the structural guarantee, not instead of it.
        cold_path: What RCM needs to evaluate the knowledge base. ``None``
            leaves the cold path dormant, so the arbitrator keeps its initial
            profile and bounded safe exploration can never engage.
        policy: The proposer's policy. Defaults to
            :class:`~astra.layers.l4_proposer.policies.KinematicPlaceholderPolicy`,
            which is scaffolding: it cannot drift and cannot be confidently
            wrong, so a run driven by it exercises the plumbing and demonstrates
            nothing about whether the gates catch what they exist to catch. Pass
            a :class:`~astra.layers.l4_proposer.learned.LearnedPolicy` for that.
            The default is the placeholder rather than a trained checkpoint
            because assembly must not depend on a file that may not have been
            produced yet.

    Returns:
        The assembled pipeline and the handles a driver needs.
    """
    # Wall 1. This read `space = automotive_actuation_space()` until 15 August
    # 2026, with no parameter to override it, while the module docstring three
    # hundred lines above claimed an adapter could supply one. The claim is now
    # true (ADR-0034).
    #
    # **The space and the projector are one decision, not two.** The default
    # projector inverts a lateral acceleration through STEER_INDEX and the
    # placeholder policy steers through it, so a caller supplying a two-channel
    # differential drive and defaulting either gets `steer_index 2 is outside a
    # 2-channel actuation space` from somewhere deep in construction. Refusing
    # here says the same thing where it can be acted on -- and refusing beats
    # defaulting, because there is no sensible projector or fallback controller
    # for a platform this function has never heard of.
    #
    # The policy half was found by writing an honest injection test, not by
    # review: making the space injectable is not the same as making the root
    # platform-neutral, and only driving it with a different space says which.
    if space is not None and (projector is None or policy is None):
        missing = [
            name
            for name, supplied in (("projector", projector), ("policy", policy))
            if supplied is None
        ]
        message = (
            f"an adapter-supplied actuation space also needs: {', '.join(missing)}. "
            "Both index a steering channel into the space -- the projector to invert "
            "a lateral acceleration, the placeholder policy to steer at all -- and "
            "both defaults assume the automotive layout"
        )
        raise ConfigurationError(
            message, context={"channels": space.dimension, "missing": ", ".join(missing)}
        )
    space = automotive_actuation_space() if space is None else space
    tick_period = Seconds(1.0 / settings.estimation.fast_rate_hz)
    slow_period_ticks = max(
        1, round(settings.estimation.fast_rate_hz / settings.estimation.slow_rate_hz)
    )

    sensor_bus: SharedSensorBus[PayloadT] = SharedSensorBus(
        clock=clock, staleness_budget=settings.sensing.staleness_budget
    )
    estimator: DualRateUKF[PayloadT] = DualRateUKF(
        settings=settings.estimation,
        extractor=extractor,
        initial_fast_state=[0.0, 0.0, float(initial_speed), 0.0, 0.0],
        initial_fast_covariance=SymmetricMatrix.from_diagonal([1.0, 1.0, 1.0, 0.1, 1.0]),
        initial_slow_state=[0.85, 0.0, 1.0],
        initial_slow_covariance=SymmetricMatrix.from_diagonal([0.01, 0.01, 0.01]),
    )

    # L3 and L6 held ONE calibration until 5 August 2026, on the reasoning that
    # "the Trust Index and the ICP gate are two readings of the same
    # non-conformity distribution, and two independently-maintained copies would
    # drift apart". The reasoning is sound and the premise was false: they read
    # *different statistics*.
    #
    # L6 scores `dist(proposal, twin_prediction) / sigma`. L3 scores the filter's
    # innovation magnitude, because at its point in the tick -- before L4 has
    # proposed anything -- no proposal exists to score. So the Trust Index was
    # querying a CDF built from the gate's scores using a quantity on an
    # unrelated scale, and the answer was always the same one: it took exactly
    # two distinct values, 0.0 and 1.0, across 4,001 consecutive ticks.
    #
    # Two calibrations, then, because there are two distributions. The drift the
    # old comment feared cannot arise between distributions that were never
    # meant to agree, and a Trust Index that disagrees with the gate is now
    # informative rather than a symptom.
    calibration = MondrianCalibration(window=settings.trust.calibration_window)
    trust_calibration = MondrianCalibration(window=settings.trust.calibration_window)
    classifier = RuleBasedContextClassifier(highway_speed=settings.trust.highway_speed_boundary)
    trust_module = ConformalTrustModule(
        classifier=classifier,
        calibration=trust_calibration,
        coverage_level=settings.trust.coverage_level,
    )

    policy = policy or KinematicPlaceholderPolicy(
        channel_count=space.dimension,
        speed_index=THROTTLE_INDEX,
        steer_index=STEER_INDEX,
        target_speed=float(settings.shield.legal_speed_limit) * 0.8,
        steer_effectiveness=float(settings.twin.control_effectiveness[STEER_INDEX]),
        tick_period=float(tick_period),
        maximum_jerk=float(settings.physical.max_lateral_jerk),
    )
    proposer = CmdpProposer(
        policy=policy,
        space=space,
        component=ComponentId(LayerId.L4_CORE_A_CMDP),
        clock=clock,
    )
    writer, reader = open_proposal_channel()

    twin = PhysicsInformedTwin(
        settings=settings.twin,
        space=space,
        component=ComponentId(LayerId.L5_PINN_TWIN),
        clock=clock,
    )
    if twin_checkpoint is not None:
        twin.load_checkpoint(twin_checkpoint)

    # A second twin of the same architecture, from the same checkpoint, that FB2
    # is allowed to move. Built here rather than deep-copied so it goes through
    # exactly the construction the real one did -- a shadow assembled by a
    # different route would be measuring the route as much as the loop.
    shadow_calibration: MondrianCalibration | None = None
    shadow_failsafe: FailSafeStateMachine | None = None
    shadow_twin: PhysicsInformedTwin | None = None
    if shadow_fb2:
        shadow_twin = PhysicsInformedTwin(
            settings=settings.twin,
            space=space,
            component=ComponentId(LayerId.L5_PINN_TWIN),
            clock=clock,
        )
        if twin_checkpoint is not None:
            shadow_twin.load_checkpoint(twin_checkpoint)
        # Seeded from the same corpus as L6's, below, so the two start identical
        # and every later difference is FB3's doing.
        shadow_calibration = MondrianCalibration(window=settings.trust.calibration_window)
        # Same thresholds as the real machine, so the escalation it reports is
        # the one the vehicle would actually have suffered.
        shadow_failsafe = FailSafeStateMachine(settings.failsafe)

    profile = ablation or AblationProfile.NONE
    require_ablation_is_permitted(profile, environment=environment)
    # A disarmed gate is a *subtype*, so these names keep their declared types
    # and the pipeline's required parameters are never widened -- ADR-0021.
    statistical_type = (
        TransparentStatisticalGate if profile.statistical_gate else IcpStatisticalGate
    )
    statistical_gate = statistical_type(
        calibration=calibration,
        classifier=classifier,
        detector=MmdShiftDetector(
            window=settings.gate.mmd_window, threshold=settings.gate.mmd_threshold
        ),
        significance_epsilon=settings.gate.significance_epsilon,
        shift_epsilon_multiplier=settings.gate.shift_epsilon_multiplier,
    )
    physical_type = TransparentPhysicalGate if profile.physical_gate else PhysicalAdmissibilityGate
    physical_gate = physical_type(
        settings=settings.physical,
        control_effectiveness=settings.twin.control_effectiveness,
        tick_period=tick_period,
    )
    shield_type = TransparentShield if profile.shield else HardSafetyShield
    shield = shield_type(settings.shield)
    failsafe = FailSafeStateMachine(settings.failsafe)

    fallback = ProportionalFallbackController(
        channel_count=space.dimension,
        speed_index=THROTTLE_INDEX,
        target_speed=MetresPerSecond(float(settings.shield.legal_speed_limit) * 0.5),
        proportional_gain=0.2,
        tick_period=tick_period,
    )
    if corpus is not None:
        corpus.seed_into(calibration)
        corpus.seed_innovations_into(trust_calibration)
        if shadow_calibration is not None:
            corpus.seed_into(shadow_calibration)
    profiles = seed_profiles(
        now=clock.wall_clock(),
        max_speed=settings.shield.legal_speed_limit,
        corpus=corpus,
    )
    # SI-9: Core-B validates the table independently before activation, even
    # though RCM proposed it. Monotonicity is checked at construction; this is
    # the other half -- a profile whose contents were altered after
    # certification has a digest that no longer matches, and that is exactly the
    # shape a calibration-poisoning attack takes.
    verify_profiles(profiles)

    arbiter = RuntimeCalibrationManager(
        component=ComponentId(LayerId.L9_RCM),
        space=space,
        clock=clock,
        fallback=fallback,
        profiles=profiles,
        weights=SearchWeights(similarity=0.4, validation=0.3, history=0.2, risk=0.1),
        active=profiles[0],
        # Wall 2, and the same story. The default stays automotive because this
        # root is; the point is that it is now a default rather than a fact.
        projector=projector
        if projector is not None
        else AutomotiveCommandProjector(
            steering_index=STEER_INDEX,
            effectiveness=settings.twin.control_effectiveness[STEER_INDEX],
        ),
        # Which reason codes a bounded approach can answer is decided here, in
        # the module that knows what every layer is, rather than by the
        # arbitrator importing a gate's vocabulary. Exactly one qualifies: the
        # jerk bound is a statement about *rate*, so approaching it slowly is a
        # real answer to it. Divergence from the twin and every deterministic
        # bound are statements about the destination, and arriving there in
        # small steps would defeat them while looking like compliance.
        rate_limited_reasons=frozenset({PHYSICAL_REASON_LATERAL_JERK}),
    )

    pipeline: GovernancePipeline[PayloadT] = GovernancePipeline(
        run=run,
        config_hash=config_hash,
        sensor_bus=sensor_bus,
        estimator=estimator,
        trust_module=trust_module,
        proposer=proposer,
        proposal_writer=writer,
        proposal_reader=reader,
        twin=twin,
        statistical_gate=statistical_gate,
        physical_gate=physical_gate,
        shield=shield,
        failsafe=failsafe,
        arbiter=arbiter,
        audit_sink=audit_sink,
        clock=clock,
        staleness_budget=settings.sensing.staleness_budget,
        slow_period_ticks=slow_period_ticks,
        control_effectiveness=settings.twin.control_effectiveness,
        context=cold_path,
        shadow_twin=shadow_twin,
        shadow_calibration=shadow_calibration,
        shadow_failsafe=shadow_failsafe,
        ablation=profile.render(),
        integrity=integrity,
    )
    return AssembledPipeline(
        pipeline=pipeline,
        sensor_bus=sensor_bus,
        calibration=calibration,
        trust_calibration=trust_calibration,
        fallback=fallback,
        space=space,
    )
