"""The separation invariants that are expressible as a property of the code itself.

Each test here corresponds to an ``SI-n`` entry whose declared enforcement is
``STATIC``. The catalogue claims these are enforced by construction; this module
is what makes that claim falsifiable.
"""

from __future__ import annotations

import ast
import dataclasses
import itertools
from pathlib import Path

import pytest

from astra.contracts.actuation import (
    CommandOrigin,
    ControlCommand,
    IssuedCommand,
)
from astra.contracts.assurance import SafetyVerdict
from astra.kernel.enums import LayerId, Verdict
from astra.kernel.errors import InvariantViolationError
from astra.kernel.identifiers import ComponentId, TickId
from astra.kernel.time import Instant
from astra.ports.pipeline import (
    CommandProposer,
    DeterministicShield,
    PhysicalAdmissibilityChecker,
    StatisticalGate,
    TrustEstimator,
)

pytestmark = pytest.mark.architecture

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PORTS_ROOT = REPOSITORY_ROOT / "src" / "astra" / "ports"

_GATE_PROTOCOLS = (StatisticalGate, PhysicalAdmissibilityChecker, DeterministicShield)
_NON_SI_TYPE_NAMES = ("KilometresPerHour", "Degrees", "Milliseconds")
_NON_L9_LAYERS = [layer for layer in LayerId if layer is not LayerId.L9_RCM]


def _port_modules() -> list[Path]:
    """Return every port module.

    Returns:
        The sorted list of ``src/astra/ports/*.py`` files.
    """
    return sorted(path for path in PORTS_ROOT.glob("*.py") if "__pycache__" not in path.parts)


def _source_without_docstrings(path: Path) -> str:
    """Return a file's source with every string-literal statement removed.

    Docstrings are prose about the code, not code. The unit-policy test below
    asserts that no non-SI type *appears in a signature*, and the ports module
    quite properly explains in its own docstring why those types exist -- a
    naive text scan would read that explanation as a violation of the rule it
    describes.

    Args:
        path: The file to read.

    Returns:
        The source with docstring lines blanked out.
    """
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(path))
    docstring_lines: set[int] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
            and node.end_lineno is not None
        ):
            docstring_lines.update(range(node.lineno, node.end_lineno + 1))
    return "\n".join(
        line
        for number, line in enumerate(text.splitlines(), start=1)
        if number not in docstring_lines
    )


# --------------------------------------------------------------------------- #
# SI-4: trust isolation
# --------------------------------------------------------------------------- #


def test_the_safety_verdict_has_no_field_whose_name_mentions_trust() -> None:
    names = [field.name for field in dataclasses.fields(SafetyVerdict)]
    assert names
    assert [name for name in names if "trust" in name.lower()] == []


def test_the_safety_verdict_carries_only_the_tick_and_the_gate_verdicts() -> None:
    names = {field.name for field in dataclasses.fields(SafetyVerdict)}
    assert names == {"tick", "gate_verdicts"}


@pytest.mark.parametrize("protocol", _GATE_PROTOCOLS, ids=lambda protocol: protocol.__name__)
def test_no_gate_protocol_accepts_a_trust_assessment(protocol: type) -> None:
    annotations = protocol.evaluate.__annotations__  # type: ignore[attr-defined]
    assert annotations
    rendered = " ".join(str(value) for value in annotations.values())
    assert "TrustAssessment" not in rendered


@pytest.mark.parametrize("protocol", _GATE_PROTOCOLS, ids=lambda protocol: protocol.__name__)
def test_no_gate_protocol_declares_a_parameter_named_for_trust(protocol: type) -> None:
    annotations = protocol.evaluate.__annotations__  # type: ignore[attr-defined]
    assert [name for name in annotations if "trust" in name.lower()] == []


@pytest.mark.parametrize(
    ("protocol", "method"),
    [(TrustEstimator, "assess"), (CommandProposer, "propose")],
    ids=["TrustEstimator.assess", "CommandProposer.propose"],
)
def test_the_trust_assessment_does_reach_the_layers_permitted_to_see_it(
    protocol: type, method: str
) -> None:
    annotations = getattr(protocol, method).__annotations__
    rendered = " ".join(str(value) for value in annotations.values())
    assert "TrustAssessment" in rendered


# --------------------------------------------------------------------------- #
# SI-7: sole actuation authority
# --------------------------------------------------------------------------- #


@pytest.fixture
def admissible_command(actuation_space: object) -> ControlCommand:
    return ControlCommand(space=actuation_space, values=(0.5, 0.0))  # type: ignore[arg-type]


def test_an_l9_component_can_issue_a_command(
    admissible_command: ControlCommand, now: Instant
) -> None:
    issued = IssuedCommand(
        tick=TickId(7),
        issued_at=now,
        command=admissible_command,
        origin=CommandOrigin.PROPOSED,
        issuer=ComponentId(LayerId.L9_RCM),
    )
    assert issued.issuer.layer is LayerId.L9_RCM


@pytest.mark.parametrize("layer", _NON_L9_LAYERS, ids=lambda layer: layer.value)
def test_no_layer_other_than_l9_can_construct_an_issued_command(
    layer: LayerId, admissible_command: ControlCommand, now: Instant
) -> None:
    with pytest.raises(InvariantViolationError) as excinfo:
        IssuedCommand(
            tick=TickId(7),
            issued_at=now,
            command=admissible_command,
            origin=CommandOrigin.PROPOSED,
            issuer=ComponentId(layer),
        )
    assert "SI-7" in str(excinfo.value)
    assert excinfo.value.layer is layer


def test_the_layer_enumeration_has_exactly_one_layer_with_actuation_authority() -> None:
    assert len(_NON_L9_LAYERS) == len(LayerId) - 1


# --------------------------------------------------------------------------- #
# SI-3: unconditional veto
# --------------------------------------------------------------------------- #


# Exhaustive over the whole vocabulary, not a chosen subset. When ADR-0016 added
# ABSTAIN, enumerating only (PASS, VETO) would have kept these tests green while
# leaving the new value entirely uncovered -- passing quietly rather than
# passing. Deriving the alphabet from the enum means the next value added is
# covered on the day it is added, or these tests fail and say so.
_VERDICT_ALPHABET = tuple(Verdict)


@pytest.mark.parametrize(
    "verdicts",
    [
        combination
        for size in range(4)
        for combination in itertools.product(_VERDICT_ALPHABET, repeat=size)
    ],
    ids=lambda verdicts: "-".join(verdict.value for verdict in verdicts) or "empty",
)
def test_merging_passes_only_when_something_judged_and_every_judgement_was_pass(
    verdicts: tuple[Verdict, ...],
) -> None:
    judged = [verdict for verdict in verdicts if verdict.participates]
    expected = Verdict.PASS if judged and all(v is Verdict.PASS for v in judged) else Verdict.VETO
    assert Verdict.merge(verdicts) is expected


@pytest.mark.parametrize(
    "verdicts",
    [
        combination
        for size in range(1, 4)
        for combination in itertools.product(_VERDICT_ALPHABET, repeat=size)
        if Verdict.VETO in combination
    ],
    ids=lambda verdicts: "-".join(verdict.value for verdict in verdicts),
)
def test_a_single_veto_survives_any_number_of_passes(verdicts: tuple[Verdict, ...]) -> None:
    assert Verdict.merge(verdicts) is Verdict.VETO
    assert Verdict.merge(verdicts).is_blocking


@pytest.mark.parametrize(
    "verdicts",
    [
        combination
        for size in range(1, 4)
        for combination in itertools.product(_VERDICT_ALPHABET, repeat=size)
        if all(verdict is Verdict.ABSTAIN for verdict in combination)
    ],
    ids=lambda verdicts: "-".join(verdict.value for verdict in verdicts),
)
def test_a_set_in_which_every_gate_abstained_is_a_veto(verdicts: tuple[Verdict, ...]) -> None:
    # SI-3, extended by ADR-0016. A command that nothing judged has not been
    # cleared -- whether the verdict set was empty because no gate ran, or
    # because every gate that ran declined to judge.
    assert Verdict.merge(verdicts) is Verdict.VETO
    assert Verdict.merge(verdicts) is Verdict.merge(())


def test_an_empty_verdict_set_is_a_veto_because_an_uninspected_command_is_not_a_cleared_one() -> (
    None
):
    assert Verdict.merge(()) is Verdict.VETO


# --------------------------------------------------------------------------- #
# The unit policy at the port boundary
# --------------------------------------------------------------------------- #


def test_the_port_package_was_actually_found() -> None:
    assert _port_modules()


@pytest.mark.parametrize("path", _port_modules(), ids=lambda path: path.name)
@pytest.mark.parametrize("type_name", _NON_SI_TYPE_NAMES)
def test_no_non_si_unit_type_appears_in_a_port_signature(path: Path, type_name: str) -> None:
    assert type_name not in _source_without_docstrings(path)


def test_stripping_docstrings_removes_the_prose_and_keeps_the_code() -> None:
    stripped = _source_without_docstrings(PORTS_ROOT / "pipeline.py")
    assert "from __future__ import annotations" in stripped
    assert "class StatisticalGate" in stripped
    assert "def evaluate" in stripped
    # The sentence in the module docstring that explains why the non-SI types
    # exist is prose about the rule, not a violation of it.
    assert "human-facing values are visible" not in stripped
