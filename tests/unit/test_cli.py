"""The ``astra`` command-line interface."""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

import pytest

from astra import __version__
from astra.bootstrap.cli import main
from astra.invariants.catalogue import SEPARATION_INVARIANTS
from astra.observability.logging import shutdown_logging

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_IDENTIFIERS = tuple(entry.identifier for entry in SEPARATION_INVARIANTS)


@pytest.fixture(autouse=True)
def _hermetic_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in [key for key in os.environ if key.startswith("ASTRA_")]:
        monkeypatch.delenv(name, raising=False)
    # The doctor probes the configured evidence directory for writability, which
    # would otherwise create one inside the repository tree.
    monkeypatch.setenv("ASTRA_OBSERVABILITY__LOG_DIRECTORY", str(tmp_path / "runs"))


@pytest.fixture(autouse=True)
def _no_leaked_logging_listener() -> Iterator[None]:
    try:
        yield
    finally:
        shutdown_logging()


# --------------------------------------------------------------------------- #
# version
# --------------------------------------------------------------------------- #


def test_the_version_command_succeeds_and_prints_the_package_version(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["version"]) == 0
    assert f"astra {__version__}" in capsys.readouterr().out


def test_the_version_flag_exits_zero_through_argparse(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_invoking_no_command_is_a_usage_error() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main([])
    assert excinfo.value.code != 0


# --------------------------------------------------------------------------- #
# doctor
# --------------------------------------------------------------------------- #


def test_the_doctor_succeeds_on_the_development_environment(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["doctor", "-e", "development"]) == 0
    assert "this installation can start a run" in capsys.readouterr().out


def test_the_doctor_succeeds_on_the_default_environment(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["doctor"]) == 0
    assert "OK" in capsys.readouterr().out


def test_the_doctor_does_not_create_the_evidence_directory_it_probes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    # A diagnostic must not modify the system it reports on. If doctor created
    # the directory, its own next run would pass for a reason unrelated to the
    # installation being sound.
    evidence = tmp_path / "not-yet" / "runs"
    monkeypatch.setenv("ASTRA_OBSERVABILITY__LOG_DIRECTORY", str(evidence))

    assert main(["doctor", "-e", "development"]) == 0

    assert "writable" in capsys.readouterr().out
    assert not evidence.exists()


def test_the_doctor_reports_an_unwritable_evidence_directory_as_a_problem(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    blocker = tmp_path / "a-file-not-a-directory"
    blocker.write_text("", encoding="utf-8")
    monkeypatch.setenv("ASTRA_OBSERVABILITY__LOG_DIRECTORY", str(blocker / "runs"))

    assert main(["doctor", "-e", "development"]) == 1
    assert "NOT WRITABLE" in capsys.readouterr().out


def test_the_doctor_reports_the_invariant_count_and_the_configuration_hash(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["doctor"]) == 0
    output = capsys.readouterr().out
    assert "Separation invariants" in output
    assert f"declared           {len(SEPARATION_INVARIANTS)}" in output
    assert "mechanically enforced" in output
    assert "config hash" in output


def test_the_doctor_reports_the_interpreter_and_the_architecture_cardinalities(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["doctor"]) == 0
    output = capsys.readouterr().out
    assert "ASTRA environment" in output
    assert "python" in output
    assert "layers" in output


def test_the_doctor_fails_on_the_incomplete_certification_environment(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["doctor", "-e", "certification"]) == 1
    output = capsys.readouterr().out
    assert "FAILED" in output
    assert "A-4" in output or "assumption A-4" in output
    assert "would prevent a run" in output


def test_the_doctor_names_the_missing_safety_thresholds_on_certification(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["doctor", "-e", "certification"]) == 1
    output = capsys.readouterr().out
    assert "safety threshold" in output
    assert "shield" in output


def test_the_doctor_fails_on_an_unknown_environment(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["doctor", "-e", "no-such-environment"]) == 1
    assert "PROBLEM" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# config show
# --------------------------------------------------------------------------- #


def test_config_show_renders_the_resolved_configuration_as_text(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["config", "show"]) == 0
    output = capsys.readouterr().out
    assert "# environment  development" in output
    assert "# hash" in output
    assert "shield:" in output


def test_config_show_emits_parseable_json_carrying_the_hash_and_the_settings(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["config", "show", "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert set(payload) == {"hash", "sources", "settings"}
    assert isinstance(payload["hash"], str)
    assert payload["hash"]
    assert payload["settings"]["environment"] == "development"
    assert "shield" in payload["settings"]


def test_config_show_json_lists_the_sources_the_configuration_came_from(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["config", "show", "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert any("astra.defaults.toml" in source for source in payload["sources"])


def test_config_show_fails_on_the_incomplete_certification_environment(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["config", "show", "-e", "certification"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "could not be resolved" in captured.err


def test_config_show_json_also_fails_on_certification(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["config", "show", "-e", "certification", "--format", "json"]) == 1
    assert capsys.readouterr().out == ""


# --------------------------------------------------------------------------- #
# invariants list
# --------------------------------------------------------------------------- #


def test_invariants_list_prints_every_declared_identifier(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["invariants", "list"]) == 0
    output = capsys.readouterr().out
    for identifier in _IDENTIFIERS:
        assert identifier in output


def test_invariants_list_prints_each_statement_and_enforcement_mechanism(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["invariants", "list"]) == 0
    output = capsys.readouterr().out
    assert "enforced by:" in output
    assert f"{len(SEPARATION_INVARIANTS)} declared" in output
    for entry in SEPARATION_INVARIANTS:
        assert entry.statement.split("\n")[0][:40] in output


def test_invariants_list_omits_the_rationale_unless_asked(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["invariants", "list"]) == 0
    assert "why:" not in capsys.readouterr().out


def test_verbose_invariants_list_includes_the_rationale_and_the_consequence(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["invariants", "list", "--verbose"]) == 0
    output = capsys.readouterr().out
    assert "why:" in output
    assert "if violated:" in output
    assert SEPARATION_INVARIANTS[0].rationale[:40] in output


def test_the_short_verbose_flag_behaves_like_the_long_one(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["invariants", "list", "-v"]) == 0
    assert "why:" in capsys.readouterr().out


def test_invariants_list_names_the_invariants_that_rest_on_review_only(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["invariants", "list"]) == 0
    output = capsys.readouterr().out
    review_only = [
        entry.identifier for entry in SEPARATION_INVARIANTS if not entry.is_mechanically_enforced
    ]
    assert "resting on review only" in output
    for identifier in review_only:
        assert identifier in output
