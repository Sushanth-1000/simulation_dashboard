"""The composition root: catalogue verification and runtime assembly."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from astra.bootstrap import composition
from astra.bootstrap.composition import (
    AstraRuntime,
    build_runtime,
    verify_invariant_catalogue,
)
from astra.invariants.catalogue import (
    SEPARATION_INVARIANTS,
    EnforcementKind,
    SeparationInvariant,
)
from astra.kernel.errors import ConfigurationError, InvariantViolationError
from astra.kernel.identifiers import RunId
from astra.kernel.time import Clock, SystemClock
from astra.observability.audit import JsonlAuditSink
from astra.observability.logging import shutdown_logging

if TYPE_CHECKING:
    from collections.abc import Iterator

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CONFIG_ROOT = REPOSITORY_ROOT / "config"

_PROBE = SeparationInvariant(
    identifier="SI-1",
    title="probe",
    statement="s",
    rationale="r",
    consequence="c",
    enforcement=EnforcementKind.REVIEW,
    mechanism="m",
)


@pytest.fixture(autouse=True)
def _hermetic_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in [key for key in os.environ if key.startswith("ASTRA_")]:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _no_leaked_logging_listener() -> Iterator[None]:
    try:
        yield
    finally:
        shutdown_logging()


@pytest.fixture
def runtime(tmp_path: Path) -> Iterator[AstraRuntime]:
    with build_runtime(
        environment="development", config_root=CONFIG_ROOT, log_directory=tmp_path
    ) as assembled:
        yield assembled


# --------------------------------------------------------------------------- #
# verify_invariant_catalogue
# --------------------------------------------------------------------------- #


def test_the_real_catalogue_verifies() -> None:
    verify_invariant_catalogue()  # must not raise


def test_a_catalogue_of_the_wrong_length_fails_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(composition, "SEPARATION_INVARIANTS", SEPARATION_INVARIANTS[:-1])
    with pytest.raises(InvariantViolationError) as excinfo:
        verify_invariant_catalogue()
    assert excinfo.value.context == {"declared": 9}


def test_an_empty_catalogue_fails_verification(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(composition, "SEPARATION_INVARIANTS", ())
    with pytest.raises(InvariantViolationError):
        verify_invariant_catalogue()


def test_a_catalogue_with_a_duplicate_identifier_fails_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    duplicated = (*SEPARATION_INVARIANTS[:-1], _PROBE)
    monkeypatch.setattr(composition, "SEPARATION_INVARIANTS", duplicated)
    with pytest.raises(InvariantViolationError) as excinfo:
        verify_invariant_catalogue()
    assert "duplicate" in str(excinfo.value)


def test_a_catalogue_entry_with_an_empty_mechanism_fails_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stripped = (
        *SEPARATION_INVARIANTS[:-1],
        SeparationInvariant(
            identifier="SI-10",
            title=SEPARATION_INVARIANTS[-1].title,
            statement=SEPARATION_INVARIANTS[-1].statement,
            rationale=SEPARATION_INVARIANTS[-1].rationale,
            consequence=SEPARATION_INVARIANTS[-1].consequence,
            enforcement=SEPARATION_INVARIANTS[-1].enforcement,
            mechanism="",
        ),
    )
    monkeypatch.setattr(composition, "SEPARATION_INVARIANTS", stripped)
    with pytest.raises(InvariantViolationError) as excinfo:
        verify_invariant_catalogue()
    assert excinfo.value.context == {"identifier": "SI-10"}


def test_a_catalogue_entry_with_an_empty_statement_fails_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stripped = (
        SeparationInvariant(
            identifier="SI-1",
            title="Sensor opacity",
            statement="",
            rationale="r",
            consequence="c",
            enforcement=EnforcementKind.STATIC,
            mechanism="m",
        ),
        *SEPARATION_INVARIANTS[1:],
    )
    monkeypatch.setattr(composition, "SEPARATION_INVARIANTS", stripped)
    with pytest.raises(InvariantViolationError) as excinfo:
        verify_invariant_catalogue()
    assert excinfo.value.context == {"identifier": "SI-1"}


# --------------------------------------------------------------------------- #
# build_runtime
# --------------------------------------------------------------------------- #


def test_building_a_development_runtime_yields_every_declared_component(
    runtime: AstraRuntime,
) -> None:
    assert isinstance(runtime, AstraRuntime)
    assert isinstance(runtime.run, RunId)
    assert isinstance(runtime.clock, Clock)
    assert isinstance(runtime.clock, SystemClock)
    assert isinstance(runtime.audit_sink, JsonlAuditSink)


def test_the_runtime_exposes_the_resolved_development_settings(runtime: AstraRuntime) -> None:
    assert runtime.settings is runtime.configuration.settings
    assert runtime.settings.environment == "development"


def test_the_runtime_exposes_the_configuration_hash_stamped_on_every_record(
    runtime: AstraRuntime,
) -> None:
    assert runtime.config_hash == runtime.configuration.hash
    assert runtime.config_hash
    assert len(runtime.config_hash) == len(runtime.configuration.hash)


def test_the_evidence_directory_is_created_beneath_the_requested_log_directory(
    tmp_path: Path,
) -> None:
    with build_runtime(
        environment="development", config_root=CONFIG_ROOT, log_directory=tmp_path
    ) as assembled:
        assert assembled.audit_sink.path.parent == tmp_path / assembled.run.value
        assert assembled.audit_sink.path.parent.is_dir()


def test_an_explicit_run_identity_is_used_verbatim_so_a_run_can_be_replayed(
    tmp_path: Path,
) -> None:
    replayed = RunId("run-replay000001")
    with build_runtime(
        environment="development",
        config_root=CONFIG_ROOT,
        run=replayed,
        log_directory=tmp_path,
    ) as assembled:
        assert assembled.run == replayed
        assert assembled.audit_sink.path.parent.name == replayed.value


def test_two_runtimes_built_without_an_explicit_run_get_distinct_identities(
    tmp_path: Path,
) -> None:
    with (
        build_runtime(
            environment="development", config_root=CONFIG_ROOT, log_directory=tmp_path
        ) as first,
        build_runtime(
            environment="development", config_root=CONFIG_ROOT, log_directory=tmp_path
        ) as second,
    ):
        assert first.run != second.run


def test_two_runtimes_on_the_same_configuration_share_a_configuration_hash(
    tmp_path: Path,
) -> None:
    with (
        build_runtime(
            environment="development", config_root=CONFIG_ROOT, log_directory=tmp_path
        ) as first,
        build_runtime(
            environment="development", config_root=CONFIG_ROOT, log_directory=tmp_path
        ) as second,
    ):
        assert first.config_hash == second.config_hash


def test_the_runtime_is_frozen_so_no_component_can_swap_the_clock_mid_run(
    runtime: AstraRuntime,
) -> None:
    with pytest.raises((AttributeError, TypeError)):
        runtime.clock = SystemClock()  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# Lifetime
# --------------------------------------------------------------------------- #


def test_the_runtime_is_a_context_manager_returning_itself(tmp_path: Path) -> None:
    assembled = build_runtime(
        environment="development", config_root=CONFIG_ROOT, log_directory=tmp_path
    )
    try:
        with assembled as entered:
            assert entered is assembled
    finally:
        assembled.close()


def test_closing_the_runtime_twice_is_harmless(tmp_path: Path) -> None:
    assembled = build_runtime(
        environment="development", config_root=CONFIG_ROOT, log_directory=tmp_path
    )
    assembled.close()
    assembled.close()
    assert assembled.audit_sink.path.exists()


def test_the_context_manager_closes_the_audit_sink_even_when_the_block_raises(
    tmp_path: Path,
) -> None:
    assembled = build_runtime(
        environment="development", config_root=CONFIG_ROOT, log_directory=tmp_path
    )
    sentinel = RuntimeError("deliberate")
    with pytest.raises(RuntimeError, match="deliberate"), assembled:
        raise sentinel
    assembled.close()


# --------------------------------------------------------------------------- #
# A-4: an incomplete certification configuration stops the run
# --------------------------------------------------------------------------- #


def test_building_a_certification_runtime_fails_because_thresholds_are_unset(
    tmp_path: Path,
) -> None:
    with pytest.raises(ConfigurationError):
        build_runtime(environment="certification", config_root=CONFIG_ROOT, log_directory=tmp_path)


def test_the_certification_failure_names_the_missing_safety_thresholds(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError) as excinfo:
        build_runtime(environment="certification", config_root=CONFIG_ROOT, log_directory=tmp_path)
    assert "A-4" in str(excinfo.value)
    fields = {detail["field"] for detail in excinfo.value.context["errors"]}
    assert fields


def test_a_failed_certification_build_leaves_no_evidence_directory_behind(
    tmp_path: Path,
) -> None:
    with pytest.raises(ConfigurationError):
        build_runtime(environment="certification", config_root=CONFIG_ROOT, log_directory=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_an_unknown_environment_is_a_configuration_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError):
        build_runtime(
            environment="no-such-environment",
            config_root=CONFIG_ROOT,
            log_directory=tmp_path,
        )
