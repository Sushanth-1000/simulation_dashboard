"""The mechanics that connect the layers: channels, and later the tick loop.

Distinct from :mod:`astra.layers`, which is where the layers themselves live.
This package holds the plumbing between them -- the topology through which
records move -- because that topology carries safety properties of its own. The
one-way Core-A to Core-B channel is not an implementation detail of either core;
it is separation invariant SI-5, expressed as a shape.
"""

from __future__ import annotations
