"""L5 -- the physics-informed digital twin.

Predicts the command the modelled physics expects next. That prediction is the
right operand of the statistical gate's non-conformity score, so this layer is a
safety input rather than a diagnostic: a twin that drifts moves the acceptance
band under L6 without L6 noticing.

The twin is trained against physics, not against the proposer. A twin fitted
closely to Core-A's policy would drive every non-conformity score towards zero
and quietly disarm the statistical gate while every dashboard reported health --
which is why the physics residual, not the data fit, is what anchors it.

L7b, the physical admissibility checker, consumes this layer's prediction and
arrives alongside it in Phase 4. L7a stays independent of both, which is
reconciliation finding R-3.
"""

from __future__ import annotations
