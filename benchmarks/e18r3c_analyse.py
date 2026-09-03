"""E18-R3c analysis: does a sustained fault get detected, or only its aftermath?

Compares R3c (fault active the whole window) against R3b (fault active ticks
200-399, aftermath fills the rest), phase by phase from fault onset. The
question the ledger now forces: what does the monitor see DURING the fault,
separately from after it.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

Q = 3.7024
PHASES = [("during 200-399", 200, 400), ("400-999", 400, 1000),
          ("1000-1999", 1000, 2000), ("2000-3399", 2000, 3400)]
FAULTS = ("position_bias", "position_drift", "speed_bias",
          "lateral_noise", "speed_stuck", "imu_dropout")
R3B = Path("experiments/phase5_od8_h7/E18_R3b/raw_results/tick_series.json")
R3C = Path("experiments/phase5_od8_h7/E18_R3c/raw_results/tick_series.json")


def phase_alarm(ts: dict, fault: str, lo: int, hi: int) -> tuple[float, float]:
    keys = [k for k in ts if k.startswith(fault + "_")]
    if not keys:
        return float("nan"), float("nan")
    A = np.array([ts[k] for k in keys], float)[:, lo:hi]
    return float(np.nanmean(A)), float(np.nanmean(A > Q))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("experiments/phase5_od8_h7/E18_R3c"))
    ap.parse_args()
    r3b = json.loads(R3B.read_text(encoding="utf-8")) if R3B.exists() else {}
    r3c = json.loads(R3C.read_text(encoding="utf-8"))

    out: dict = {"threshold": Q, "phases": [p[0] for p in PHASES], "faults": {}}
    print("PHASE-RESOLVED ALARM RATE  (fraction of ticks above threshold)")
    print("R3b = fault ticks 200-399 then aftermath | R3c = fault sustained whole window\n")
    for f in FAULTS:
        print(f"  {f}")
        print(f"    {'phase':<16}{'R3b alarm':>11}{'R3c alarm':>11}{'R3b mean':>11}{'R3c mean':>11}")
        rec = {}
        for name, lo, hi in PHASES:
            mb, ab = phase_alarm(r3b, f, lo, hi)
            mc, ac = phase_alarm(r3c, f, lo, hi)
            rec[name] = {"r3b_alarm": ab, "r3c_alarm": ac, "r3b_mean": mb, "r3c_mean": mc}
            print(f"    {name:<16}{ab:>11.3f}{ac:>11.3f}{mb:>11.4f}{mc:>11.4f}")
        out["faults"][f] = rec
        print()

    # --- the two pre-registered readings for imu_dropout -------------------
    dur = out["faults"]["imu_dropout"]["during 200-399"]["r3c_alarm"]
    late = out["faults"]["imu_dropout"]["2000-3399"]["r3c_alarm"]
    clean = 0.05
    print("=" * 60)
    print("PRE-REGISTERED READINGS (imu_dropout sustained)")
    print(f"  during-fault alarm rate (R3c): {dur:.3f}   clean ~{clean:.2f}")
    print(f"  late-window alarm rate  (R3c): {late:.3f}")
    if dur < 2 * clean and late < 2 * clean:
        verdict = ("H-AFTERMATH SUPPORTED: a sustained fault stays near-invisible for the "
                   "whole window. R3b detection was aftermath. A persistent sensor failure "
                   "is not detected while it persists.")
    elif late > 0.0725:
        verdict = ("H-ACCUMULATION SUPPORTED: detection rises over the sustained window. "
                   "The monitor eventually catches a persistent fault, but slowly.")
    else:
        verdict = ("MIXED: neither pre-registered reading holds cleanly. Report the phase "
                   "curve as-is without forcing it into either hypothesis.")
    out["imu_dropout_verdict"] = verdict
    print(f"\n  -> {verdict}")

    (ap_out := out) and None
    dest = Path("experiments/phase5_od8_h7/E18_R3c/processed_results")
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "phase_comparison.json").write_text(json.dumps(out, indent=2, default=str),
                                                encoding="utf-8")
    print(f"\n  -> {dest / 'phase_comparison.json'}")


if __name__ == "__main__":
    main()
