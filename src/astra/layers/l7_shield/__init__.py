"""L7a -- the Hard Safety Shield.

The deterministic gate, and the component with unconditional veto authority.

Its independence is structural, not stylistic. It reads the UKF state and the
estimated road friction, and nothing else: not the digital twin's prediction,
not the conformal score, not the Trust Index. That absence is the entire point.
Its three bounds fail only if the state estimate itself is wrong, which is a
failure mode neither the statistical gate (which fails when exchangeability is
violated) nor the physical gate (which fails on model drift) shares.

The split between this layer and the PINN-based physical checker is
reconciliation finding R-3. Both claims in the source documents -- "L7 has no
dependency on L5 or L6" and "L7 performs a physical recheck" -- are true once
they are recognised as describing two different gates. This package is L7a. L7b
arrives with the twin in Phase 4.
"""

from __future__ import annotations
