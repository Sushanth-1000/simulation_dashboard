"""The ``astra`` command-line interface.

Four commands, each answering a question someone actually asks:

``astra doctor``
    "Is this installation sound, and what would it run as?" Reports the
    interpreter, the resolved configuration, the invariant catalogue's
    enforcement status and whether the evidence directory is writable. Exits
    non-zero if anything would prevent a run, so it is usable in CI.
``astra config show``
    "What operating point is actually in force?" Renders the *resolved*
    configuration -- after layering and environment overrides -- with the hash
    that will appear in every decision record and the list of sources it came
    from.
``astra invariants list``
    "What is the safety argument, and what is really enforced?" Prints SI-1 to
    SI-10 with their enforcement kind, honestly distinguishing mechanically
    checked invariants from those still resting on review.
``astra version``
    The package version.

Why ``argparse``
----------------
It is in the standard library. A CLI whose job is partly to diagnose a broken
installation should not itself depend on a third-party package that might be the
thing that is broken -- and adding a runtime dependency to a safety-adjacent
project requires a justification stronger than nicer help text.

This module is the single place in ASTRA where ``print()`` is permitted; the
``T20`` lint rule forbids it everywhere else. Diagnostic output for a human at a
terminal is not logging, and routing it through the logging pipeline would make
it subject to level filtering and JSON formatting, which is wrong for both.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Final

from astra import __version__
from astra.bootstrap.composition import verify_invariant_catalogue
from astra.config.loader import load_settings
from astra.invariants.catalogue import SEPARATION_INVARIANTS, EnforcementKind
from astra.kernel.constants import (
    ASTRA_LAYER_COUNT,
    AUDIT_SCHEMA_VERSION,
    CONFIG_SCHEMA_VERSION,
    CORE_B_GATE_COUNT,
    FEEDBACK_LOOP_COUNT,
)
from astra.kernel.errors import AstraError
from astra.observability.explain import explain_tick, find_tick, read_records

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["main"]

_EXIT_OK: Final = 0
_EXIT_FAILURE: Final = 1
_MINIMUM_PYTHON: Final = (3, 12)
_RULE = "-" * 78


def _print_heading(title: str) -> None:
    """Print a section heading.

    Args:
        title: The heading text.
    """
    print(f"\n{title}")
    print(_RULE)


def _command_version(_arguments: argparse.Namespace) -> int:
    """Print the package version.

    Args:
        _arguments: Parsed arguments. Unused.

    Returns:
        The process exit code.
    """
    print(f"astra {__version__}")
    return _EXIT_OK


def _report_environment() -> list[str]:
    """Print the interpreter and platform section.

    Returns:
        Any problems that would prevent a run.
    """
    _print_heading("ASTRA environment")
    print(f"  astra version      {__version__}")
    print(f"  python             {platform.python_version()} ({sys.implementation.name})")
    print(f"  platform           {platform.system()} {platform.release()} / {platform.machine()}")
    print(f"  executable         {sys.executable}")
    if sys.version_info[:2] < _MINIMUM_PYTHON:
        required = ".".join(str(part) for part in _MINIMUM_PYTHON)
        return [f"python {required}+ is required, found {platform.python_version()}"]
    return []


def _report_architecture() -> None:
    """Print the structural cardinalities and schema versions."""
    _print_heading("Architecture")
    print(f"  layers             {ASTRA_LAYER_COUNT}  (L1-L9)")
    print(f"  core-B gates       {CORE_B_GATE_COUNT}  (statistical, physical, deterministic)")
    print(f"  feedback loops     {FEEDBACK_LOOP_COUNT}  (FB1-FB4)")
    print(f"  config schema      v{CONFIG_SCHEMA_VERSION}")
    print(f"  audit schema       v{AUDIT_SCHEMA_VERSION}")


def _report_invariants() -> list[str]:
    """Print the safety argument's verification status.

    Returns:
        Any problems that would prevent a run.
    """
    _print_heading("Separation invariants")
    try:
        verify_invariant_catalogue()
    except AstraError as error:
        print(f"  catalogue          FAILED: {error}")
        return [str(error)]
    enforced = sum(1 for entry in SEPARATION_INVARIANTS if entry.is_mechanically_enforced)
    print(f"  declared           {len(SEPARATION_INVARIANTS)}")
    print(f"  mechanically enforced  {enforced}")
    print(f"  review-only        {len(SEPARATION_INVARIANTS) - enforced}")
    return []


def _report_configuration(environment: str | None) -> list[str]:
    """Print the resolved configuration, or explain why it could not resolve.

    Args:
        environment: The environment to resolve, or ``None`` for the default.

    Returns:
        Any problems that would prevent a run.
    """
    _print_heading("Configuration")
    try:
        resolved = load_settings(environment=environment)
    except AstraError as error:
        print("  status             FAILED")
        print(f"  {error}")
        details = error.context.get("errors", [])
        for detail in details:
            print(f"    - {detail['field']}: {detail['problem']}")
        if details:
            print(
                "\n  A missing safety threshold is the intended failure mode: these "
                "parameters\n  have no defensible default and must be supplied "
                "explicitly (assumption A-4)."
            )
        return [str(error)]

    settings = resolved.settings
    print(f"  environment        {settings.environment}")
    print(f"  config hash        {resolved.hash}")
    for source in resolved.sources:
        print(f"  source             {source}")

    log_directory = Path(settings.observability.log_directory)
    writable = _check_writable(log_directory)
    print(f"  evidence directory {log_directory}  ({'writable' if writable else 'NOT WRITABLE'})")
    if not writable:
        return [f"the evidence directory {log_directory} is not writable"]
    return []


def _command_doctor(arguments: argparse.Namespace) -> int:
    """Report the health of the installation, configuration and safety argument.

    Args:
        arguments: Parsed arguments, carrying the optional environment.

    Returns:
        ``0`` if a run could start, ``1`` otherwise.
    """
    problems = _report_environment()
    _report_architecture()
    problems += _report_invariants()
    problems += _report_configuration(arguments.environment)

    _print_heading("Result")
    if problems:
        for problem in problems:
            print(f"  PROBLEM  {problem}")
        print(f"\n  {len(problems)} problem(s) would prevent a run.")
        return _EXIT_FAILURE
    print("  OK  this installation can start a run.")
    return _EXIT_OK


def _check_writable(directory: Path) -> bool:
    """Return whether the evidence archive could be written to a directory.

    Deliberately does **not** create the directory. ``doctor`` is a diagnostic:
    a command that reports on a system should not modify it, and a ``doctor``
    run that silently created ``var/runs`` would make its own next run pass for
    a reason unrelated to the installation being sound.

    So the check walks up to the nearest existing ancestor and asks whether that
    is writable, which is the condition under which the run itself would be able
    to create the directory.

    Args:
        directory: The configured evidence directory.

    Returns:
        ``True`` if the evidence archive could be written there.
    """
    resolved = directory if directory.is_absolute() else Path.cwd() / directory
    existing = resolved
    while not existing.exists():
        parent = existing.parent
        if parent == existing:  # pragma: no cover - reached only at the filesystem root
            break
        existing = parent
    return existing.is_dir() and os.access(existing, os.W_OK)


def _command_config_show(arguments: argparse.Namespace) -> int:
    """Render the fully resolved configuration.

    Args:
        arguments: Parsed arguments, carrying the environment and format.

    Returns:
        The process exit code.
    """
    try:
        resolved = load_settings(environment=arguments.environment)
    except AstraError as error:
        print(f"configuration could not be resolved: {error}", file=sys.stderr)
        for detail in error.context.get("errors", []):
            print(f"  - {detail['field']}: {detail['problem']}", file=sys.stderr)
        return _EXIT_FAILURE

    if arguments.format == "json":
        print(
            json.dumps(
                {
                    "hash": resolved.hash,
                    "sources": list(resolved.sources),
                    "settings": resolved.settings.model_dump(mode="json"),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return _EXIT_OK

    print(f"# environment  {resolved.settings.environment}")
    print(f"# hash         {resolved.hash}")
    for source in resolved.sources:
        print(f"# source       {source}")
    print()
    _print_mapping(resolved.settings.model_dump(mode="json"), indent=0)
    return _EXIT_OK


def _print_mapping(mapping: dict[str, object], *, indent: int) -> None:
    """Print a nested mapping as an indented tree.

    Args:
        mapping: The mapping to render.
        indent: Current indentation depth.
    """
    padding = "  " * indent
    for key, value in mapping.items():
        if isinstance(value, dict):
            print(f"{padding}{key}:")
            _print_mapping(value, indent=indent + 1)
        else:
            print(f"{padding}{key}: {value}")


def _command_invariants_list(arguments: argparse.Namespace) -> int:
    """Print the separation invariants and their enforcement status.

    Args:
        arguments: Parsed arguments, carrying the verbosity flag.

    Returns:
        The process exit code.
    """
    _print_heading("Separation invariants")
    for entry in SEPARATION_INVARIANTS:
        marker = " " if entry.is_mechanically_enforced else "!"
        print(f"\n{marker} {entry.identifier}  {entry.title}  [{entry.enforcement.value}]")
        print(f"    {entry.statement}")
        if arguments.verbose:
            print(f"    why:         {entry.rationale}")
            print(f"    if violated: {entry.consequence}")
        print(f"    enforced by: {entry.mechanism}")

    review_only = [
        entry.identifier
        for entry in SEPARATION_INVARIANTS
        if entry.enforcement is EnforcementKind.REVIEW
    ]
    print(f"\n{_RULE}")
    print(f"  {len(SEPARATION_INVARIANTS)} declared, {len(review_only)} resting on review only.")
    if review_only:
        print(f"  Not yet mechanically enforced: {', '.join(review_only)}")
    return _EXIT_OK


def _command_explain(arguments: argparse.Namespace) -> int:
    """Reconstruct one tick's decision from an audit log.

    The forensic question after an incident is *why did it do that?*, and until
    now the answer lived in whoever still remembered the architecture. This
    answers it from the archive alone -- which is what assumption A-10 means by
    explainability: **decision provenance**, the inputs a decision was taken on,
    recorded beside it.

    Args:
        arguments: Parsed arguments carrying ``log`` and ``tick``.

    Returns:
        Zero, or one if the log is unreadable or the tick is absent.
    """
    try:
        records = list(read_records(arguments.log))
    except (OSError, ValueError) as error:
        print(f"  {error}")
        return 1

    record = find_tick(records, arguments.tick)
    if record is None:
        ticks = [entry["tick"] for entry in records if isinstance(entry.get("tick"), int)]
        span = f"{min(ticks)}-{max(ticks)}" if ticks else "empty"
        print(f"  tick {arguments.tick} is not in this log (it covers {span})")
        return 1

    for line in explain_tick(record):
        print(line)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser.

    Returns:
        The configured parser.
    """
    parser = argparse.ArgumentParser(
        prog="astra",
        description=(
            "ASTRA - Autonomous Safety, Trust, and Runtime Architecture. "
            "Runtime governance for AI-controlled cyber-physical systems."
        ),
    )
    parser.add_argument("--version", action="version", version=f"astra {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser(
        "doctor", help="verify the installation and print the environment report"
    )
    doctor.add_argument("--environment", "-e", default=None, help="environment to resolve")
    doctor.set_defaults(handler=_command_doctor)

    config = subparsers.add_parser("config", help="inspect the resolved configuration")
    config_subparsers = config.add_subparsers(dest="config_command", required=True)
    config_show = config_subparsers.add_parser(
        "show", help="render the effective, fully resolved configuration"
    )
    config_show.add_argument("--environment", "-e", default=None, help="environment to resolve")
    config_show.add_argument(
        "--format", choices=("text", "json"), default="text", help="output format"
    )
    config_show.set_defaults(handler=_command_config_show)

    invariants = subparsers.add_parser("invariants", help="inspect the separation invariants")
    invariants_subparsers = invariants.add_subparsers(dest="invariants_command", required=True)
    invariants_list = invariants_subparsers.add_parser(
        "list", help="print the separation invariants and their enforcement"
    )
    invariants_list.add_argument(
        "--verbose", "-v", action="store_true", help="include rationale and consequence"
    )
    invariants_list.set_defaults(handler=_command_invariants_list)

    explain = subparsers.add_parser(
        "explain",
        help="reconstruct one tick's decision from an audit log",
    )
    explain.add_argument("log", type=Path, help="a JSONL audit log, or a directory holding one")
    explain.add_argument("tick", type=int, help="the control tick to explain")
    explain.set_defaults(handler=_command_explain)

    version = subparsers.add_parser("version", help="print the package version")
    version.set_defaults(handler=_command_version)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line interface.

    Args:
        argv: Argument vector, defaulting to ``sys.argv[1:]``.

    Returns:
        The process exit code.
    """
    parser = _build_parser()
    arguments = parser.parse_args(argv)
    handler: object = arguments.handler
    if not callable(handler):  # pragma: no cover - unreachable via the parser
        parser.error("no handler bound to this command")
    result: int = handler(arguments)
    return result


if __name__ == "__main__":  # pragma: no cover - exercised via `python -m astra`
    sys.exit(main())
