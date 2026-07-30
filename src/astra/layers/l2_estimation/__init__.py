"""L2 -- the dual-rate unscented Kalman filter.

The single source of state for every layer above it (SI-2), and therefore the
system's one acknowledged common-cause channel: all three Core-B gates read this
estimate, so a filter that has silently diverged degrades all three at once. That
is why the innovation monitor in :mod:`astra.layers.l2_estimation.filter` is part
of the layer rather than an optional diagnostic, and why the roadmap requires the
filter to be validated in isolation against ground truth before anything
downstream is wired to it.

Two filters, two rates
----------------------
The fast filter runs at the control rate and tracks the vehicle's kinematic
state. The slow filter runs orders of magnitude slower and tracks degradation
processes -- road friction, tyre wear, aggregate sensor health -- which change on
a timescale where estimating them at 20 Hz would be fitting noise.
"""

from __future__ import annotations
