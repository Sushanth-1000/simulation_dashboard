"""Does the reconstruction say only what the record says?

Why these tests are mostly about absence
------------------------------------------
A forensic narrative is read by someone who was not there, after something went
wrong, and who has no way to check it against the system. That makes its failure
mode specific and severe: **a fluent account of a tick it did not fully have.**
Every mechanism defect this project has filed against a *document* — OD-2, OD-7,
OD-16, and the four-week staleness in ``SEPARATION_INVARIANTS.md`` — was an
artefact asserting something the system did not do, and an explainer is an
artefact-generator.

So most of what is asserted here is that a missing field stays missing. The
positive cases are easy and would pass on a module that also invents things.

The bug these tests would have caught
---------------------------------------
The first version read an absent ``integrity_counter`` as **zero**, and therefore
reported *"both counters equal; the record does not distinguish them"* on a HALT
that was caused entirely by sensor health. An inference dressed as a finding, on
exactly the field whose absence was OD-16. `test_an_absent_integrity_counter_is_not_a_zero`
is that bug.

**And this file exists because the module shipped without it.** `explain.py`
landed at **10% coverage** and passed the gate, because the 95% floor is an
aggregate over 160 files and the rest of the codebase carried it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from astra.observability.explain import explain_tick, find_tick, read_records

_HEALTHY = {"IMU": "HEALTHY", "GPS": "HEALTHY", "LIDAR": "HEALTHY"}


def record(**overrides: object) -> dict[str, Any]:
    """Return a complete record, overridable field by field."""
    base: dict[str, Any] = {
        "schema_version": 8,
        "run": "run-test0001",
        "tick": 42,
        "config_hash": "abc123",
        "ablation": "NONE",
        "frame_health": dict(_HEALTHY),
        "fast_state": {"mean": [1.0, 0.25, 12.5, 0.01, 0.08]},
        "fast_innovation": 0.9,
        "trust": {"trust_index": 0.96, "context_class": "URBAN_CLEAR", "is_calibrated": True},
        "safety_verdict": {
            "aggregate": "PASS",
            "gate_verdicts": [
                {
                    "gate": "STATISTICAL",
                    "verdict": "PASS",
                    "reason_code": "NOMINAL",
                    "evidence": {"score": 1.1},
                }
            ],
        },
        "failsafe": {
            "state": "NOMINAL",
            "ood_counter": 0,
            "integrity_counter": 0,
            "human_intervention_requested": False,
        },
        "arbitration": {
            "outcome": "CONTINUE",
            "active_profile": "urban_clear@v1",
            "signature": [0.85, 0.35, 0.7, 0.95, 0.7],
        },
        "issued": {"origin": "PROPOSED", "command": {"throttle": 0.5, "brake": 0.0, "steer": 0.01}},
    }
    base.update(overrides)
    return base


def rendered(**overrides: object) -> str:
    """Return the explanation for one record, as one searchable string."""
    return "\n".join(explain_tick(record(**overrides)))


# --------------------------------------------------------------------------- #
# Absence — the half that matters
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "field",
    ["fast_state", "trust", "safety_verdict", "failsafe", "arbitration", "fast_innovation"],
)
def test_a_missing_stage_reads_as_absent_rather_than_plausible(field: str) -> None:
    # A stage that did not run must never be filled in from what usually
    # happens. Same rule the dashboard follows, and for the same reason (E-79).
    assert "not recorded" in rendered(**{field: None})


def test_an_absent_integrity_counter_is_not_a_zero() -> None:
    """The module's own first bug, pinned.

    A pre-schema-8 archive has no ``integrity_counter``. Reading the absence as
    zero made the explainer conclude *"both counters equal"* on a HALT driven
    entirely by sensor health — which is an inference, on exactly the field
    whose absence is OD-16.
    """
    stale = {"state": "HALT", "ood_counter": 0, "human_intervention_requested": True}

    account = rendered(failsafe=stale)

    assert "cannot be told" in account
    assert "OD-16" in account
    assert "both counters equal" not in account
    assert "SUSTAINED REFUSAL" not in account


def test_an_arbitration_without_a_signature_names_the_schema_gap() -> None:
    account = rendered(arbitration={"outcome": "SAFE_EXPLORATION", "active_profile": "p@v1"})

    assert "not recorded" in account
    assert "OD-14" in account


def test_a_tick_that_issued_nothing_says_so_plainly() -> None:
    account = rendered(issued=None)

    assert "nothing" in account
    assert "no command reached an actuator" in account


# --------------------------------------------------------------------------- #
# Which counter escalated — the point of having two
# --------------------------------------------------------------------------- #


def test_a_posture_driven_by_sensor_health_says_so() -> None:
    account = rendered(
        failsafe={
            "state": "HALT",
            "ood_counter": 0,
            "integrity_counter": 40,
            "human_intervention_requested": True,
        }
    )

    assert "escalated on SENSOR HEALTH, not on any veto" in account
    assert "a handover has been requested" in account


def test_a_posture_driven_by_refusal_says_so() -> None:
    account = rendered(failsafe={"state": "LIMP", "ood_counter": 30, "integrity_counter": 0})

    assert "escalated on SUSTAINED REFUSAL, not on sensor health" in account


def test_equal_counters_are_reported_as_indistinguishable() -> None:
    # The honest third case. Claiming either cause here would be a coin toss
    # presented as a finding.
    account = rendered(failsafe={"state": "DEGRADED", "ood_counter": 10, "integrity_counter": 10})

    assert "does not distinguish them" in account


def test_a_nominal_posture_claims_no_cause_at_all() -> None:
    account = rendered()

    assert "escalated on" not in account


# --------------------------------------------------------------------------- #
# The things a reader must not miss
# --------------------------------------------------------------------------- #


def test_an_ablated_run_announces_itself_before_anything_else() -> None:
    # A study's records are identical to a governed run's by construction --
    # that is what an ablation *is* (ADR-0021). An explanation that did not lead
    # with it would describe a system that was not running.
    account = rendered(ablation="STATISTICAL")

    assert "ABLATION" in account
    assert "not a governed run" in account
    assert account.index("ABLATION") < account.index("sensor health")


def test_a_capped_command_says_the_cap_altered_it() -> None:
    account = rendered(
        issued={"origin": "SPEED_CAPPED", "command": {"throttle": 0.0, "brake": 1.0}}
    )

    assert "ALTERED" in account


def test_a_fallback_command_says_the_proposal_was_refused() -> None:
    account = rendered(
        issued={"origin": "FALLBACK_PID", "command": {"throttle": 0.1, "brake": 0.0}}
    )

    assert "the proposal was refused" in account


def test_unhealthy_modalities_are_counted_and_named() -> None:
    account = rendered(frame_health={"IMU": "ABSENT", "GPS": "HEALTHY", "LIDAR": "FAULTED"})

    assert "2 not healthy" in account
    assert "IMU" in account
    assert "LIDAR" in account


def test_every_gate_verdict_carries_its_evidence() -> None:
    account = rendered(
        safety_verdict={
            "aggregate": "VETO",
            "gate_verdicts": [
                {
                    "gate": "PHYSICAL",
                    "verdict": "VETO",
                    "reason_code": "LATERAL_JERK_EXCEEDS_LIMIT",
                    "evidence": {"demanded_jerk_mps3": 9.1, "max_lateral_jerk_mps3": 8.0},
                }
            ],
        }
    )

    assert "LATERAL_JERK_EXCEEDS_LIMIT" in account
    assert "demanded_jerk_mps3 = 9.1" in account


def test_an_uncalibrated_class_is_called_out() -> None:
    account = rendered(
        trust={"trust_index": 0.5, "context_class": "UNCLASSIFIED", "is_calibrated": False}
    )

    assert "too few samples" in account


def test_the_account_states_that_it_infers_nothing() -> None:
    # The disclaimer is part of the artefact, not decoration: a reader who does
    # not know the rule cannot apply it.
    account = rendered()

    assert "Nothing is inferred" in account


# --------------------------------------------------------------------------- #
# Reading the log
# --------------------------------------------------------------------------- #


def test_records_are_read_in_order_from_a_file(tmp_path: Path) -> None:
    log = tmp_path / "events.jsonl"
    log.write_text(
        "\n".join(json.dumps(record(tick=tick)) for tick in (1, 2, 3)) + "\n", encoding="utf-8"
    )

    assert [entry["tick"] for entry in read_records(log)] == [1, 2, 3]


def test_a_directory_is_searched_for_a_log(tmp_path: Path) -> None:
    nested = tmp_path / "run-0001"
    nested.mkdir()
    (nested / "events.jsonl").write_text(json.dumps(record()) + "\n", encoding="utf-8")

    assert len(list(read_records(tmp_path))) == 1


def test_a_directory_with_no_log_is_an_error_rather_than_an_empty_answer(tmp_path: Path) -> None:
    # Returning nothing would read as "this run did nothing", which is the
    # inverse of the truth and the worst available answer.
    with pytest.raises(ValueError, match=r"no \.jsonl audit log"):
        list(read_records(tmp_path))


def test_blank_lines_are_skipped(tmp_path: Path) -> None:
    log = tmp_path / "events.jsonl"
    log.write_text(json.dumps(record()) + "\n\n\n", encoding="utf-8")

    assert len(list(read_records(log))) == 1


def test_finding_a_tick_that_is_not_there_returns_none() -> None:
    assert find_tick([record(tick=1)], 99) is None


def test_finding_a_tick_returns_that_tick() -> None:
    found = find_tick([record(tick=1), record(tick=2)], 2)

    assert found is not None
    assert found["tick"] == 2


def test_a_frame_with_no_health_at_all_reads_as_absent() -> None:
    account = rendered(frame_health={})

    assert "not recorded" in account


def test_a_staged_switch_reports_its_candidate_and_score() -> None:
    account = rendered(
        arbitration={
            "outcome": "SHADOW_EXECUTION",
            "active_profile": "urban_clear@v1",
            "candidate_profile": "highway_clear@v1",
            "trust_score": 0.717,
            "signature": [0.85, 0.35, 0.7, 0.95, 0.7],
        }
    )

    assert "highway_clear@v1" in account
    assert "0.717" in account


def test_an_exploration_bounded_command_says_it_was_clamped() -> None:
    account = rendered(
        issued={"origin": "EXPLORATION_BOUNDED", "command": {"throttle": 0.2, "steer": 0.05}}
    )

    assert "narrowed exploration envelope" in account
