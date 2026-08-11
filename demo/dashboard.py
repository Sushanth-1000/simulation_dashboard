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

from astra.layers.l4_proposer.learned import LearnedPolicy
from training.closed_loop import CHANNEL_SIGMAS, CORPUS, TWIN, TickSample, drive_closed_loop
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

FAULT_WINDOW_TICKS = 400
"""How long an armed fault lasts. Twenty seconds at 20 Hz.

Long enough for the `imu_dropout` divergence to develop -- it took 73 ticks to
leave the corridor in E-46 -- and short enough that an audience sees it recover.
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


def build_injector(kind: str, *, tick: int, seed: int) -> FaultSpec:
    """Return the fault an audience just asked for.

    Args:
        kind: One of ``dropout``, ``position_bias``, ``position_drift``,
            ``speed_stuck`` or ``lateral_noise``.
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
        case "position_bias":
            return bias(FaultChannel.POSITION_Y, first_tick=tick, last_tick=last, offset=1.0)
        case "position_drift":
            return drift(FaultChannel.POSITION_Y, first_tick=tick, last_tick=last, final=2.0)
        case "speed_stuck":
            return stuck_at(FaultChannel.SPEED, first_tick=tick, last_tick=last)
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


class FrameStream:
    """Runs the pipeline on a background thread and publishes frames.

    The drive owns the clock. Subscribers read a bounded queue and are dropped
    from rather than blocking -- a browser that cannot keep up must not slow the
    thing it is watching.
    """

    __slots__ = (
        "_injector",
        "_lock",
        "_recorder",
        "_subscribers",
        "_tick",
        "dropped",
        "replaying",
        "started",
    )

    def __init__(self, injector: FaultInjector, *, recorder: object | None = None) -> None:
        """Initialise the stream.

        Args:
            injector: The live injector, armed by the fault buttons.
            recorder: An open text file to write frames to, or ``None``.
        """
        self._injector = injector
        self._recorder = recorder
        self._lock = threading.Lock()
        self._subscribers: list[queue.Queue[str]] = []
        self._tick = 0
        self.dropped = 0
        self.started = False
        self.replaying = False

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

    def arm(self, kind: str) -> FaultSpec:
        """Arm a fault from now, and return what was armed.

        Args:
            kind: The fault the audience chose.

        Returns:
            The specification, so the page can echo exactly what it asked for.
        """
        spec = build_injector(kind, tick=self._tick + 1, seed=0)
        self._injector.arm(spec)
        return spec

    def publish(self, sample: TickSample) -> None:
        """Project a tick and fan it out.

        Args:
            sample: The tick, from the harness's observer callback.
        """
        self._tick = sample.tick
        payload = json.dumps(asdict(Frame.from_sample(sample)), separators=(",", ":"))
        if self._recorder is not None:
            self._recorder.write(payload + "\n")  # type: ignore[attr-defined]
        with self._lock:
            subscribers = list(self._subscribers)
        for outbox in subscribers:
            try:
                outbox.put_nowait(payload)
            except queue.Full:
                self.dropped += 1


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
    period_s: float = 0.05,
) -> int:
    """Run the pipeline and the dashboard until interrupted.

    Args:
        ticks: How many control ticks to drive.
        seed: The run seed.
        policy_path: The trained proposer.
        port: The port to listen on.
        record: Where to write frames as they are produced, or ``None``.
        recording: A recording to replay instead of driving, or ``None``.
        period_s: Replay frame interval.

    Returns:
        Process exit status.
    """
    injector = FaultInjector((), seed=seed, sigmas=CHANNEL_SIGMAS)
    handle = None if record is None else record.open("w", encoding="utf-8")
    if record is not None:
        record.parent.mkdir(parents=True, exist_ok=True)
        handle = record.open("w", encoding="utf-8")
    stream = FrameStream(injector, recorder=handle)
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
        )
        if handle is not None:
            handle.flush()

    server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    worker = threading.Thread(target=drive, name="astra-demo-drive", daemon=True)
    print(f"  dashboard: http://127.0.0.1:{port}/")
    print(f"  driving {ticks} ticks from seed {seed}; Ctrl-C to stop")
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
    )


if __name__ == "__main__":
    sys.exit(main())
