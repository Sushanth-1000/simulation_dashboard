"""A three-channel position adapter, and the monitor that catches a liar.

What this is for
-----------------
OD-9's remaining two thirds: a channel that lies *fluently* -- a constant offset,
a slow ramp, a value frozen at its last good reading -- keeps the stream
perfectly fresh, so every mechanism downstream of L2 reports normality. Four
candidates were built and measured against it and all four are silent (E-53,
E-94, E-105, E-106), each for one shared reason: **a self-consistent lie slower
than the sensor noise cannot be distinguished from truth by any function of a
single sensor chain.**

The answer is to stop having a single chain. This adapter publishes three
**independent** position readings and cross-checks them.

Why it lives in ``training/`` and not in ``src/``
--------------------------------------------------
Deciding that two readings *should* agree requires knowing what each modality
measures, and NFR5 keeps that knowledge out of the layers. So this is an
adapter, supplied through the ``IntegrityMonitor`` port that sits beside
``MeasurementExtractor`` -- the two components permitted to read a raw payload.

The seam it fills was reserved long before anything could fill it.
``SensorReading.health_at`` says only ``HEALTHY`` and ``DEGRADED`` can be decided
from freshness, and that ``FAULTED`` needs a monitor which knows what a reading
*should* have been. It named the UKF's innovation gate as that monitor;
measured, that gate fires on tick 0 of every arm **including the control** and on
no injected fault (E-105). This is the producer the seam was waiting for.

The median, and why three
--------------------------
Three is the smallest number that permits a median, and the median is what makes
a liar **identifiable** rather than merely detectable: with two channels a
disagreement says something is wrong and cannot say which one. The fused
measurement is the median, so a single faulted channel is excluded from the
estimate *by construction* rather than by a decision.

The sigmas are deliberately **unequal**. Identical sigmas model identical
sensors, and identical sensors share a failure mode -- two devices from one batch
drift the same way at the same temperature. Common-mode failure is exactly what
dissimilar redundancy buys protection against, and modelling it away would make
this look better than it is.
"""

from __future__ import annotations

import statistics
from typing import TYPE_CHECKING, Any

from astra.kernel.enums import SensorModality, StreamHealth
from astra.layers.l2_estimation.measurement import (
    Measurement,
    fast_measurement,
    slow_measurement,
)
from training.closed_loop import FRICTION, FRICTION_SIGMA, LATERAL_SIGMA, SPEED_SIGMA

if TYPE_CHECKING:
    from collections.abc import Mapping

    from astra.contracts.sensing import FusedSensorFrame

__all__ = ["CHANNELS", "PATIENCE", "RESIDUAL_LIMIT", "RedundantExtractor", "ResidualMonitor"]

CHANNELS: tuple[SensorModality, ...] = (
    SensorModality.IMU,
    SensorModality.GPS,
    SensorModality.LIDAR,
)
"""The modalities that independently measure lateral position."""

RESIDUAL_LIMIT = 0.45
"""Metres of residual against the median before a channel is called FAULTED.

Calibrated on the **clean run only**, which is the weakest possible calibration
and the honest one: the largest residual any channel reaches with no fault
present is 0.541 m over 400 ticks (E-109), dominated by the GPS channel whose
sigma is twice the IMU's.

It sits *under* that clean peak deliberately, and :data:`PATIENCE` is what makes
that safe: a single excursion past 0.45 m happens several times in a clean run,
and a **sustained** one does not. Choosing the limit against the six hand-picked
faults instead would be fitting to the test set -- the defect E-41 records for
the conformal corpus.
"""

PATIENCE = 10
"""Consecutive ticks a channel must exceed the limit before it is FAULTED.

Half a second at 20 Hz. Long enough that a clean run's excursions do not fire it,
short enough to land well inside the 73 ticks the measured departure takes.
"""


class RedundantExtractor:
    """Fuses three position channels by median.

    Satisfies :class:`~astra.layers.l2_estimation.measurement.MeasurementExtractor`
    structurally.
    """

    __slots__ = ("_sigmas",)

    def __init__(self, sigmas: Mapping[SensorModality, float]) -> None:
        """Build the extractor.

        Args:
            sigmas: Per-channel measurement sigma. The fused sigma is the
                **largest** of them, which is conservative: the median of three
                readings is at least as good as the worst of them, and claiming
                better would tell the filter to trust the fusion more than any
                single channel justifies.
        """
        self._sigmas = dict(sigmas)

    def extract_fast(self, frame: FusedSensorFrame[Any]) -> Measurement | None:
        """Return the fast measurement, fusing position by median.

        Args:
            frame: The fused frame for this tick.

        Returns:
            A measurement, or ``None`` if no channel published. ``None`` is a
            legitimate outcome: the filter then predicts without correcting.
        """
        readings = positions(frame)
        anchor = frame.sample_for(SensorModality.IMU)
        if not readings or anchor is None:
            return None
        payload = anchor.payload
        return fast_measurement(
            [
                ("position_y", statistics.median(readings.values()), max(self._sigmas.values())),
                ("speed", float(payload["v"]), SPEED_SIGMA),
                ("lateral_acceleration", float(payload["a"]), LATERAL_SIGMA),
            ]
        )

    def extract_slow(self, frame: FusedSensorFrame[Any]) -> Measurement | None:
        """Return the slow measurement.

        Args:
            frame: The fused frame, unused.

        Returns:
            The road friction coefficient.
        """
        del frame
        return slow_measurement([("road_friction_coefficient", FRICTION, FRICTION_SIGMA)])


class ResidualMonitor:
    """Calls a channel FAULTED when it disagrees with the median for long enough.

    Satisfies :class:`~astra.layers.l2_estimation.measurement.IntegrityMonitor`
    structurally. Stateful across ticks, because :data:`PATIENCE` is the point:
    one excursion is noise and a sustained one is a fault.
    """

    __slots__ = ("_streak",)

    def __init__(self) -> None:
        """Start with every channel's streak at zero."""
        self._streak: dict[SensorModality, int] = dict.fromkeys(CHANNELS, 0)

    def health(self, frame: FusedSensorFrame[Any]) -> Mapping[SensorModality, StreamHealth]:
        """Return FAULTED for any channel sustaining a large residual.

        **A channel this monitor does not fault is omitted rather than reported
        healthy.** The pipeline keeps L1's staleness verdict for anything absent
        from the mapping, so a monitor that can only judge position must not
        clear a channel on the strength of its position agreeing.

        Args:
            frame: The fused frame for this tick.

        Returns:
            ``{modality: FAULTED}`` for the channels currently faulted, possibly
            empty.
        """
        readings = positions(frame)
        if len(readings) < len(CHANNELS):
            # Fewer than three channels leaves no median worth the name. Say
            # nothing rather than guess -- L1 already reports the missing one,
            # and inventing a verdict here would double-count that fault.
            return {}
        median = statistics.median(readings.values())
        faulted: dict[SensorModality, StreamHealth] = {}
        for channel, reading in readings.items():
            if abs(reading - median) > RESIDUAL_LIMIT:
                self._streak[channel] += 1
            else:
                self._streak[channel] = 0
            if self._streak[channel] >= PATIENCE:
                faulted[channel] = StreamHealth.FAULTED
        return faulted


def positions(frame: FusedSensorFrame[Any]) -> dict[SensorModality, float]:
    """Return each channel's reported lateral position, for the channels present.

    Args:
        frame: The fused frame for this tick.

    Returns:
        One entry per channel that published, possibly empty.
    """
    found: dict[SensorModality, float] = {}
    for channel in CHANNELS:
        sample = frame.sample_for(channel)
        if sample is not None:
            found[channel] = float(sample.payload["y"])
    return found
