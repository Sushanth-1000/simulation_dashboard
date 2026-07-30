"""L6 -- the statistical gate.

Scores the untrusted proposal against the twin's prediction, normalised by the
filter's own uncertainty, and compares the result to a class-conditional
conformal quantile.

This is the gate an adversary can defeat, and that is not a defect. Conformal
coverage assumes exchangeability between calibration and runtime data, and an
adversarial perturbation violates that by construction. The architecture's
answer is not to make this gate unbreakable but to place two gates beside it
that fail for unrelated reasons.

The complementary property is what the validation plan is built around: a
perturbation that is kinematically plausible and inside every hard bound is
invisible to L7a and L7b and visible only here.

By SI-4 this gate never sees the Trust Index. It shares L3's calibration
*scores*, which are data, and not the index derived from them.
"""

from __future__ import annotations
