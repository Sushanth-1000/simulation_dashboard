"""The module dependency graph, asserted rather than described.

A layering rule that lives only in a diagram is a rule that erodes. These tests
read the source itself, so a violation is a red build on the commit that
introduced it rather than a discovery made during integration.
"""

from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPOSITORY_ROOT / "src" / "astra"
KERNEL_ROOT = SOURCE_ROOT / "kernel"

_PRINT_IS_PERMITTED_IN = frozenset({SOURCE_ROOT / "bootstrap" / "cli.py"})
_FORBIDDEN_THIRD_PARTY = "carla"
_IMPORT_LINTER_TIMEOUT_SECONDS = 300


def _python_files(root: Path) -> list[Path]:
    """Return every ``.py`` file beneath a root, in a stable order.

    Args:
        root: The directory to walk.

    Returns:
        The sorted list of Python source files.
    """
    return sorted(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)


def _parse(path: Path) -> ast.Module:
    """Parse one source file.

    Args:
        path: The file to parse.

    Returns:
        The parsed module.
    """
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imported_modules(tree: ast.Module) -> list[str]:
    """Return every module name imported by a parsed module.

    Both ``import a.b`` and ``from a.b import c`` contribute ``a.b``, which is
    the granularity the layering rules are written at.

    Args:
        tree: The parsed module.

    Returns:
        The imported module names, including duplicates.
    """
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            modules.append(node.module)
    return modules


def _imported_modules_of(node: ast.AST) -> list[str]:
    """Return the module names one import statement contributes.

    The single-node counterpart of :func:`_imported_modules`, so a caller can
    decide per statement whether it counts -- which is what distinguishes a
    runtime import from one confined to a ``TYPE_CHECKING`` block.

    Args:
        node: Any AST node. Non-import nodes contribute nothing.

    Returns:
        The module names this node imports.
    """
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
        return [node.module]
    return []


def _is_type_checking_guard(node: ast.If) -> bool:
    """Return whether an ``if`` statement is a ``TYPE_CHECKING`` guard.

    Imports inside one exist only for the type checker and are never executed,
    so they cannot read a clock and are exempt from the time-import rule.

    Args:
        node: The ``if`` statement to classify.

    Returns:
        ``True`` for ``if TYPE_CHECKING:`` and ``if typing.TYPE_CHECKING:``.
    """
    test = node.test
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    return isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"


_SOURCE_FILES = _python_files(SOURCE_ROOT)
_KERNEL_FILES = _python_files(KERNEL_ROOT)
_TIME_MODULE = SOURCE_ROOT / "kernel" / "time.py"
_TIME_LIBRARIES = frozenset({"time", "datetime"})


def test_the_source_tree_was_actually_found() -> None:
    assert SOURCE_ROOT.is_dir()
    assert _SOURCE_FILES
    assert _KERNEL_FILES


# --------------------------------------------------------------------------- #
# The declared fitness contracts
# --------------------------------------------------------------------------- #


def _lint_imports_argv() -> list[str]:
    """Return the argument vector that runs ``lint-imports`` in this interpreter.

    The console script is preferred when it sits alongside the running
    interpreter. Otherwise the command object is invoked directly. Note that
    ``python -m importlinter.cli`` is *not* usable: that module has no
    ``__main__`` guard, so it exits zero having checked nothing -- a silent
    false pass, which for a fitness test is worse than no test.

    Returns:
        The argument vector, without the ``--no-cache`` flag.
    """
    script = Path(sys.executable).parent / "lint-imports"
    if script.is_file():
        return [str(script)]
    return [
        sys.executable,
        "-c",
        "from importlinter.cli import lint_imports_command; lint_imports_command()",
    ]


def test_every_import_linter_contract_holds() -> None:
    if importlib.util.find_spec("importlinter") is None:  # pragma: no cover - tooling absent
        pytest.skip("import-linter is not installed in this environment")
    completed = subprocess.run(  # noqa: S603 - fixed argument vector, no shell
        [*_lint_imports_argv(), "--no-cache"],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=_IMPORT_LINTER_TIMEOUT_SECONDS,
    )
    report = (
        f"exit code {completed.returncode}\n"
        f"--- stdout ---\n{completed.stdout}\n--- stderr ---\n{completed.stderr}"
    )
    # Asserted before the exit code: a runner that checks nothing also exits 0.
    assert "Contracts:" in completed.stdout, report
    assert "0 broken" in completed.stdout, report
    assert completed.returncode == 0, report


def test_the_fitness_contract_file_is_present_and_declares_the_layering() -> None:
    contracts = (REPOSITORY_ROOT / ".importlinter").read_text(encoding="utf-8")
    assert "root_package = astra" in contracts
    assert "astra.kernel" in contracts


# --------------------------------------------------------------------------- #
# The kernel sits at the bottom
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("path", _KERNEL_FILES, ids=lambda path: str(path.relative_to(SOURCE_ROOT)))
def test_no_kernel_module_imports_anything_from_astra_outside_the_kernel(path: Path) -> None:
    internal = [
        module for module in _imported_modules(_parse(path)) if module.split(".")[0] == "astra"
    ]
    offenders = [module for module in internal if not module.startswith("astra.kernel")]
    assert offenders == [], f"{path} imports {offenders} from outside the kernel"


@pytest.mark.parametrize("path", _KERNEL_FILES, ids=lambda path: str(path.relative_to(SOURCE_ROOT)))
def test_no_kernel_module_uses_a_relative_import(path: Path) -> None:
    relative = [
        node
        for node in ast.walk(_parse(path))
        if isinstance(node, ast.ImportFrom) and node.level > 0
    ]
    assert relative == []


# --------------------------------------------------------------------------- #
# The simulator never reaches the core
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("path", _SOURCE_FILES, ids=lambda path: str(path.relative_to(SOURCE_ROOT)))
def test_no_module_in_the_core_imports_the_simulator_client(path: Path) -> None:
    roots = {module.split(".")[0] for module in _imported_modules(_parse(path))}
    assert _FORBIDDEN_THIRD_PARTY not in roots


# --------------------------------------------------------------------------- #
# print() belongs to the CLI alone
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("path", _SOURCE_FILES, ids=lambda path: str(path.relative_to(SOURCE_ROOT)))
def test_print_is_called_nowhere_except_the_command_line_interface(path: Path) -> None:
    calls = [
        node.lineno
        for node in ast.walk(_parse(path))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "print"
    ]
    if path in _PRINT_IS_PERMITTED_IN:
        assert calls, "the CLI is the one module that is supposed to print"
    else:
        assert calls == [], f"{path} calls print() at lines {calls}"


def test_the_only_module_permitted_to_print_actually_exists() -> None:
    for path in _PRINT_IS_PERMITTED_IN:
        assert path.is_file()


# --------------------------------------------------------------------------- #
# The injected clock is the only way to read time
# --------------------------------------------------------------------------- #
# `astra.kernel.time` documents this as an enforced property. These tests are
# that enforcement. A component that reads the wall clock directly defeats
# replay, mismeasures staleness across an NTP correction, and reports latency
# against a different timeline than the simulator advances on.


@pytest.mark.parametrize("path", _SOURCE_FILES, ids=lambda path: str(path.relative_to(SOURCE_ROOT)))
def test_only_the_time_module_imports_the_time_library_at_runtime(path: Path) -> None:
    tree = _parse(path)
    type_checking_only = {
        node
        for branch in ast.walk(tree)
        if isinstance(branch, ast.If) and _is_type_checking_guard(branch)
        for node in ast.walk(branch)
    }
    runtime_roots = {
        module.split(".")[0]
        for node in ast.walk(tree)
        if node not in type_checking_only
        for module in _imported_modules_of(node)
    }

    offenders = runtime_roots & _TIME_LIBRARIES
    if path == _TIME_MODULE:
        assert offenders, "the time module is supposed to own these imports"
    else:
        assert offenders == set(), (
            f"{path.relative_to(SOURCE_ROOT)} imports {sorted(offenders)} at runtime; "
            f"read time through the injected Clock instead"
        )


@pytest.mark.parametrize("path", _SOURCE_FILES, ids=lambda path: str(path.relative_to(SOURCE_ROOT)))
def test_no_module_outside_the_time_module_calls_a_wall_clock_function(path: Path) -> None:
    # Catches `datetime.now(...)`, `time.time()` and `time.monotonic_ns()` even
    # where the module was reached by an alias, which the import check alone
    # would miss.
    forbidden = {"now", "today", "utcnow", "time", "monotonic", "monotonic_ns", "perf_counter"}
    calls = sorted(
        {
            node.func.attr
            for node in ast.walk(_parse(path))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in forbidden
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in {"time", "datetime", "date"}
        }
    )

    if path == _TIME_MODULE:
        assert calls, "the time module is supposed to make these calls"
    else:
        assert calls == [], (
            f"{path.relative_to(SOURCE_ROOT)} reads the wall clock via {calls}; "
            f"read time through the injected Clock instead"
        )
