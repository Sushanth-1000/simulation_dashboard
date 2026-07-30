"""L1 -- the shared sensor bus.

Fuses the five modalities into one timestamped frame per tick and classifies
each stream's freshness against the 50 ms staleness budget of FR1.

The layer is deliberately free of any simulator or vehicle knowledge: it is
generic in the payload type, so binding it to CARLA -- or to a real sensor bus,
or to a recorded run -- is an adapter's job. See
:mod:`astra.layers.l1_sensing.bus`.
"""

from __future__ import annotations
