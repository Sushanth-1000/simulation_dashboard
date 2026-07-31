"""Building the Runtime Context Signature from what the pipeline can observe.

The signature is RCM's question to the knowledge base: *which certified profile,
if any, describes the situation the vehicle is in right now?* Everything about
the cold path -- the Mahalanobis search, the mandatory gates, the admissibility
score, and ultimately whether bounded safe exploration engages -- follows from
this five-number vector.

Reliability weighting, and why it is the interesting part
----------------------------------------------------------
The architecture specifies the sensor component as *reliability-weighted*, so
that a degraded sensor lowers its own contribution rather than silently
dominating the signature. That is not a refinement; it is the difference between
a signature that notices its own inputs are failing and one that reports high
confidence built on a stream that has stopped updating.

Concretely: `sensor_reliability` is the mean of each modality's quality
*discounted by its health*, with an absent stream contributing zero rather than
being skipped. Skipping it would raise the mean -- losing a sensor would make
the vehicle look *more* certain about its context, which is precisely backwards.

What is honestly observable, and what is estimated
---------------------------------------------------
Two of the five components are directly observable from the pipeline's own
state, and three are not:

* ``ego_speed`` -- observable. The fast filter's speed, normalised by the legal
  limit.
* ``sensor_reliability`` -- observable. From the frame's per-modality health and
  quality.
* ``visibility``, ``traffic_dynamicity``, ``road_complexity`` -- **not
  observable without perception.** Nothing in the state vector carries fog
  density, the number of surrounding vehicles, or road geometry.

Rather than invent them, this module takes them as explicit inputs with no
defaults, so a caller has to say where its numbers come from. The synthetic
driver supplies scenario values it knows because it authored them; a CARLA
adapter would supply values derived from the simulator's world state. Neither
pretends the pipeline computed something it cannot.

That honesty has a cost worth naming: a signature carrying three
externally-supplied components is only as good as the caller, and the mandatory
gates downstream cannot tell a well-sourced value from an invented one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from astra.contracts.governance import RuntimeContextSignature
from astra.kernel.constants import RCS_FIELDS
from astra.kernel.enums import LayerId, SensorModality, StreamHealth
from astra.kernel.units import Probability
from astra.kernel.validation import require_positive, require_probability

if TYPE_CHECKING:
    from collections.abc import Mapping

    from astra.contracts.estimation import FastStateEstimate
    from astra.contracts.sensing import FusedSensorFrame
    from astra.kernel.identifiers import TickId
    from astra.kernel.units import MetresPerSecond

__all__ = ["build_signature", "sensor_reliability"]

# How much each health state discounts a stream's reported quality. A stream
# reporting high quality while stale is not a high-quality stream: staleness is
# a statement about the reading's age that the reading itself cannot make.
_HEALTH_WEIGHT: Mapping[StreamHealth, float] = {
    StreamHealth.HEALTHY: 1.0,
    StreamHealth.DEGRADED: 0.5,
    StreamHealth.FAULTED: 0.1,
    StreamHealth.ABSENT: 0.0,
}

_VISIBILITY = RCS_FIELDS.index("visibility")
_EGO_SPEED = RCS_FIELDS.index("ego_speed")
_TRAFFIC = RCS_FIELDS.index("traffic_dynamicity")
_RELIABILITY = RCS_FIELDS.index("sensor_reliability")
_ROAD = RCS_FIELDS.index("road_complexity")


def sensor_reliability[PayloadT](
    frame: FusedSensorFrame[PayloadT], health: Mapping[SensorModality, StreamHealth]
) -> Probability:
    """Return the reliability-weighted aggregate sensor quality.

    Averaged over **every** modality the architecture defines, not over the ones
    that happened to report. A missing stream contributes zero; dropping it from
    the average would make losing a sensor raise the aggregate, so the vehicle
    would look more certain about its context precisely as it learned less.

    Args:
        frame: The fused frame for this tick.
        health: Per-modality health, as classified against the staleness budget.

    Returns:
        The aggregate in ``[0, 1]``.
    """
    total = 0.0
    for modality in SensorModality:
        sample = frame.sample_for(modality)
        if sample is None:
            continue
        weight = _HEALTH_WEIGHT[health.get(modality, StreamHealth.ABSENT)]
        total += float(sample.quality) * weight
    return require_probability(
        total / len(SensorModality), name="rcs.sensor_reliability", layer=LayerId.L9_RCM
    )


def build_signature[PayloadT](
    *,
    tick: TickId,
    frame: FusedSensorFrame[PayloadT],
    health: Mapping[SensorModality, StreamHealth],
    state: FastStateEstimate,
    legal_speed_limit: MetresPerSecond,
    visibility: Probability,
    traffic_dynamicity: Probability,
    road_complexity: Probability,
) -> RuntimeContextSignature:
    """Assemble the five-component signature for this tick.

    Args:
        tick: The control tick.
        frame: The fused sensor frame.
        health: Per-modality health for that frame.
        state: The fast state estimate, supplying ego speed.
        legal_speed_limit: The speed the ego component is normalised against.
        visibility: Normalised visibility. **Externally supplied**: nothing in
            the state vector carries fog density or ambient light.
        traffic_dynamicity: Normalised traffic dynamicity. Externally supplied.
        road_complexity: Normalised road complexity. Externally supplied.

    Returns:
        The signature, every component clamped into ``[0, 1]``.

    Raises:
        RangeViolationError: If an externally supplied component lies outside
            ``[0, 1]``, or the legal speed limit is not positive.
    """
    require_positive(legal_speed_limit, name="rcs.legal_speed_limit", layer=LayerId.L9_RCM)
    for name, value in (
        ("visibility", visibility),
        ("traffic_dynamicity", traffic_dynamicity),
        ("road_complexity", road_complexity),
    ):
        require_probability(value, name=f"rcs.{name}", layer=LayerId.L9_RCM)

    # Clamped rather than validated: a vehicle above the legal limit is a
    # situation the shield exists to catch, not a reason the signature cannot be
    # built. Refusing to describe the context at exactly the moment it becomes
    # interesting would be the wrong failure.
    normalised_speed = min(1.0, max(0.0, float(state.speed) / float(legal_speed_limit)))

    components = [0.0] * len(RCS_FIELDS)
    components[_VISIBILITY] = float(visibility)
    components[_EGO_SPEED] = normalised_speed
    components[_TRAFFIC] = float(traffic_dynamicity)
    components[_RELIABILITY] = float(sensor_reliability(frame, health))
    components[_ROAD] = float(road_complexity)

    return RuntimeContextSignature(
        tick=tick,
        components=tuple(Probability(value) for value in components),
    )
