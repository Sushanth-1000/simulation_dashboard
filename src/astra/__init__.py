"""ASTRA — Autonomous Safety, Trust, and Runtime Architecture.

A runtime governance framework that sits at the actuation boundary between a
learning-based controller and a physical plant. The controller is treated as an
untrusted proposer; an independent pipeline validates every command it proposes
statistically, physically and deterministically before any of it reaches an
actuator.

Package map
-----------
``astra.kernel``
    Dependency-free primitives: units, identifiers, time, errors, validation,
    enumerations, architectural constants. Imported by everything; imports
    nothing.
``astra.contracts``
    The immutable records that layers exchange. Pure data with invariants.
``astra.ports``
    The interfaces (``Protocol`` classes) each of the nine layers implements.
``astra.invariants``
    The declared separation invariants and their runtime guards.
``astra.config``
    Layered, validated, startup-frozen configuration.
``astra.observability``
    Structured audit logging and the correlation context that binds records to
    a tick.
``astra.bootstrap``
    The composition root and command-line entry point.

Import convention
-----------------
Sub-packages deliberately do not re-export their contents. Every import names
the defining module (``from astra.kernel.units import Metres``), never a
package facade. Two reasons: the dependency graph stays precise enough for the
architecture fitness contracts in ``.importlinter`` to be meaningful, and a
reader can locate any symbol from its import line alone.

Phase status
------------
Phase 1 (foundation) is complete. Layers L1-L9 are specified as ports and
contracts here but implemented in later phases; see ``docs/ROADMAP.md``.
"""

from __future__ import annotations

__version__ = "0.1.0"
__all__ = ["__version__"]
