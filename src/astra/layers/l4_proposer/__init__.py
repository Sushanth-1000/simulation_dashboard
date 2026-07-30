"""L4 -- Core-A, the constrained-MDP proposer.

The untrusted half of the system. Core-A proposes one command per tick and has
no authority to issue it, no way to observe what Core-B decided, and no term in
its reward that describes a safety component.

That last point is separation invariant SI-6, and it is the one this package
finally makes mechanical. Until now the catalogue recorded SI-6's enforcement as
``REVIEW`` -- the only one of the ten invariants with nothing behind it but
attention. :mod:`astra.layers.l4_proposer.signal` closes the set of quantities
the reward may read, and the test suite asserts that set against the type.

The import contract naming this package as forbidden from reaching any Core-B
module activates here too. Before this package existed, `lint-imports` could not
express SI-5 at all: the rule referred to a module that did not yet exist, and
import-linter errors on those rather than passing them vacuously.
"""

from __future__ import annotations
