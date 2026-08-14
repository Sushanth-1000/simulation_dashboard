"""Architectural constants: values fixed by the design, not by configuration.

The constant / configuration distinction
----------------------------------------
This module holds only values that cannot change without changing the
architecture itself. Changing ``RCS_DIMENSION`` from 5 to 6 is not a tuning
exercise; it invalidates every certified profile's centroid and covariance in
the Calibration Knowledge Base and requires re-certification. Such a value
belongs in source, under review, with a git history.

Everything with a *threshold* character -- the OOD counter thresholds
theta-1/2/3, the conformal significance level epsilon, the trust admissibility
threshold tau, the CDI limit delta_CDI, speed caps, the innovation Mahalanobis
gate gamma -- is **not** here. Those are operating points, they differ between
the development, simulation and certification environments, and a safety
engineer must be able to change them without a code review. They live in
:mod:`astra.config`.

The test for which module a value belongs in is: *if this value changed, would
the change be reviewed by a software engineer or by a safety engineer?*
Software engineer means here; safety engineer means configuration.

A note on the absence of thresholds
-----------------------------------
The source documents never assign numeric values to theta-1, theta-2, theta-3,
epsilon, gamma, tau or delta_CDI. That is not an oversight in the documents --
those values can only be fixed empirically once the pipeline runs. Phase 1
therefore provides the *typed, validated, documented slot* for each of them and
deliberately supplies no default that could be mistaken for a certified value.
See ``docs/ASSUMPTIONS.md``, assumption A-4.
"""

from __future__ import annotations

from typing import Final

__all__ = [
    "ASTRA_LAYER_COUNT",
    "AUDIT_SCHEMA_VERSION",
    "CONFIG_SCHEMA_VERSION",
    "CORE_B_GATE_COUNT",
    "FAILSAFE_STATE_COUNT",
    "FAST_STATE_DIMENSION",
    "FAST_STATE_FIELDS",
    "FEEDBACK_LOOP_COUNT",
    "RCS_DIMENSION",
    "RCS_FIELDS",
    "SENSOR_MODALITY_COUNT",
    "SLOW_STATE_DIMENSION",
    "SLOW_STATE_FIELDS",
]

# --------------------------------------------------------------------------- #
# Structural cardinalities
# --------------------------------------------------------------------------- #
# These are asserted against the enumerations in `astra.kernel.enums` by the
# architecture test suite. If someone adds a tenth layer or a fourth gate
# without updating the architecture documentation, the build fails.

ASTRA_LAYER_COUNT: Final = 9
"""Number of functional layers in the governance pipeline (L1-L9)."""

CORE_B_GATE_COUNT: Final = 3
"""Number of structurally independent safety gates inside Core-B.

Three is a load-bearing number, not an implementation detail. The independence
argument requires that each gate has a distinct failure mode; adding a fourth
gate that shares a failure mode with an existing one would weaken the argument
while appearing to strengthen it.
"""

FEEDBACK_LOOP_COUNT: Final = 4
"""Number of closed feedback loops (FB1-FB4)."""

FAILSAFE_STATE_COUNT: Final = 4
"""Number of states in the L8 fail-safe state machine."""

SENSOR_MODALITY_COUNT: Final = 5
"""Number of sensor modalities fused on the L1 shared sensor bus."""

# --------------------------------------------------------------------------- #
# State vector layouts
# --------------------------------------------------------------------------- #
# The *ordering* of these tuples is architectural. The ICP non-conformity score
# normalises by sigma(x) = sqrt(P_f[control dim]); "control dim" is an index
# into the fast covariance matrix. If the field order changed and one call site
# was missed, the gate would normalise by the wrong variance and would still
# produce plausible-looking numbers. Naming the layout once, here, makes that
# class of defect impossible to introduce silently.

FAST_STATE_FIELDS: Final[tuple[str, ...]] = (
    "position_x",
    "position_y",
    "speed",
    "heading",
    "lateral_acceleration",
)
"""Ordered field names of the fast UKF state ``x_f = [px, py, v, psi, a_lat]``."""

FAST_STATE_DIMENSION: Final = len(FAST_STATE_FIELDS)
"""Dimension ``n`` of the fast filter state. Drives the ``2n+1`` sigma points."""

SLOW_STATE_FIELDS: Final[tuple[str, ...]] = (
    "road_friction_coefficient",
    "tyre_wear_index",
    "sensor_health_score",
)
"""Ordered field names of the slow UKF state ``x_s = [mu_road, delta_tyre, rho_sensor]``."""

SLOW_STATE_DIMENSION: Final = len(SLOW_STATE_FIELDS)
"""Dimension of the slow filter state, tracking degradation processes."""

RCS_FIELDS: Final[tuple[str, ...]] = (
    "visibility",
    "ego_speed",
    "traffic_dynamicity",
    "sensor_reliability",
    "road_complexity",
)
"""Ordered components of the Runtime Context Signature ``r``.

Every element is normalised to [0, 1]. The ordering is fixed because a profile's
certified centroid and covariance in the Knowledge Base are stored as bare
numeric vectors; a reordering would silently invalidate every stored profile.
"""

RCS_DIMENSION: Final = len(RCS_FIELDS)
"""Dimension of the Runtime Context Signature. Five, per the paper's Section 2.6."""

# --------------------------------------------------------------------------- #
# Schema versions
# --------------------------------------------------------------------------- #
# Both the audit log and the configuration file carry an explicit schema
# version. NFR8 requires audit records to serve as certification evidence,
# which means records written today must still be interpretable years from now,
# after the schema has moved on. A version field is the cheapest possible
# insurance against an unreadable evidence archive.

AUDIT_SCHEMA_VERSION: Final = 9
"""Schema version stamped on every audit record. Increment on any field change.

Version 2 (ADR-0016) widened the verdict vocabulary: a gate verdict may now read
``ABSTAIN`` as well as ``PASS`` or ``VETO``. No field was added or removed, so a
version-1 reader will parse a version-2 record structurally -- and will
mis-classify an abstention, most likely as an unrecognised veto. That is exactly
the failure the version field exists to make loud rather than silent.

Version 3 (9 August 2026) adds ``fast_innovation`` to the decision record: the
Mahalanobis distance of the tick's fast innovation. The quantity was always
computed -- L6's covariate-shift window is fed from it and L3's Trust Index is
derived from it -- and reached the archive through neither, so a run's evidence
did not contain the one number in the pipeline that can *disagree* with the
state estimate. Added while measuring OD-9, where the question "could anything
in Core-B have seen this fault?" turned out to be unanswerable from the archive.

A version-2 reader parses a version-3 record structurally and will not see the
new key. That is the benign direction: it loses a signal rather than
misinterpreting one, unlike the version-1/2 boundary above.

Version 4 (9 August 2026) adds ``ablation``, naming which layers were disarmed
for the run. Unlike version 3 this boundary is **not** benign in the reading
direction: a version-3 reader sees an ablated run's records as a governed
run's, because every other field is identical by construction -- that is what
an ablation *is*. The version field is the only thing standing between an
ablation study and a certification artefact describing a system that was not
running, which is why ADR-0021 stamps the profile per tick rather than once
per run.

Version 5 (10 August 2026) adds ``previous_digest`` to every record, making
the evidence log a hash chain and therefore **tamper-evident** rather than
merely integrity-checked -- N-10, and the cheapest item in the threat model
written the same day. A version-4 reader ignores the field and loses only the
ability to detect tampering it could not detect before.

Version 6 (11 August 2026) adds ``integrity_counter`` to the fail-safe snapshot
(ADR-0024). The machine now escalates on two independent counters -- one for
sustained refusal, one for sustained sensor unhealth -- and the state alone no
longer says which. **This boundary is asymmetric in an interesting way.** A
version-5 reader loses only the new field, so it reads a DEGRADED posture and
cannot tell whether the gates refused or a sensor went dark; that is a loss of
attribution, not a misreading. But the *converse* matters more for a safety
case: every record written before version 6 was produced by a machine that
could not escalate on sensor health at all, so a version-5 archive showing
NOMINAL throughout a sensor fault is **correct about what that machine did** and
must not be compared against a version-6 archive as though the two were the same
system. That is precisely the OD-9 evidence (E-46), and the version field is
what keeps it from being quietly re-interpreted.

Version 7 (11 August 2026) adds ``signature`` to the arbitration decision: the
five-component runtime context signature RCM actually decided on. **It was
computed every cold-path evaluation, searched the knowledge base with, decided
on, and archived nowhere** -- so a record could say ``SAFE_EXPLORATION, trust
0.62`` and could not say what context produced it. The one question a reader of
an arbitration record most wants to ask was unanswerable from the archive
(OD-14).

Third time this shape has appeared: ``fast_innovation`` at version 3, and
``previous_digest`` at version 5 were both quantities the pipeline had and the
evidence did not. A version-6 reader loses the field and is back to not being
able to answer the question, which is the benign direction.

Version 8 (11 August 2026) adds ``integrity_counter`` to the fail-safe snapshot,
and it is the **fourth** instance of that shape in five versions. ADR-0024 gave
the machine two counters four days earlier and argued they must be reported
separately -- *"one integer cannot say which happened"* -- and the field went
onto the snapshot and not onto the record. So every archive between schema 6 and
8 carries that argument's conclusion and none of its evidence: a DEGRADED
posture with no way to tell whether the gates refused or a sensor went dark
(OD-16).

Found by the tool built to *read* the evidence, which is the same way OD-14 was
found one version earlier. A pipeline that computes a number is not a pipeline
whose evidence has it, and the only reliable way to notice is to try to use the
archive for something."""

CONFIG_SCHEMA_VERSION: Final = 1
"""Schema version required in every configuration file. Rejected if mismatched."""
