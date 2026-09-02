"""E17 30-seed sweep -- operating-regime-aware discriminability study.

Configuration is the **frozen protocol as the repository implements it**, which
is 6 scenarios at one severity each -- not the 13x3 registry in
`ASTRA_RESEARCH_FREEZE.md`, which is a plan and not yet built. Running 13x3
would require adding fault definitions, which the freeze forbids. The
discrepancy is recorded here rather than silently resolved either way.

    6 scenarios x 30 seeds x 3 policies x 2 arms = 2,160 runs of 400 ticks

Seeds are `20260731 + i` for i in 0..29: deterministic, contiguous, and fixed
before execution.

    python -m benchmarks.e17_sweep
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import time
from pathlib import Path

from astra.layers.l4_proposer.learned import LearnedPolicy
from benchmarks.discriminability import _ABSORPTION_THRESHOLD, profile

BASE_SEED = 20260731
N_SEEDS = 30
POLICIES = {
    "P1": Path("var/policy/synthetic.pt"),
    "P2": Path("var/policy/long.pt"),
    "P3": Path("var/policy/jerkscaled.pt"),
}


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return "unknown"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=Path("results/E17_30SEED"))
    ap.add_argument("--seeds", type=int, default=N_SEEDS)
    ap.add_argument("--ticks", type=int, default=400)
    args = ap.parse_args()

    for sub in ("raw", "manifests", "logs"):
        (args.out / sub).mkdir(parents=True, exist_ok=True)

    commit = _git_commit()
    manifest = {
        "experiment_id": "E17_30SEED",
        "git_commit": commit,
        "base_seed": BASE_SEED,
        "n_seeds": args.seeds,
        "ticks": args.ticks,
        "absorption_threshold": _ABSORPTION_THRESHOLD,
        "policies": {k: str(v) for k, v in POLICIES.items()},
        "protocol_note": (
            "6 scenarios at one severity each, as implemented in "
            "benchmarks/fault_study.py. The 13-fault x 3-severity registry in "
            "ASTRA_RESEARCH_FREEZE.md is a plan, not built; running it would "
            "require new fault definitions, which the freeze forbids."
        ),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    (args.out / "manifests" / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )

    loaded = {name: LearnedPolicy.load(path) for name, path in POLICIES.items()}
    total = args.seeds * len(POLICIES)
    done = failed = 0
    failures: list[dict[str, object]] = []
    t0 = time.time()

    for i in range(args.seeds):
        seed = BASE_SEED + i
        for pname, policy in loaded.items():
            target = args.out / "raw" / f"{pname}_seed{seed}.json"
            if target.exists():
                done += 1
                continue
            try:
                result = profile(policy, seed, args.ticks)
                target.write_text(
                    json.dumps(
                        {
                            "run_id": f"{pname}_seed{seed}",
                            "policy": pname,
                            "checkpoint": str(POLICIES[pname]),
                            "seed": seed,
                            "ticks": args.ticks,
                            "git_commit": commit,
                            "final_status": "ok",
                            "scenarios": result,
                        },
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                done += 1
            except Exception as exc:  # noqa: BLE001 - a failed run is data
                failed += 1
                failures.append(
                    {
                        "run_id": f"{pname}_seed{seed}",
                        "reason": f"{type(exc).__name__}: {exc}",
                        "retry": False,
                        "final_status": "failed",
                    }
                )
            elapsed = time.time() - t0
            rate = elapsed / max(done + failed, 1)
            print(
                f"  [{done + failed:>3}/{total}] {pname} seed {seed}  "
                f"ok={done} failed={failed}  eta={rate * (total - done - failed) / 60:.1f} min",
                flush=True,
            )

    (args.out / "logs" / "failures.json").write_text(
        json.dumps(failures, indent=2), encoding="utf-8"
    )
    print(f"\n  complete: {done} ok, {failed} failed, {time.time() - t0:.0f}s")
    print(f"  raw: {args.out / 'raw'}")


if __name__ == "__main__":
    main()
