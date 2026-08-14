"""Why did the vehicle do that, at that tick? Answered from the log alone.

What this is for
-----------------
After an incident, somebody asks one question: *why did it do that?* Today the
answer lives in whoever still remembers the architecture. This turns it into a
command anyone can run against the evidence archive, months later, on a machine
that has never seen the vehicle.

That is assumption **A-10**, which defines explainability for this project as
**decision provenance** rather than model-internal attribution:

    the inputs a decision was taken on, recorded beside it.

A-10 has been a definition without a reader. This is the reader.

Why it can exist now and could not before
------------------------------------------
Three things had to land first, and each was a defect when it was found.

- **The innovation** reached the archive at audit schema 3 (E-54). Before that
  the one quantity that can *disagree* with the state estimate was computed,
  consumed by two layers, and archived nowhere.
- **The ablation profile** at schema 4, so a reconstruction cannot mistake a
  study for a governed run (ADR-0021).
- **The context signature** at schema 7 (OD-14), so an arbitration decision can
  finally say *what it was about* rather than only what it was.

A narrative built before any of those would have been fluent and incomplete,
which is worse than absent: it reads as an explanation.

What it refuses to do
----------------------
**It never infers.** Every line traces to a field on the record, and a field
that is ``None`` is reported as *not recorded* rather than filled in from what
usually happens. A stage that did not run reads as absent, which is the same
rule ``demo/dashboard.py`` follows and for the same reason (E-79): the most
alarming thing an explanation can do is sound complete.

**It does not rank causes.** A tick with three vetoes is reported as three
vetoes, not as one root cause and two consequences. Attributing causality
between gates is exactly what SI-3 forbids the *escalation policy* from doing,
and an explainer that did it anyway would put the same forbidden reasoning in
front of a reader who cannot see that it is forbidden.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from astra.kernel.constants import RCS_FIELDS

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from pathlib import Path

__all__ = ["explain_tick", "find_tick", "read_records"]

_ABSENT = "not recorded"
"""What a missing field reads as. Never a plausible default."""


def read_records(path: Path) -> Iterator[dict[str, Any]]:
    """Yield the decision records in an audit log, in order.

    Args:
        path: A JSONL audit log, or a directory containing one.

    Yields:
        Each record as a mapping.

    Raises:
        ValueError: If the path holds no ``.jsonl`` log.
    """
    if path.is_dir():
        candidates = sorted(path.rglob("*.jsonl"))
        if not candidates:
            message = f"no .jsonl audit log under {path}"
            raise ValueError(message)
        path = candidates[0]
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def find_tick(records: Sequence[dict[str, Any]], tick: int) -> dict[str, Any] | None:
    """Return the record for one tick.

    Args:
        records: The log, in order.
        tick: The tick to find.

    Returns:
        The record, or ``None`` if the log does not contain that tick.
    """
    return next((record for record in records if record.get("tick") == tick), None)


def _sentence(label: str, value: object) -> str:
    """Return one reported line, or the absence marker."""
    return f"  {label:<24}{_ABSENT if value is None else value}"


def _sensing(record: dict[str, Any]) -> list[str]:
    """Return what the sensors said."""
    health = record.get("frame_health")
    if not health:
        return [_sentence("sensor health", None)]
    lines = ["  sensor health"]
    lines.extend(f"    {name:<20}{state}" for name, state in sorted(health.items()))
    unhealthy = [name for name, state in sorted(health.items()) if state != "HEALTHY"]
    if unhealthy:
        lines.append(f"    -> {len(unhealthy)} not healthy: {', '.join(unhealthy)}")
    return lines


def _estimate(record: dict[str, Any]) -> list[str]:
    """Return what the filter concluded, and how surprised it was."""
    state = record.get("fast_state")
    lines = [
        _sentence(
            "position estimate",
            None if state is None else f"{state['mean'][1]:+.3f} m lateral",
        ),
        _sentence("speed estimate", None if state is None else f"{state['mean'][2]:.2f} m/s"),
        _sentence("innovation", record.get("fast_innovation")),
    ]
    trust = record.get("trust")
    if trust is not None:
        lines.append(_sentence("trust index", f"{trust['trust_index']:.3f}"))
        lines.append(_sentence("context class", trust.get("context_class")))
        if trust.get("is_calibrated") is False:
            lines.append("    -> the class held too few samples to certify a quantile")
    return lines


def _verdicts(record: dict[str, Any]) -> list[str]:
    """Return what each gate decided, and why."""
    verdict = record.get("safety_verdict")
    if verdict is None:
        return [_sentence("gates", None)]
    lines = [f"  {'gates':<24}{verdict['aggregate']}"]
    for gate in verdict.get("gate_verdicts", ()):
        lines.append(f"    {gate['gate']:<20}{gate['verdict']:<10}{gate['reason_code']}")
        for key, value in (gate.get("evidence") or {}).items():
            lines.append(f"      {key} = {value}")
    return lines


def _posture(record: dict[str, Any]) -> list[str]:
    """Return the fail-safe posture and **which counter** put it there."""
    failsafe = record.get("failsafe")
    if failsafe is None:
        return [_sentence("fail-safe", None)]
    lines = [
        f"  {'fail-safe':<24}{failsafe['state']}",
        f"    {'ood counter':<20}{failsafe['ood_counter']}  (sustained refusal)",
        (
            f"    {'integrity counter':<20}"
            f"{failsafe.get('integrity_counter', _ABSENT)}  (sustained sensor unhealth)"
        ),
    ]
    # The two counters exist precisely so a reader can tell which condition
    # escalated the posture (ADR-0024). Saying so is the point of the pair.
    ood = failsafe["ood_counter"]
    integrity = failsafe.get("integrity_counter")
    if failsafe["state"] != "NOMINAL":
        if integrity is None:
            # An absent field is not a zero. Reading it as one would have
            # reported "escalated on sustained refusal" for a run whose archive
            # simply predates schema 8 -- an inference dressed as a finding, and
            # exactly what this module refuses to do.
            lines.append("    -> which counter escalated cannot be told: the integrity")
            lines.append("       counter is absent from this archive (schema < 8, OD-16)")
        elif integrity > ood:
            lines.append("    -> escalated on SENSOR HEALTH, not on any veto")
        elif ood > integrity:
            lines.append("    -> escalated on SUSTAINED REFUSAL, not on sensor health")
        else:
            lines.append("    -> both counters equal; the record does not distinguish them")
    if failsafe.get("human_intervention_requested"):
        lines.append("    -> a handover has been requested")
    return lines


def _arbitration(record: dict[str, Any]) -> list[str]:
    """Return what RCM decided, and the context it decided about."""
    arbitration = record.get("arbitration")
    if arbitration is None:
        return [_sentence("arbitration", None)]
    lines = [
        f"  {'arbitration':<24}{arbitration['outcome']}",
        f"    {'active profile':<20}{arbitration['active_profile']}",
    ]
    if arbitration.get("candidate_profile"):
        lines.append(f"    {'candidate':<20}{arbitration['candidate_profile']}")
    if arbitration.get("trust_score") is not None:
        lines.append(f"    {'trust score':<20}{arbitration['trust_score']:.3f}")
    signature = arbitration.get("signature")
    if signature is None:
        lines.append(f"    {'context':<20}{_ABSENT} (audit schema < 7; see OD-14)")
    else:
        lines.append("    context")
        lines.extend(
            f"      {name:<18}{value:.3f}"
            for name, value in zip(RCS_FIELDS, signature, strict=True)
        )
    return lines


def _issued(record: dict[str, Any]) -> list[str]:
    """Return what actually reached the actuators."""
    issued = record.get("issued")
    if issued is None:
        return [
            f"  {'issued':<24}nothing",
            "    -> no command reached an actuator on this tick",
        ]
    lines = [
        f"  {'issued':<24}{issued['origin']}",
        f"    {'command':<20}"
        + ", ".join(f"{name}={value:+.4f}" for name, value in issued["command"].items()),
    ]
    if issued["origin"] == "SPEED_CAPPED":
        lines.append("    -> a cap ALTERED this command; it is not the one proposed")
    elif issued["origin"] == "FALLBACK_PID":
        lines.append("    -> the proposal was refused; this came from the fallback controller")
    elif issued["origin"] == "EXPLORATION_BOUNDED":
        lines.append("    -> clamped into the narrowed exploration envelope")
    return lines


def explain_tick(record: dict[str, Any]) -> list[str]:
    """Return a human-readable account of one tick, from the record alone.

    The order is the order the pipeline ran in — sensors, estimate, gates,
    posture, arbitration, command — so a reader follows causality forwards
    rather than reconstructing it.

    Args:
        record: One decision record.

    Returns:
        Lines to print.
    """
    lines = [
        "",
        f"  TICK {record.get('tick')}   run {record.get('run')}",
        f"  {'config':<24}{record.get('config_hash', _ABSENT)}",
        f"  {'audit schema':<24}v{record.get('schema_version', _ABSENT)}",
    ]
    ablation = record.get("ablation", "NONE")
    if ablation != "NONE":
        lines.append(f"  {'ABLATION':<24}{ablation}")
        lines.append("    -> layers were DISARMED for this run; it is not a governed run")
    lines.append("")
    for section in (_sensing, _estimate, _verdicts, _posture, _arbitration, _issued):
        lines.extend(section(record))
        lines.append("")
    lines.append("  Every line above is a field of this record. Nothing is inferred,")
    lines.append(f"  and a stage that did not run reads as '{_ABSENT}'.")
    return lines
