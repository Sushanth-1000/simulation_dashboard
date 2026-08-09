"""The four hard bounds, and why they are the ones that matter.

What this layer may look at
----------------------------
The fast state estimate, the slow degradation estimate, and configuration.
Nothing else. Not the twin's prediction, not the conformal non-conformity score,
not the Trust Index, not the fail-safe state. Every one of those omissions is
load-bearing: a gate that consulted another gate's evidence would fail whenever
that evidence was wrong, and the three gates would stop being independent in
exactly the way the architecture claims they are.

The signature enforces most of this. :meth:`HardSafetyShield.evaluate` accepts a
proposal, a state and a degradation estimate; there is no parameter through
which a prediction or a score could arrive.

The four bounds
---------------
**1. Tyre friction.** ``|a_lat| <= margin * mu_road * g``

The lateral acceleration a tyre can deliver is bounded by the friction available
between it and the road. Exceed it and the vehicle slides regardless of what any
controller intended. Using the *estimated* ``mu_road`` from the slow filter
rather than a fixed constant is what makes this bound adaptive: the same command
that is comfortably safe on dry tarmac is a loss of control on ice, and a shield
with a hard-coded friction figure would pass it.

**2. Stopping distance.** ``d_stop(v, mu) <= d_avail``

with ``d_stop = d_min + v^2 / (2 * margin * mu * g)``. The first term covers
reaction and actuation latency; the second is the braking distance at the
friction actually available. This is not a restatement of the speed limit: on a
wet road the legal speed can be perfectly lawful and still leave the vehicle
unable to stop inside the distance its operational design domain assures.

``d_avail`` is a certified ODD parameter rather than a perception output,
because the state vector carries no distance-to-obstacle and SI-1 and SI-2
forbid this layer from re-reading the sensors to find one. That is a real
limitation and it is recorded as such rather than papered over.

**3. Legal speed.** ``v <= v_legal``

The simplest bound and the only one that is a legal rather than a physical fact.
It is separate from the stopping-distance bound precisely because the two fail
for unrelated reasons.

**4. Lateral corridor.** ``|position_y| <= corridor_half_width``

Added 5 August 2026. The other three bound how the vehicle is *moving*; this one
bounds where it *is*, and its absence was a hole in the whole three-gate
argument rather than in this gate alone. In a 100,000-tick run the vehicle
travelled 2.9 km outside a corridor 1.75 m wide with a **0.00% veto rate and a
Trust Index of exactly 1.00**: L7b bounds jerk and divergence from the twin, L6
scores the proposal against the twin, and this gate bounded only speed,
acceleration and stopping distance. A departure was invisible to all three, so
the hazard that actually occurred was outside the union of what Core-B checked.

Deliberately a *corridor* rather than a lane. A lane is a road concept and NFR5
keeps road concepts out of the core; a warehouse AGV has a permitted corridor
just as a car has a lane, and the bound is the same quantity in both.

**This bound is only as good as the position estimate, and that is not a
quibble.** It reads ``state.position_y``, so it detects a departure the filter
knows about and is blind to one the filter does not. In the run described above
the estimate sat at zero while the vehicle left: lateral position was measured by
no sensor, so the UKF dead-reckoned it from an unobserved heading. **Had this
bound existed then, it would have passed every tick.** What closed that hazard
was making the quantity observable; what this bound adds is that a departure the
filter *can* see is now refused by a gate rather than noticed by nobody. Both
were needed and neither substitutes for the other.

Why the bounds are evaluated against the *state*, not the proposal
------------------------------------------------------------------
A subtlety worth stating, because it looks like a bug until it is explained. The
shield checks the state the vehicle is *in*, and the command's contribution to
it, rather than checking the proposed command in isolation. A steering command
is not unsafe on its own -- it is unsafe at 30 m/s on ice and fine at 5 m/s on
tarmac. Judging a command without the state it will act on would be judging a
number.

Latency
-------
Four comparisons and two multiplications. No allocation on the nominal path
beyond the verdict record itself, no iteration, no I/O. This is the cheapest
component in Core-B and the one with the strongest authority, which is the
correct relationship between the two.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Final

from astra.contracts.assurance import GateVerdict
from astra.kernel.enums import GateId, LayerId, Verdict
from astra.kernel.errors import SafetyPathError
from astra.kernel.units import STANDARD_GRAVITY

if TYPE_CHECKING:
    from astra.config.schema import ShieldSettings
    from astra.contracts.actuation import ProposedCommand
    from astra.contracts.estimation import FastStateEstimate, SlowStateEstimate
    from astra.kernel.identifiers import TickId

__all__ = ["REASON_CODES", "HardSafetyShield"]

# Stable, greppable reason codes. They appear verbatim in the evidence log, so a
# code never changes meaning: an analysis written against a year-old archive has
# to keep working.
REASON_NOMINAL: Final = "NOMINAL"
REASON_LATERAL_ACCELERATION: Final = "LATERAL_ACCELERATION_EXCEEDS_FRICTION"
REASON_CORRIDOR_DEPARTURE: Final = "LATERAL_OFFSET_EXCEEDS_CORRIDOR"
REASON_STOPPING_DISTANCE: Final = "STOPPING_DISTANCE_EXCEEDS_ASSURED_CLEAR"
REASON_LEGAL_SPEED: Final = "SPEED_EXCEEDS_LEGAL_LIMIT"
REASON_STATE_NOT_FINITE: Final = "STATE_NOT_FINITE"

REASON_CODES: Final[tuple[str, ...]] = (
    REASON_NOMINAL,
    REASON_LATERAL_ACCELERATION,
    REASON_CORRIDOR_DEPARTURE,
    REASON_STOPPING_DISTANCE,
    REASON_LEGAL_SPEED,
    REASON_STATE_NOT_FINITE,
)
"""Every reason code this gate can emit. Part of the evidence schema."""

_MINIMUM_FRICTION: Final = 1e-3
"""Floor on the friction coefficient used in a denominator.

A friction estimate at or below this means the road offers effectively no grip.
Dividing by it would produce an unbounded stopping distance -- arithmetically a
VETO, which is the right answer, but by way of an overflow rather than a
decision. The floor makes the veto explicit and keeps the number in the evidence
log finite and readable.
"""


class HardSafetyShield:
    """The deterministic gate. Four O(1) bounds, unconditional veto authority.

    Satisfies :class:`~astra.ports.pipeline.DeterministicShield` structurally.

    Stateless by construction: it holds configuration and nothing else. A shield
    that accumulated state between ticks could be driven into a permissive mode
    by a sequence of inputs, and its verdict would stop being a pure function of
    the state it was given -- which is what makes it independently auditable.
    """

    __slots__ = ("_settings",)

    def __init__(self, settings: ShieldSettings) -> None:
        """Build the shield from its certified bounds.

        Args:
            settings: The four bounds and the friction margin. Every one is
                required configuration with no default (A-4): a shield running
                on invented limits is worse than no shield, because its PASS
                carries the authority of a deterministic check.
        """
        self._settings = settings

    def evaluate(
        self,
        *,
        tick: TickId,
        proposal: ProposedCommand,
        state: FastStateEstimate,
        degradation: SlowStateEstimate,
    ) -> GateVerdict:
        """Check the current state against the four hard bounds.

        Args:
            tick: The control tick.
            proposal: The untrusted proposed command. **Accepted and not read**
                -- see ``del proposal`` in the body. It is part of the port's
                signature because every gate takes one, and the bounds here are
                evaluated against the state the command will act on, for the
                reason given in the module docstring.

                This entry previously said the proposal was "carried into the
                verdict for attribution". It is not, and
                :class:`~astra.contracts.assurance.GateVerdict` has no field it
                could be carried in.
            state: The fast state estimate.
            degradation: The slow estimate, supplying the road friction that
                makes the friction and stopping-distance bounds adaptive.

        Returns:
            A verdict tagged :attr:`~astra.kernel.enums.GateId.DETERMINISTIC`,
            carrying every computed quantity as evidence -- including on a PASS,
            so an analyst can see the margin the vehicle actually had rather
            than only that it was inside the limit.

        Raises:
            SafetyPathError: If the state estimate contains a non-finite value.
                NaN defeats every comparison below rather than failing it, so a
                NaN speed would silently satisfy every bound. This is the
                one case the gate cannot decide, and it fails closed.
        """
        del proposal  # attribution only; the bounds read the state

        speed = float(state.speed)
        lateral_acceleration = float(state.lateral_acceleration)
        lateral_offset = float(state.position_y)
        friction = float(degradation.road_friction_coefficient)
        self._require_finite_state(tick, speed, lateral_acceleration, friction, lateral_offset)

        margin = float(self._settings.friction_margin)
        friction_limit = margin * friction * STANDARD_GRAVITY
        effective_friction = max(friction * margin, _MINIMUM_FRICTION)
        braking_distance = (speed * speed) / (2.0 * effective_friction * STANDARD_GRAVITY)
        stopping_distance = float(self._settings.minimum_stopping_distance) + braking_distance
        assured_clear = float(self._settings.assured_clear_distance)
        legal_speed = float(self._settings.legal_speed_limit)
        corridor = float(self._settings.lateral_corridor_half_width)

        evidence: tuple[tuple[str, float], ...] = (
            ("speed_mps", speed),
            ("lateral_acceleration_mps2", abs(lateral_acceleration)),
            ("friction_limit_mps2", friction_limit),
            ("road_friction", friction),
            ("stopping_distance_m", stopping_distance),
            ("assured_clear_distance_m", assured_clear),
            ("legal_speed_mps", legal_speed),
            ("lateral_offset_m", abs(lateral_offset)),
            ("lateral_corridor_half_width_m", corridor),
        )

        # Order matters only for which reason is reported first; any breach is a
        # VETO regardless. Friction is checked first because it is the bound
        # whose breach is least recoverable -- a sliding vehicle has already
        # stopped responding to the controller.
        if abs(lateral_acceleration) > friction_limit:
            return self._veto(tick, REASON_LATERAL_ACCELERATION, evidence)
        if abs(lateral_offset) > corridor:
            return self._veto(tick, REASON_CORRIDOR_DEPARTURE, evidence)
        if stopping_distance > assured_clear:
            return self._veto(tick, REASON_STOPPING_DISTANCE, evidence)
        if speed > legal_speed:
            return self._veto(tick, REASON_LEGAL_SPEED, evidence)
        return GateVerdict(
            tick=tick,
            gate=GateId.DETERMINISTIC,
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
            reason_code: Which bound was breached.
            evidence: The computed quantities.

        Returns:
            The verdict.
        """
        return GateVerdict(
            tick=tick,
            gate=GateId.DETERMINISTIC,
            verdict=Verdict.VETO,
            reason_code=reason_code,
            evidence=evidence,
        )

    @staticmethod
    def _require_finite_state(
        tick: TickId,
        speed: float,
        lateral_acceleration: float,
        friction: float,
        lateral_offset: float,
    ) -> None:
        """Refuse to judge a state containing a non-finite value.

        Returning a VETO here would be defensible, but raising is better: a
        non-finite state is a filter fault rather than an unsafe manoeuvre, and
        the fail-safe machine should see it as the former. The disposition on
        :class:`~astra.kernel.errors.SafetyPathError` is ``FAIL_CLOSED``, so the
        tick becomes a VETO either way -- the difference is what the evidence
        says happened.

        Args:
            tick: The control tick.
            speed: The estimated speed.
            lateral_acceleration: The estimated lateral acceleration.
            friction: The estimated road friction.
            lateral_offset: The estimated lateral offset from the corridor
                centreline.

        Raises:
            SafetyPathError: If any value is NaN or infinite.
        """
        offenders = [
            name
            for name, value in (
                ("speed", speed),
                ("lateral_acceleration", lateral_acceleration),
                ("road_friction_coefficient", friction),
                ("position_y", lateral_offset),
            )
            if not math.isfinite(value)
        ]
        if offenders:
            message = (
                f"the shield cannot judge a non-finite state: {', '.join(offenders)}. "
                f"NaN defeats every bound comparison rather than failing it, so this "
                f"tick fails closed rather than silently passing all four"
            )
            raise SafetyPathError(
                message,
                layer=LayerId.L7_HARD_SAFETY_SHIELD,
                context={
                    "tick": tick.value,
                    "fields": offenders,
                    "reason": REASON_STATE_NOT_FINITE,
                },
            )
