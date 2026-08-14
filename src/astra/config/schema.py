"""The configuration schema: every operating point, validated and typed.

The rule that shapes this whole module
--------------------------------------
**No safety threshold has a default.** The source documents never assign a
numeric value to theta-1/2/3, epsilon, gamma, tau or delta_CDI, and that is not
an oversight: those values can only be fixed empirically once the pipeline runs
against real scenarios. Shipping a plausible-looking default would let a run
proceed under a threshold nobody chose and nobody reviewed, and the resulting
number would then appear in a report as though it meant something.

So a missing safety threshold is a startup failure. That is assumption A-4, and
it is the single most important property of this file. Non-safety values --
log levels, directories, filter rates, buffer sizes -- do carry defaults,
because a wrong default there is an inconvenience rather than an unsound safety
claim.

Why pydantic here and frozen dataclasses elsewhere
--------------------------------------------------
Configuration is parsed once, at startup, from text a human wrote. That is
exactly the boundary pydantic is for: rich validation, and error messages that
name the file, the field and the constraint. The hot path never touches these
objects' validators again -- the settings are frozen after load and read as
plain attributes, which is O(1) and allocation-free.

Non-SI units at the boundary, SI everywhere else
------------------------------------------------
Humans write ``50`` for milliseconds and ``20`` for km/h; the pipeline computes
in seconds and m/s. Fields that a human authors are therefore named with their
non-SI unit (``staleness_budget_ms``) and exposed through an accessor that
converts once (:meth:`SensingSettings.staleness_budget`). The conversion happens
here, at the boundary, and never again -- which is the unit policy, applied to
configuration.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from astra.kernel.constants import (
    CONFIG_SCHEMA_VERSION,
    FAST_STATE_DIMENSION,
    FAST_STATE_FIELDS,
    SLOW_STATE_DIMENSION,
    SLOW_STATE_FIELDS,
)
from astra.kernel.enums import SensorModality
from astra.kernel.units import (
    Degrees,
    Hertz,
    KilometresPerHour,
    Metres,
    MetresPerSecond,
    MetresPerSecondSquared,
    Milliseconds,
    Probability,
    Radians,
    Seconds,
    degrees_to_radians,
    kmh_to_mps,
    ms_to_seconds,
)

__all__ = [
    "ArbitrationSettings",
    "AstraSettings",
    "Environment",
    "EstimationSettings",
    "FailSafeSettings",
    "GateSettings",
    "ObservabilitySettings",
    "SensingSettings",
    "ShieldSettings",
    "TrustSettings",
]

type Environment = Literal["development", "simulation", "certification"]
"""The operating environments. `certification` is the one a safety engineer edits."""

# A probability expressed in configuration. Bounds are enforced by pydantic so a
# malformed coverage level fails with a field-level message rather than at the
# first arithmetic use.
type UnitInterval = Annotated[float, Field(ge=0.0, le=1.0)]
type PositiveFloat = Annotated[float, Field(gt=0.0)]
type NonNegativeFloat = Annotated[float, Field(ge=0.0)]
type PositiveInt = Annotated[int, Field(gt=0)]
type NonNegativeInt = Annotated[int, Field(ge=0)]


class _Section(BaseModel):
    """Base for every configuration section.

    Frozen so that a component cannot mutate the operating point mid-run, and
    ``extra="forbid"`` so that a typo in a TOML key is a startup error instead of
    a silently ignored line. A misspelled safety threshold that is quietly
    dropped would leave the system running on a different value than the file
    appears to specify -- the worst possible failure mode for a config file.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=False)


class SensingSettings(_Section):
    """L1 -- the shared sensor bus.

    Attributes:
        staleness_budget_ms: The freshness budget behind FR1's 50 ms rule. A
            reading older than this marks its stream DEGRADED. Defaulted,
            because 50 ms is stated explicitly in the requirements rather than
            left to be determined empirically.
    """

    staleness_budget_ms: PositiveFloat = 50.0

    @property
    def staleness_budget(self) -> Seconds:
        """Return the staleness budget in SI seconds."""
        return ms_to_seconds(Milliseconds(self.staleness_budget_ms))


class EstimationSettings(_Section):
    """L2 -- the dual-rate unscented Kalman filter.

    Attributes:
        fast_rate_hz: The fast filter's rate. 20 Hz sets the control tick.
        slow_rate_hz: The slow filter's rate. 1 Hz in deployment, 0.1 Hz in the
            prototype -- both are configuration, not a contradiction between the
            documents (finding R-5).
        innovation_gate_gamma: The Mahalanobis threshold above which an
            innovation is flagged as anomalous. **No default**: it is one of the
            empirically determined safety thresholds of A-4.

            **It does not raise a fault, and this docstring said it did until
            11 August 2026.** The flag reaches exactly one consumer -- L3's
            classifier, which switches the Mondrian context class to
            ``DEGRADED_SENSOR`` -- so it changes which calibration window L6
            compares against and nothing else. The measurement is **not**
            rejected: ``update_fast`` fuses it first and computes the flag from
            the residual afterwards.

            Measured at the shipped value of 7.5, the flag fires on **one tick
            in every arm of the fault study including the control** -- tick 0,
            the plant's deliberate 1 m initial offset -- and is silent on every
            injected fault but the 25-sigma noise burst (E-105). It is a
            gross-outlier check, and every fault in that study is designed to be
            self-consistent.
        fast_process_noise: Diagonal of the fast filter's process noise ``Q_f``,
            one variance per field of
            :data:`~astra.kernel.constants.FAST_STATE_FIELDS`. **No default**:
            ``Q`` governs how quickly the filter trusts new measurements over
            its own model, so it sets the state estimate that all three gates
            read. It is determined empirically against ground truth (Phase 2)
            and shipping a plausible guess would put an unreviewed number under
            the whole safety argument.
        slow_process_noise: Diagonal of the slow filter's process noise ``Q_s``,
            one variance per field of
            :data:`~astra.kernel.constants.SLOW_STATE_FIELDS`. **No default**,
            for the same reason.
        yaw_rate_minimum_speed: Speed below which the yaw rate is taken as zero
            rather than computed from ``a_lat / v``. Guards the division at
            standstill, where the quotient is numerically unbounded and
            physically meaningless.
    """

    fast_rate_hz: PositiveFloat = 20.0
    slow_rate_hz: PositiveFloat = 1.0
    innovation_gate_gamma: PositiveFloat
    fast_process_noise: tuple[PositiveFloat, ...]
    slow_process_noise: tuple[PositiveFloat, ...]
    yaw_rate_minimum_speed: PositiveFloat = 0.1

    @field_validator("fast_process_noise")
    @classmethod
    def _fast_process_noise_matches_the_state(cls, value: tuple[float, ...]) -> tuple[float, ...]:
        """Validate that the fast process noise has one entry per state field.

        Args:
            value: The declared diagonal.

        Returns:
            The value, unchanged.

        Raises:
            ValueError: If the length does not match the fast state dimension.
        """
        if len(value) != FAST_STATE_DIMENSION:
            message = (
                f"fast_process_noise needs {FAST_STATE_DIMENSION} entries, one per "
                f"{FAST_STATE_FIELDS}, got {len(value)}"
            )
            raise ValueError(message)
        return value

    @field_validator("slow_process_noise")
    @classmethod
    def _slow_process_noise_matches_the_state(cls, value: tuple[float, ...]) -> tuple[float, ...]:
        """Validate that the slow process noise has one entry per state field.

        Args:
            value: The declared diagonal.

        Returns:
            The value, unchanged.

        Raises:
            ValueError: If the length does not match the slow state dimension.
        """
        if len(value) != SLOW_STATE_DIMENSION:
            message = (
                f"slow_process_noise needs {SLOW_STATE_DIMENSION} entries, one per "
                f"{SLOW_STATE_FIELDS}, got {len(value)}"
            )
            raise ValueError(message)
        return value

    @property
    def fast_rate(self) -> Hertz:
        """Return the fast filter rate."""
        return Hertz(self.fast_rate_hz)

    @property
    def slow_rate(self) -> Hertz:
        """Return the slow filter rate."""
        return Hertz(self.slow_rate_hz)

    @property
    def tick_period(self) -> Seconds:
        """Return the control period implied by the fast rate."""
        return Seconds(1.0 / self.fast_rate_hz)


class TrustSettings(_Section):
    """L3 -- the conformal Trust Module.

    Attributes:
        coverage_level: The conformal coverage ``1 - epsilon`` the Trust Module
            targets. **No default** (A-4).
        ensemble_size: Number of bootstrap models in the EnbPI ensemble.
        minimum_calibration_samples: Below this many residuals in a context
            class, the class-conditional quantile is not yet meaningful. The
            validation plan calls for at least 500 calibration samples per
            context.
    """

    coverage_level: UnitInterval
    ensemble_size: PositiveInt = 10
    minimum_calibration_samples: PositiveInt = 500
    calibration_window: PositiveInt = 500
    highway_speed_boundary_kmh: PositiveFloat

    @property
    def highway_speed_boundary(self) -> MetresPerSecond:
        """Return the urban/highway classification boundary in SI m/s."""
        return kmh_to_mps(KilometresPerHour(self.highway_speed_boundary_kmh))

    @property
    def coverage(self) -> Probability:
        """Return the coverage level as a probability."""
        return Probability(self.coverage_level)


class TwinSettings(_Section):
    """L5 -- the physics-informed digital twin.

    The twin's prediction is the right operand of the ICP non-conformity score
    ``alpha = |pi_prop - pi_hat| / sigma(x)``, so every value here shapes a gate
    input rather than a diagnostic. The empirical ones therefore follow the same
    no-default discipline as every other safety parameter (A-4).

    Attributes:
        physics_weight: Weight on the physics residual in the training loss. It
            sets how strongly the twin is held to Newtonian consistency versus
            fitting its training data, which is the whole point of a PINN rather
            than a plain regressor. **No default** (A-4).
        control_effectiveness: Row mapping a command vector to the lateral
            acceleration it produces, in the actuation space's channel order.
            This is a platform fact, not a core assumption, which is why it is
            configured rather than written into the layer -- NFR5. Its length
            must equal the actuation space dimension, checked at construction
            because the space is not known here. **No default** (A-4).
        hidden_width: Width of the network's single hidden layer. Architectural
            rather than empirical, so it carries a default.
        adaptation_buffer: Fresh measurements to accumulate before an EWC update
            fires. The validation plan specifies 50.
        adaptation_steps: Gradient steps taken per consolidation.
        seed: Seed for weight initialisation. Present because A-5 requires a run
            to be byte-reproducible, and a randomly initialised network would
            defeat that in the one layer whose output feeds a gate.
    """

    physics_weight: NonNegativeFloat
    control_effectiveness: list[float]
    hidden_width: PositiveInt = 32
    adaptation_buffer: PositiveInt = 50
    adaptation_steps: PositiveInt = 10
    seed: int = 0

    @field_validator("control_effectiveness")
    @classmethod
    def _effectiveness_is_finite_and_non_empty(cls, value: list[float]) -> list[float]:
        """Reject an empty or non-finite control-effectiveness row.

        Args:
            value: The configured row.

        Returns:
            The validated row.

        Raises:
            ValueError: If the row is empty or contains a non-finite entry. A
                NaN here would propagate silently into every prediction and
                therefore into every non-conformity score.
        """
        if not value:
            message = "twin.control_effectiveness must name at least one channel"
            raise ValueError(message)
        if not all(math.isfinite(entry) for entry in value):
            message = f"twin.control_effectiveness must be finite, got {value}"
            raise ValueError(message)
        return value


class GateSettings(_Section):
    """L6 -- the statistical (inductive conformal prediction) gate.

    Attributes:
        significance_epsilon: The conformal significance level ``epsilon``.
            **No default** (A-4).
        mmd_window: Number of innovation samples in the rolling window the
            maximum-mean-discrepancy covariate-shift detector operates over.
        mmd_threshold: The MMD value above which covariate shift is declared and
            ``epsilon`` is tightened. **No default** (A-4).
        shift_epsilon_multiplier: Factor applied to ``epsilon`` when shift is
            declared. Must be **at least 1**, and the direction matters more
            than the magnitude. The conformal acceptance region is
            ``{score <= q_{1-epsilon}}``, so a *smaller* epsilon raises the
            quantile and *widens* the region. Multiplying below 1 would
            therefore make the gate more permissive at exactly the moment the
            world stopped matching the calibration data, and nothing would
            raise: coverage would still be achieved, at a weaker level. **No
            default** (A-4).
    """

    significance_epsilon: UnitInterval
    mmd_window: PositiveInt = 100
    mmd_threshold: NonNegativeFloat
    shift_epsilon_multiplier: float = Field(ge=1.0)


class PhysicalGateSettings(_Section):
    """L7b -- the physical admissibility gate.

    Both bounds are rate limits rather than magnitude limits, and that is what
    separates this gate from the deterministic shield. L7a asks whether the
    vehicle is outside its envelope *now*; L7b asks whether the proposal demands
    a change that Newtonian mechanics cannot deliver in one tick. A command can
    be comfortably inside every hard bound and still be physically impossible to
    execute, and vice versa.

    Attributes:
        max_lateral_jerk: Largest admissible rate of change of lateral
            acceleration, in m/s^3. Tyres and suspension cannot transfer force
            instantaneously, so a command demanding a step change in lateral
            acceleration is asking for something no vehicle can do. Derived from
            the platform's suspension and tyre characterisation. **No default**
            (A-4).
        admissible_divergence: Largest admissible difference, in m/s^2, between
            the lateral acceleration the proposal implies and the one the twin
            predicts. This is the term through which twin drift becomes this
            gate's failure mode, which is what makes it structurally distinct
            from the shield. **No default** (A-4).
    """

    max_lateral_jerk_mps3: PositiveFloat
    admissible_divergence_mps2: PositiveFloat

    @property
    def max_lateral_jerk(self) -> float:
        """Return the lateral jerk bound in m/s^3."""
        return self.max_lateral_jerk_mps3

    @property
    def admissible_divergence(self) -> MetresPerSecondSquared:
        """Return the admissible model divergence in m/s^2."""
        return MetresPerSecondSquared(self.admissible_divergence_mps2)


class ShieldSettings(_Section):
    """L7a -- the Hard Safety Shield's three deterministic bounds.

    Every value here is a hard physical or legal limit, so each is required.
    A shield running on invented bounds is worse than no shield: it produces
    PASS verdicts that carry the authority of a deterministic check.

    Attributes:
        legal_speed_limit_kmh: ``v_legal``, the legal speed bound, in km/h as a
            human would write it.
        friction_margin: Multiplier applied to the estimated road friction in
            ``a_lat <= margin * mu * g``. Below 1.0 it is a safety margin.
        minimum_stopping_distance_m: Floor on ``d_stop`` regardless of speed,
            covering reaction and actuation latency.
        assured_clear_distance_m: ``d_avail`` -- the clear distance ahead the
            operational design domain guarantees. The shield requires the
            stopping distance implied by the current speed and the *estimated*
            road friction to fit inside it.

            This is a **certified ODD parameter, not a perception output.** The
            fast state vector carries no distance-to-obstacle, and SI-1 and SI-2
            forbid the shield from re-reading the sensors to find one, so the
            bound it can honestly enforce is against the distance the ODD
            assures rather than against a measured one. Sourcing ``d_avail``
            from perception would require extending the state vector, which is
            a visible architectural change and is recorded as Phase 3 debt.
        lateral_corridor_half_width_m: How far the vehicle may be from the
            centreline of the path it is permitted to occupy.

            Deliberately *not* called a lane. A lane is a road concept and NFR5
            keeps road concepts out of the core; a warehouse AGV has a permitted
            corridor just as a car has a lane, and the bound is the same
            quantity in both. The adapter decides what the corridor is.

            Added 5 August 2026, after a 100,000-tick run in which the vehicle
            travelled 2.9 km outside a corridor 1.75 m wide with a **0.00% veto
            rate and a Trust Index of exactly 1.00**. No gate in Core-B measured
            where the vehicle was: this one bounded speed, lateral acceleration
            and stopping distance; L7b bounds jerk and divergence from the twin;
            L6 scores the proposal against the twin. A departure was invisible
            to all three, which meant the three-gate argument did not cover the
            hazard that actually occurred.
    """

    legal_speed_limit_kmh: PositiveFloat
    friction_margin: UnitInterval
    minimum_stopping_distance_m: NonNegativeFloat
    assured_clear_distance_m: PositiveFloat
    lateral_corridor_half_width_m: PositiveFloat

    @property
    def legal_speed_limit(self) -> MetresPerSecond:
        """Return ``v_legal`` in SI metres per second."""
        return kmh_to_mps(KilometresPerHour(self.legal_speed_limit_kmh))

    @property
    def minimum_stopping_distance(self) -> Metres:
        """Return the stopping-distance floor in metres."""
        return Metres(self.minimum_stopping_distance_m)

    @property
    def assured_clear_distance(self) -> Metres:
        """Return the ODD's assured clear distance ahead, in metres."""
        return Metres(self.assured_clear_distance_m)

    @property
    def lateral_corridor_half_width(self) -> Metres:
        """Return the permitted lateral corridor half-width, in metres."""
        return Metres(self.lateral_corridor_half_width_m)


class FailSafeSettings(_Section):
    """L8 -- the fail-safe state machine's thresholds and speed caps.

    **The thresholds are durations wearing counts.** The out-of-distribution
    counter increments on a VETO and decrements on a PASS, so a threshold
    divided by ``estimation.fast_rate_hz`` is how long sustained refusal must
    last before the posture escalates. Choosing them as bare integers is how
    ``ood_threshold_halt = 20`` came to mean "declare a terminal pull-over after
    one second", which is shorter than a legitimate recovery from 1 m off the
    lane centre -- see the note in ``config/environments/simulation.toml``.

    Set them by deciding the duration first.

    Attributes:
        ood_threshold_degraded: ``theta-1``. OOD counter above this enters
            DEGRADED. **No default** (A-4).
        ood_threshold_limp: ``theta-2``. Enters LIMP. **No default** (A-4).
        ood_threshold_halt: ``theta-3``. Enters HALT, which is terminal --
            :meth:`~astra.layers.l8_failsafe.machine.FailSafeStateMachine.reset`
            is its only exit. A threshold reachable by a transient therefore
            makes the transient permanent. **No default** (A-4).
        degraded_speed_cap_kmh: Speed cap imposed in DEGRADED. Reported to L9
            and, today, enforced on no actuator -- see
            :class:`~astra.kernel.enums.FailSafeState`.
        limp_speed_cap_kmh: Speed cap imposed in LIMP. The same caveat applies.
        integrity_threshold_degraded: ``phi-1``. **Sensor-integrity** counter
            above this enters DEGRADED. **No default** (A-4).
        integrity_threshold_limp: ``phi-2``. Enters LIMP. **No default** (A-4).
        integrity_threshold_halt: ``phi-3``. Enters HALT. **No default** (A-4).
        critical_modalities: The modalities whose health drives the integrity
            counter. A modality **outside** this set is still recorded in every
            frame-health map and every audit record -- it is simply not counted
            as a reason to change the vehicle's posture.

            **No default** (A-4), because naming a modality non-critical is a
            safety claim: that nothing the safety argument depends on reads it.
            Get it wrong and the vehicle drives on a dead sensor it needed.

            **Every shipped profile lists all five**, which is exactly the
            behaviour before this field existed. The prototype deliberately does
            **not** use the escape hatch it provides: its extractor happens to
            read only the IMU, so declaring the other four non-critical would be
            *true of this build* -- and true only because of OD-15, which is a
            defect to fix rather than a property to encode in a safety file
            (ADR-0028).
        integrity_tolerated_faults: How many modalities may be unhealthy
            *simultaneously* before the integrity counter rises. **No
            default** (A-4), and **zero is the only value a deployment
            without redundancy may set**.

            Raising it above zero is a *claim*: that the sensor set carries
            enough independent measurements of each quantity to keep working
            with that many of them lying, and that something excludes the
            liar from the fusion. A deployment fusing three position
            channels by median tolerates one; a deployment with one channel
            per quantity tolerates none, and setting one there would mean
            ignoring the only sensor it has (ADR-0027).
        capabilities: What each autonomy function requires, as
            ``{name: modalities}``. A function is **withdrawn** for as long as
            any modality it requires is worse than ``HEALTHY``.

            **This is the second axis, and it is orthogonal to everything above
            it.** The thresholds and ``critical_modalities`` answer *how bad is
            this getting* with a severity level; this answers *what is broken*
            with a set of lost functions. One integer cannot hold both, and
            ADR-0029 is the record of finding that out: before it, a camera
            fault could stop the vehicle or do nothing at all, and could not do
            the one useful thing -- stop offering lane changes and drive on.

            The two axes compose by **intersection**: a capability is available
            only where the posture allows it *and* its sensors support it.
            Withdrawal can therefore only ever subtract. A capability set that
            could *grant* something the posture forbids would be a fourth gate
            with veto-override authority, which SI-3 forbids.

            Being orthogonal to ``critical_modalities`` is the point. A camera
            may be non-critical -- never a reason to slow down -- *and* required
            by ``lane_change``, so losing it withdraws lane changes and leaves
            the vehicle driving. Neither field alone can express that.

            The names are **opaque to L8**, which is what keeps NFR5: the layer
            knows that capabilities exist and get withdrawn, never what a lane
            is. Only a domain adapter reads the names.

            **Defaults to empty**, and that is not an A-4 exception. An empty
            ``critical_modalities`` would disable a counter that already
            escalates, so it is a fail-open claim and is refused. An empty
            ``capabilities`` withdraws nothing, which is precisely the behaviour
            shipped before this field existed -- an absence of a claim rather
            than a weak one. ``benchmarks/commissioning.py`` prints the
            resulting degradation table, so a deployment that declared none can
            see that it declared none.

    **Why there are two sets of thresholds, and why the second set is tighter.**
    The ``ood_*`` thresholds answer *"how long should sustained refusal be
    tolerated?"*, and their floor is set by a legitimate recovery: a vehicle 1 m
    off the lane centre needs ~21 vetoed ticks to correct, so a threshold below
    that turns a correction into a pull-over. The ``integrity_*`` thresholds
    answer a different question -- *"how long should a sensor channel be allowed
    to say nothing?"* -- and it has no legitimate answer above a fraction of a
    second. There is no benign reason for a modality to stop publishing.

    Sharing one set would have forced the tighter question to accept the looser
    answer, and measured (E-46) the loose answer is too slow: the vehicle leaves
    its corridor 73 ticks after an IMU dropout opens, and ``ood_threshold_halt``
    is 100. See ADR-0024.
    """

    ood_threshold_degraded: PositiveInt
    ood_threshold_limp: PositiveInt
    ood_threshold_halt: PositiveInt
    degraded_speed_cap_kmh: PositiveFloat
    limp_speed_cap_kmh: PositiveFloat
    integrity_threshold_degraded: PositiveInt
    integrity_threshold_limp: PositiveInt
    integrity_threshold_halt: PositiveInt
    integrity_tolerated_faults: NonNegativeInt
    critical_modalities: tuple[SensorModality, ...]
    capabilities: tuple[tuple[str, tuple[SensorModality, ...]], ...] = ()

    @field_validator("capabilities", mode="before")
    @classmethod
    def _capabilities_are_sorted_pairs(cls, value: object) -> object:
        """Normalise the TOML table into sorted name/requirement pairs.

        The file declares a table because ``lane_change = ["CAMERA"]`` is what a
        safety engineer can read, and the readability of that table is half the
        point of the feature. The field stores **pairs** because a ``dict`` on a
        frozen settings model is mutable through the attribute, and because
        pydantic can serialise neither it nor a ``mappingproxy`` -- the config
        hash that pins a run to its operating point is computed by serialising
        this model, so an unserialisable field would have taken the provenance
        record down with it.

        Sorting makes the hash independent of the order the keys happen to
        appear in the file. Two profiles that declare the same capabilities
        differently ordered are the same operating point and must hash alike.

        Args:
            value: Whatever the loader produced -- a table from TOML, or pairs
                from a caller constructing settings directly.

        Returns:
            Sorted pairs, or the value untouched when it is not a mapping.
        """
        if isinstance(value, Mapping):
            return tuple(sorted((str(name), tuple(required)) for name, required in value.items()))
        return value

    @field_validator("capabilities")
    @classmethod
    def _every_capability_requires_a_modality(
        cls, value: tuple[tuple[str, tuple[SensorModality, ...]], ...]
    ) -> tuple[tuple[str, tuple[SensorModality, ...]], ...]:
        """Validate that no capability declares an empty requirement.

        A capability requiring nothing can never be withdrawn: the derivation
        intersects its requirement with the unhealthy set, and an empty
        requirement intersects nothing. It would sit in the commissioning table
        looking like a modelled function and would survive the loss of every
        sensor on the vehicle.

        That is the same fail-open shape as an empty ``critical_modalities`` and
        it is refused for the same reason -- a capability nobody can withdraw is
        indistinguishable, in the record, from one that was never at risk.

        Args:
            value: The declared capability requirements.

        Returns:
            The value, unchanged.

        Raises:
            ValueError: If any capability requires no modality, or is unnamed.
        """
        for name, required in value:
            if not name.strip():
                message = "failsafe.capabilities contains an unnamed capability"
                raise ValueError(message)
            if not required:
                message = (
                    f"failsafe.capabilities[{name!r}] requires no modality; "
                    "a capability that requires nothing can never be withdrawn"
                )
                raise ValueError(message)
        return value

    @field_validator("critical_modalities")
    @classmethod
    def _at_least_one_modality_is_critical(
        cls, value: tuple[SensorModality, ...]
    ) -> tuple[SensorModality, ...]:
        """Validate that the critical set is not empty.

        An empty set silently disables the sensor-integrity counter: nothing
        would ever be counted, the machine would never escalate on sensor
        health, and every run would look healthy. That is a fail-open mode
        reachable by deleting a line from a TOML file, which is precisely the
        failure ``extra="forbid"`` and A-4 exist to prevent elsewhere.

        Args:
            value: The declared critical modalities.

        Returns:
            The value, unchanged.

        Raises:
            ValueError: If the set is empty.
        """
        if not value:
            message = (
                "failsafe.critical_modalities must name at least one modality; "
                "an empty set disables the integrity counter entirely"
            )
            raise ValueError(message)
        return value

    @field_validator("integrity_threshold_halt")
    @classmethod
    def _integrity_thresholds_must_be_ordered(cls, value: int, info: object) -> int:
        """Validate that the three integrity thresholds increase with severity.

        Same reasoning as :meth:`_thresholds_must_be_ordered`, and it is a
        separate validator rather than a shared one because the two triples are
        independent operating points: nothing requires them to relate, and a
        validator that compared them would invent a constraint the architecture
        does not have.

        Args:
            value: The HALT threshold under validation.
            info: Pydantic's validation context, carrying the already-validated
                fields.

        Returns:
            The value, unchanged.

        Raises:
            ValueError: If the thresholds are not strictly increasing.
        """
        data = getattr(info, "data", {})
        degraded = data.get("integrity_threshold_degraded")
        limp = data.get("integrity_threshold_limp")
        if degraded is not None and limp is not None and not degraded < limp < value:
            message = (
                f"sensor-integrity thresholds must strictly increase with severity: "
                f"phi1={degraded} < phi2={limp} < phi3={value}"
            )
            raise ValueError(message)
        return value

    @field_validator("ood_threshold_halt")
    @classmethod
    def _thresholds_must_be_ordered(cls, value: int, info: object) -> int:
        """Validate that the three OOD thresholds increase with severity.

        Out-of-order thresholds would make a state unreachable: if theta-2 were
        below theta-1, the machine would jump past DEGRADED and the graduated
        response the architecture promises would not exist.

        Args:
            value: The HALT threshold under validation.
            info: Pydantic's validation context, carrying the already-validated
                fields.

        Returns:
            The value, unchanged.

        Raises:
            ValueError: If the thresholds are not strictly increasing.
        """
        data = getattr(info, "data", {})
        degraded = data.get("ood_threshold_degraded")
        limp = data.get("ood_threshold_limp")
        if degraded is not None and limp is not None and not degraded < limp < value:
            message = (
                f"fail-safe thresholds must strictly increase with severity: "
                f"theta1={degraded} < theta2={limp} < theta3={value}"
            )
            raise ValueError(message)
        return value

    @property
    def degraded_speed_cap(self) -> MetresPerSecond:
        """Return the DEGRADED speed cap in SI metres per second."""
        return kmh_to_mps(KilometresPerHour(self.degraded_speed_cap_kmh))

    @property
    def limp_speed_cap(self) -> MetresPerSecond:
        """Return the LIMP speed cap in SI metres per second."""
        return kmh_to_mps(KilometresPerHour(self.limp_speed_cap_kmh))


class ArbitrationSettings(_Section):
    """L9 -- Runtime Calibration Management.

    Attributes:
        trust_threshold_tau: ``tau``, the admissibility threshold in
            ``T(c) >= tau AND val(c) = 1``. **No default** (A-4).
        divergence_limit_delta: ``delta_CDI``, the Calibration Divergence Index
            above which a staged switch rolls back. **No default** (A-4).
        exploration_speed_fraction: Fraction of the nearest certified maximum
            speed that bounded safe exploration may use. The architecture
            specifies 50%.
        exploration_steering_limit_deg: The +-15 degree steering limit during
            bounded safe exploration, in degrees as the documents state it.
        exploration_permits_lane_change: Whether lane changes are allowed during
            exploration. The architecture says they are not; it is configurable
            so the ablation study can demonstrate why.
    """

    trust_threshold_tau: float
    divergence_limit_delta: UnitInterval
    exploration_speed_fraction: UnitInterval = 0.5
    exploration_steering_limit_deg: PositiveFloat = 15.0
    exploration_permits_lane_change: bool = False

    @property
    def exploration_steering_limit(self) -> Radians:
        """Return the exploration steering limit in SI radians."""
        return degrees_to_radians(Degrees(self.exploration_steering_limit_deg))


class ObservabilitySettings(_Section):
    """Audit logging and diagnostic logging.

    Attributes:
        log_directory: Root under which each run's evidence directory is created.
        log_level: Diagnostic logging level. Distinct from audit severity: a
            component silent in the console may still emit SAFETY_CRITICAL audit
            records.
        audit_queue_size: Bound on the non-blocking audit queue. Bounded rather
            than infinite so that a stalled writer surfaces as a reported drop
            instead of unbounded memory growth on a real-time system.
        fsync_each_record: Whether to fsync after every audit record. Durable
            but slow; the background writer means it never blocks a tick either
            way (SI-8).
    """

    log_directory: str = "var/runs"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    audit_queue_size: PositiveInt = 10_000
    fsync_each_record: bool = False


class AstraSettings(BaseSettings):
    """The complete, validated, startup-frozen configuration for one run.

    Frozen after construction: an operating point that could change mid-run
    would make the configuration hash stamped on every decision record a lie,
    and that hash is what ties a reported number back to the conditions that
    produced it.

    Attributes:
        schema_version: Must equal
            :data:`~astra.kernel.constants.CONFIG_SCHEMA_VERSION`. A file from a
            different schema is refused rather than best-effort interpreted.
        environment: Which operating environment this configuration describes.
        sensing: L1 settings.
        estimation: L2 settings.
        trust: L3 settings.
        twin: L5 settings.
        gate: L6 settings.
        physical: L7b settings.
        shield: L7a settings.
        failsafe: L8 settings.
        arbitration: L9 settings.
        observability: Logging and audit settings.
    """

    model_config = SettingsConfigDict(
        frozen=True,
        extra="forbid",
        env_prefix="ASTRA_",
        env_nested_delimiter="__",
        case_sensitive=False,
    )

    schema_version: int
    environment: Environment
    sensing: SensingSettings = SensingSettings()
    estimation: EstimationSettings
    trust: TrustSettings
    twin: TwinSettings
    gate: GateSettings
    physical: PhysicalGateSettings
    shield: ShieldSettings
    failsafe: FailSafeSettings
    arbitration: ArbitrationSettings
    observability: ObservabilitySettings = ObservabilitySettings()

    @field_validator("schema_version")
    @classmethod
    def _schema_version_is_supported(cls, value: int) -> int:
        """Reject a configuration written against a different schema.

        Args:
            value: The declared schema version.

        Returns:
            The value, unchanged.

        Raises:
            ValueError: If the version is not the one this build supports.
        """
        if value != CONFIG_SCHEMA_VERSION:
            message = (
                f"configuration schema version {value} is not supported by this build, "
                f"which requires version {CONFIG_SCHEMA_VERSION}"
            )
            raise ValueError(message)
        return value
