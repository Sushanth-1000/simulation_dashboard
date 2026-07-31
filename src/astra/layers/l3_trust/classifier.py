"""Deciding which operational context a tick belongs to.

Mondrian conformal prediction conditions its quantiles on a class, so something
has to name the class. That is this module's whole job, and it is a smaller job
than it looks: the classifier does not decide whether a situation is *safe*, only
which population of past situations it should be compared against.

What can be classified from the state, and what cannot
-------------------------------------------------------
The signature carries a fast state estimate and an innovation record. From those
two, three of the four certified classes are decidable:

* ``DEGRADED_SENSOR`` -- the innovation monitor has flagged a fault. This is
  checked first, because a degraded sensor changes which population the tick
  belongs to regardless of how fast the vehicle is going.
* ``HIGHWAY_CLEAR`` -- speed at or above the configured boundary.
* ``URBAN_CLEAR`` -- speed below it.

``RAIN_NIGHT`` is **not** decidable here, and that is worth stating plainly
rather than approximating. Precipitation and ambient light are not in the fast
state vector; the nearest observable proxy is the road-friction coefficient,
which lives in the *slow* state and is not passed to this method. Returning
``RAIN_NIGHT`` on a friction heuristic the signature cannot see would be
inventing a classification.

The consequence is honest and bounded: a wet-night tick classifies as
``HIGHWAY_CLEAR`` or ``URBAN_CLEAR`` and is compared against a population that
does not match it, which shows up as degraded empirical coverage for that class
rather than as a silent error. Closing it properly means either widening the
classifier's inputs to include the slow state, or sourcing weather from an
adapter -- both visible architectural changes, and both recorded as debt.

Why a rule and not a model
---------------------------
A learned classifier would need its own calibration, its own failure modes and
its own place in the safety argument, to decide something a threshold decides
adequately. It would also be a second learned component inside the assurance
path, which is exactly the coupling the architecture spends its effort avoiding.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from astra.kernel.enums import ContextClass, LayerId
from astra.kernel.validation import require_non_negative

if TYPE_CHECKING:
    from astra.contracts.estimation import FastStateEstimate, InnovationRecord
    from astra.kernel.units import MetresPerSecond

__all__ = ["RuleBasedContextClassifier"]


class RuleBasedContextClassifier:
    """Names a tick's context class from the state estimate and the innovation.

    Satisfies :class:`~astra.layers.l3_trust.trust.ContextClassifier`
    structurally. Stateless: the same inputs always produce the same class, so a
    classification can be reproduced from an evidence record without replaying
    the run that produced it.
    """

    __slots__ = ("_highway_speed",)

    def __init__(self, *, highway_speed: MetresPerSecond) -> None:
        """Build the classifier.

        Args:
            highway_speed: The speed at or above which a tick is treated as
                highway rather than urban. Configuration rather than a constant:
                the boundary is a property of the operational design domain, and
                a jurisdiction with different road classes moves it.

        Raises:
            RangeViolationError: If the boundary speed is negative.
            NonFiniteValueError: If it is NaN or infinite.
        """
        require_non_negative(highway_speed, name="highway_speed", layer=LayerId.L3_CONFORMAL_TRUST)
        self._highway_speed = highway_speed

    @property
    def highway_speed(self) -> MetresPerSecond:
        """Return the urban/highway boundary speed."""
        return self._highway_speed

    def classify(
        self, *, state: FastStateEstimate, innovation: InnovationRecord | None
    ) -> ContextClass:
        """Return the operational context class for this tick.

        Args:
            state: The current fast state estimate.
            innovation: The latest innovation record, if the filter has run.

        Returns:
            The class to condition on. ``DEGRADED_SENSOR`` takes precedence over
            the speed-based classes: a flagged sensor fault changes which
            population the tick belongs to whatever the vehicle is doing.
        """
        if innovation is not None and innovation.fault_flagged:
            return ContextClass.DEGRADED_SENSOR
        if float(state.speed) >= float(self._highway_speed):
            return ContextClass.HIGHWAY_CLEAR
        return ContextClass.URBAN_CLEAR
