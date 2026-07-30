"""Recording and replay of a run's sensor inputs.

Built in Phase 2, not Phase 7. The Prototype & Demo Plan is explicit that this
tooling must exist *before* closed-loop integration rather than during it, and
names the difference as debugging in hours versus days. Phase 7's failures are
usually not code bugs but emergent dynamics -- oscillation, drift,
overcorrection -- and those can only be studied by re-driving the exact input
sequence that produced them.

What is recorded, and why it is the inputs
-------------------------------------------
The tape records what entered the pipeline, never what the pipeline concluded.
Replaying inputs through the same code reproduces the outputs; recording outputs
would only let them be re-read. The distinction is what makes replay a debugging
instrument rather than a log viewer: a fix can be applied and the same input
sequence re-run to see whether the emergent behaviour changed.

See :mod:`astra.replay.tape` for the format, :mod:`astra.replay.recorder` for
capture and :mod:`astra.replay.harness` for playback.
"""

from __future__ import annotations
