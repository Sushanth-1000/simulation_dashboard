"""L3 -- the conformal Trust Module.

Produces the Trust Index by Mondrian-conditioned conformal prediction. Its
output routes to L4 as a monitoring signal and to L9 as a routing input, and by
SI-4 it never participates in Core-B's verdict.

This package is built and tested in isolation before it is integrated, which is
the mitigation the roadmap prescribes for RK-2. The risk is specific: a subtly
wrong conformal implementation does not crash, it produces a *silently invalid*
coverage guarantee. Every downstream component keeps working, the evidence log
keeps filling, and the central statistical claim of the architecture is false.

The two mistakes that cause it -- omitting the ``+1`` in the quantile rank, and
clamping to the largest observed score when no finite threshold exists -- are
described and tested in :mod:`astra.layers.l3_trust.quantile`.
"""

from __future__ import annotations
