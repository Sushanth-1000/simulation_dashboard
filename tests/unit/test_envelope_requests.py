"""Does the proposer refuse the episodes it should, and propose nothing that acts?

The line these tests defend
-----------------------------
A calibration **request** carries a centroid, a spread and a safety record. A
calibration **profile** carries a conformal quantile table. The proposer must
never cross from one to the other, because a quantile table fitted to the
vehicle's own exploration is FB3 by another name: requantilising on
self-generated scores pins the veto rate to ``significance_epsilon`` **by
construction**, and nothing about it looks like an error (E-40).

Two of these tests exist solely to assert that line, and they check the *type*
rather than the behaviour -- a proposer that grew a quantile table would still
pass every behavioural test in this file.

The three filters, tested at their boundaries
-----------------------------------------------
An episode is proposable only if it is **sustained** (not a transition),
**safe** (not evidence against the context), and **coherent** (one context
rather than an average of several). The third is the one that is easy to forget
and the easiest to get wrong silently: a vehicle passing through three
unfamiliar contexts produces a mean signature describing none of them.
"""

from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path
from typing import Any

import pytest

from astra.contracts.governance import CalibrationProfile
from astra.kernel.constants import RCS_DIMENSION
from benchmarks.envelope import (
    _COHERENCE_LIMIT,
    _MINIMUM_TICKS,
    Request,
    propose,
    read_ticks,
)

TUNNEL = [0.05, 0.25, 0.7, 0.95, 0.95]


def record(
    tick: int,
    *,
    exploring: bool = True,
    signature: list[float] | None = None,
    veto: bool = False,
    escalated: bool = False,
    issued: bool = True,
) -> dict[str, Any]:
    """Build one decision record as the audit log renders it."""
    return {
        "schema_version": 7,
        "tick": tick,
        "arbitration": {
            "outcome": "SAFE_EXPLORATION" if exploring else "CONTINUE",
            "active_profile": "highway_clear@v1",
            "signature": TUNNEL if signature is None else signature,
        },
        "safety_verdict": {"aggregate": "VETO" if veto else "PASS"},
        "failsafe": {"state": "DEGRADED" if escalated else "NOMINAL"},
        "issued": {"origin": "PROPOSED"} if issued else None,
    }


def episode(
    ticks: int,
    *,
    signature: list[float] | None = None,
    veto: bool = False,
    escalated: bool = False,
    issued: bool = True,
) -> list[dict[str, Any]]:
    """Build one uninterrupted exploration episode."""
    return [
        record(tick, signature=signature, veto=veto, escalated=escalated, issued=issued)
        for tick in range(ticks)
    ]


# --------------------------------------------------------------------------- #
# The line that must not be crossed
# --------------------------------------------------------------------------- #


def test_a_request_carries_no_quantile_table() -> None:
    """The whole safety argument, asserted structurally.

    A behavioural test cannot catch this: a proposer that started emitting
    quantile tables would still produce correct centroids and spreads. So the
    check is on the type, and it fails the moment the field appears.
    """
    names = {declared.name for declared in fields(Request)}

    assert "quantile_table" not in names
    assert "coverage_level" not in names
    assert "certified_at" not in names
    assert "expires_at" not in names


def test_a_request_is_not_a_calibration_profile() -> None:
    # Stated as a type relationship rather than a comment, so that "just return
    # a CalibrationProfile, it is nearly the same shape" fails the build.
    #
    # The discriminating field is named explicitly: a profile carries a
    # quantile table and a request must never acquire one, so the two field
    # sets are asserted to differ in exactly that direction.
    profile_fields = {declared.name for declared in fields(CalibrationProfile)}
    request_fields = {declared.name for declared in fields(Request)}

    assert not issubclass(Request, CalibrationProfile)
    assert "quantile_table" in profile_fields
    assert "quantile_table" not in request_fields


# --------------------------------------------------------------------------- #
# Sustained
# --------------------------------------------------------------------------- #


def test_a_long_safe_coherent_episode_is_proposable() -> None:
    requests = propose(episode(_MINIMUM_TICKS + 50))

    assert len(requests) == 1
    assert requests[0].proposable
    assert requests[0].ticks == _MINIMUM_TICKS + 50


def test_a_short_episode_is_a_transition_not_a_context() -> None:
    requests = propose(episode(_MINIMUM_TICKS - 1))

    assert not requests[0].proposable
    assert "transition" in requests[0].reason


def test_a_rejected_episode_is_still_reported() -> None:
    # A proposer that silently dropped what it rejected would give an engineer
    # no way to discover that its filters were wrong.
    requests = propose(episode(10))

    assert len(requests) == 1
    assert not requests[0].proposable
    assert requests[0].reason


def test_non_exploration_ticks_split_episodes() -> None:
    records = [
        *episode(100),
        record(100, exploring=False),
        *(record(tick) for tick in range(101, 201)),
    ]

    requests = propose(records)

    assert len(requests) == 2


# --------------------------------------------------------------------------- #
# Safe
# --------------------------------------------------------------------------- #


def test_a_heavily_vetoed_episode_is_evidence_against_the_context() -> None:
    records = episode(_MINIMUM_TICKS + 50, veto=True)

    requests = propose(records)

    assert not requests[0].proposable
    assert "unsafe" in requests[0].reason


def test_an_escalated_episode_is_refused() -> None:
    records = episode(_MINIMUM_TICKS + 50, escalated=True)

    requests = propose(records)

    assert not requests[0].proposable
    assert "fail-safe" in requests[0].reason


def test_an_episode_that_stopped_driving_is_refused() -> None:
    # Availability below 1.0 means the vehicle was not being commanded, so the
    # episode is not evidence that it drives well here.
    records = episode(_MINIMUM_TICKS + 50, issued=False)

    requests = propose(records)

    assert not requests[0].proposable
    assert "not driving" in requests[0].reason


# --------------------------------------------------------------------------- #
# Coherent — the filter that is easy to forget
# --------------------------------------------------------------------------- #


def test_two_contexts_in_one_stretch_are_refused_rather_than_averaged() -> None:
    """The failure this filter exists for.

    A vehicle that drives from a tunnel into clear daylight without any profile
    matching produces one long exploration episode whose *mean* visibility is
    about 0.5 -- a context that never existed and that nobody should be asked to
    calibrate for.
    """
    dark = [0.05, 0.25, 0.7, 0.95, 0.95]
    bright = [0.95, 0.25, 0.7, 0.95, 0.95]
    records = [
        record(tick, signature=dark if tick < 150 else bright)
        for tick in range(_MINIMUM_TICKS + 100)
    ]

    requests = propose(records)

    assert not requests[0].proposable
    assert "incoherent" in requests[0].reason
    assert "visibility" in requests[0].reason


def test_the_coherence_limit_is_on_every_component_not_just_the_worst() -> None:
    requests = propose(episode(_MINIMUM_TICKS + 50))

    assert requests[0].coherent
    assert max(requests[0].spread) <= _COHERENCE_LIMIT


def test_the_centroid_has_one_value_per_signature_component() -> None:
    requests = propose(episode(_MINIMUM_TICKS + 50))

    assert len(requests[0].centroid) == RCS_DIMENSION
    assert len(requests[0].spread) == RCS_DIMENSION


# --------------------------------------------------------------------------- #
# The schema dependency
# --------------------------------------------------------------------------- #


def test_a_pre_version_7_log_is_refused_rather_than_guessed_at(tmp_path: Path) -> None:
    """OD-14's boundary, asserted.

    A version-6 archive records that RCM chose SAFE_EXPLORATION and cannot say
    what context that was about. Proposing from it would mean inventing the one
    field this module exists to read.
    """
    log = tmp_path / "events.jsonl"
    stale = record(0)
    stale["schema_version"] = 6
    log.write_text(json.dumps(stale) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match=r"v6.*v7") as raised:
        list(read_ticks(log))

    assert "signature" in str(raised.value)


def test_an_episode_with_no_signature_is_not_proposable() -> None:
    records = episode(_MINIMUM_TICKS + 50)
    for entry in records:
        arbitration = entry["arbitration"]
        assert isinstance(arbitration, dict)
        arbitration.pop("signature")

    requests = propose(records)

    assert not requests[0].proposable
    assert "signature" in requests[0].reason
