"""Harvest non-conformity scores from the trained twin, and measure the coverage they buy.

    python -m training.generate_calibration --out var/calibration/synthetic.json

What a calibration corpus is for
---------------------------------
The ICP gate accepts a proposal when its non-conformity score falls at or below
a threshold, and that threshold is the ``1 - epsilon`` empirical quantile of
scores gathered from *past* situations in the same context class. With no such
scores the quantile is correctly infinite and the gate vetoes everything as
``CONTEXT_NOT_CALIBRATED``. This script is what fills that in.

The score computed here is deliberately the same expression L6 computes::

    score = euclidean_distance(pi_prop, pi_hat) / sqrt(P_f[lateral_acceleration])

Not an approximation of it, and not a reimplementation: the scores are harvested
by running the real proposer, the real twin and the real filter, so a corpus
cannot drift away from the gate that consumes it. A calibration set built from a
different definition would produce a threshold that looks reasonable and means
nothing.

What this corpus is, and is not
--------------------------------
It comes from a synthetic kinematic vehicle and a twin trained on the same
family of motion. Two consequences travel with every number derived from it:

* It **can** expose an implementation error -- a wrong quantile rank, a broken
  normalisation, a gate reading the wrong covariance entry.
* It **cannot** establish that the gate's coverage holds on real driving. The
  corpus and the twin share their assumptions, so the calibration is coverage
  against a world the twin already models.

Phase 9's CARLA drives replace it. Until then, every coverage figure this script
prints must be quoted with the word "synthetic" attached.

Why coverage is reported twice
-------------------------------
Conformal coverage is guaranteed under **exchangeability**. Consecutive ticks in
a control loop are autocorrelated and therefore not exchangeable, so:

* the **shuffled** split is exchangeable by construction and tests whether the
  quantile arithmetic is correct -- this is the number held to ``1 - epsilon``;
* the **sequential** split preserves the autocorrelation a live run faces, and
  is reported beside it because a large gap between the two is a real finding
  about the gate, not a rounding difference.
"""

from __future__ import annotations

import argparse
import math
import random
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from astra.config.loader import load_settings
from astra.contracts.sensing import SensorSample
from astra.kernel.enums import ContextClass, LayerId, SensorModality
from astra.kernel.identifiers import ComponentId, TickId
from astra.kernel.matrix import SymmetricMatrix
from astra.kernel.time import Instant, ManualClock, Timeline
from astra.kernel.units import Probability, Seconds
from astra.layers.l1_sensing.bus import SharedSensorBus
from astra.layers.l2_estimation.filter import DualRateUKF
from astra.layers.l2_estimation.measurement import fast_measurement, slow_measurement
from astra.layers.l3_trust.classifier import RuleBasedContextClassifier
from astra.layers.l3_trust.corpus import CalibrationCorpus, coverage_report
from astra.layers.l4_proposer.learned import LearnedPolicy
from astra.layers.l4_proposer.policies import KinematicPlaceholderPolicy
from astra.layers.l4_proposer.proposer import CmdpProposer
from astra.layers.l5_twin.twin import PhysicsInformedTwin
from astra.layers.l6_statistical_gate.gate import CONTROL_DIMENSION
from astra.runtime.assembly import STEER_INDEX, THROTTLE_INDEX, automotive_actuation_space
from training.closed_loop import LATERAL_SIGMA, POSITION_SIGMA, SPEED_SIGMA

if TYPE_CHECKING:
    from collections.abc import Sequence

    from astra.layers.l2_estimation.measurement import Measurement
    from astra.layers.l4_proposer.proposer import Policy

DEFAULT_CHECKPOINT = Path("var/twin/synthetic.pt")
DEFAULT_OUT = Path("var/calibration/synthetic.json")
MINIMUM_SIGMA = 1e-6
SEGMENTS = 240
"""How many operating points the sweep samples across the envelope."""

SETTLE_TICKS = 60
"""Ticks held at each operating point, long enough for the filter to settle."""

DISCARD_TICKS = 20
"""Leading ticks of each segment thrown away as filter transient."""

FAULTED_SEGMENT_MODULUS = 3
"""Every third segment injects sensor faults, so DEGRADED_SENSOR is reached
often enough to calibrate without dominating the corpus."""

MAXIMUM_SAMPLED_LATERAL = 3.0
"""Largest lateral acceleration sampled, in m/s^2. Below the shield's friction
bound on dry tarmac, so the corpus describes admissible driving rather than the
manoeuvres the shield exists to reject."""

SPLITS = 200
"""How many random splits the coverage mean is taken over. One split has a
standard deviation near 1.5 percentage points, wide enough to produce both false
alarms and false passes."""

TARGET_MARGIN = 0.005
"""How far below nominal an empirical coverage may fall before it is a failure.

Sampling noise on a few hundred held-out points is worth half a percentage
point; the Demo Plan's own acceptance figure is 94.5% against a 95% nominal, and
this constant is that gap expressed once rather than written at each call site.
"""


class _Segment:
    """One held operating point the corpus samples from.

    A segment rather than a per-tick random walk because the filter needs time
    to settle. Scores harvested while the UKF is still converging describe the
    filter's transient, not the twin's accuracy, and a corpus full of them would
    calibrate the gate against a situation that lasts two seconds after startup.
    """

    __slots__ = ("fault_rate", "lateral", "speed", "ticks")

    def __init__(self, *, speed: float, lateral: float, fault_rate: float, ticks: int) -> None:
        self.speed = speed
        self.lateral = lateral
        self.fault_rate = fault_rate
        self.ticks = ticks


def _sweep(
    *,
    highway_boundary: float,
    legal_limit: float,
    segments: int,
    settle_ticks: int,
    noise: random.Random,
) -> tuple[_Segment, ...]:
    """Sample operating points across the whole envelope, not at two points.

    The first version of this generator sampled two fixed speeds -- one urban,
    one highway -- and the resulting corpus could not calibrate a run cruising
    anywhere between them. The gate correctly reported that it had no
    calibration for the situation, which is the right behaviour and a useless
    corpus.

    A calibration set has to span the operational design domain it certifies. So
    speeds are drawn across the whole admissible range and lateral accelerations
    across the range the shield permits, in held segments long enough for the
    filter to settle in each.

    Args:
        highway_boundary: The urban/highway classification speed.
        legal_limit: The configured legal speed limit.
        segments: How many operating points to sample.
        settle_ticks: How many ticks to hold each one.
        noise: The seeded random source.

    Returns:
        The segments, spanning urban and highway speeds, straight and cornering,
        with and without induced sensor faults.
    """
    lowest = highway_boundary * 0.25
    highest = legal_limit * 0.95
    return tuple(
        _Segment(
            speed=noise.uniform(lowest, highest),
            lateral=noise.uniform(0.0, MAXIMUM_SAMPLED_LATERAL),
            fault_rate=0.30
            if index % FAULTED_SEGMENT_MODULUS == FAULTED_SEGMENT_MODULUS - 1
            else 0.0,
            ticks=settle_ticks,
        )
        for index in range(segments)
    )


class _Extractor:
    """Reads the synthetic payload, as a real adapter would."""

    def extract_fast(self, frame: object) -> Measurement | None:
        sample = frame.sample_for(SensorModality.IMU)  # type: ignore[attr-defined]
        if sample is None:
            return None
        payload = sample.payload
        return fast_measurement(
            [
                # Lateral position is observed here for the same reason it is in
                # `training/closed_loop.py`: a corpus harvested under different
                # observability from the run it calibrates describes a different
                # filter. Without it `position_y` is dead-reckoned, the
                # covariance the non-conformity score divides by is that of an
                # unobserved state, and the quantile certifies a filter nobody
                # runs.
                ("position_y", float(payload["y"]), POSITION_SIGMA),
                ("speed", float(payload["v"]), SPEED_SIGMA),
                ("lateral_acceleration", float(payload["a"]), LATERAL_SIGMA),
            ]
        )

    def extract_slow(self, frame: object) -> Measurement | None:
        del frame
        return slow_measurement([("road_friction_coefficient", 0.85, 4e-4)])


class _NullTrust:
    """A stand-in Trust Index for the proposer, which needs one to build an observation.

    The proposer appends the Trust Index to its observation vector. During corpus
    generation there is no calibration yet -- that is what is being generated --
    so a fixed neutral value is supplied. It reaches only the placeholder policy,
    which ignores it, so it cannot bias the scores being harvested.
    """

    trust_index = Probability(0.5)


def generate(
    *,
    environment: str,
    checkpoint: Path,
    per_class: int,
    seed: int,
    policy_checkpoint: Path | None = None,
) -> CalibrationCorpus:
    """Harvest non-conformity scores until every reachable class has enough.

    **The corpus must be harvested from the proposer that will be judged
    against it.** A conformal quantile is a statement about one distribution of
    non-conformity scores, and scoring a different proposer against it asks
    whether policy B is typical of policy A -- a question with no bearing on
    whether policy B is behaving.

    That was not merely theoretical. The placeholder harvested here is built with
    ``maximum_jerk=settings.physical.max_lateral_jerk``, so it respects L7b's
    bound *by construction*; the trained PPO policy has no such term. A corpus
    drawn from the first and used to judge the second had the statistical gate
    vetoing 100% of ticks in a 100,000-tick soak while the Trust Index read
    exactly 1.00 throughout.

    Args:
        environment: Which configuration to load.
        checkpoint: The trained twin's weights.
        per_class: How many scores each class needs.
        seed: Random seed for the sensor noise and fault injection.
        policy_checkpoint: A trained policy to harvest from. ``None`` keeps the
            deterministic placeholder, which is right when no policy has been
            trained yet -- an uncalibrated gate refuses everything, so some
            corpus is needed before anything can be observed at all.

    Returns:
        The corpus.
    """
    resolved = load_settings(environment=environment, include_environment_variables=False)
    settings = resolved.settings
    space = automotive_actuation_space()
    noise = random.Random(seed)

    classifier = RuleBasedContextClassifier(highway_speed=settings.trust.highway_speed_boundary)
    policy: Policy = (
        LearnedPolicy.load(policy_checkpoint)
        if policy_checkpoint is not None
        else KinematicPlaceholderPolicy(
            channel_count=space.dimension,
            speed_index=THROTTLE_INDEX,
            steer_index=STEER_INDEX,
            target_speed=float(settings.shield.legal_speed_limit) * 0.8,
            steer_effectiveness=float(settings.twin.control_effectiveness[STEER_INDEX]),
            tick_period=1.0 / settings.estimation.fast_rate_hz,
            maximum_jerk=float(settings.physical.max_lateral_jerk),
        )
    )
    scores: dict[ContextClass, list[float]] = {}
    innovations: dict[ContextClass, list[float]] = {}
    digest = ""
    tick = 0

    segments = _sweep(
        highway_boundary=float(settings.trust.highway_speed_boundary),
        legal_limit=float(settings.shield.legal_speed_limit),
        segments=SEGMENTS,
        settle_ticks=SETTLE_TICKS,
        noise=noise,
    )
    for regime in segments:
        clock = ManualClock(Instant(0, Timeline.MANUAL))
        period = Seconds(1.0 / settings.estimation.fast_rate_hz)
        bus: SharedSensorBus[object] = SharedSensorBus(
            clock=clock, staleness_budget=settings.sensing.staleness_budget
        )
        estimator: DualRateUKF[object] = DualRateUKF(
            settings=settings.estimation,
            extractor=_Extractor(),
            initial_fast_state=[0.0, 0.0, regime.speed, 0.0, 0.0],
            initial_fast_covariance=SymmetricMatrix.from_diagonal([1.0, 1.0, 1.0, 0.1, 1.0]),
            initial_slow_state=[0.85, 0.0, 1.0],
            initial_slow_covariance=SymmetricMatrix.from_diagonal([0.01, 0.01, 0.01]),
        )
        proposer = CmdpProposer(
            policy=policy,
            space=space,
            component=ComponentId(LayerId.L4_CORE_A_CMDP),
            clock=clock,
        )
        twin = PhysicsInformedTwin(
            settings=settings.twin,
            space=space,
            component=ComponentId(LayerId.L5_PINN_TWIN),
            clock=clock,
        )
        twin.load_checkpoint(checkpoint)
        digest = twin.weights_digest

        for held in range(regime.ticks):
            faulted = noise.random() < regime.fault_rate
            spike = 40.0 if faulted else 0.0
            bus.publish(
                SensorSample(
                    modality=SensorModality.IMU,
                    observed_at=clock.now(),
                    quality=Probability(1.0),
                    payload={
                        # Injected at exactly the sigma declared to the filter.
                        # These were 0.08 and 0.12 against declared 0.01 and
                        # 0.04 until 5 August 2026 -- an eightfold and threefold
                        # underestimate, which makes the UKF over-trust its
                        # measurements and inflates every normalised innovation
                        # the Trust Index then reads.
                        "v": regime.speed + noise.gauss(0.0, SPEED_SIGMA) + spike,
                        "a": regime.lateral + noise.gauss(0.0, LATERAL_SIGMA),
                        "y": noise.gauss(0.0, POSITION_SIGMA),
                    },
                )
            )
            frame = bus.acquire(TickId(tick))
            state = estimator.update_fast(frame)
            estimator.update_slow(frame)
            innovation = estimator.latest_innovation()
            context = classifier.classify(state=state, innovation=innovation)

            proposal = proposer.propose(
                tick=TickId(tick),
                state=state,
                trust=_NullTrust(),  # type: ignore[arg-type]
            )
            prediction = twin.predict(tick=TickId(tick), state=state)

            # Feedback loop FB1, as the pipeline runs it. The corpus has to be
            # generated under the same filter behaviour the gate will score
            # against: FB1 changes the state estimate, the estimate changes the
            # non-conformity score, and a quantile table calibrated with the
            # loop open does not describe the distribution a closed-loop run
            # produces. Leaving it out here raised the placeholder policy's
            # measured veto rate from 60% to 100% with no change to the policy.
            estimator.apply_command(
                sum(
                    float(gain) * float(value)
                    for gain, value in zip(
                        settings.twin.control_effectiveness,
                        proposal.command.values,
                        strict=True,
                    )
                )
            )

            departure = math.dist(proposal.command.values, prediction.command.values)
            sigma = math.sqrt(max(state.variance_of(CONTROL_DIMENSION), MINIMUM_SIGMA))
            bucket = scores.setdefault(context, [])
            # Discard the settling transient: the first ticks of a segment
            # measure the filter converging on the new operating point, not the
            # twin's accuracy at it.
            if held >= DISCARD_TICKS and len(bucket) < per_class:
                bucket.append(departure / sigma)

            # The Trust Index's calibration, harvested alongside and kept apart.
            # It scores the filter's innovation, not the proposal: L3 runs
            # before L4 in the tick, so no proposal exists for it to score. One
            # distribution served both until 5 August 2026, and the Trust Index
            # -- querying a CDF of proposal-vs-twin scores with an innovation
            # magnitude -- returned two distinct values across 4,001 ticks.
            if innovation is not None:
                innovation_bucket = innovations.setdefault(context, [])
                if held >= DISCARD_TICKS and len(innovation_bucket) < per_class:
                    innovation_bucket.append(float(innovation.mahalanobis_distance))

            tick += 1
            clock.advance(period)

    return CalibrationCorpus(
        scores={context: tuple(values) for context, values in scores.items()},
        innovations={context: tuple(values) for context, values in innovations.items()},
        twin_weights_digest=digest,
        config_hash=resolved.hash,
        seed=seed,
    )


def _report(corpus: CalibrationCorpus, *, epsilon: float, seed: int) -> bool:
    """Print the coverage report and return whether every class met its target.

    Args:
        corpus: The corpus to measure.
        epsilon: The conformal significance level.
        seed: Seed for the reproducible shuffle.

    Returns:
        ``True`` if every calibrated class met the target.
    """
    longest = max((len(context.value) for context in corpus.calibrated_classes), default=10)
    results = coverage_report(corpus, epsilon=epsilon, splits=SPLITS, seed=seed)
    target = 1.0 - epsilon
    floor = target - TARGET_MARGIN

    print(f"\n  nominal coverage 1 - epsilon = {target:.3f}   accept >= {floor:.3f}")
    print(f"  mean over {SPLITS} random calibration/validation splits\n")
    print(
        f"  {'class':<{longest}}  {'n_fit':>6} {'quantile':>9} "
        f"{'shuffled':>9} {'+-sd':>7} {'worst':>7} {'sequential':>11}"
    )
    print("  " + "-" * (longest + 56))
    passed = True
    for result in results:
        ok = result.shuffled_coverage >= floor
        passed = passed and ok
        print(
            f"  {result.context.value:<{longest}}  {result.calibration_count:>6} "
            f"{result.quantile:>9.4f} {result.shuffled_coverage:>9.4f} "
            f"{result.shuffled_spread:>7.4f} {result.worst_split:>7.4f} "
            f"{result.sequential_coverage:>11.4f}"
            f"{'' if ok else '   BELOW TARGET'}"
        )

    unreached = tuple(
        context
        for context in ContextClass
        if context.is_certified and corpus.sample_count(context) == 0
    )
    if unreached:
        print(
            f"\n  not reachable by the classifier, so uncalibrated: "
            f"{', '.join(context.value for context in unreached)}"
        )
        print("  see l3_trust/classifier.py -- RAIN_NIGHT needs an input the")
        print("  fast state vector does not carry. Recorded as debt, not approximated.")
    return passed


def main(argv: Sequence[str] | None = None) -> int:
    """Generate a corpus, measure its coverage and persist it.

    Args:
        argv: Argument vector, defaulting to ``sys.argv[1:]``.

    Returns:
        ``0`` if every calibrated class met its coverage target, ``1`` if one
        did not, ``2`` if the twin checkpoint is missing.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--environment", default="simulation")
    parser.add_argument("--per-class", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=20260731)
    parser.add_argument(
        "--policy",
        type=Path,
        default=None,
        help=(
            "harvest from a trained policy instead of the placeholder. The corpus "
            "must describe the proposer it will judge; see generate()"
        ),
    )
    arguments = parser.parse_args(argv)

    if not arguments.checkpoint.exists():
        print(f"no trained twin at {arguments.checkpoint}")
        print(f"    python training/train_twin.py --out {arguments.checkpoint}")
        return 2

    resolved = load_settings(environment=arguments.environment, include_environment_variables=False)
    epsilon = resolved.settings.gate.significance_epsilon

    print(f"environment    {arguments.environment}")
    print(f"config hash    {resolved.hash}")
    print(f"twin           {arguments.checkpoint}")
    print(f"epsilon        {epsilon}")
    print(f"target per class {arguments.per_class}")

    corpus = generate(
        environment=arguments.environment,
        checkpoint=arguments.checkpoint,
        per_class=arguments.per_class,
        seed=arguments.seed,
        policy_checkpoint=arguments.policy,
    )
    print(f"twin digest    {corpus.twin_weights_digest}")
    for context in corpus.calibrated_classes:
        print(f"  harvested {corpus.sample_count(context):>5} scores for {context.value}")

    passed = _report(corpus, epsilon=epsilon, seed=arguments.seed)
    corpus.write(arguments.out)
    print(f"\n  corpus written to {arguments.out}")
    print("\n  Synthetic corpus from a twin trained on synthetic kinematics.")
    print("  It can expose an implementation error; it cannot establish that")
    print("  coverage holds on real driving. Phase 9's CARLA drives replace it.")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
