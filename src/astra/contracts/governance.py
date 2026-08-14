"""Governance contracts: the runtime context, calibration profiles and arbitration.

These records belong to RCM (L9), the arbitrator. Two things the architecture
insists on are enforced here at the type level:

* **SI-9 (independent calibration validation).** A :class:`CalibrationProfile`
  rejects a non-monotonic quantile table at construction, using the same
  monotonicity guard Core-B applies before activating any table. A table that
  is not non-decreasing can map a *higher* non-conformity score to a *lower*
  rejection threshold, which is the shape a calibration-poisoning attack takes.

* **The admissibility rule is a hard gate.** :func:`is_candidate_admissible`
  encodes ``T(c) >= tau AND val(c) == 1`` as a conjunction with no scoring
  escape hatch: a candidate that fails validity is inadmissible no matter how
  high its trust score. Writing it once, here, keeps every call site honest.

Phase 1 scope: this module defines the *records and the admissibility
predicate*. The knowledge-base search, the Mahalanobis scoring and the shadow
execution that consume them are L9 logic and arrive in Phase 6; they are not
implemented here (see the handoff's phase-discipline rule).
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from astra.kernel.constants import RCS_DIMENSION, RCS_FIELDS
from astra.kernel.enums import ArbitrationOutcome
from astra.kernel.errors import ContractViolationError, DimensionMismatchError
from astra.kernel.units import Probability
from astra.kernel.validation import (
    require_dimension,
    require_finite,
    require_non_decreasing,
    require_non_negative,
    require_probability,
)

if TYPE_CHECKING:
    from datetime import datetime

    from astra.kernel.enums import ContextClass
    from astra.kernel.identifiers import ProfileId, TickId
    from astra.kernel.matrix import SymmetricMatrix
    from astra.kernel.units import MetresPerSecond

__all__ = [
    "ArbitrationDecision",
    "CalibrationProfile",
    "ProfileFieldHistory",
    "RuntimeContextSignature",
    "is_candidate_admissible",
]

_VISIBILITY_INDEX = RCS_FIELDS.index("visibility")
_EGO_SPEED_INDEX = RCS_FIELDS.index("ego_speed")
_TRAFFIC_DYNAMICITY_INDEX = RCS_FIELDS.index("traffic_dynamicity")
_SENSOR_RELIABILITY_INDEX = RCS_FIELDS.index("sensor_reliability")
_ROAD_COMPLEXITY_INDEX = RCS_FIELDS.index("road_complexity")


@dataclass(frozen=True, slots=True)
class RuntimeContextSignature:
    """The five-component normalised description of the current operating context.

    RCM builds this each cold-path evaluation and searches the Calibration
    Knowledge Base for the nearest certified profile by Mahalanobis distance.
    Every component is a :data:`~astra.kernel.units.Probability` in ``[0, 1]``:
    the signature is deliberately dimensionless and normalised so that a single
    covariance-weighted distance is meaningful across heterogeneous quantities.

    The sensor-reliability component is reliability-weighted upstream, so a
    degraded sensor lowers its own contribution to the signature rather than
    silently dominating it -- the mitigation the architecture names for the
    shared-state common-cause weakness.

    Attributes:
        tick: The control tick this signature describes.
        components: The five values, ordered per
            :data:`~astra.kernel.constants.RCS_FIELDS`.
    """

    tick: TickId
    components: tuple[Probability, ...]

    def __post_init__(self) -> None:
        """Validate the signature's dimension and per-component range.

        Raises:
            DimensionMismatchError: If there are not exactly
                :data:`~astra.kernel.constants.RCS_DIMENSION` components.
            RangeViolationError: If any component lies outside ``[0, 1]``.
        """
        checked = require_dimension(self.components, expected=RCS_DIMENSION, name="rcs")
        validated = tuple(
            require_probability(value, name=f"rcs.{RCS_FIELDS[index]}")
            for index, value in enumerate(checked)
        )
        object.__setattr__(self, "components", validated)

    @property
    def visibility(self) -> Probability:
        """Return the normalised visibility component."""
        return self.components[_VISIBILITY_INDEX]

    @property
    def ego_speed(self) -> Probability:
        """Return the normalised ego-speed component."""
        return self.components[_EGO_SPEED_INDEX]

    @property
    def traffic_dynamicity(self) -> Probability:
        """Return the normalised traffic-dynamicity component."""
        return self.components[_TRAFFIC_DYNAMICITY_INDEX]

    @property
    def sensor_reliability(self) -> Probability:
        """Return the normalised, reliability-weighted sensor component."""
        return self.components[_SENSOR_RELIABILITY_INDEX]

    @property
    def road_complexity(self) -> Probability:
        """Return the normalised road-complexity component."""
        return self.components[_ROAD_COMPLEXITY_INDEX]

    def as_vector(self) -> tuple[float, ...]:
        """Return the signature as a bare numeric vector.

        The form RCM's Mahalanobis distance consumes, and the form a profile's
        certified centroid is stored in, so the two are directly comparable.

        Returns:
            The five components as plain floats in canonical order.
        """
        return tuple(float(component) for component in self.components)


@dataclass(frozen=True, slots=True)
class ProfileFieldHistory:
    """Operational history a certified profile carries into the mandatory gates.

    RCM's mandatory gates disqualify a profile with a critical-failure history
    regardless of how well it scores. Recording that history on the profile is
    what lets that gate be a lookup rather than a query against external state.

    Attributes:
        deployments: How many certified deployments this profile has backed.
        critical_failures: How many of them ended in a critical safety failure.
            A non-zero count is what the failure-history mandatory gate keys on.
    """

    deployments: int = 0
    critical_failures: int = 0

    def __post_init__(self) -> None:
        """Validate that the counts are non-negative and mutually consistent.

        Raises:
            ContractViolationError: If a count is negative, or the number of
                critical failures exceeds the number of deployments.
        """
        if self.deployments < 0 or self.critical_failures < 0:
            message = "profile field-history counts must be non-negative"
            raise ContractViolationError(
                message,
                context={
                    "deployments": self.deployments,
                    "critical_failures": self.critical_failures,
                },
            )
        if self.critical_failures > self.deployments:
            message = "critical failures cannot exceed deployments"
            raise ContractViolationError(
                message,
                context={
                    "deployments": self.deployments,
                    "critical_failures": self.critical_failures,
                },
            )

    @property
    def has_critical_failure_history(self) -> bool:
        """Return whether this profile has ever failed critically in the field.

        Returns:
            ``True`` if :attr:`critical_failures` is non-zero.
        """
        return self.critical_failures > 0


@dataclass(frozen=True, slots=True)
class CalibrationProfile:
    """One immutable, certified calibration profile in RCM's knowledge base.

    A profile binds an operational context to the certified parameters the
    pipeline should run under in that context: where the context sits in RCS
    space, how far from it is still "this context", the conformal quantile table
    the ICP gate uses, and the operating limits. Profiles are versioned and
    immutable (NFR7): a change is a new version, never an edit, so an audit
    record naming ``highway_clear@v2`` is unambiguous forever.

    Attributes:
        profile_id: The versioned identity, e.g. ``highway_clear@v2``.
        context_class: The context class this profile certifies.
        centroid: The profile's location in RCS space, one value per
            :data:`~astra.kernel.constants.RCS_FIELDS`, each in ``[0, 1]``.
        covariance: The certified covariance about the centroid, used for the
            Mahalanobis distance in RCM's cold-path search.
        quantile_table: The non-decreasing conformal quantile table for the ICP
            gate. Monotonicity is enforced (SI-9).
        coverage_level: The conformal coverage ``1 - epsilon`` the table
            certifies.
        validation_fraction: The fraction of the certification corpus held out
            for validation, in ``[0, 1]``. Metadata about *how much* evidence
            backs the profile, and a term in RCM's trust score -- a profile
            validated against more held-out data scores higher.

            **Not** the same thing as :attr:`validation_passed`, and conflating
            the two is a mistake this codebase actually made: the knowledge base
            once read this field as ``val(c)`` and required it to equal 1.0,
            which made every correctly-certified profile -- one holding out a
            sensible 20% -- permanently inadmissible. The architecture's
            ``val(c)`` is binary; the held-out fraction is not.
        validation_passed: ``val(c)``. Whether the profile passed its
            certification suite.

            Binary on purpose, and a **hard conjunct** in the admissibility
            rule: a profile that passed 99% of its suite is not 99% admissible,
            it is inadmissible. No trust score, however high, may rescue it.
        max_speed: The certified maximum speed for this context, in m/s.
        field_history: Operational history feeding the mandatory gates.
        checksum: The signed checksum Core-B independently verifies before
            activating the table (SI-9). Opaque here; verified in Phase 6.
        platform: Platform identifier, keyed on by the platform-mismatch gate.
        certified_at: When the profile was certified. Timezone-aware UTC.
        expires_at: When the certification lapses. Timezone-aware UTC.
    """

    profile_id: ProfileId
    context_class: ContextClass
    centroid: tuple[float, ...]
    covariance: SymmetricMatrix
    quantile_table: tuple[float, ...]
    coverage_level: Probability
    validation_fraction: Probability
    validation_passed: bool
    max_speed: MetresPerSecond
    checksum: str
    platform: str
    certified_at: datetime
    expires_at: datetime
    field_history: ProfileFieldHistory = ProfileFieldHistory()

    def __post_init__(self) -> None:
        """Validate the profile's structure, ranges, monotonicity and dates.

        Raises:
            DimensionMismatchError: If the centroid or covariance is not
                :data:`~astra.kernel.constants.RCS_DIMENSION`-dimensional.
            RangeViolationError: If a centroid component, the coverage level, the
                validation fraction or the max speed is out of range, or the
                quantile table is not non-decreasing.
            ContractViolationError: If the checksum or platform is empty, the
                dates are naive, or the expiry is not after certification.
        """
        centroid = require_dimension(self.centroid, expected=RCS_DIMENSION, name="centroid")
        for index, value in enumerate(centroid):
            require_probability(value, name=f"centroid.{RCS_FIELDS[index]}")
        object.__setattr__(self, "centroid", centroid)
        if self.covariance.dimension != RCS_DIMENSION:
            message = (
                f"profile covariance is {self.covariance.dimension}-dimensional, "
                f"expected {RCS_DIMENSION}"
            )
            raise DimensionMismatchError(message, context={"expected": RCS_DIMENSION})
        object.__setattr__(
            self,
            "quantile_table",
            require_non_decreasing(self.quantile_table, name="quantile_table"),
        )
        require_probability(self.coverage_level, name="coverage_level")
        require_probability(self.validation_fraction, name="validation_fraction")
        require_non_negative(self.max_speed, name="max_speed")
        if not self.checksum:
            message = "a calibration profile must carry a non-empty checksum"
            raise ContractViolationError(message, context={"profile": str(self.profile_id)})
        if not self.platform:
            message = "a calibration profile must name a platform"
            raise ContractViolationError(message, context={"profile": str(self.profile_id)})
        self._validate_dates()

    def _validate_dates(self) -> None:
        """Validate that certification dates are timezone-aware and ordered.

        Raises:
            ContractViolationError: If either date is naive, or the expiry does
                not strictly follow certification.
        """
        for label, moment in (("certified_at", self.certified_at), ("expires_at", self.expires_at)):
            if moment.tzinfo is None:
                message = f"{label} must be timezone-aware"
                raise ContractViolationError(message, context={"field": label})
        if self.expires_at <= self.certified_at:
            message = "a profile's expiry must be strictly after its certification"
            raise ContractViolationError(
                message,
                context={
                    "certified_at": self.certified_at.isoformat(),
                    "expires_at": self.expires_at.isoformat(),
                },
            )

    def compute_checksum(self) -> str:
        """Return the digest of every field this profile's authority rests on.

        SI-9 requires Core-B to validate a calibration table independently before
        activating it, "even though RCM proposed it". Monotonicity is one half of
        that; this is the other. A profile whose quantile table has been altered
        between certification and activation is a calibration-poisoning attack,
        and it is invisible unless something recomputes the digest and compares.

        The digest covers exactly the fields that change what the profile
        *authorises*: its identity, the context it claims, where it sits in RCS
        space, the thresholds it certifies, its operating limits, its platform
        and its validity window. It deliberately excludes :attr:`checksum`
        itself, which would be circular.

        Field-separated with a delimiter that cannot appear in the rendered
        values, so that moving a character from one field to the next cannot
        produce the same digest -- a concatenation without separators is a
        classic way to make two different profiles collide.

        Returns:
            A hex SHA-256 digest.
        """
        parts = (
            str(self.profile_id),
            self.context_class.value,
            ",".join(repr(value) for value in self.centroid),
            ",".join(repr(value) for value in self.covariance.lower_triangle),
            ",".join(repr(value) for value in self.quantile_table),
            repr(float(self.coverage_level)),
            repr(float(self.validation_fraction)),
            repr(float(self.max_speed)),
            self.platform,
            self.certified_at.isoformat(),
            self.expires_at.isoformat(),
            str(self.field_history.deployments),
            str(self.field_history.critical_failures),
        )
        digest = hashlib.sha256()
        digest.update("\x1f".join(parts).encode("utf-8"))
        return digest.hexdigest()

    def has_valid_checksum(self) -> bool:
        """Return whether the stored checksum matches the profile's contents.

        Returns:
            ``True`` if the profile has not been altered since its checksum was
            computed.
        """
        return hmac.compare_digest(self.checksum, self.compute_checksum())

    def with_checksum(self) -> CalibrationProfile:
        """Return a copy carrying the checksum of its own contents.

        The certification-time operation. Used when a profile is minted; a
        profile read back from a knowledge base keeps whatever checksum it was
        stored with, so that tampering is detectable rather than overwritten.

        Returns:
            An identical profile whose checksum is correct.
        """
        return replace(self, checksum=self.compute_checksum())

    def is_expired(self, now: datetime) -> bool:
        """Return whether the profile's certification has lapsed.

        The predicate behind RCM's expired-signature mandatory gate. Evaluated on
        the cold path with civil time, never on the hot path.

        Args:
            now: The current civil time, timezone-aware.

        Returns:
            ``True`` if ``now`` is at or after :attr:`expires_at`.

        Raises:
            ContractViolationError: If ``now`` is naive.
        """
        if now.tzinfo is None:
            message = "the current time passed to is_expired must be timezone-aware"
            raise ContractViolationError(message)
        return now >= self.expires_at


@dataclass(frozen=True, slots=True)
class ArbitrationDecision:
    """RCM's decision for one cold-path evaluation.

    Records what RCM decided to do and the scored evidence behind it: which
    table stays or becomes active, which candidate (if any) was under
    consideration, the candidate's trust score ``T(c)`` and, during a staged
    switch, the Calibration Divergence Index that governs commit-or-rollback.

    Attributes:
        tick: The control tick this decision was taken at.
        outcome: What RCM decided.
        active_profile: The profile that is active after this decision.
        candidate_profile: The candidate under evaluation, if any.
        trust_score: The candidate's ``T(c)``, or the active table's, as a bare
            score. Not bounded to ``[0, 1]``: it is a weighted sum that may be
            negative when the risk term dominates.
        calibration_divergence_index: The CDI during shadow execution, in
            ``[0, 1]``, or ``None`` when no switch is in progress.
        signature: **The context this decision was taken about.**

            Optional only so that a caller constructing a decision by hand --
            every test that predates this field -- is not forced to invent a
            signature it does not have. The arbitrator always supplies it.

            **Until 11 August 2026 this was not recorded anywhere.** RCM built a
            signature each cold-path evaluation, searched the knowledge base
            with it, decided on it, and returned a decision that did not carry
            it. The evidence log could therefore say *"SAFE_EXPLORATION, trust
            0.62"* and could **not** say what context produced that, so the one
            question a reader most wants to ask -- *why did RCM decide that?* --
            was unanswerable from the archive.

            That is the same shape as E-54, where ``fast_innovation`` was
            computed every tick, consumed by two layers, and archived nowhere.
            It also contradicts assumption A-10, which defines explainability
            for this project as **decision provenance**: the inputs a decision
            was taken on, recorded beside it.
    """

    tick: TickId
    outcome: ArbitrationOutcome
    active_profile: ProfileId
    candidate_profile: ProfileId | None = None
    trust_score: float | None = None
    calibration_divergence_index: Probability | None = None
    signature: RuntimeContextSignature | None = None

    def __post_init__(self) -> None:
        """Validate the decision's numeric fields and cross-field consistency.

        Raises:
            NonFiniteValueError: If a present trust score is not finite.
            RangeViolationError: If a present CDI is outside ``[0, 1]``.
            ContractViolationError: If an outcome that requires a candidate has
                none.
        """
        if self.trust_score is not None:
            require_finite(self.trust_score, name="trust_score")
        if self.calibration_divergence_index is not None:
            require_probability(
                self.calibration_divergence_index, name="calibration_divergence_index"
            )
        requires_candidate = {
            ArbitrationOutcome.SHADOW_EXECUTION,
            ArbitrationOutcome.SWITCH_COMMITTED,
            ArbitrationOutcome.ROLLBACK,
        }
        if self.outcome in requires_candidate and self.candidate_profile is None:
            message = f"outcome {self.outcome.value} requires a candidate profile"
            raise ContractViolationError(message, context={"outcome": self.outcome.value})


def is_candidate_admissible(
    *,
    trust_score: float,
    threshold: float,
    is_valid: bool,
) -> bool:
    """Return whether a scored candidate may be committed.

    The executable form of RCM's hard admissibility rule
    ``T(c) >= tau AND val(c) == 1``. It is a conjunction on purpose: validity is
    a veto, not a weight, so no trust score however high can rescue a candidate
    that failed validation. A safety engineer reads this predicate as the single
    definition of "admissible candidate".

    Args:
        trust_score: The candidate's ``T(c)``.
        threshold: The admissibility threshold ``tau``, from configuration.
        is_valid: The binary validity ``val(c) == 1``.

    Returns:
        ``True`` only if the candidate is valid and its score meets the
        threshold.
    """
    return is_valid and trust_score >= threshold
