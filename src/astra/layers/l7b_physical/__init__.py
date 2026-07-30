"""L7b -- the physical admissibility gate.

Asks whether the proposed command is physically *reachable* from the current
state within one tick, rather than whether the vehicle is currently inside its
envelope. That second question is L7a's, and answering it here as well would
merge two of the three gates while leaving both still reporting verdicts --
independence lost invisibly, which is the worst way to lose it.

This package is separate from :mod:`astra.layers.l7_shield` for that reason. L7a
must not acquire a dependency on the digital twin; keeping the two gates in
different packages lets an import contract say so and lets a build fail if
anyone changes their mind quietly.

The split between L7a and L7b is reconciliation finding R-3: the source
documents claim both that "L7 has no dependency on L5 or L6" and that "L7
performs a physical recheck", and both are true once they are read as
describing two different gates.
"""

from __future__ import annotations
