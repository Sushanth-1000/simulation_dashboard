"""Does the evidence log actually detect tampering?

Why this file exists
---------------------
`EVIDENCE.md` N-10 said the log was *"integrity-checked, not tamper-evident"* --
records were append-only JSONL with a schema version and a configuration hash,
and nothing chained one record to the next, so a record could be altered,
removed or inserted without any other record disagreeing.

That matters more than it first sounds. The evidence log is what a certification
argument is made of, so an adversary who can rewrite it does not need to touch
the vehicle at all: they change what the vehicle is *recorded* to have done.
Every other threat in ``docs/THREAT_MODEL.md`` leaves a physical signature
somewhere. That one does not.

Each record now carries the SHA-256 digest of the serialised line before it. The
claim under test is therefore precise: **altering, removing or inserting a record
anywhere in the file must break verification.**

The one thing this cannot do, asserted so it stays honest
-----------------------------------------------------------
:func:`test_dropping_the_last_records_is_not_detectable` asserts a *limitation*
rather than a capability, and it is deliberate. A prefix of a valid chain is
itself a valid chain, so truncating the tail is undetectable by chaining alone.
Catching it needs an external record of the expected length or a signed root,
and signing needs key management this project does not have.

A test suite that only demonstrated the strengths would be the same defect as an
evidence pack without a "not demonstrated" section.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from astra.kernel.identifiers import RunId, TickId
from astra.observability.audit import (
    EVENTS_FILENAME,
    GENESIS_DIGEST,
    JsonlAuditSink,
    verify_chain,
)

if TYPE_CHECKING:
    from pathlib import Path

RUN = RunId("run-chaintest000001")
RECORDS = 12


def written(directory: Path) -> Path:
    """Return the evidence file for a run written under this directory."""
    return directory / RUN.value / EVENTS_FILENAME


@pytest.fixture
def evidence(tmp_path: Path) -> Path:
    """Write a short, valid run and return its evidence file."""
    from astra.contracts.audit import DecisionRecord  # noqa: PLC0415

    with JsonlAuditSink(run=RUN, directory=tmp_path) as sink:
        for tick in range(RECORDS):
            sink.record_decision(
                DecisionRecord(run=RUN, tick=TickId(tick), config_hash="sha256:test")
            )
        sink.flush()
    return written(tmp_path)


def lines(path: Path) -> list[str]:
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def rewrite(path: Path, rows: list[str]) -> None:
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# An untouched log verifies
# --------------------------------------------------------------------------- #


def test_a_run_written_normally_verifies(evidence: Path) -> None:
    assert verify_chain(evidence) is None
    assert len(lines(evidence)) == RECORDS


def test_the_first_record_starts_from_the_genesis_digest(evidence: Path) -> None:
    # So a verifier needs nothing but the file to check the chain from its
    # first line -- no out-of-band starting value to be lost or substituted.
    assert json.loads(lines(evidence)[0])["previous_digest"] == GENESIS_DIGEST


def test_every_record_carries_the_link(evidence: Path) -> None:
    assert all("previous_digest" in json.loads(line) for line in lines(evidence))


# --------------------------------------------------------------------------- #
# Tampering is detected
# --------------------------------------------------------------------------- #


def test_altering_a_record_breaks_the_chain_at_the_next_one(evidence: Path) -> None:
    rows = lines(evidence)
    target = 5
    payload = json.loads(rows[target])
    payload["config_hash"] = "sha256:forged"
    rows[target] = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    rewrite(evidence, rows)

    break_ = verify_chain(evidence)

    assert break_ is not None
    assert break_.index == target + 1  # the altered record's *successor* disagrees
    assert break_.reason == "mismatch"


def test_removing_a_record_breaks_the_chain(evidence: Path) -> None:
    rows = lines(evidence)
    del rows[4]
    rewrite(evidence, rows)

    break_ = verify_chain(evidence)

    assert break_ is not None
    assert break_.index == 4


def test_inserting_a_record_breaks_the_chain(evidence: Path) -> None:
    rows = lines(evidence)
    forged = json.loads(rows[2])
    forged["tick"] = 999
    rows.insert(6, json.dumps(forged, separators=(",", ":"), ensure_ascii=False))
    rewrite(evidence, rows)

    break_ = verify_chain(evidence)

    assert break_ is not None
    assert break_.index == 6


def test_reordering_two_records_breaks_the_chain(evidence: Path) -> None:
    rows = lines(evidence)
    rows[3], rows[7] = rows[7], rows[3]
    rewrite(evidence, rows)

    assert verify_chain(evidence) is not None


def test_a_record_with_its_link_stripped_is_reported_as_missing(evidence: Path) -> None:
    rows = lines(evidence)
    payload = json.loads(rows[2])
    del payload["previous_digest"]
    rows[2] = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    rewrite(evidence, rows)

    break_ = verify_chain(evidence)

    assert break_ is not None
    assert break_.reason == "missing"


def test_an_unparseable_line_is_reported_rather_than_skipped(evidence: Path) -> None:
    # Skipping it would let an attacker hide a record behind a syntax error.
    rows = lines(evidence)
    rows[3] = "{not json"
    rewrite(evidence, rows)

    break_ = verify_chain(evidence)

    assert break_ is not None
    assert break_.reason == "unparseable"


def test_rewriting_one_record_and_relinking_only_it_still_breaks(evidence: Path) -> None:
    # The realistic attempt: alter a record and fix up its *own* link so it
    # follows its predecessor. The chain still breaks at the successor, because
    # the successor's link covers the altered line's digest.
    import hashlib  # noqa: PLC0415

    rows = lines(evidence)
    target = 4
    payload = json.loads(rows[target])
    payload["config_hash"] = "sha256:forged"
    payload["previous_digest"] = hashlib.sha256(rows[target - 1].encode("utf-8")).hexdigest()
    rows[target] = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    rewrite(evidence, rows)

    break_ = verify_chain(evidence)

    assert break_ is not None
    assert break_.index == target + 1


# --------------------------------------------------------------------------- #
# The limitation, asserted rather than omitted
# --------------------------------------------------------------------------- #


def test_dropping_the_last_records_is_not_detectable(evidence: Path) -> None:
    # A prefix of a valid chain is a valid chain. This is the honest bound on
    # what chaining buys, and it is why THREAT_MODEL.md 5.4 lists a signed root
    # as a separate requirement rather than treating this as closed.
    rows = lines(evidence)
    rewrite(evidence, rows[:6])

    assert verify_chain(evidence) is None


def test_rewriting_the_whole_file_consistently_is_not_detectable(evidence: Path) -> None:
    # Tamper-*evident*, not tamper-proof. An adversary who can rewrite every
    # record can recompute every link. What chaining removes is the *silent*
    # single-record edit, and what would catch this is an independently held
    # digest of the final record.
    import hashlib  # noqa: PLC0415

    rows = []
    previous = GENESIS_DIGEST
    for tick in range(RECORDS):
        payload = {"schema_version": 5, "tick": tick, "forged": True, "previous_digest": previous}
        line = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        previous = hashlib.sha256(line.encode("utf-8")).hexdigest()
        rows.append(line)
    rewrite(evidence, rows)

    assert verify_chain(evidence) is None


# --------------------------------------------------------------------------- #
# Operational edges
# --------------------------------------------------------------------------- #


def test_an_empty_log_verifies(tmp_path: Path) -> None:
    path = tmp_path / "empty.jsonl"
    path.write_text("", encoding="utf-8")

    assert verify_chain(path) is None


def test_blank_lines_do_not_break_a_valid_chain(evidence: Path) -> None:
    rows = lines(evidence)
    rows.insert(4, "")
    rewrite(evidence, rows)

    assert verify_chain(evidence) is None


def test_a_missing_file_is_an_adapter_error_rather_than_a_silent_pass(tmp_path: Path) -> None:
    from astra.kernel.errors import AdapterError  # noqa: PLC0415

    with pytest.raises(AdapterError):
        verify_chain(tmp_path / "does-not-exist.jsonl")


def test_events_and_decisions_share_one_chain(tmp_path: Path) -> None:
    # Both record types go through the same sink, so both must be links in the
    # same chain -- a separate chain per type would let a whole type be dropped.
    from astra.contracts.audit import AuditEvent, DecisionRecord  # noqa: PLC0415
    from astra.kernel.enums import EventSeverity  # noqa: PLC0415
    from astra.kernel.identifiers import EventId  # noqa: PLC0415

    with JsonlAuditSink(run=RUN, directory=tmp_path) as sink:
        for tick in range(4):
            sink.record_decision(
                DecisionRecord(run=RUN, tick=TickId(tick), config_hash="sha256:test")
            )
            sink.emit(
                AuditEvent(
                    event_id=EventId(run=RUN, tick=TickId(tick), sequence=0),
                    severity=EventSeverity.INFO,
                    kind="tick",
                    payload={},
                )
            )
        sink.flush()

    path = written(tmp_path)
    assert verify_chain(path) is None
    assert len(lines(path)) == 8
