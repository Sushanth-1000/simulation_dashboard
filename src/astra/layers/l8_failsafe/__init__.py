"""L8 -- the fail-safe finite state machine.

Turns a sequence of per-tick verdicts into a graduated safety posture. A single
VETO is not an emergency; a sustained pattern of them is. The machine is what
draws that distinction, and its output -- the state, the speed cap, the
lane-change permission -- is what L9 arbitrates under.

Recovery is automatic and bidirectional, without a restart. That is a
requirement rather than a nicety: a vehicle that had to be stopped and
reinitialised to leave DEGRADED would treat a transient sensor glitch the same
way it treats a permanent fault.
"""

from __future__ import annotations
