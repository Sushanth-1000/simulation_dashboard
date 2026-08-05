"""The package's executable and importable entry points."""

from __future__ import annotations

import subprocess
import sys

import pytest

from astra import __version__
from astra.ports import infrastructure, pipeline

_INFRASTRUCTURE_PORTS = ("ActuationSink", "EventSink", "FeedbackBus", "ProfileRepository")
_PIPELINE_PORTS = (
    "CalibrationArbiter",
    # Not a layer's role, unlike its neighbours here: the seam through which the
    # adapter supplies the one piece of platform knowledge L9 needs and cannot
    # derive -- how much lateral acceleration a unit of steering produces. Added
    # by ADR-0017. It is a port for the same reason the actuation space is a
    # parameter: NFR5 keeps vehicles out of the layers.
    "CommandProjector",
    "CommandProposer",
    "DeterministicShield",
    "DynamicsPredictor",
    "PhysicalAdmissibilityChecker",
    "SafetyStateMachine",
    "SensorSource",
    "StateEstimator",
    "StatisticalGate",
    "TrustEstimator",
)


def test_python_dash_m_astra_runs_the_cli() -> None:
    # `python -m astra` is the entry point that still works when the console
    # script was not installed -- which is exactly the situation `doctor` exists
    # to diagnose, so it must not be allowed to rot.
    result = subprocess.run(
        [sys.executable, "-m", "astra", "version"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert __version__ in result.stdout


def test_python_dash_m_astra_reports_a_failing_environment_with_a_nonzero_exit() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "astra", "doctor", "-e", "certification"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1


@pytest.mark.parametrize("name", _INFRASTRUCTURE_PORTS)
def test_every_infrastructure_port_is_importable(name: str) -> None:
    assert name in infrastructure.__all__
    assert hasattr(infrastructure, name)


@pytest.mark.parametrize("name", _PIPELINE_PORTS)
def test_every_pipeline_port_is_importable(name: str) -> None:
    assert name in pipeline.__all__
    assert hasattr(pipeline, name)


def test_the_pipeline_declares_exactly_one_port_per_architectural_role() -> None:
    assert set(pipeline.__all__) == set(_PIPELINE_PORTS)


def test_the_infrastructure_module_declares_exactly_the_injected_dependencies() -> None:
    assert set(infrastructure.__all__) == set(_INFRASTRUCTURE_PORTS)


@pytest.mark.parametrize("name", _INFRASTRUCTURE_PORTS)
def test_infrastructure_ports_are_runtime_checkable(name: str) -> None:
    # The composition root uses isinstance as a wiring sanity check, which is
    # only possible on a runtime_checkable protocol.
    port = getattr(infrastructure, name)

    assert isinstance(object(), port) is False


def test_a_minimal_duck_typed_object_satisfies_a_port_without_inheritance() -> None:
    # The point of structural typing: an adapter never imports an ASTRA base
    # class, so the dependency arrow keeps pointing inward.
    class Sink:
        def apply(self, command: object) -> None:
            del command

    assert isinstance(Sink(), infrastructure.ActuationSink)
