"""Shadow execution and the Calibration Divergence Index.

Why a switch is staged rather than applied
--------------------------------------------
A calibration table sets the thresholds every statistical judgement is made
against. Swapping one in is not a configuration change; it is a change to what
the system considers anomalous. A table that is subtly wrong -- stale, mislabelled,
built from a corpus collected in different conditions -- does not announce itself.
It just starts agreeing with proposals it should have questioned, and the
evidence log fills with passes.

So the candidate runs *beside* the active table without authority for a while,
and the two are compared on live commands before either is trusted.

What the index measures
------------------------
Agreement, not closeness. CDI is the fraction of shadow ticks on which the two
tables reached *different verdicts* about the same command.

That is deliberate and it is not the obvious choice: comparing the two quantiles
numerically would be easier and would produce a smoother number. But two tables
whose thresholds differ by a wide margin and never disagree about an actual
command are, for every purpose the system has, the same table. And two tables
whose thresholds are close but straddle the operating point disagree constantly
and are not. The index has to describe the decisions, because the decisions are
what reach the vehicle.

It also lands naturally in ``[0, 1]``, which is what
:class:`~astra.contracts.governance.ArbitrationDecision` requires of it.

Why a minimum sample count
---------------------------
A CDI computed from three ticks is noise. Committing a switch on it would mean
the staging period bought nothing, which is worse than not staging at all: it
would produce an evidence record stating that divergence was checked and cleared.
:meth:`ShadowExecution.has_cleared` therefore returns ``False`` until enough
comparisons exist, and the caller reads
:attr:`~ShadowExecution.sample_count` to tell "clear" from "not yet".
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Final

from astra.kernel.enums import LayerId
from astra.kernel.errors import ConfigurationError

if TYPE_CHECKING:
    from astra.kernel.enums import Verdict

__all__ = ["MINIMUM_SHADOW_SAMPLES", "ShadowExecution"]

MINIMUM_SHADOW_SAMPLES: Final = 20
"""Comparisons required before the divergence index means anything.

An architectural property of the mechanism rather than an operating point. A
staging period that can clear on three ticks is not a staging period, and the
evidence record it produces -- "divergence checked, cleared" -- would be worse
than no record at all.
"""


class ShadowExecution:
    """Tracks agreement between the active table and a staged candidate.

    Cold-path state. Nothing on the hot path reads this object; it accumulates
    as verdicts are produced and is consulted when the arbiter next evaluates.
    """

    __slots__ = ("_disagreements", "_samples")

    def __init__(self) -> None:
        """Start a staging period with no comparisons recorded."""
        self._samples = 0
        self._disagreements = 0

    @property
    def sample_count(self) -> int:
        """Return how many commands both tables have judged."""
        return self._samples

    @property
    def divergence_index(self) -> float:
        """Return the Calibration Divergence Index.

        Returns:
            The fraction of comparisons on which the two tables disagreed, in
            ``[0, 1]``. Zero before any comparison: no observed disagreement,
            which is why :meth:`has_cleared` and not this property decides
            whether a switch may commit.
        """
        if self._samples == 0:
            return 0.0
        return self._disagreements / self._samples

    def observe(self, *, active: Verdict, candidate: Verdict) -> None:
        """Record one comparison between the two tables.

        Args:
            active: The verdict the active table produced.
            candidate: The verdict the staged candidate produced for the same
                command.
        """
        self._samples += 1
        if active is not candidate:
            self._disagreements += 1

    def has_cleared(self, limit: float) -> bool:
        """Return whether the candidate may be committed.

        Args:
            limit: ``delta_CDI``, the divergence the switch tolerates.

        Returns:
            ``True`` only if enough comparisons have accumulated *and* the
            index is below the limit. Insufficient evidence is not clearance.

        Raises:
            ConfigurationError: If the limit is non-finite or outside
                ``[0, 1]``. A limit of 1 or above accepts a candidate that
                disagreed with the active table on every single command, which
                makes the staging period ceremonial.
        """
        if not math.isfinite(limit) or not (0.0 <= limit < 1.0):
            message = (
                f"the divergence limit must lie in [0, 1), got {limit}; at 1 or above a "
                f"candidate that disagreed with the active table on every command would "
                f"still commit, and the staging period would be ceremonial"
            )
            raise ConfigurationError(message, layer=LayerId.L9_RCM, context={"limit": str(limit)})
        if self._samples < MINIMUM_SHADOW_SAMPLES:
            return False
        return self.divergence_index < limit
