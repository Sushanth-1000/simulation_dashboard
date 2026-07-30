"""The nine functional layers of the governance pipeline.

Each layer is a package named for its position and role (``l1_sensing``,
``l2_estimation``, ...) and implements the corresponding protocol from
:mod:`astra.ports.pipeline`. The protocols are structural, so a layer never
imports the port it satisfies; the composition root is what checks the two
agree.

Layers may depend on :mod:`astra.contracts`, :mod:`astra.kernel`,
:mod:`astra.config` and :mod:`astra.observability`. They may not depend on each
other except through the records they exchange, and the Core-A layer may not
depend on any Core-B layer at all (SI-5). Both rules are enforced by the
contracts in ``.importlinter`` rather than by review.
"""

from __future__ import annotations
