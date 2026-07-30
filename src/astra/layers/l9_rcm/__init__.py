"""L9 -- Runtime Calibration Management, and the sole issuer of commands.

Two responsibilities on two timing domains, and the split is the point. The hot
path is an active-table lookup and a decision inside the tick budget. The cold
path -- the Mahalanobis knowledge-base search, the mandatory gates, ``T(c)``
scoring, shadow execution -- runs on a millisecond-to-second timescale and must
never block a tick. That is SI-8.

L9 is also the only component permitted to construct an
:class:`~astra.contracts.actuation.IssuedCommand`, which the contract enforces
at construction rather than by convention. SI-7 is therefore unrepresentable to
violate rather than forbidden.

The behaviour that distinguishes this layer from every system in the survey is
what it does when nothing matches: it shrinks the envelope and keeps moving,
rather than stopping. See :mod:`astra.layers.l9_rcm.exploration`.
"""

from __future__ import annotations
