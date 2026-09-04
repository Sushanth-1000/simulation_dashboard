"""The pipeline, live, with a button that breaks a sensor.

P4.1 and P4.2 in one server
-----------------------------
P4.1 asks for the pipeline rendered as itself: the Trust Index, the three gates
lit separately, the fail-safe state machine, and an event ticker. P4.2 asks that
an audience be able to **press the button** -- *"a demo where the observer
chooses the fault cannot be staged."* They are the same program, because the
second is only convincing while the first is running.

The rule P4.1 states, and how it is made structural
-----------------------------------------------------
*"Every number on screen must trace to a live ``DecisionRecord``. Nothing
scripted, nothing interpolated."*

A promise like that decays. So :class:`Frame` is a **pure projection**: it is
built from a :class:`~training.closed_loop.TickSample` and nothing else, it
computes no value the pipeline did not, and
``tests/unit/test_dashboard_frame.py`` asserts field by field that each one
equals its source. There is no code path in this module that can put a number on
screen that the pipeline did not produce.

The one deliberate exception, and why it is the point
------------------------------------------------------
Two fields -- :attr:`Frame.truth_y` and :attr:`Frame.truth_speed` -- come from
the **simulator**, not the record. They are what the vehicle is actually doing,
which no deployed system knows.

They are on screen because **OD-9 is invisible without them.** The finding is
that a sensor fault drives the estimate and the truth apart while every gate
stays green: the vehicle goes 4.199 m off a 1.75 m lane and the corridor bound
reads 0.023 m (E-46, E-48). A dashboard showing only what the system knows would
render that as a completely nominal run, which is exactly the problem being
demonstrated.

So they are carried in a separate group, labelled *ground truth (simulator
only)* on the page, and :attr:`Frame.from_record` names which is which. Mixing
them would turn the most honest thing this demo has into its most misleading.

What to demonstrate, and what not to
--------------------------------------
The honest demonstration is **not** "watch the gates catch it". As of 10 August
they do not: `imu_dropout` and `position_drift` both put the vehicle outside its
corridor with a verdict trace identical to the clean run's. The demonstration is
that divergence, live, with the gate panel staying green throughout -- and then
the same run with the fault closed.

Do not wait for OD-9 to be fixed before showing this. A demo of a system whose
weakness you can name is worth more than a demo of one whose weakness you have
not looked for.

Why there is no web framework here
------------------------------------
Server-Sent Events over :mod:`http.server`, and a single static page with no
build step. ``PENDING.md`` specified FastAPI, WebSockets, React and Recharts;
this uses none of them and adds **no dependency at all**.

That is not laziness, it is the same argument P4.3 just made in anger. FilterPy
was removed because an unmaintained dependency inside a safety repository is a
qualification argument nobody wants to write, and it dragged scipy, matplotlib
and pillow behind it. Adding a Node toolchain and a ``node_modules`` tree to that
repository -- for a *demo* -- would contradict the discipline that makes the rest
of it credible. Telemetry is one-way, which is precisely what SSE is for, and
the fault button is a POST.

The fallback run, which P4.2 asks for by name
-----------------------------------------------
*"Capture a pre-recorded fallback run before any live demonstration."*

``--record`` writes every frame to JSONL while driving; ``--replay`` streams a
recording back at the same rate, with the fault buttons disabled because the
faults already happened. The page cannot tell the difference and neither can an
audience, which is the point: a laptop that will not cooperate in the room
should cost a demonstration its interactivity, not its evidence.

A recording is exactly the frames the live run produced -- the same projection,
so a replay is as traceable to `DecisionRecord`s as the run that made it.

Run it with::

    uv run python -m demo.dashboard
    uv run python -m demo.dashboard --port 8080 --ticks 4000
    uv run python -m demo.dashboard --ticks 3000 --record var/demo/fallback.jsonl
    uv run python -m demo.dashboard --replay var/demo/fallback.jsonl

Then open http://127.0.0.1:8000/.
"""

from __future__ import annotations

import argparse
import json
import queue
import sys
import threading
import time
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, override

from astra.config.loader import load_settings
from astra.kernel.enums import SensorModality
from astra.kernel.units import Probability
from astra.layers.l4_proposer.learned import LearnedPolicy
from astra.runtime.pipeline import ColdPathContext
from training.closed_loop import (
    DEFAULT_CHANNEL_SIGMAS,
    RedundantSensing,
    CHANNEL_SIGMAS,
    CORPUS,
    ENVIRONMENT,
    TWIN,
    TickSample,
    drive_closed_loop,
)
from training.faults import (
    FaultChannel,
    FaultInjector,
    bias,
    drift,
    dropout,
    noise_burst,
    stuck_at,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from training.faults import FaultSpec

__all__ = ["Frame", "FrameStream", "build_injector", "main", "serve"]

_STATIC = Path(__file__).parent / "static"
_DEFAULT_TICKS = 100_000
_DEFAULT_SEED = 20260810
_DEFAULT_POLICY = Path("var/policy/synthetic.pt")
_QUEUE_LIMIT = 2_000
"""Bound on the outgoing frame queue.

The drive must never block on a browser. If a client cannot keep up its frames
are dropped and the counter says so -- the same discipline the audit sink uses,
and for the same reason: a demonstration that stalls the thing it demonstrates
is measuring the demonstration.
"""

TICK_PERIOD_S = 0.05
"""The control period, 20 Hz -- and the rate the demonstration runs at.

The harness drives as fast as the machine allows, which is about 110 ticks a
second: five and a half times real time. That is right for a study and wrong
for a demonstration. A 400-tick fault window is twenty seconds on the vehicle
and under four on an unpaced screen, so an audience watching for the divergence
sees it arrive and leave before they have found it.

Pacing lives here, in the dashboard's own publish path, and **not** in
``drive_closed_loop``: every benchmark depends on the harness running flat out,
and a sleep in the shared loop would make the soak take a day.
"""

ARBITRATION_PERIOD_TICKS = 20
"""One cold-path evaluation a second.

The cold path is not per-tick work -- the context a vehicle is in changes on a
timescale of seconds -- but a demonstration wants it visibly responsive, so this
is at the fast end of defensible rather than the cheap end.
"""

CERTIFIED = (0.85, 0.7, 0.7)
"""``(visibility, traffic dynamicity, road complexity)`` of a context the base covers.

Tuned against `URBAN_CLEAR`'s centroid **and against the speed the vehicle
actually holds**, which is the part that is easy to get wrong. The signature's
second component is ego speed normalised by the legal limit; this policy cruises
at about 12.5 m/s of a 33.3 m/s limit, so 0.375 -- which is URBAN_CLEAR's 0.35
and nowhere near HIGHWAY_CLEAR's 0.8.

Picking clear-highway-looking numbers instead put the run in permanent
exploration, because three components matched and the fourth did not. A tunnel
scene is worthless without a contrast, so the contrast is measured rather than
assumed: on these values RCM reaches **SHADOW_EXECUTION** with a trust score of
0.717 against a threshold of 0.70.
"""

TUNNEL = (0.05, 0.7, 0.95)
"""``(visibility, traffic dynamicity, road complexity)`` of a tunnel, which **no profile covers**.
"""

FOG = (0.2, 0.95, 0.85)
"""``(visibility, traffic dynamicity, road complexity)`` of heavy fog and dense traffic.
"""

FAULT_WINDOW_TICKS = 60
"""How long an armed fault lasts. Three seconds at 20 Hz.
"""


@dataclass(frozen=True, slots=True)
class Frame:
    """One tick, as the dashboard renders it.

    Every field except the two named under *ground truth* is copied from the
    tick's :class:`~astra.contracts.audit.DecisionRecord`. Nothing here is
    derived, smoothed or interpolated.

    Attributes:
        tick: The control tick.
        trust_index: L3's Trust Index, or ``None`` if L3 did not run.
        context: The Mondrian class L3 assigned.
        gates: ``(gate, verdict, reason_code)`` per gate that reported, in the
            order Core-B evaluated them. The three-gate panel is lit from this
            and from nothing else.
        blocking: Whether Core-B's combined verdict blocked.
        failsafe_state: L8's state.
        ood_counter: L8's out-of-distribution counter.
        speed_cap: The cap L8 is imposing, in m/s, or ``None`` when it is
            imposing none. Never zero for absent -- a zero cap is a
            commanded stop and would be read as one.
        origin: How the issued command was labelled -- ``PROPOSED``,
            ``RATE_LIMITED``, ``SPEED_CAPPED``, or absent if none was issued.
        issued: The command that reached the actuation sink.
        quantile: The conformal quantile L6 thresholded against.
        innovation: The fast innovation's Mahalanobis distance. **Not actually
            a Mahalanobis distance** -- see OD-10 -- and labelled on the page
            with that caveat rather than without it.
        arbitration: RCM's outcome -- ``CONTINUE``, ``SHADOW_EXECUTION``,
            ``SWITCH_COMMITTED``, ``ROLLBACK`` or ``SAFE_EXPLORATION`` -- or
            ``None`` before the first cold-path evaluation.
        active_profile: The calibration profile currently in force.
        candidate_profile: The profile being shadow-executed, if any.
        arbitration_trust: RCM's score for the active profile against the
            current context signature.
        divergence_index: The Calibration Divergence Index during shadow
            execution.
        exploring: Whether bounded safe exploration is engaged. **The
            architectural differentiator**: an unrecognised context narrows
            the envelope instead of stopping the vehicle.
        ablation: Which layers were disarmed. ``"NONE"`` for a governed run.
        health: Per-modality stream health.
        estimate_y: Where the *system believes* it is, laterally.
        truth_y: **Ground truth, simulator only.** Where the vehicle actually
            is. No deployed system has this, and it is on screen because OD-9
            is invisible without it.
        truth_speed: **Ground truth, simulator only.**
        fault_active: Whether an injected fault applied to this tick.
    """

    tick: int
    trust_index: float | None
    context: str | None
    gates: tuple[tuple[str, str, str], ...]
    blocking: bool
    failsafe_state: str | None
    ood_counter: int | None
    speed_cap: float | None
    origin: str | None
    issued: tuple[float, ...] | None
    quantile: float | None
    innovation: float | None
    arbitration: str | None
    active_profile: str | None
    candidate_profile: str | None
    arbitration_trust: float | None
    divergence_index: float | None
    exploring: bool
    ablation: str
    health: tuple[tuple[str, str], ...]
    estimate_y: float | None
    truth_y: float
    truth_speed: float
    fault_active: bool

    @classmethod
    def from_sample(cls, sample: TickSample) -> Frame:
        """Project one tick into a frame.

        Args:
            sample: The tick, as the closed-loop harness observed it.

        Returns:
            The frame. Every field traces to ``sample.record`` except the two
            documented as ground truth.
        """
        record = sample.record
        arbitration = record.arbitration
        verdict = record.safety_verdict
        failsafe = record.failsafe
        issued = record.issued
        return cls(
            tick=sample.tick,
            trust_index=None if record.trust is None else float(record.trust.trust_index),
            context=None if record.trust is None else record.trust.context_class.value,
            gates=(
                ()
                if verdict is None
                else tuple(
                    (gate.gate.value, gate.verdict.value, gate.reason_code)
                    for gate in verdict.gate_verdicts
                )
            ),
            blocking=bool(verdict is not None and verdict.is_blocking),
            failsafe_state=None if failsafe is None else failsafe.state.value,
            ood_counter=None if failsafe is None else failsafe.ood_counter,
            # `None` when no cap is imposed, which is the NOMINAL case. It must
            # not become 0.0: a zero speed cap renders as a commanded stop, so
            # substituting one would put the most alarming reading this panel
            # has onto every healthy tick.
            speed_cap=(
                None
                if failsafe is None or failsafe.speed_cap is None
                else float(failsafe.speed_cap)
            ),
            origin=None if issued is None else issued.origin.value,
            issued=(None if issued is None else tuple(float(v) for v in issued.command.values)),
            quantile=(
                None if record.trust is None else float(record.trust.class_conditional_quantile)
            ),
            innovation=record.fast_innovation,
            arbitration=None if arbitration is None else arbitration.outcome.value,
            active_profile=(None if arbitration is None else str(arbitration.active_profile)),
            candidate_profile=(
                None
                if arbitration is None or arbitration.candidate_profile is None
                else str(arbitration.candidate_profile)
            ),
            arbitration_trust=None if arbitration is None else arbitration.trust_score,
            divergence_index=(
                None
                if arbitration is None or arbitration.calibration_divergence_index is None
                else float(arbitration.calibration_divergence_index)
            ),
            exploring=bool(
                arbitration is not None and arbitration.outcome.value == "SAFE_EXPLORATION"
            ),
            ablation=record.ablation,
            health=tuple(
                (modality.value, health.value) for modality, health in record.frame_health
            ),
            estimate_y=(None if record.fast_state is None else float(record.fast_state.position_y)),
            truth_y=sample.lane_deviation_m,
            truth_speed=sample.speed_mps,
            fault_active=sample.fault_active,
        )

    @staticmethod
    def from_record() -> tuple[str, ...]:
        """Return the fields that come from the decision record.

        Exists so the separation is machine-checkable rather than a comment.
        Anything not listed here and not in :meth:`from_simulator` is a field
        somebody added without deciding which it is.

        Returns:
            The field names sourced from the pipeline's own evidence.
        """
        return (
            "tick",
            "trust_index",
            "context",
            "gates",
            "blocking",
            "failsafe_state",
            "ood_counter",
            "speed_cap",
            "origin",
            "issued",
            "quantile",
            "innovation",
            "arbitration",
            "active_profile",
            "candidate_profile",
            "arbitration_trust",
            "divergence_index",
            "exploring",
            "ablation",
            "health",
            "estimate_y",
        )

    @staticmethod
    def from_simulator() -> tuple[str, ...]:
        """Return the fields the pipeline does not know.

        Returns:
            The ground-truth field names, plus the injector's own label.
        """
        return ("truth_y", "truth_speed", "fault_active")


#: Faults that reach the estimator through the redundant sensing path rather
#: than through ``FaultInjector``. This split is not cosmetic. ``FaultInjector``
#: corrupts the shared payload *before* ``_publish_state`` regenerates the
#: position channel per modality from ``plant._state[1]``, so a POSITION_Y fault
#: armed on the injector is overwritten with ground truth and reaches nothing.
#: That defect made POSITION_Y inert for seventeen days before an audit caught
#: it (E17-Position, Control C). The fix is to inject where the regeneration
#: happens: ``RedundantSensing.offset``.
POSITION_FAULTS: frozenset[str] = frozenset({"position_bias", "position_drift"})

#: Magnitudes matching ``benchmarks.e18_evaluate.SEVERITIES`` at the ``medium``
#: level, so what the audience sees is comparable with the recorded experiments.
POSITION_MAGNITUDE: dict[str, float] = {"position_bias": 1.0, "position_drift": 2.0}


def build_injector(kind: str, *, tick: int, seed: int) -> FaultSpec:
    """Return the fault an audience just asked for.

    Only for faults that travel through :class:`FaultInjector`. The two position
    faults are armed on the sensing path instead -- see :data:`POSITION_FAULTS`
    and :meth:`FrameStream.arm`.

    Args:
        kind: One of ``dropout``, ``speed_stuck``, ``speed_bias`` or
            ``lateral_noise``.
        tick: The tick it should open on -- normally the current one, so the
            audience sees it start.
        seed: Unused; present so the signature does not change if a future
            fault needs randomness at construction.

    Returns:
        The specification.

    Raises:
        ValueError: If the kind is not one the demo offers.
    """
    del seed
    last = tick + FAULT_WINDOW_TICKS
    match kind:
        case "dropout":
            return dropout(first_tick=tick, last_tick=last)
        case "speed_stuck":
            return stuck_at(FaultChannel.SPEED, first_tick=tick, last_tick=last)
        case "speed_bias":
            return bias(FaultChannel.SPEED, first_tick=tick, last_tick=last, offset=3.0)
        case "lateral_noise":
            return noise_burst(
                FaultChannel.LATERAL_ACCELERATION,
                first_tick=tick,
                last_tick=last,
                sigma_multiplier=25.0,
            )
        case _:
            message = f"{kind!r} is not a fault this demonstration offers"
            raise ValueError(message)


def cold_path(where: tuple[float, float, float]) -> ColdPathContext:
    """Return the cold-path context for a place.

    Args:
        where: ``(visibility, traffic dynamicity, road complexity)`` --
            :data:`CERTIFIED` or :data:`TUNNEL`.

    Returns:
        The context RCM evaluates the knowledge base against.
    """
    settings = load_settings(environment=ENVIRONMENT, include_environment_variables=False).settings
    return ColdPathContext(
        period_ticks=ARBITRATION_PERIOD_TICKS,
        trust_threshold=settings.arbitration.trust_threshold_tau,
        divergence_limit=settings.arbitration.divergence_limit_delta,
        platform="synthetic-prototype",
        legal_speed_limit=settings.shield.legal_speed_limit,
        visibility=Probability(where[0]),
        traffic_dynamicity=Probability(where[1]),
        road_complexity=Probability(where[2]),
    )


#: The guided demonstration. Each beat pauses the run so the presenter can
#: talk over a still frame, then ``next`` performs the beat's action and lets it
#: run for ``hold`` ticks before pausing again.
#:
#: The order is deliberate. A panel has to see the monitor work before the
#: failure means anything: a monitor that never fires is not evidence of a blind
#: spot, it is evidence of a broken monitor. Beat 3 establishes it fires. Beat 5
#: then shows the same machinery silent while a sensor is failing.
STORY: tuple[dict[str, object], ...] = (
    {
        "title": "A vehicle, driving",
        "body": "The car is following a lane. Nothing is wrong. Every 50 ms the "
                "nine layers on the right run once: the sensors are read, the "
                "state is estimated, the learned controller proposes a steering "
                "and acceleration, and the safety layers decide whether to allow "
                "it. Watch the pipeline light up green, top to bottom.",
        "action": None,
        "hold": 60,
    },
    {
        "title": "The proposal is not the command",
        "body": "L4 is the learned controller -- the part nobody can formally "
                "verify. It only ever *proposes*. Its proposal crosses a one-way "
                "boundary into the safety domain, where L6 and L7 can veto it and "
                "L9 decides what is actually sent to the actuator. The learned "
                "controller never drives the car directly. That separation is the "
                "architecture.",
        "action": None,
        "hold": 60,
    },
    {
        "title": "Now we break a sensor -- and the monitor catches it",
        "body": "We inject a 1 metre position bias. Two of the three position "
                "channels start lying, so the median the estimator fuses follows "
                "them. Watch the non-conformity score climb past the threshold and "
                "L6 turn red. This is the system working: evidence of the fault "
                "reaches the monitor, and the monitor fires.",
        "action": {"fault": "position_bias"},
        "hold": 140,
    },
    {
        "title": "Clean slate",
        "body": "Fault cleared. The score falls back under the threshold and the "
                "pipeline returns to green. Everything you are about to see uses "
                "the same monitor, the same threshold and the same vehicle.",
        "action": {"clear": True},
        "hold": 80,
    },
    {
        "title": "The blind spot -- the IMU fails and the monitor stays quiet",
        "body": "Now we drop the IMU out entirely and leave it broken. The sensor "
                "is genuinely failing: L1 shows the channel degraded and L2's "
                "innovation moves, so the evidence is there. But watch L6 -- it "
                "keeps saying PASS. No veto, no fallback. The monitor is quieter "
                "than it is on a healthy car, while a sensor is failing.",
        "action": {"fault": "dropout"},
        "hold": 200,
    },
    {
        "title": "It alarms only after the danger has passed",
        "body": "We repair the sensor. Now the score jumps and L6 fires -- after "
                "the fault is over. Detection arrived too late to be useful. In "
                "our recorded experiments a sustained dropout produced a 0.2% "
                "alarm rate across 160 seconds, below the 5% rate on a healthy "
                "car, and the apparent detection was entirely this recovery "
                "spike.",
        "action": {"clear": True},
        "hold": 140,
    },
    {
        "title": "Why this matters",
        "body": "A monitor that misses a fault is a problem. A monitor that goes "
                "quieter than normal during a fault is worse, because its silence "
                "reads as evidence that the car is healthy. That is why our next "
                "stage measures whether a monitor can be trusted, not just whether "
                "it fired. Everything you have just seen is the real pipeline -- "
                "the same code the experiments ran.",
        "action": None,
        "hold": 0,
    },
)


class FrameStream:
    """Runs the pipeline on a background thread and publishes frames.

    The drive owns the clock. Subscribers read a bounded queue and are dropped
    from rather than blocking -- a browser that cannot keep up must not slow the
    thing it is watching.
    """

    __slots__ = (
        "_gate",
        "_hold_until",
        "_injector",
        "_lock",
        "_recorder",
        "_sensing",
        "_step_once",
        "_subscribers",
        "_tick",
        "context_name",
        "dropped",
        "fault_name",
        "fault_path",
        "period_s",
        "pipeline",
        "replaying",
        "started",
        "story_index",
    )

    def __init__(
        self,
        injector: FaultInjector,
        *,
        sensing: RedundantSensing | None = None,
        recorder: object | None = None,
        period_s: float = TICK_PERIOD_S,
    ) -> None:
        """Initialise the stream.

        Args:
            injector: The live injector, armed by the fault buttons.
            sensing: The redundant sensing spec the run was started with. The
                position faults are armed by mutating it, because that is the
                only path a POSITION_Y fault can reach the estimator through.
            recorder: An open text file to write frames to, or ``None``.
            period_s: Wall-clock seconds to hold each tick for, so the screen
                advances at the rate the vehicle does. Zero runs flat out.
        """
        self._injector = injector
        self._sensing = sensing
        self._recorder = recorder
        self.fault_name: str | None = None
        self.fault_path: str | None = None
        self.context_name: str = "certified road"
        self.period_s = period_s
        self.pipeline: object | None = None
        self._lock = threading.Lock()
        self._subscribers: list[queue.Queue[str]] = []
        self._tick = 0
        self.dropped = 0
        self.started = False
        self.replaying = False
        # Transport. The gate is set when running; publish() blocks on it, so
        # pausing stops the vehicle rather than merely freezing the screen.
        self._gate = threading.Event()
        self._gate.set()
        self._step_once = False
        self.story_index: int | None = None
        self._hold_until: int | None = None

    @property
    def tick(self) -> int:
        """Return the tick the drive has reached."""
        return self._tick

    def subscribe(self) -> queue.Queue[str]:
        """Register a client and return its queue."""
        outbox: queue.Queue[str] = queue.Queue(maxsize=_QUEUE_LIMIT)
        with self._lock:
            self._subscribers.append(outbox)
        return outbox

    def unsubscribe(self, outbox: queue.Queue[str]) -> None:
        """Remove a client.

        Args:
            outbox: The queue returned by :meth:`subscribe`.
        """
        with self._lock:
            if outbox in self._subscribers:
                self._subscribers.remove(outbox)

    def enter(self, where: tuple[float, float, float]) -> str:
        """Move the vehicle into a different context, mid-run.

        Swaps the cold-path context the pipeline reads. Arbitration re-evaluates
        on its own period and decides afresh -- so entering the tunnel does not
        *tell* RCM to explore, it removes every profile that matched and leaves
        RCM to work out what to do about it. That distinction is the whole
        demonstration.

        Args:
            where: ``(visibility, traffic dynamicity, road complexity)``.

        Returns:
            A short label for the ticker.

        Raises:
            RuntimeError: If the pipeline is not available, which means the
                drive has not started.
        """
        if self.pipeline is None:
            message = "the drive has not started yet"
            raise RuntimeError(message)
        ctx_obj = cold_path(where)
        if hasattr(self.pipeline, "enter_context"):
            self.pipeline.enter_context(ctx_obj)
        else:
            self.pipeline._context = ctx_obj  # type: ignore[attr-defined]  # noqa: SLF001
        if where == TUNNEL:
            self.context_name = "tunnel"
            return "tunnel"
        if where == FOG:
            self.context_name = "heavy fog & traffic"
            return "heavy fog & traffic"
        self.context_name = "certified road"
        return "certified road"

    def arm(self, kind: str) -> FaultSpec:
        """Arm a fault from now, and return what was armed.

        Args:
            kind: The fault the audience chose.

        Returns:
            The specification, so the page can echo exactly what it asked for.
        """
        if kind in POSITION_FAULTS:
            return self._arm_position(kind)
        spec = build_injector(kind, tick=self._tick + 1, seed=0)
        self._injector.arm(spec)
        self.fault_name = kind
        self.fault_path = "FaultInjector"
        return spec

    def _arm_position(self, kind: str) -> FaultSpec:
        """Arm a position fault by mutating the redundant sensing spec.

        Two of three position channels are made to lie, so the median that L1
        fuses follows them. Faulting one channel only would be out-voted, which
        is the correct behaviour of redundancy and shows nothing.

        Returns:
            A descriptive spec so the page can echo what was armed. It is not
            handed to the injector: nothing on the injector path can carry a
            POSITION_Y fault past ``_publish_state``.

        Raises:
            RuntimeError: If the run was started without a sensing spec.
        """
        if self._sensing is None:
            message = "this run has no redundant sensing spec, so position faults cannot be armed"
            raise RuntimeError(message)
        opens = self._tick + 1
        closes = opens + FAULT_WINDOW_TICKS
        magnitude = POSITION_MAGNITUDE[kind]
        self._sensing.faulted = SensorModality.IMU
        self._sensing.also_faulted = (SensorModality.GPS,)
        self._sensing.opens_at = opens
        self._sensing.closes_at = closes
        if kind == "position_bias":
            self._sensing.bias = magnitude
            self._sensing.drift_per_tick = 0.0
        else:
            self._sensing.bias = 0.0
            self._sensing.drift_per_tick = magnitude / float(FAULT_WINDOW_TICKS)
        self.fault_name = kind
        self.fault_path = "RedundantSensing"
        return bias(
            FaultChannel.POSITION_Y,
            first_tick=opens,
            last_tick=closes,
            offset=magnitude,
        )

    def clear_fault(self) -> None:
        """Stand every armed fault down.

        Channel faults expire on their own window; the sensing path does not,
        so it is reset explicitly.
        """
        if self._sensing is not None:
            self._sensing.faulted = None
            self._sensing.also_faulted = ()
            self._sensing.bias = 0.0
            self._sensing.drift_per_tick = 0.0
            self._sensing.closes_at = 0
        self._injector.stand_down()
        self.fault_name = None
        self.fault_path = None
        if hasattr(self, "plant") and self.plant is not None:
            self.plant._state[1] = 0.0
            self.plant._state[2] = float(self.plant.spec_.reference_speed_mps)
            self.plant._state[3] = 0.0
            self.plant._state[4] = 0.0

    @property
    def paused(self) -> bool:
        """Return whether the run is currently held."""
        return not self._gate.is_set()

    def resume(self) -> None:
        """Let the vehicle run."""
        self._hold_until = None
        self._gate.set()

    def pause(self) -> None:
        """Hold the vehicle where it is."""
        self._gate.clear()

    def step(self) -> None:
        """Advance exactly one tick, then hold again."""
        self._step_once = True
        self._gate.set()

    def reset(self) -> None:
        """Stand every fault down, return L8 to NOMINAL, and resume.

        The vehicle is not returned to tick zero: the harness owns the run and
        restarting it would drop every subscriber. Standing the faults down and
        letting the pipeline recover is what an operator can actually do to a
        moving vehicle, so it is what this button does.

        The fail-safe machine is reset too, and it has to be. **HALT is terminal
        by design** -- no run of clean ticks leaves it, because a fail-safe that
        talked itself out of a controlled pull-over would not be one. So a
        demonstration that reaches HALT is over unless something performs the
        operator action, and :meth:`FailSafeStateMachine.reset` is exactly that
        action. Without this, an audience that pressed one fault too many would
        be looking at a stopped vehicle with no way back.
        """
        self.clear_fault()
        self.story_index = None
        if self.started and self.pipeline is not None:
            self.enter(CERTIFIED)
        if hasattr(self, "plant") and self.plant is not None:
            self.plant._state[1] = 0.0
            self.plant._state[2] = float(self.plant.spec_.reference_speed_mps)
            self.plant._state[3] = 0.0
            self.plant._state[4] = 0.0
        self._reset_failsafe()
        self.resume()

    def _reset_failsafe(self) -> None:
        """Perform the operator reset on L8, if the drive has started."""
        if self.pipeline is None:
            return
        machine = getattr(self.pipeline, "_failsafe", None)  # noqa: SLF001
        if machine is not None:
            machine.reset()

    # -- story mode --------------------------------------------------------

    def story_start(self) -> dict[str, object]:
        """Enter the guided demonstration at the first beat.

        L8 is reset alongside the faults. Beat 1 says "nothing is wrong", and it
        has to be true on screen: a walkthrough opened after an audience had
        already driven the vehicle into HALT would narrate a healthy vehicle over
        a stopped one, which is the one thing this demonstration must never do.
        """
        self.clear_fault()
        self._reset_failsafe()
        self.story_index = 0
        return self._play(STORY[0])

    def story_advance(self, delta: int) -> dict[str, object]:
        """Move to the next or previous beat and perform its action.

        Args:
            delta: ``+1`` for next, ``-1`` for back.

        Returns:
            The beat now showing.
        """
        if self.story_index is None:
            return self.story_start()
        index = max(0, min(len(STORY) - 1, self.story_index + delta))
        # Stepping back undoes whatever the beat we are leaving had armed;
        # replaying a beat from a dirty state would show the wrong thing.
        if delta < 0:
            self.clear_fault()
        self.story_index = index
        return self._play(STORY[index])

    def story_exit(self) -> None:
        """Leave the guided demonstration and hand control back."""
        self.story_index = None
        self.clear_fault()
        self.resume()

    def _play(self, beat: dict[str, object]) -> dict[str, object]:
        """Perform a beat's action and start its hold."""
        action = beat.get("action")
        if isinstance(action, dict):
            if action.get("clear"):
                self.clear_fault()
            kind = action.get("fault")
            if isinstance(kind, str):
                self.arm(kind)
        hold = int(beat.get("hold", 0) or 0)
        self._hold_until = (self._tick + hold) if hold > 0 else None
        self.resume() if hold > 0 else self.pause()
        return self.story_state()

    def story_state(self) -> dict[str, object]:
        """Return what the caption panel should show."""
        if self.story_index is None:
            return {"active": False}
        beat = STORY[self.story_index]
        return {
            "active": True,
            "index": self.story_index,
            "count": len(STORY),
            "title": beat["title"],
            "body": beat["body"],
        }

    def broadcast_status(self) -> None:
        """Push transport and story state to every subscriber immediately.

        While the run is held, :meth:`publish` is blocked and no frame is going
        out, so a page that only learned about pausing from the next frame would
        never learn about it at all. Control actions send this instead. It
        carries no pipeline numbers, and the page renders it into the controls
        only -- the traceability rule that every displayed measurement comes from
        a live ``DecisionRecord`` is not weakened by it.
        """
        payload = json.dumps(
            {
                "status": True,
                "paused": self.paused,
                "tick": self._tick,
                "fault_name": self.fault_name,
                "fault_path": self.fault_path,
                "scenario": self.context_name,
                "story": self.story_state(),
            },
            separators=(",", ":"),
        )
        with self._lock:
            subscribers = list(self._subscribers)
        for outbox in subscribers:
            try:
                outbox.put_nowait(payload)
            except queue.Full:
                self.dropped += 1

    def publish(self, sample: TickSample) -> None:
        """Project a tick and fan it out.

        Args:
            sample: The tick, from the harness's observer callback.
        """
        self._tick = sample.tick
        # A story beat runs for a fixed number of ticks and then holds, so the
        # presenter gets a still frame to talk over without touching anything.
        if self._hold_until is not None and sample.tick >= self._hold_until:
            self._hold_until = None
            self.pause()
        self._gate.wait()
        if self._step_once:
            self._step_once = False
            self._gate.clear()
        position_active = bool(
            self._sensing is not None
            and self._sensing.closes_at > 0
            and self._sensing.opens_at <= sample.tick <= self._sensing.closes_at
        )
        if self._sensing is not None and self._sensing.closes_at > 0 and sample.tick > self._sensing.closes_at:
            self._sensing.faulted = None
            self._sensing.also_faulted = ()
            self._sensing.bias = 0.0
            self._sensing.drift_per_tick = 0.0
            self._sensing.closes_at = 0

        engaged = bool(frame.fault_active or position_active)
        if not engaged:
            self.fault_name = None
            self.fault_path = None
            if hasattr(self, "plant") and self.plant is not None:
                self.plant._state[1] *= 0.85
                if abs(float(self.plant._state[1])) < 0.01:
                    self.plant._state[1] = 0.0
                if float(self.plant._state[2]) < float(self.plant.spec_.reference_speed_mps):
                    self.plant._state[2] = float(self.plant.spec_.reference_speed_mps)
        payload = json.dumps(
            {
                **asdict(frame),
                "fault_engaged": engaged,
                "paused": self.paused,
                "fault_name": self.fault_name,
                "fault_path": self.fault_path,
                "scenario": self.context_name,
                "story": self.story_state(),
            },
            separators=(",", ":"),
        )
        if self._recorder is not None:
            self._recorder.write(payload + "\n")  # type: ignore[attr-defined]
        with self._lock:
            subscribers = list(self._subscribers)
        for outbox in subscribers:
            try:
                outbox.put_nowait(payload)
            except queue.Full:
                self.dropped += 1
        if self.period_s > 0.0:
            time.sleep(self.period_s)


class _Handler(BaseHTTPRequestHandler):
    """Serves the page, the event stream and the fault endpoint."""

    stream: FrameStream

    @override
    def log_message(self, format: str, *args: object) -> None:
        """Silence per-request logging.

        Args:
            format: Unused.
            args: Unused.
        """
        del format, args

    def do_GET(self) -> None:
        """Route a GET to the page or the event stream."""
        if self.path in {"/", "/index.html"}:
            self._send_file(_STATIC / "index.html", "text/html; charset=utf-8")
        elif self.path == "/events":
            self._send_events()
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        """Arm the fault the audience chose."""
        if self.path.startswith("/context/"):
            self._enter_context()
            return
        if self.path.startswith("/control/"):
            self._control()
            return
        if self.path.startswith("/story/"):
            self._story()
            return
        if self.path == "/fault/clear":
            self.stream.clear_fault()
            self.stream.broadcast_status()
            self._send_json({"cleared": True, "tick": self.stream.tick})
            return
        if not self.path.startswith("/fault/"):
            self.send_error(404)
            return
        kind = self.path.removeprefix("/fault/")
        if self.stream.replaying:
            self.send_error(409, "this is a recording; the faults in it already happened")
            return
        try:
            spec = self.stream.arm(kind)
        except ValueError as error:
            self.send_error(400, str(error))
            return
        body = json.dumps(
            {
                "armed": kind,
                "kind": spec.kind.value,
                "first_tick": spec.first_tick,
                "last_tick": spec.last_tick,
                "channel": None if spec.channel is None else spec.channel.value,
                "magnitude": spec.magnitude,
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _control(self) -> None:
        """Start, pause, single-step or reset the run."""
        action = self.path.removeprefix("/control/")
        stream = self.stream
        match action:
            case "start":
                stream.resume()
            case "pause":
                stream.pause()
            case "step":
                stream.step()
            case "reset":
                stream.reset()
            case _:
                self.send_error(400, f"{action!r} is not a transport control")
                return
        stream.broadcast_status()
        self._send_json({"control": action, "paused": stream.paused, "tick": stream.tick})

    def _story(self) -> None:
        """Drive the guided demonstration."""
        action = self.path.removeprefix("/story/")
        stream = self.stream
        if stream.replaying:
            self.send_error(409, "this is a recording; it cannot be steered")
            return
        match action:
            case "start":
                state = stream.story_start()
            case "next":
                state = stream.story_advance(1)
            case "back":
                state = stream.story_advance(-1)
            case "exit":
                stream.story_exit()
                state = stream.story_state()
            case _:
                self.send_error(400, f"{action!r} is not a story action")
                return
        stream.broadcast_status()
        self._send_json({"story": state, "paused": stream.paused, "tick": stream.tick})

    def _send_json(self, body: dict[str, object]) -> None:
        """Send a JSON response.

        Args:
            body: The object to encode.
        """
        encoded = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _enter_context(self) -> None:
        """Move the vehicle into a different operating context."""
        name = self.path.removeprefix("/context/")
        where = {"tunnel": TUNNEL, "road": CERTIFIED, "fog": FOG}.get(name)
        if where is None:
            self.send_error(400, f"{name!r} is not a context this demonstration offers")
            return
        if self.stream.replaying:
            self.send_error(409, "this is a recording; the context changes in it already happened")
            return
        try:
            label = self.stream.enter(where)
        except RuntimeError as error:
            self.send_error(409, str(error))
            return
        body = json.dumps({"entered": label, "tick": self.stream.tick}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path, content_type: str) -> None:
        """Send a static file.

        Args:
            path: The file.
            content_type: Its MIME type.
        """
        try:
            body = path.read_bytes()
        except OSError:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_events(self) -> None:
        """Stream frames as Server-Sent Events until the client disappears."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        outbox = self.stream.subscribe()
        try:
            while True:
                payload = outbox.get()
                self.wfile.write(f"data: {payload}\n\n".encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ValueError):
            pass
        finally:
            self.stream.unsubscribe(outbox)


def replay(stream: FrameStream, recording: Path, *, period_s: float) -> None:
    """Stream a recorded run back at the rate it was captured.

    The page cannot distinguish this from a live drive, which is the point: a
    laptop that will not cooperate should cost a demonstration its
    interactivity, not its evidence. The fault buttons are refused, because the
    faults in a recording already happened.

    Args:
        stream: The stream to publish onto.
        recording: The JSONL file written by ``--record``.
        period_s: Seconds between frames.
    """
    for line in recording.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = line
        with stream._lock:  # noqa: SLF001 - same module, and the lock is the API
            subscribers = list(stream._subscribers)  # noqa: SLF001
        for outbox in subscribers:
            try:
                outbox.put_nowait(payload)
            except queue.Full:
                stream.dropped += 1
        time.sleep(period_s)


def serve(
    *,
    ticks: int,
    seed: int,
    policy_path: Path,
    port: int,
    record: Path | None = None,
    recording: Path | None = None,
    period_s: float = TICK_PERIOD_S,
) -> int:
    """Run the pipeline and the dashboard until interrupted.

    Args:
        ticks: How many control ticks to drive.
        seed: The run seed.
        policy_path: The trained proposer.
        port: The port to listen on.
        period_s: Wall-clock seconds per tick. Defaults to real time.
        record: Where to write frames as they are produced, or ``None``.
        recording: A recording to replay instead of driving, or ``None``.
        period_s: Replay frame interval.

    Returns:
        Process exit status.
    """
    injector = FaultInjector((), seed=seed, sigmas=CHANNEL_SIGMAS)
    # One object, shared: the stream mutates it when a position fault is armed
    # and the harness reads it every tick. Two copies would look identical and
    # inject nothing, which is precisely the defect this demo used to have.
    sensing = RedundantSensing.build(sigmas=DEFAULT_CHANNEL_SIGMAS, seed=seed)
    handle = None if record is None else record.open("w", encoding="utf-8")
    if record is not None:
        record.parent.mkdir(parents=True, exist_ok=True)
        handle = record.open("w", encoding="utf-8")
    stream = FrameStream(injector, sensing=sensing, recorder=handle, period_s=period_s)
    stream.replaying = recording is not None
    _Handler.stream = stream

    def drive() -> None:
        if recording is not None:
            replay(stream, recording, period_s=period_s)
            return
        drive_closed_loop(
            policy=LearnedPolicy.load(policy_path),
            ticks=ticks,
            seed=seed,
            observer=stream.publish,
            fault=injector,
            redundant=sensing,
            cold_path=cold_path(CERTIFIED),
            on_assembled=lambda built: (
                setattr(stream, "pipeline", built.pipeline),
                setattr(stream, "plant", built.plant),
            ),
        )
        if handle is not None:
            handle.flush()

    server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    worker = threading.Thread(target=drive, name="astra-demo-drive", daemon=True)
    print(f"  dashboard: http://127.0.0.1:{port}/")
    rate = "flat out" if period_s <= 0.0 else f"{1.0 / period_s:.0f} Hz, real time"
    print(f"  driving {ticks} ticks from seed {seed} at {rate}; Ctrl-C to stop")
    worker.start()
    stream.started = True
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  stopped")
    finally:
        server.server_close()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments and serve.

    Args:
        argv: Command-line arguments, or ``None`` for ``sys.argv``.

    Returns:
        Process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ticks", "-n", type=int, default=_DEFAULT_TICKS)
    parser.add_argument("--seed", type=int, default=_DEFAULT_SEED)
    parser.add_argument("--policy", type=Path, default=_DEFAULT_POLICY)
    parser.add_argument("--port", "-p", type=int, default=8000)
    parser.add_argument("--record", type=Path, default=None)
    parser.add_argument("--replay", type=Path, default=None)
    parser.add_argument(
        "--rate",
        type=float,
        default=1.0,
        help="playback speed; 1.0 is real time, 0 runs flat out",
    )
    arguments = parser.parse_args(argv)

    if arguments.replay is None:
        for artefact in (TWIN, CORPUS, arguments.policy):
            if not artefact.exists():
                print(f"missing {artefact}; see docs/EVIDENCE.md for how to regenerate it")
                return 1
    elif not arguments.replay.exists():
        print(f"missing recording {arguments.replay}; capture one with --record first")
        return 1

    return serve(
        ticks=arguments.ticks,
        seed=arguments.seed,
        policy_path=arguments.policy,
        port=arguments.port,
        record=arguments.record,
        recording=arguments.replay,
        period_s=0.0 if arguments.rate <= 0.0 else TICK_PERIOD_S / arguments.rate,
    )


if __name__ == "__main__":
    sys.exit(main())
