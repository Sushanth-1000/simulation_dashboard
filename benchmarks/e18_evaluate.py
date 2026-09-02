"""E18 section 5.5 - evaluate all six faults against the FROZEN thresholds.

The thresholds in `configuration.md` were computed from clean data only and are
read here as constants. Nothing in this module may alter them.

Severity levels (section 6) carry a physical rationale and were chosen before
any detection result was seen. Two faults are not magnitude-parameterisable and
run at a single level, which is recorded rather than faked.

    python -m benchmarks.e18_evaluate
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import numpy as np

from astra.kernel.enums import SensorModality
from astra.layers.l4_proposer.learned import LearnedPolicy
from benchmarks.discriminability import CHANNEL_SIGMAS, _FAULT_FIRST, _stages_for, auc
from training.closed_loop import (
    DEFAULT_CHANNEL_SIGMAS,
    RedundantSensing,
    drive_closed_loop,
)
from training.faults import FaultChannel, FaultInjector, bias, drift, dropout, noise_burst, stuck_at

# ---- FROZEN. From E18_OD8_CALIBRATION/configuration.md. Do not edit. -------
FROZEN_QUANTILE = {"P1": 3.7095, "P2": 5.9024, "P3": 3.4000}
EPSILON = 0.05
POLICIES = {"P1": "synthetic", "P2": "long", "P3": "jerkscaled"}
TICKS = 400

# ---- Severity levels, with the engineering rationale for each -------------
# Chosen before any detection result was inspected. `None` marks a fault whose
# mechanism has no magnitude parameter; it runs at one level and says so.
SEVERITIES: dict[str, dict[str, Any]] = {
    "position_bias": {
        "levels": {"low": 0.25, "medium": 1.0, "high": 2.0},
        "unit": "m",
        "rationale": "0.25 m ~ routine GNSS multipath error in open sky; 1.0 m is the original "
                     "E17 magnitude, retained for comparability; 2.0 m ~ half a lane width, "
                     "the point at which a lateral offset is safety-relevant.",
    },
    "position_drift": {
        "levels": {"low": 0.5, "medium": 2.0, "high": 4.0},
        "unit": "m final",
        "rationale": "final offset after a 200-tick window. 0.5 m ~ slow IMU integration drift; "
                     "2.0 m is the original magnitude; 4.0 m ~ a full lane departure.",
    },
    "speed_bias": {
        "levels": {"low": 0.75, "medium": 3.0, "high": 6.0},
        "unit": "m/s",
        "rationale": "0.75 m/s ~ wheel-speed scale error from tyre-radius mismatch (~3 % at "
                     "25 m/s); 3.0 m/s is the original magnitude; 6.0 m/s ~ a gross sensor "
                     "failure a speed bound should certainly catch.",
    },
    "lateral_noise": {
        "levels": {"low": 5.0, "medium": 25.0, "high": 50.0},
        "unit": "x sigma",
        "rationale": "multiplier on the channel's nominal noise sigma. x5 ~ a degraded but "
                     "operating IMU; x25 is the original magnitude; x50 ~ a failing sensor.",
    },
    "speed_stuck": {
        "levels": {"medium": None},
        "unit": "n/a",
        "rationale": "STUCK_AT holds the last value; it has no magnitude parameter. The "
                     "effective severity is set by how far the true value drifts from the held "
                     "one, which is a property of the trajectory rather than of the fault. Run "
                     "at a single level and reported as such.",
    },
    "imu_dropout": {
        "levels": {"medium": None},
        "unit": "n/a",
        "rationale": "DROPOUT suppresses the IMU publish; it has no magnitude parameter. "
                     "Duration could be swept but that changes the fault definition, which the "
                     "freeze forbids. Run at a single level.",
    },
}
POSITION_FAULTS = ("position_bias", "position_drift")


def _build_injector(fault: str, magnitude: float | None, seed: int):
    """FaultInjector for the four channel faults; None for the position faults."""
    last = TICKS - 1
    if fault == "speed_bias":
        specs = (bias(FaultChannel.SPEED, first_tick=_FAULT_FIRST, last_tick=last,
                      offset=float(magnitude)),)
    elif fault == "speed_stuck":
        specs = (stuck_at(FaultChannel.SPEED, first_tick=_FAULT_FIRST, last_tick=last),)
    elif fault == "lateral_noise":
        specs = (noise_burst(FaultChannel.LATERAL_ACCELERATION, first_tick=_FAULT_FIRST,
                             last_tick=last, sigma_multiplier=float(magnitude)),)
    elif fault == "imu_dropout":
        specs = (dropout(first_tick=_FAULT_FIRST, last_tick=last),)
    else:
        return None
    return FaultInjector(specs, seed=seed, sigmas=CHANNEL_SIGMAS)


def _sensing(fault: str, magnitude: float | None, seed: int, active: bool):
    """Redundant spec. Position faults inject here; everything else stays clean."""
    if fault not in POSITION_FAULTS or not active:
        return RedundantSensing.build(sigmas=DEFAULT_CHANNEL_SIGMAS, seed=seed)
    span = TICKS - 1 - _FAULT_FIRST
    return RedundantSensing.build(
        sigmas=DEFAULT_CHANNEL_SIGMAS, seed=seed,
        faulted=SensorModality.IMU, also_faulted=(SensorModality.GPS,),
        opens_at=_FAULT_FIRST,
        bias=float(magnitude) if fault == "position_bias" else 0.0,
        drift_per_tick=0.0 if fault == "position_bias" else float(magnitude) / span,
    )


def _run(policy, fault, magnitude, seed, active):  # noqa: ANN001, ANN201
    stages = _stages_for(fault)
    vals: dict[str, list[float]] = {c: [] for c, _, _ in stages}
    ticks: list[int] = []
    scores: list[float] = []
    est_y: list[float] = []

    def obs(s: Any) -> None:
        ticks.append(s.tick)
        for code, _, fn in stages:
            vals[code].append(fn(s))
        sc = float("nan")
        sv = getattr(s.record, "safety_verdict", None)
        if sv is not None:
            for gv in getattr(sv, "gate_verdicts", ()):
                if str(getattr(gv, "gate", "")).endswith("STATISTICAL"):
                    for k, v in getattr(gv, "evidence", ()):
                        if k == "non_conformity_score":
                            sc = float(v)
        scores.append(sc)
        st = getattr(s.record, "fast_state", None)
        m = getattr(st, "mean", None) if st is not None else None
        est_y.append(float(m[1]) if m is not None and len(m) > 1 else float("nan"))

    drive_closed_loop(
        policy=policy, ticks=TICKS, seed=seed, observer=obs,
        fault=_build_injector(fault, magnitude, seed) if active else None,
        redundant=_sensing(fault, magnitude, seed, active),
    )
    return {"values": vals, "ticks": ticks, "scores": scores, "est_y": est_y}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=30)
    ap.add_argument("--base-seed", type=int, default=20260731)
    ap.add_argument("--out", type=Path,
                    default=Path("experiments/phase5_od8_h7/E18_OD8_CALIBRATION/raw_results"))
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    pols = {k: LearnedPolicy.load(Path(f"var/policy/{v}.pt")) for k, v in POLICIES.items()}

    records: list[dict[str, Any]] = []
    combos = [(f, lvl, mag) for f, spec in SEVERITIES.items()
              for lvl, mag in spec["levels"].items()]
    total = len(combos) * len(pols) * args.seeds
    done = 0
    t0 = time.time()

    for pname, policy in pols.items():
        q = FROZEN_QUANTILE[pname]
        for fault, level, mag in combos:
            for i in range(args.seeds):
                seed = args.base_seed + i
                clean = _run(policy, fault, mag, seed, False)
                faulted = _run(policy, fault, mag, seed, True)
                win = [j for j, t in enumerate(clean["ticks"]) if t >= _FAULT_FIRST]

                D = {}
                for code, _, _ in _stages_for(fault):
                    c = np.array([clean["values"][code][j] for j in win], float)
                    fv = np.array([faulted["values"][code][j] for j in win], float)
                    D[code] = auc(fv, c)

                sf = np.array([faulted["scores"][j] for j in win], float)
                sc = np.array([clean["scores"][j] for j in win], float)
                sf_f, sc_f = sf[np.isfinite(sf)], sc[np.isfinite(sc)]
                alarms = sf_f > q
                # latency: ticks from injection to first alarm
                first = next((k for k, a in enumerate(alarms) if a), None)
                ey_c = np.nanmean([clean["est_y"][j] for j in win])
                ey_f = np.nanmean([faulted["est_y"][j] for j in win])

                records.append({
                    "policy": pname, "fault": fault, "severity_level": level,
                    "severity_value": mag, "seed": seed, "frozen_quantile": q,
                    "D": D,
                    "alarm_rate_faulted": float(alarms.mean()) if sf_f.size else float("nan"),
                    "alarm_rate_clean": float((sc_f > q).mean()) if sc_f.size else float("nan"),
                    "detected": bool(alarms.any()),
                    "detection_latency_ticks": None if first is None else int(first),
                    "score_mean_clean": float(sc_f.mean()) if sc_f.size else float("nan"),
                    "score_mean_faulted": float(sf_f.mean()) if sf_f.size else float("nan"),
                    "score_max_faulted": float(sf_f.max()) if sf_f.size else float("nan"),
                    "threshold_margin": float(sf_f.mean() - q) if sf_f.size else float("nan"),
                    "fault_reached_estimator": bool(abs(ey_f - ey_c) > 1e-9),
                })
                done += 1
            print(f"  [{done:>4}/{total}] {pname} {fault} {level}  {time.time() - t0:.0f}s",
                  flush=True)

    (args.out / "fault_evaluation.json").write_text(
        json.dumps(records, indent=2, default=str), encoding="utf-8")
    reached = sum(1 for r in records if r["fault_reached_estimator"])
    print(f"\n  {len(records)} records | fault reached estimator in {reached}/{len(records)}")
    print(f"  -> {args.out / 'fault_evaluation.json'}")


if __name__ == "__main__":
    main()
