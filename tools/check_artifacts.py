"""Are the trained artefacts present, and does the policy actually drive?

Why the second question is the point
--------------------------------------
On 15 August 2026 this project published a finding, retracted a correct
conclusion on the strength of it, and withdrew the retraction four hours later.
The measurement was arithmetically perfect. It ran on a vehicle with **400 of
400 ticks vetoed and a final speed of zero**, because a new benchmark defaulted
to ``artifacts/policy/policy.json`` -- a path invented that afternoon, which has
never existed -- and fell back silently to the placeholder proposer (E-143).

Nothing in the repository could have caught it. Nothing **regenerated** the
artefacts, nothing **verified** them, and the commands lived only in a status
document from 31 July. ``var/`` is gitignored by design, so a clean checkout has
none of them and every ``[M-syn]`` row is measured through all three.

**The canonical artefacts were present the whole time and the policy drives.** A
first diagnosis said ``var/policy/synthetic.pt`` was missing; that came from an
``ls`` of three directories piped through ``head -20``, where the cut landed one
line above it, and it is retracted at E-145. Worth recording here rather than
tidied away, because it is the *same* error as the one this file guards against:
a conclusion assembled correctly from an observation nobody checked was complete.

So presence is not the check. **Driving is the check.** An artefact that loads
and yields a car that never moves is worse than a missing one, because a missing
one raises an error and this one produces numbers.

What this refuses
-----------------
Any artefact absent, or a policy under which the vehicle does not drive: every
tick vetoed, or a final speed at rest. Both are cheap to test — one short closed
loop — and either one invalidates every measurement taken downstream of it.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

_SMOKE_TICKS: Final = 200
"""Long enough for the vehicle to reach cruise from rest. The failure this
catches showed at 120 and at 400 alike, so the window is not delicate; it is
kept short because this runs before every regeneration and every evidence run."""

_SEED: Final = 20260731
"""The seed every benchmark uses, so a pass here means the same trajectory the
evidence pack is measured on."""

_STATIONARY_MPS: Final = 0.1
"""Below this the vehicle has not left rest. Deliberately far above the
`1e-6` a float comparison would need: a policy that creeps at centimetres per
second is not driving either, and the measured healthy value is 11.4 m/s, so
there is two orders of magnitude of daylight on both sides."""

ARTEFACTS: Final = (
    ("twin", Path("var/twin/synthetic.pt"), "training/train_twin.py"),
    ("corpus", Path("var/calibration/synthetic.json"), "training/generate_calibration.py"),
    ("policy", Path("var/policy/synthetic.pt"), "training.train_policy"),
)
"""Name, canonical path, and what regenerates it — in dependency order. The
corpus is generated *through* the twin and the policy is trained against both,
so a regeneration out of order silently produces a mismatched set."""


@dataclass(frozen=True, slots=True)
class Finding:
    """One problem worth refusing on."""

    artefact: str
    detail: str
    remedy: str


def missing() -> list[Finding]:
    """Return a finding per absent artefact.

    Returns:
        One entry per artefact that is not on disk, in dependency order so the
        first thing a reader is told to rebuild is the first thing to rebuild.
    """
    return [
        Finding(
            artefact=name,
            detail=f"{path} does not exist",
            remedy=f"regenerate with {source}, or run `make artifacts`",
        )
        for name, path, source in ARTEFACTS
        if not path.exists()
    ]


def stationary() -> list[Finding]:
    """Return a finding if the policy loads but the vehicle does not drive.

    Imported lazily: this module is the *first* thing `make artifacts-check`
    runs, and importing the training package costs seconds that a missing-file
    check should not pay.

    Returns:
        One finding if the loop is open, otherwise empty.
    """
    from astra.layers.l4_proposer.learned import LearnedPolicy  # noqa: PLC0415
    from training.closed_loop import drive_closed_loop  # noqa: PLC0415

    _, policy_path, _ = ARTEFACTS[2]
    result = drive_closed_loop(
        policy=LearnedPolicy.load(policy_path), ticks=_SMOKE_TICKS, seed=_SEED
    )
    if result.vetoed >= result.ticks:
        return [
            Finding(
                artefact="policy",
                detail=(
                    f"every one of {result.ticks} ticks was vetoed and the final speed is "
                    f"{result.final_speed_mps:.4f} m/s -- the vehicle never drove"
                ),
                remedy=(
                    "this checkpoint cannot be measured against: the closed loop is open, "
                    "so any benchmark run on it reports the absence of the mechanism as a "
                    "signal. Retrain, or point at a checkpoint that drives"
                ),
            )
        ]
    if result.final_speed_mps <= _STATIONARY_MPS:
        return [
            Finding(
                artefact="policy",
                detail=f"final speed {result.final_speed_mps:.4f} m/s -- the vehicle is at rest",
                remedy="retrain; a policy that does not accelerate measures nothing",
            )
        ]
    return []


def main() -> int:
    """Entry point.

    Returns:
        Zero when every artefact is present and the vehicle drives, one
        otherwise. Non-zero deliberately: this gates the evidence run, and a
        warning would be read past.
    """
    findings = missing()
    if not findings:
        findings = stationary()

    if findings:
        print()
        print("  artefact check: FAILED")
        print()
        for finding in findings:
            print(f"  {finding.artefact}: {finding.detail}")
            print(f"    -> {finding.remedy}")
        print()
        print("  Every [M-syn] row in docs/EVIDENCE.md is measured through these.")
        print("  A benchmark run now would report numbers with nothing behind them,")
        print("  which is exactly how E-139 - E-142 came to be published and retracted.")
        print()
        return 1

    print("  artefact check: twin, corpus and policy present; the vehicle drives")
    return 0


if __name__ == "__main__":
    sys.exit(main())
