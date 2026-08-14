"""Refuse any single module far below the aggregate coverage gate.

Why this exists
----------------
The 95% coverage gate is an **aggregate** over eighty-odd files, so a new module
can ship at 10% and pass, carried by everything around it.

That happened on 11 August 2026. ``astra explain`` -- a forensic tool a safety
case would lean on -- landed with **no tests at all**, at **10.3% coverage**, and
``make check`` was green. The aggregate moved by less than a tenth of a point,
because 94 uncovered statements against a codebase of several thousand is noise.

It is the same shape as half this project's register: a check that asserts
something it does not actually verify. The gate said *"95% coverage"* and meant
*"95% on average, and no statement about any particular thing you just wrote."*

Why the floor is far below the gate
-------------------------------------
80%, against an aggregate gate of 95%. That looks lax and is deliberate: this
target's job is to catch a module with **no** tests, not to force the last few
branches out of code that is already well covered. A floor set near the aggregate
would fail three files that are fine and would be turned off within a week.

At 80% it passes every file in the tree today **and would have failed the defect
that motivated it**, which is the whole specification. A guard that only ever
fires on the case that created it is worth more than one nobody keeps.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

FLOOR = 80.0
"""Minimum per-file statement coverage, in percent."""

EXCLUDED = frozenset({"src/astra/__main__.py"})
"""Files exempt from the floor, named rather than silently skipped.

``__main__.py`` is three lines of ``sys.exit(main())`` behind an
``if __name__ == "__main__"`` guard that the test process never takes. Excluding
it by name keeps the exemption reviewable; a pattern would quietly grow.
"""


def below_floor(report: dict[str, object]) -> list[tuple[str, float]]:
    """Return every file under the floor, worst first.

    Args:
        report: A parsed ``coverage json`` report.

    Returns:
        ``(path, percent)`` pairs, ascending by percent.
    """
    files = report.get("files", {})
    if not isinstance(files, dict):  # pragma: no cover - malformed report
        return []
    found = [
        (name, float(data["summary"]["percent_covered"]))
        for name, data in files.items()
        if name not in EXCLUDED and float(data["summary"]["percent_covered"]) < FLOOR
    ]
    return sorted(found, key=lambda pair: pair[1])


def main(argv: list[str] | None = None) -> int:
    """Check a coverage report against the per-file floor.

    Args:
        argv: Command-line arguments; the report path, defaulting to
            ``.coverage.json``.

    Returns:
        Zero if every file clears the floor, one otherwise.
    """
    arguments = sys.argv[1:] if argv is None else argv
    path = Path(arguments[0] if arguments else ".coverage.json")
    if not path.exists():
        print(f"  {path} not found; run pytest with --cov-report=json first")
        return 1

    low = below_floor(json.loads(path.read_text(encoding="utf-8")))
    for name, percent in low:
        print(f"  {name}: {percent:.1f}% is below the {FLOOR:.0f}% per-file floor")
    if low:
        print()
        print(f"  {len(low)} file(s) below the floor. A module with no tests passes the")
        print("  aggregate gate and fails this one; that is what this check is for.")
        return 1

    print(f"  per-file coverage floor: every file at or above {FLOOR:.0f}%")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through the Makefile
    sys.exit(main())
