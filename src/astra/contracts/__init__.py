"""The immutable records exchanged between ASTRA layers.

Every value that crosses a layer boundary is one of these types. They are
frozen, slot-based dataclasses that validate their invariants once, at
construction, and are then trusted for the remainder of the tick.

These types are the stable interface of the whole system. A port signature can
be refactored; a contract change alters what is written to the audit log and
therefore what can be replayed and what a certification archive means, so it
carries a schema version.
"""
