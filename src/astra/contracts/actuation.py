"""Actuation contracts: the command space and the commands that move through it.

Why the actuation space is a value, not a set of constants
----------------------------------------------------------
NFR5 requires the architecture to be domain-independent: a new operational
domain -- a different vehicle, or a non-automotive plant entirely -- must be
supported by adding configuration, never by editing the core. The single place
the pipeline would otherwise hard-code a vehicle assumption is the shape of the
actuator command: "throttle in [0, 1], brake in [0, 1], steer in [-0.5, 0.5]
rad" is a fact about *one* platform.

:class:`ActuationSpace` lifts that fact out of the code and into a configured
value. The pipeline reasons about "a command in the actuation space" and asks
the space itself whether a vector is admissible; it never names a channel. The
automotive adapter constructs the concrete space from a certified profile, and
a different platform supplies a different space without a line of core code
changing.

Why several command types rather than one
-----------------------------------------
A raw :class:`ControlCommand` carries no provenance. But in ASTRA *where a
command came from* is a safety-relevant fact: a command proposed by the
untrusted Core-A agent, a command predicted by the digital twin, and the single
command L9 is authorised to issue are three different things with three
different trust levels, and collapsing them into one type would make separation
invariant SI-7 (only L9 may issue) unenforceable. Each stage therefore has its
own record, and :class:`IssuedCommand` is the only one that records an issuer --
and checks it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, unique
from typing import TYPE_CHECKING

from astra.kernel.enums import LayerId
from astra.kernel.errors import ContractViolationError, InvariantViolationError
from astra.kernel.validation import require_dimension, require_finite

if TYPE_CHECKING:
    from collections.abc import Sequence

    from astra.kernel.identifiers import ComponentId, TickId
    from astra.kernel.time import Instant

__all__ = [
    "ActuationChannel",
    "ActuationSpace",
    "CommandOrigin",
    "ControlCommand",
    "IssuedCommand",
    "PredictedCommand",
    "ProposedCommand",
]


@unique
class CommandOrigin(StrEnum):
    """How a command that reached the actuation boundary came to exist.

    Recorded on every issued command so that the audit log can answer, for any
    tick, *why* the vehicle did what it did: it followed the learned policy, it
    fell back to the deterministic controller, it was speed-limited by the FSM,
    or it was produced by bounded safe exploration when no certified profile
    applied. This is decision provenance in the sense of finding R-7 -- the
    project's definition of explainability -- not model-internal attribution.
    """

    PROPOSED = "PROPOSED"
    """The learned Core-A policy's command passed every gate unmodified."""

    FALLBACK_PID = "FALLBACK_PID"
    """The deterministic PID controller governed, because a gate vetoed or the FSM left NOMINAL."""

    SPEED_CAPPED = "SPEED_CAPPED"
    """The fail-safe speed cap altered this command.

    Propulsion withdrawn and braking applied because the vehicle was at or above
    the ceiling the L8 state machine imposes. Recorded **only when the cap
    actually changed the vector**, so the label distinguishes a capped command
    from one merely issued while a cap was in force.

    It did not, until 6 August 2026. The cap was one branch among four,
    reachable only on a tick that was neither blocked nor exploring, and that
    branch clamped to the actuation space exactly as the uncapped branch did --
    so a ``SPEED_CAPPED`` record described a vector bit-identical to a
    ``PROPOSED`` one. In a 100,000-tick run the vehicle held 17.2 m/s in HALT,
    whose cap is 0.0 m/s, with 99,000 ticks labelled capped. The cap is now
    applied to whatever governed, last, because a posture is not a branch."""

    EXPLORATION_BOUNDED = "EXPLORATION_BOUNDED"
    """A bounded safe-exploration command, issued when no admissible profile was found."""

    RATE_LIMITED = "RATE_LIMITED"
    """The largest step toward a vetoed proposal that the jerk bound permits.

    Issued when L7b refused a proposal solely because the change in lateral
    acceleration it demanded was too fast. **The veto stands and the proposal is
    not issued**; what goes out is a different command, derived from the bound
    that refused it and therefore admissible under that bound by construction.

    It exists because the alternative was a deadlock. The fallback commands zero
    steering, so under a sustained veto the vehicle's lateral acceleration is
    pinned at zero, every correction the proposer offers is a step too large
    from there, and the veto that follows re-establishes the condition that
    caused it. Measured: the vehicle left the lane and never returned, at 2.9 km
    by tick 100,000, under three different policies. See ADR-0017."""


@dataclass(frozen=True, slots=True)
class ActuationChannel:
    """One named, bounded, SI-typed degree of freedom of the actuator.

    Attributes:
        name: Stable identifier, e.g. ``"steer"``. Appears in audit records, so
            it is part of the evidence schema and must not be renamed casually.
        lower: Inclusive minimum admissible value, in the channel's SI unit.
        upper: Inclusive maximum admissible value, in the channel's SI unit.
        unit: Human-readable SI unit label for diagnostics only, e.g. ``"rad"``
            or ``"m/s^2"``. Never parsed; the pipeline's arithmetic is unitless
            float and the unit safety lives in the surrounding NewType aliases.
    """

    name: str
    lower: float
    upper: float
    unit: str

    def __post_init__(self) -> None:
        """Validate that the channel describes a non-empty, finite interval.

        Raises:
            ContractViolationError: If the name is empty, a bound is not finite,
                or the lower bound exceeds the upper bound.
        """
        if not self.name:
            message = "an actuation channel must have a non-empty name"
            raise ContractViolationError(message)
        require_finite(self.lower, name=f"{self.name}.lower")
        require_finite(self.upper, name=f"{self.name}.upper")
        if self.lower > self.upper:
            message = f"channel {self.name!r} has lower {self.lower} above upper {self.upper}"
            raise ContractViolationError(
                message, context={"channel": self.name, "lower": self.lower, "upper": self.upper}
            )

    def contains(self, value: float) -> bool:
        """Return whether a value lies within this channel's inclusive bounds.

        Args:
            value: The candidate value in the channel's SI unit.

        Returns:
            ``True`` if ``lower <= value <= upper``. A non-finite value is never
            contained, so a NaN cannot slip through a bounds check.
        """
        return bool(self.lower <= value <= self.upper)

    def clamp(self, value: float) -> float:
        """Return the value confined to this channel's bounds.

        Args:
            value: The value to confine, in the channel's SI unit.

        Returns:
            ``value`` limited to ``[lower, upper]``.

        Raises:
            NonFiniteValueError: If the value is NaN or infinite; clamping a NaN
                would silently produce a bound and hide the fault.
        """
        require_finite(value, name=f"{self.name}.value")
        return min(max(value, self.lower), self.upper)


@dataclass(frozen=True, slots=True)
class ActuationSpace:
    """The ordered set of actuator channels a command is a vector over.

    Constructed once, from a certified profile, at the adapter boundary. Every
    :class:`ControlCommand` is validated against it, which is the mechanism that
    keeps the pipeline free of any hard-coded platform assumption.

    Attributes:
        channels: The channels in a fixed order. A command's values are
            positionally aligned to this order, so reordering the channels
            reinterprets every stored command -- which is why the order is part
            of the contract and not an implementation detail.
    """

    channels: tuple[ActuationChannel, ...]

    def __post_init__(self) -> None:
        """Validate that the space is non-empty and has unique channel names.

        Raises:
            ContractViolationError: If there are no channels, or two channels
                share a name.
        """
        if not self.channels:
            message = "an actuation space must define at least one channel"
            raise ContractViolationError(message)
        names = [channel.name for channel in self.channels]
        if len(names) != len(set(names)):
            message = "actuation channel names must be unique"
            raise ContractViolationError(message, context={"names": names})

    @property
    def dimension(self) -> int:
        """Return the number of channels, i.e. the length of a command vector."""
        return len(self.channels)

    @property
    def names(self) -> tuple[str, ...]:
        """Return the channel names in their canonical order."""
        return tuple(channel.name for channel in self.channels)

    def channel(self, name: str) -> ActuationChannel:
        """Return the channel with a given name.

        Args:
            name: The channel name to look up.

        Returns:
            The matching channel.

        Raises:
            ContractViolationError: If no channel has that name.
        """
        for channel in self.channels:
            if channel.name == name:
                return channel
        message = f"{name!r} is not a channel of this actuation space"
        raise ContractViolationError(message, context={"name": name, "known": list(self.names)})

    def contains(self, values: Sequence[float]) -> bool:
        """Return whether a vector is admissible in every channel.

        Args:
            values: A vector positionally aligned to :attr:`channels`.

        Returns:
            ``True`` if the vector has the right dimension and each component is
            within its channel's bounds.
        """
        if len(values) != self.dimension:
            return False
        return all(
            channel.contains(value) for channel, value in zip(self.channels, values, strict=True)
        )

    def clamp(self, values: Sequence[float]) -> tuple[float, ...]:
        """Return the vector with each component confined to its channel bounds.

        The operation the L8 state machine performs when it applies a speed cap
        and the operation bounded safe exploration performs on its limited
        command envelope.

        Args:
            values: A vector positionally aligned to :attr:`channels`.

        Returns:
            The clamped vector.

        Raises:
            DimensionMismatchError: If the vector's length is not the space
                dimension.
        """
        checked = require_dimension(values, expected=self.dimension, name="command")
        return tuple(
            channel.clamp(value) for channel, value in zip(self.channels, checked, strict=True)
        )


@dataclass(frozen=True, slots=True)
class ControlCommand:
    """A dimensioned vector in an actuation space, with no provenance of its own.

    Deliberately does *not* reject an out-of-bounds vector at construction. A
    command the untrusted proposer offers may violate a bound -- detecting
    exactly that is the Hard Safety Shield's job -- and a type that could not
    represent an inadmissible proposal would make the violation it is meant to
    catch unrepresentable. Admissibility is therefore a question asked of a
    command (:meth:`is_admissible`), not a precondition of building one.

    Attributes:
        space: The actuation space this command is a vector over.
        values: The commanded value per channel, positionally aligned to
            ``space.channels``.
    """

    space: ActuationSpace
    values: tuple[float, ...]

    def __post_init__(self) -> None:
        """Validate dimension and finiteness against the space.

        Raises:
            DimensionMismatchError: If the vector's length is not the space
                dimension.
            NonFiniteValueError: If any component is NaN or infinite.
        """
        checked = require_dimension(self.values, expected=self.space.dimension, name="command")
        for channel, value in zip(self.space.channels, checked, strict=True):
            require_finite(value, name=f"command.{channel.name}")
        object.__setattr__(self, "values", checked)

    def value_of(self, channel_name: str) -> float:
        """Return the commanded value for one named channel.

        Args:
            channel_name: A channel name from the space.

        Returns:
            The commanded value in that channel's SI unit.

        Raises:
            ContractViolationError: If the space has no such channel.
        """
        try:
            index = self.space.names.index(channel_name)
        except ValueError:
            message = f"{channel_name!r} is not a channel of this actuation space"
            raise ContractViolationError(
                message, context={"name": channel_name, "known": list(self.space.names)}
            ) from None
        return self.values[index]

    def is_admissible(self) -> bool:
        """Return whether every component lies within its channel bounds.

        Returns:
            ``True`` if the command could be issued without violating a bound.
        """
        return self.space.contains(self.values)

    def clamped(self) -> ControlCommand:
        """Return a copy with each component confined to its channel bounds.

        Returns:
            A new command whose values are within the space, leaving this one
            unchanged.
        """
        return ControlCommand(space=self.space, values=self.space.clamp(self.values))


@dataclass(frozen=True, slots=True)
class ProposedCommand:
    """The command Core-A (L4) offers for a tick: ``pi_prop``.

    This is the untrusted proposal. It crosses the one-way Core-A -> Core-B
    channel (SI-5) and is the left operand of the ICP non-conformity score
    ``alpha = |pi_prop - pi_hat| / sigma(x)``. It carries the originating
    component so that a proposal can be attributed, but it grants no authority:
    nothing downstream may issue it without a verdict.

    Attributes:
        tick: The control tick this proposal is for.
        proposed_at: When the proposer emitted it.
        command: The proposed vector in the actuation space.
        origin: Whether this came from the learned policy or the fallback PID.
        source: The Core-A component that produced it.
    """

    tick: TickId
    proposed_at: Instant
    command: ControlCommand
    origin: CommandOrigin
    source: ComponentId

    def __post_init__(self) -> None:
        """Validate that the proposal originates in Core-A.

        Raises:
            ContractViolationError: If the proposing component is not the
                Core-A proposer layer. A proposal attributed to a Core-B layer
                would misrepresent the trust boundary in the evidence log.
        """
        if self.source.layer is not LayerId.L4_CORE_A_CMDP:
            message = f"a proposed command must originate in L4, not {self.source.layer.value}"
            raise ContractViolationError(
                message, layer=self.source.layer, context={"source": str(self.source)}
            )


@dataclass(frozen=True, slots=True)
class PredictedCommand:
    """The digital twin's (L5) one-step prediction ``pi_hat_{t+1}``.

    The twin answers "given the current state, what command does the modelled
    physics expect next?" The magnitude by which the untrusted proposal departs
    from this prediction, normalised by state uncertainty, is the ICP gate's
    non-conformity score. The prediction is therefore a safety input and gets a
    record of its own rather than being an anonymous array inside the twin.

    Attributes:
        tick: The control tick this prediction is for.
        predicted_at: When the twin produced it.
        command: The predicted vector in the actuation space.
        source: The L5 component that produced it.
    """

    tick: TickId
    predicted_at: Instant
    command: ControlCommand
    source: ComponentId

    def __post_init__(self) -> None:
        """Validate that the prediction originates in the digital twin.

        Raises:
            ContractViolationError: If the predicting component is not L5.
        """
        if self.source.layer is not LayerId.L5_PINN_TWIN:
            message = f"a predicted command must originate in L5, not {self.source.layer.value}"
            raise ContractViolationError(
                message, layer=self.source.layer, context={"source": str(self.source)}
            )


@dataclass(frozen=True, slots=True)
class IssuedCommand:
    """The single command sent to the actuators for a tick. Only L9 may build one.

    This record is the executable form of separation invariant SI-7: sole
    actuation authority. Construction refuses any issuer whose layer is not L9,
    and refuses any command that is not admissible in its own actuation space --
    an out-of-bounds command must never reach an actuator, whatever produced it.
    The two checks together make "the vehicle did something inadmissible, issued
    by something other than the arbitrator" an unconstructable state rather than
    a bug to be found in review.

    Attributes:
        tick: The control tick this command was issued for.
        issued_at: When L9 committed it.
        command: The admissible vector sent to the actuators.
        origin: Why this command exists (policy, fallback, cap, exploration).
        issuer: The component issuing it. Must be an L9 instance.
    """

    tick: TickId
    issued_at: Instant
    command: ControlCommand
    origin: CommandOrigin
    issuer: ComponentId

    def __post_init__(self) -> None:
        """Enforce sole actuation authority and command admissibility.

        Raises:
            InvariantViolationError: If the issuer is not an L9 component. This
                is SI-7 and is unrecoverable: a command issued by anything else
                means the safety argument no longer describes the running
                system.
            ContractViolationError: If the command is not admissible in its
                actuation space.
        """
        if self.issuer.layer is not LayerId.L9_RCM:
            message = (
                f"only L9 (RCM) may issue an actuator command; "
                f"{self.issuer.layer.value} attempted to (SI-7)"
            )
            raise InvariantViolationError(
                message, layer=self.issuer.layer, context={"issuer": str(self.issuer)}
            )
        if not self.command.is_admissible():
            message = "an issued command must be admissible in its actuation space"
            raise ContractViolationError(
                message,
                layer=LayerId.L9_RCM,
                context={"values": list(self.command.values)},
            )
