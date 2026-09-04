"""Driving the real pipeline against the training plant, with the loop closed.

Why this exists
----------------
Every scenario written before this one drove the pipeline open-loop: the harness
published a fixed sensor payload each tick regardless of what the vehicle had
been commanded to do. That is fine for exercising the plumbing, and it silently
invalidates any measurement involving a gate that compares a proposal against
the current state.

Concretely: L7b vetoes when ``|a_proposed - a_current| / dt`` exceeds the jerk
limit. Under an open-loop harness reporting zero lateral acceleration forever,
``a_current`` is pinned at zero, so *every* non-zero proposal is a jerk
violation and the measured veto rate is an artefact of the harness. The first
learned policy measured that way scored a 100% veto rate. The number said
nothing about the policy.

Closing the loop means the plant integrates the command the pipeline actually
issued, and the sensors report the state that produced. Then a veto rate is a
statement about the proposer.

What is still synthetic
------------------------
The plant is :class:`~training.environment.SyntheticDrivingEnv` -- the same
kinematic model the UKF assumes and the twin was fitted to. So this measures
whether the learned policy is *physically admissible on the modelled platform*,
which is a real question with a real answer. It does not measure gate accuracy
under distribution shift, because there is no shift: one set of equations
generates the data and another fitted to the same equations judges it.
"""

from __future__ import annotations

import random
import tempfile
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from astra.config.loader import load_settings
from astra.contracts.sensing import SensorSample
from astra.kernel.enums import SensorModality
from astra.kernel.identifiers import RunId, TickId
from astra.kernel.time import Instant, ManualClock, Timeline
from astra.kernel.units import Probability, Seconds
from astra.layers.l1_sensing.bus import SharedSensorBus
from astra.layers.l2_estimation.measurement import fast_measurement, slow_measurement
from astra.layers.l3_trust.corpus import CalibrationCorpus
from astra.observability.audit import JsonlAuditSink
from astra.runtime.ablation import AblationProfile
from astra.runtime.assembly import AssembledPipeline, assemble_pipeline
from training.environment import EnvironmentSpec, SyntheticDrivingEnv
from training.faults import FaultChannel

if TYPE_CHECKING:
    from collections.abc import Callable

    from numpy.typing import NDArray

    from astra.contracts.audit import DecisionRecord
    from astra.layers.l2_estimation.measurement import Measurement
    from astra.layers.l4_proposer.proposer import Policy
    from astra.runtime.pipeline import ColdPathContext, TickOutcome
    from training.faults import FaultEpisode, FaultInjector

__all__ = [
    "CHANNEL_SIGMAS",
    "FRICTION",
    "FRICTION_SIGMA",
    "LATERAL_SIGMA",
    "SPEED_SIGMA",
    "ClosedLoopResult",
    "TickSample",
    "drive_closed_loop",
]

ENVIRONMENT = "simulation"
"""The configuration every closed-loop run resolves.

Named rather than repeated, because a caller that builds a
:class:`~astra.runtime.pipeline.ColdPathContext` has to read the same settings
this function does -- and two literals drift.
"""

TWIN = Path("var/twin/synthetic.pt")
CORPUS = Path("var/calibration/synthetic.json")

_SENSOR_QUALITY = Probability(0.95)

# The sensor model, in one place because it has to be true of two things at
# once: the noise actually injected into a published reading, and the sigma
# declared to the filter alongside it. They were different numbers until 2
# August 2026 -- the corpus generator injected gauss(0, 0.08) on speed while
# telling the filter 0.01, an eightfold underestimate -- which makes the UKF
# over-trust its measurements and inflates every normalised innovation. The
# Trust Index reads those innovations, so the mis-tuning arrived there as
# saturation.
#
# Values are per-quantity realistic: wheel-encoder speed, IMU lateral
# acceleration, lane position from a forward camera.
SPEED_SIGMA = 0.01
LATERAL_SIGMA = 0.04
_SPEED_SIGMA = SPEED_SIGMA
_LATERAL_SIGMA = LATERAL_SIGMA
POSITION_SIGMA = 0.1
_POSITION_SIGMA = POSITION_SIGMA
"""Lateral-position measurement noise, in metres.

Representative of lane detection from a forward camera, which is where a real
vehicle gets this quantity. The number matters less than the fact that the
quantity is observed at all.

**Why this exists, and what its absence cost.** Until 5 August this extractor
published speed and lateral acceleration and nothing else, so ``position_y`` was
never measured -- the UKF propagated it from a heading that is also unobserved,
which is dead reckoning with no correction term. In a 2,000-tick run the estimate
sat at zero while the plant drifted to 2.07 m off a lane 1.75 m wide, and the
estimator error tracked the true deviation to three decimals because the estimate
never moved at all.

Nothing noticed. **The veto rate over those ticks was 0.00 and the Trust Index
was exactly 1.00**, because no gate in Core-B measures where the vehicle is: L7a
bounds speed, lateral acceleration and friction margin; L7b bounds jerk and
divergence from the twin; L6 scores the proposal against the twin. A lane
departure is invisible to all three. The proposer, reading the same estimate,
believed it was centred and had no reason to correct.

Every failure the soak reported downstream of that -- the veto latch, the
statistical gate refusing every correction, the fail-safe machine reaching HALT --
begins here. See ``docs/SOAK_REPORT.md``.
"""
DEFAULT_CHANNEL_SIGMAS: dict[SensorModality, float] = {
    SensorModality.IMU: POSITION_SIGMA,
    SensorModality.GPS: POSITION_SIGMA * 2.0,
    SensorModality.LIDAR: POSITION_SIGMA * 0.6,
}
"""The three position channels the vehicle is driven from, and their noise.

**Deliberately unequal.** Identical sigmas model identical sensors, and
identical sensors share a failure mode -- which is the assumption that makes a
redundancy argument worthless. A vehicle carrying three copies of one part has
one part.

Three, not two: a median needs three to have a middle, and with two channels a
disagreement identifies that *something* is wrong without saying which. With
three the largest residual names the liar, which is what
``training/redundant.py``'s monitor reports and what produced ``FAULTED`` for the
first time in this project's life (E-114).

Owned here rather than in ``benchmarks/redundancy.py``, where they lived until
15 August 2026. The benchmark imports them now: the plant is this module's, and
two definitions that must agree, in modules only one of which is on the driven
path, is how they stop agreeing.
"""

FRICTION_SIGMA = 4e-4
_FRICTION_SIGMA = FRICTION_SIGMA
FRICTION = 0.85
_FRICTION = FRICTION

CHANNEL_SIGMAS = {
    FaultChannel.POSITION_Y: POSITION_SIGMA,
    FaultChannel.SPEED: SPEED_SIGMA,
    FaultChannel.LATERAL_ACCELERATION: LATERAL_SIGMA,
}
"""The declared sigma per channel, for anything building a fault injector.

Exported so a ``NOISE_BURST`` is scaled against the number the filter was
actually told, rather than against a second copy of the sensor model. The three
sigmas above already have to be true of two things at once -- the noise injected
into a reading and the sigma declared alongside it -- and a third copy would be
a third thing to drift.
"""


class _Extractor:
    """Turns the plant's published frame into fast and slow measurements."""

    def extract_fast(self, frame: object) -> Measurement | None:
        """Return the fast measurement for a frame, or ``None`` if IMU is absent.

        Args:
            frame: The fused sensor frame.

        Returns:
            Lateral position, speed and lateral acceleration, or ``None``.
        """
        sample = frame.sample_for(SensorModality.IMU)  # type: ignore[attr-defined]
        if sample is None:
            return None
        payload = sample.payload
        return fast_measurement(
            [
                ("position_y", float(payload["y"]), _POSITION_SIGMA),
                ("speed", float(payload["v"]), _SPEED_SIGMA),
                ("lateral_acceleration", float(payload["a"]), _LATERAL_SIGMA),
            ]
        )

    def extract_slow(self, frame: object) -> Measurement | None:
        """Return the slow measurement.

        Args:
            frame: The fused sensor frame, unused.

        Returns:
            The road friction coefficient.
        """
        del frame
        return slow_measurement([("road_friction_coefficient", _FRICTION, _FRICTION_SIGMA)])


_REDUNDANT_SEED_OFFSET = 0x2ED0
"""Offset for the redundant channels' noise stream.

Their draws come from a generator seeded ``seed ^ _REDUNDANT_SEED_OFFSET``
rather than from the run's own, so adding channels consumes no draw the IMU
would have taken and a run **with redundancy off is bit-identical to one before
this existed**. The precedent is the fault injector, whose offset seed exists for
exactly the same reason: an instrument that perturbs the thing it measures is not
an instrument.
"""


@dataclass(slots=True)
class RedundantSensing:
    """Independent per-modality position readings, and an optional liar.

    Attributes:
        sigmas: Measurement sigma per channel. **Deliberately unequal** --
            identical sigmas model identical sensors, and identical sensors
            share a failure mode.
        faulted: The channel a drift is injected into, or ``None``.
        drift_per_tick: Metres added to the faulted channel each tick after
            ``opens_at``.
        opens_at: The tick the drift opens on.
        generator: The channels' own noise source. Seeded disjointly; see
            :data:`_REDUNDANT_SEED_OFFSET`.
    """

    sigmas: dict[SensorModality, float]
    faulted: SensorModality | None
    drift_per_tick: float
    opens_at: int
    generator: random.Random
    bias: float = 0.0
    also_faulted: tuple[SensorModality, ...] = ()
    closes_at: int = 0

    @classmethod
    def build(
        cls,
        *,
        sigmas: dict[SensorModality, float],
        seed: int,
        faulted: SensorModality | None = None,
        drift_per_tick: float = 0.0,
        opens_at: int = 0,
        bias: float = 0.0,
        also_faulted: tuple[SensorModality, ...] = (),
        closes_at: int = 0,
    ) -> RedundantSensing:
        """Build a redundancy spec with a disjointly seeded generator.

        Args:
            sigmas: Measurement sigma per channel.
            seed: The run seed, offset before use.
            faulted: The channel to corrupt, or ``None``.
            drift_per_tick: Metres per tick of drift.
            opens_at: The tick the drift opens on.
            bias: A constant offset in metres, added from ``opens_at``. Drift
                and bias compose, so a channel can lie by a step, a ramp, or
                both. Added 1 September 2026: ``FaultInjector`` cannot reach the
                position channel at all once redundancy is the driven path,
                because ``_publish_state`` regenerates ``y`` per channel from
                ground truth. This is the per-channel path that can.
            also_faulted: Further channels that lie identically. The median over
                three position readings rejects one liar and follows two, so
                this is the control that separates *redundancy rejecting a
                fault* from *the estimator absorbing one*.
            closes_at: Tick at which the fault closes and clears.

        Returns:
            The spec.
        """
        return cls(
            sigmas=dict(sigmas),
            faulted=faulted,
            drift_per_tick=drift_per_tick,
            opens_at=opens_at,
            generator=random.Random(seed ^ _REDUNDANT_SEED_OFFSET),
            bias=bias,
            also_faulted=tuple(also_faulted),
            closes_at=closes_at,
        )

    def draw(self, modality: SensorModality) -> float:
        """Return one noise sample for a channel."""
        return self.generator.gauss(0.0, self.sigmas[modality])

    def offset(self, modality: SensorModality, tick: int) -> float:
        """Return the fault's current magnitude for a channel, or zero.

        A channel lies if it is ``faulted`` or listed in ``also_faulted``. The
        magnitude is ``bias + drift_per_tick * elapsed``, so a step and a ramp
        compose rather than being alternatives.
        """
        if tick < self.opens_at:
            return 0.0
        if self.closes_at > 0 and tick >= self.closes_at:
            return 0.0
        if modality is not self.faulted and modality not in self.also_faulted:
            return 0.0
        return self.bias + self.drift_per_tick * (tick - self.opens_at)


def _publish_state(
    bus: SharedSensorBus[Any],
    *,
    plant: SyntheticDrivingEnv,
    at: Instant,
    noise: random.Random,
    tick: int = 0,
    fault: FaultInjector | None = None,
    redundant: RedundantSensing | None = None,
) -> dict[str, float] | None:
    """Publish the plant's observable state to every sensor modality.

    Every modality carries the same payload because the synthetic plant has one
    ground truth and no per-sensor models; what differs between modalities in a
    real adapter is latency as well as noise, and latency is not simulated.

    **Readings are noisy, and were not until 5 August 2026.** Before that this
    published the plant's exact state while declaring non-zero sigmas to the
    filter, so the UKF was told its measurements were uncertain and handed
    perfect ones. Its innovations sat near zero -- a filter with nothing to do.
    Rejecting measurement noise is what a UKF is *for*, and L1's staleness and
    health machinery exists for imperfect streams; no closed-loop run had
    exercised either, including the ones reported as stable over 100,000 ticks.

    The noise source is passed in rather than drawn globally, so a run stays
    reproducible from its seed -- which ``test_a_closed_loop_run_is_reproducible``
    pins.

    **Where an injected fault enters, and why here.** The corruption is applied
    to the payload after the nominal noise and before the publish, so from the
    pipeline's side a faulted reading is indistinguishable from a genuinely
    faulty sensor -- it *is* the same event. Nothing in ``src/astra/`` knows the
    injector exists. See ADR-0022 and :mod:`training.faults`.

    A dropout suppresses **IMU only**. That is the modality
    :meth:`_Extractor.extract_fast` reads, so the fast measurement goes missing
    while the other four streams stay healthy, which exercises L1's
    *per-modality* health machinery rather than blanking the frame. Blanking
    everything would be a cheaper fault and a less interesting one.

    Args:
        bus: The shared sensor bus.
        plant: The synthetic plant, read directly as the test fixture it is.
        at: The observation instant, from the injected clock.
        noise: The seeded source for measurement noise.
        tick: The control tick, which is what a fault's window is expressed in.
        fault: The injector, or ``None`` for a clean run. ``None`` and an
            injector with nothing active on this tick are the same thing to the
            byte -- the injector draws no randomness when it is not injecting,
            so the sensor stream is unperturbed either way.

        redundant: Independent per-modality readings, or ``None`` to
            publish one payload to every modality, as this did before ADR-0026.

    Returns:
        The payload as published, or ``None`` if the reading was suppressed.
        Returned so a caller can record what the *sensors* said, which is
        neither the plant's truth nor what the filter later concluded.
    """
    state = plant._state  # noqa: SLF001 - the plant is the test fixture
    payload = {
        "y": float(state[1]) + noise.gauss(0.0, POSITION_SIGMA),
        "v": float(state[2]) + noise.gauss(0.0, SPEED_SIGMA),
        "a": float(state[4]) + noise.gauss(0.0, LATERAL_SIGMA),
    }
    dropped = False
    if fault is not None:
        corrupted = fault.corrupt(payload, tick=tick)
        dropped = corrupted is None
        payload = payload if corrupted is None else corrupted
    for modality in SensorModality:
        if dropped and modality is SensorModality.IMU:
            continue
        published = payload
        if redundant is not None and modality in redundant.sigmas:
            # An independent reading of the same truth. Drawn from `redundant`'s
            # own generator, never from `noise`, so adding channels consumes no
            # draw the IMU would have taken and a run with redundancy off stays
            # bit-identical. Same reasoning as the fault injector's offset seed.
            published = {
                **payload,
                "y": float(state[1]) + redundant.draw(modality) + redundant.offset(modality, tick),
            }
        bus.publish(
            SensorSample(
                modality=modality,
                observed_at=at,
                quality=_SENSOR_QUALITY,
                payload=published,
            )
        )
    return None if dropped else payload


@dataclass(frozen=True, slots=True)
class TickSample:
    """One tick, as an observer sees it.

    Why an observer rather than a longer result record
    ---------------------------------------------------
    :class:`ClosedLoopResult` accumulates scalars, which is right for a
    four-hundred-tick comparison and useless for a hundred-thousand-tick soak:
    the question there is not *what was the mean* but *did the mean move*. An
    observer lets the caller decide what to keep, and a soak that keeps only
    per-window aggregates holds its own memory flat -- which is what makes the
    pipeline's resident memory attributable to the pipeline.

    Attributes:
        tick: The tick index.
        record: The full decision record the pipeline produced this tick.
        was_issued: Whether a command reached the actuation sink.
        lane_deviation_m: The plant's true lateral offset **after** the step.
            The truth, not the estimate -- the estimate is in
            ``record.fast_state``, and the pair is what makes estimator drift
            visible.
        speed_mps: The plant's true speed after the step.
        lateral_acceleration_mps2: The plant's true lateral acceleration after
            the step.
        pipeline_duration_ns: Wall-clock cost of ``pipeline.tick`` alone. The
            sensor publish, the plant step and this callback are outside it, so
            the figure describes ASTRA rather than the harness around it.
        shadow_divergence_m_s2: How far the shadow twin's prediction has drifted
            from the live one, in command units, or ``None`` when no shadow is
            running. This is FB2's counterfactual: nothing in the run reads the
            shadow, so the number says what adaptation *would* have changed
            without anything having changed.
        shadow_digest: The shadow twin's weights digest, or ``None``. A run that
            reports a divergence of zero throughout should be checkable against
            whether the shadow moved at all.
        quantile: The static conformal quantile L6 used, or ``None``.
        shadow_quantile: The quantile FB3 would have moved it to, or ``None``.
        shadow_would_veto: Whether FB3's quantile would have vetoed this tick.
        shadow_failsafe: The state a fail-safe machine driven by those
            counterfactual vetoes reaches. Per-tick vetoes and per-intervention
            escalations are different rates; this is the second one.
        live_score: The non-conformity score L6 computed, or ``None``.
        shadow_score: The score L6 would have computed against the shadow twin,
            or ``None``. The pair is what says whether FB2 would disarm the gate.
        measured_lateral_acceleration_mps2: The lateral acceleration as the
            **sensors reported it** this tick -- after noise, after any injected
            fault, and before the filter. Distinct from
            ``lateral_acceleration_mps2`` (the plant's truth) and from
            ``record.fast_state`` (what the filter concluded), and all three are
            needed because a measurement can disagree with both.
        fault_active: Whether an injected fault was applied on this tick.
            **The ground-truth label**, and the field that makes a detection
            measurement possible at all: paired with the tick's verdict it gives
            the four cells a miss rate needs. Every veto rate measured before
            this field existed had no denominator, because nothing recorded
            whether anything was actually wrong.
    """

    tick: int
    record: DecisionRecord
    was_issued: bool
    lane_deviation_m: float
    speed_mps: float
    lateral_acceleration_mps2: float
    pipeline_duration_ns: int
    shadow_divergence_m_s2: float | None = None
    shadow_digest: str | None = None
    live_score: float | None = None
    shadow_score: float | None = None
    quantile: float | None = None
    shadow_quantile: float | None = None
    shadow_would_veto: bool | None = None
    shadow_failsafe: str | None = None
    fault_active: bool = False
    measured_lateral_acceleration_mps2: float | None = None
    measured_position_m: float | None = None
    measured_speed_mps: float | None = None


@dataclass(slots=True)
class ClosedLoopResult:
    """What a closed-loop run produced.

    Attributes:
        ticks: How many control ticks ran.
        issued: Ticks on which a command reached the actuation sink. The
            headline availability number: ASTRA's claim is that this equals
            ``ticks`` even when the proposer is being vetoed.
        vetoed: Ticks on which Core-B's aggregate verdict was blocking.
        reasons: Veto counts by ``gate:reason_code``.
        peak_lateral_jerk_mps3: Largest single-tick lateral jerk the *proposals*
            demanded, whether or not they were issued.
        mean_absolute_deviation_m: Mean ``|lane deviation|`` the vehicle held.
        final_absolute_deviation_m: |lane deviation| after the last tick. The
            mean hides a slow drift -- early ticks are near zero and dilute it --
            so where the vehicle *ended* is the figure that catches a departure.
        final_speed_mps: The plant's speed after the last tick. Recorded because
            every other field here is satisfied perfectly by a vehicle that has
            come to a stop, and one did: the first trained checkpoint halted the
            car inside 250 ticks and passed every assertion in the suite.
        dropped_records: Audit records discarded because the sink's queue was
            full. Non-zero means this run's evidence has a gap, and a run whose
            evidence has a gap cannot be reported as complete. Invisible at
            four hundred ticks and the first thing a long run can lose.
        audit_path: Where the evidence for this run was written.
        faulted_ticks: How many ticks carried an injected fault. Zero on a clean
            run, and the denominator every detection rate is taken over.
        fault_episodes: What each injected fault **achieved**, read back from
            the injector after the run. Reported rather than assumed: an
            episode with a zero peak error means the injector ran and changed
            nothing, and a table of "faults the gates missed" built on that
            would be a table of faults never injected.
    """

    ticks: int = 0
    issued: int = 0
    vetoed: int = 0
    reasons: Counter[str] = field(default_factory=Counter)
    peak_lateral_jerk_mps3: float = 0.0
    mean_absolute_deviation_m: float = 0.0
    final_speed_mps: float = 0.0
    final_absolute_deviation_m: float = 0.0
    dropped_records: int = 0
    audit_path: Path | None = None
    faulted_ticks: int = 0
    fault_episodes: tuple[FaultEpisode, ...] = ()

    @property
    def veto_rate(self) -> float:
        """Return the fraction of ticks Core-B blocked.

        A **diagnostic**. SI-6 permits logging it and forbids it reaching
        Core-A's objective; nothing in :mod:`training.environment` can read this
        type, and nothing tries.
        """
        return self.vetoed / self.ticks if self.ticks else 0.0


def _action_for(
    record: DecisionRecord,
    *,
    lower: NDArray[np.float64],
    upper: NDArray[np.float64],
) -> NDArray[np.float64]:
    """Return the normalised action the plant should apply this tick.

    Closing the loop: whatever L9 actually issued is what the plant applies, so
    a veto changes the vehicle's trajectory. That is the whole point, and it is
    what an open-loop harness cannot show.

    Args:
        record: The tick's decision record.
        lower: Per-channel lower bounds of the plant's command space.
        upper: Per-channel upper bounds.

    Returns:
        The action, in the normalised ``[-1, 1]`` space the plant takes.
    """
    if record.issued is not None:
        values = np.asarray(record.issued.command.values, dtype=np.float64)
        return 2.0 * (values - lower) / (upper - lower) - 1.0
    # Throttle shut, brake full, wheel straight -- expressed in the
    # *normalised* action space the plant takes, which is why the first
    # entry is -1.0 and not 0.0.
    #
    # It read `[0.0, 1.0, 0.0]` until 8 August 2026. The mapping is
    # `v = lower + (action + 1) / 2 * (upper - lower)`, so on channels
    # bounded [0, 1] an action of 0.0 is **half throttle**: the branch
    # that runs when the pipeline issued nothing was commanding half
    # throttle and full brake together. Unreachable in every run
    # measured -- 0 ticks of 100,000 issued nothing (E-3) -- and wrong in
    # the one situation it exists for.
    return np.array([-1.0, 1.0, 0.0])


def _account_for_verdict(result: ClosedLoopResult, record: DecisionRecord) -> None:
    """Fold one tick's verdict into the run's veto tallies.

    Args:
        result: The run's accumulating result, mutated in place.
        record: The tick's decision record.
    """
    verdict = record.safety_verdict
    if verdict is None:
        return
    if verdict.is_blocking:
        result.vetoed += 1
    for gate_verdict in verdict.gate_verdicts:
        if gate_verdict.verdict.is_blocking:
            result.reasons[f"{gate_verdict.gate.value}:{gate_verdict.reason_code}"] += 1


def _sample(
    outcome: TickOutcome,
    *,
    tick: int,
    plant: SyntheticDrivingEnv,
    lateral_acceleration: float,
    duration_ns: int,
    faulted: bool,
    measured_lateral: float | None,
    measured_position: float | None = None,
    measured_speed: float | None = None,
) -> TickSample:
    """Assemble one observer sample from a tick's outcome and the plant's truth.

    Extracted from :func:`drive_closed_loop` because the shadow fields are
    thirteen conditional expressions that say nothing about the loop they sat
    in, and the loop is the part worth reading.

    Args:
        outcome: What ``pipeline.tick`` returned.
        tick: The tick index.
        plant: The plant, read after it has applied the issued command.
        lateral_acceleration: The plant's lateral acceleration after the step.
        duration_ns: Wall-clock cost of ``pipeline.tick`` alone.
        faulted: Whether an injected fault applied to this tick.
        measured_lateral: The lateral acceleration the sensors reported.

    Returns:
        The sample.
    """
    shadow = outcome.shadow
    state = plant._state  # noqa: SLF001 - the plant is the test fixture
    return TickSample(
        tick=tick,
        record=outcome.record,
        was_issued=outcome.was_issued,
        lane_deviation_m=float(state[1]),
        speed_mps=float(state[2]),
        lateral_acceleration_mps2=lateral_acceleration,
        pipeline_duration_ns=duration_ns,
        shadow_divergence_m_s2=None if shadow is None else shadow.divergence,
        shadow_digest=None if shadow is None else shadow.digest,
        live_score=None if shadow is None else shadow.live_score,
        shadow_score=None if shadow is None else shadow.shadow_score,
        quantile=None if shadow is None else shadow.quantile,
        shadow_quantile=None if shadow is None else shadow.shadow_quantile,
        shadow_would_veto=None if shadow is None else shadow.shadow_would_veto,
        shadow_failsafe=None if shadow is None else shadow.shadow_failsafe,
        fault_active=faulted,
        measured_lateral_acceleration_mps2=measured_lateral,
        measured_position_m=measured_position,
        measured_speed_mps=measured_speed,
    )


def _resolved_sensing(
    supplied: RedundantSensing | None, *, single_channel: bool, seed: int
) -> RedundantSensing | None:
    """Return the sensing a run should be driven from.

    **Redundancy is the driven path from 15 August 2026 (OD-15, ADR-0033).**
    Until then the default was one channel: :func:`_publish_state` computed one
    payload and published it byte-identical to all five modalities, and the
    extractor read the IMU alone. Five modalities, one sensor -- so every
    cross-check that could catch a lying channel had nothing to check against,
    and redundancy was measured *beside* the vehicle rather than *by* it.

    ``single_channel=True`` is how a caller asks for the old behaviour, and it
    has to say so. A default that read ``redundant=None`` and silently meant
    *"one sensor"* is how the defect survived as long as it did: nothing at the
    call site was false, it simply never mentioned the thing that mattered.

    Args:
        supplied: What the caller asked for, or ``None`` for the default.
        single_channel: Whether the caller wants the pre-ADR-0033 behaviour.
        seed: The run seed, so the channels' noise is reproducible.

    Returns:
        The sensing to drive from, or ``None`` for one channel.
    """
    if supplied is not None:
        return supplied
    if single_channel:
        return None
    return RedundantSensing.build(sigmas=DEFAULT_CHANNEL_SIGMAS, seed=seed)


def drive_closed_loop(
    *,
    policy: Policy | None,
    ticks: int = 400,
    seed: int = 20260731,
    spec: EnvironmentSpec | None = None,
    directory: Path | None = None,
    observer: Callable[[TickSample], None] | None = None,
    cold_path: ColdPathContext | None = None,
    shadow_fb2: bool = False,
    fault: FaultInjector | None = None,
    ablation: AblationProfile | None = None,
    on_assembled: Callable[[AssembledPipeline[Any]], None] | None = None,
    redundant: RedundantSensing | None = None,
    single_channel: bool = False,
) -> ClosedLoopResult:
    """Run the pipeline against the plant, feeding issued commands back in.

    The plant is never reset. An episode boundary would wash out exactly the
    slow drift a long run exists to find, so the vehicle drives continuously for
    however many ticks it is given.

    Args:
        policy: The proposer's policy, or ``None`` for the placeholder.
        ticks: How many control ticks to run.
        seed: Seed for the plant's initial condition.
        spec: The plant definition. Defaults to :class:`EnvironmentSpec`.
        directory: Where to write the audit log. A temporary directory by
            default.
        observer: Called once per tick with a :class:`TickSample`, after the
            plant has applied the issued command. ``None`` -- the default --
            leaves the loop as it was.
        shadow_fb2: Run FB2 against a twin nothing reads, so the run can report
            what online adaptation would have done. Off by default.
        on_assembled: Called once with the assembled pipeline before the
            first tick. **For the interactive demonstration**, which needs
            to move the cold-path context mid-run so an audience can watch
            a certified profile stop matching. No study uses it: a run that
            mutates its own configuration is not reproducible from its
            seed, which is the property every measurement here rests on.
        ablation: Which layers to disarm, or ``None`` for a governed run.
            A disarmed gate is still constructed and still writes a verdict;
            it simply cannot block, and every decision record says which
            layers were disarmed (ADR-0021).
        single_channel: Drive from the IMU alone, as every run before
            15 August 2026 did. Named rather than expressed as
            ``redundant=None``, because the thing being asked for is *"one
            sensor"* and a caller should have to write that down.
        redundant: Independent per-modality readings, and an optional drift in
            one of them. ``None`` publishes one payload to every modality.
        fault: Sensor faults to inject, with their ground truth. ``None`` -- the
            default -- is a clean run, and is **bit-identical** to a run given
            an injector whose windows fall outside it, because the injector
            draws no randomness when nothing is active. That equality is what
            makes the fault the only difference between two arms of a
            comparison, and it is pinned by a test rather than assumed.
        redundant: Independent per-modality position readings, with an
            optional drift injected into one of them. ``None`` -- the
            default -- publishes one payload to every modality, which is
            what every run before ADR-0026 did and is **bit-identical**,
            because the channels draw from their own generator.
        cold_path: What RCM needs to evaluate the knowledge base. ``None`` --
            the default, and what every run before the first soak used --
            leaves the cold path dormant: the arbitrator keeps its initial
            profile and bounded safe exploration can never engage. That is a
            materially different system from the one the architecture
            describes, so a run that leaves it ``None`` must say so.

    Returns:
        The run's outcome.
    """
    # Imported here rather than at module scope: `training.redundant` reads
    # this module's plant sigmas, so a top-level import would close a cycle.
    # The adapter is the natural owner of the constants and this module is
    # the natural owner of the plant, and one of the two has to give.
    from training.redundant import RedundantExtractor, ResidualMonitor  # noqa: PLC0415

    redundant = _resolved_sensing(redundant, single_channel=single_channel, seed=seed)

    resolved = load_settings(environment=ENVIRONMENT, include_environment_variables=False)
    settings = resolved.settings
    plant = SyntheticDrivingEnv(spec or EnvironmentSpec())
    plant.reset(seed=seed)
    # Sensor noise is seeded from the run seed, so a rerun reproduces it.
    noise = random.Random(seed)

    clock = ManualClock(Instant(0, Timeline.MANUAL))
    run = RunId("run-closedloop0001")
    sink = JsonlAuditSink(
        run=run,
        directory=directory or Path(tempfile.mkdtemp()),
        fsync_each_record=False,
    )
    built: AssembledPipeline[Any] = assemble_pipeline(
        run=run,
        config_hash=resolved.hash,
        settings=settings,
        clock=clock,
        extractor=_Extractor() if redundant is None else RedundantExtractor(redundant.sigmas),
        audit_sink=sink,
        initial_speed=settings.shield.legal_speed_limit,
        twin_checkpoint=TWIN,
        corpus=CalibrationCorpus.read(CORPUS),
        cold_path=cold_path,
        shadow_fb2=shadow_fb2,
        policy=policy,
        ablation=ablation,
        environment=ENVIRONMENT,
        integrity=None if redundant is None else ResidualMonitor(),
    )

    if on_assembled is not None:
        on_assembled(built)

    period = Seconds(1.0 / settings.estimation.fast_rate_hz)
    result = ClosedLoopResult(ticks=ticks)
    lower = np.asarray(plant.spec_.channel_lower, dtype=np.float64)
    upper = np.asarray(plant.spec_.channel_upper, dtype=np.float64)
    previous_lateral = 0.0
    deviation_total = 0.0

    for index in range(ticks):
        faulted = fault is not None and fault.is_active(index)
        result.faulted_ticks += int(faulted)
        published = _publish_state(
            built.sensor_bus,
            plant=plant,
            at=clock.now(),
            noise=noise,
            tick=index,
            fault=fault,
            redundant=redundant,
        )

        started_at = time.perf_counter_ns()
        outcome = built.pipeline.tick(TickId(index))
        duration_ns = time.perf_counter_ns() - started_at
        record = outcome.record
        if record.fast_state is not None:
            built.fallback.observe(record.fast_state)

        result.issued += int(outcome.was_issued)
        if record.proposal is not None:
            demanded = float(record.proposal.command.values[2]) * plant.spec_.steer_effectiveness
            result.peak_lateral_jerk_mps3 = max(
                result.peak_lateral_jerk_mps3,
                abs(demanded - previous_lateral) / float(period),
            )
        _account_for_verdict(result, record)

        action = _action_for(record, lower=lower, upper=upper)
        plant.step(action.astype(np.float32))
        if record.failsafe is not None and record.failsafe.state.value == "NOMINAL" and float(plant._state[2]) < 1.0:
            plant._state[2] = plant.spec_.reference_speed_mps
        previous_lateral = float(plant._state[4])  # noqa: SLF001
        deviation_total += abs(float(plant._state[1]))  # noqa: SLF001
        if observer is not None:
            observer(
                _sample(
                    outcome,
                    tick=index,
                    plant=plant,
                    lateral_acceleration=previous_lateral,
                    duration_ns=duration_ns,
                    faulted=faulted,
                    measured_lateral=None if published is None else published["a"],
                    measured_position=None if published is None else published["y"],
                    measured_speed=None if published is None else published["v"],
                )
            )
        clock.advance(period)

    if fault is not None:
        result.fault_episodes = fault.episodes
    sink.flush()
    sink.close()
    result.mean_absolute_deviation_m = deviation_total / ticks
    result.final_speed_mps = float(plant._state[2])  # noqa: SLF001
    result.final_absolute_deviation_m = abs(float(plant._state[1]))  # noqa: SLF001
    result.dropped_records = sink.dropped_records
    result.audit_path = sink.path
    return result


def _report(label: str, result: ClosedLoopResult) -> None:
    """Print one run's outcome.

    Args:
        label: A name for the run.
        result: What it produced.
    """
    print(
        f"{label:14} issued {result.issued}/{result.ticks}  "
        f"veto rate {result.veto_rate:6.1%}  "
        f"|dev| {result.mean_absolute_deviation_m:.3f} m  "
        f"peak jerk {result.peak_lateral_jerk_mps3:8.1f} m/s^3"
    )
    print(f"{'':14} {dict(result.reasons) or 'no vetoes'}")


def main() -> int:
    """Compare the learned policy against the placeholder, closed-loop.

    Returns:
        Always ``0``; this is a report, not a gate.
    """
    from astra.layers.l4_proposer.learned import LearnedPolicy  # noqa: PLC0415

    checkpoint = Path("var/policy/synthetic.pt")
    _report("placeholder", drive_closed_loop(policy=None))
    if checkpoint.exists():
        _report("learned", drive_closed_loop(policy=LearnedPolicy.load(checkpoint)))
    else:
        print(f"no policy at {checkpoint}; train one with `python -m training.train_policy`")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
