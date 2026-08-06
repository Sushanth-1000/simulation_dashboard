"""L5 -- the physics-informed digital twin, and why it adapts the way it does.

What this layer is for
----------------------
The twin answers one question per tick: *given the state the vehicle is in, what
command does the modelled physics expect next?* That prediction, ``pi_hat``, is
the right operand of the statistical gate's non-conformity score

    ``alpha = |pi_prop - pi_hat| / sigma(x)``

so the twin is not a diagnostic. It is a safety input, and a twin that drifted
would move the acceptance band under the gate without the gate noticing.

Why the twin must not become a good controller
----------------------------------------------
There is a failure mode here that looks like success. If the twin were trained
until it predicted Core-A's policy accurately, every non-conformity score would
be small, the statistical gate would stop firing, and the system would look
healthy while having disarmed one of its three gates. The twin is trained
against *physics*, not against the proposer, and the physics residual in
:mod:`astra.layers.l5_twin.network` is what keeps it anchored to something the
proposer cannot move.

Why adaptation touches the output layer only
--------------------------------------------
Feedback loop FB2 lets the twin track real changes -- tyre wear, load shifts, a
wet road. The risk is catastrophic forgetting: adapting to rain silently
destroys highway accuracy, and nothing in the pipeline would report it, because
a confidently wrong twin produces confidently wrong scores rather than errors.

Two mechanisms guard against it. Only :attr:`TwinNetwork.output` receives
gradients, so the learned physics representation in the hidden layer is
structurally out of reach of any single context's data. And the update carries
an elastic-weight-consolidation penalty anchored on the Fisher information of a
window of historical samples, so parameters that mattered to earlier contexts
resist being moved.

Neither mechanism is a proof. RK-5 records that EWC may fail to prevent
forgetting in practice, and the validation plan requires an explicit test --
highway accuracy must not degrade after adapting to rain -- rather than an
assumption that the penalty worked.

Determinism
-----------
Weight initialisation is seeded from configuration. A randomly initialised
network would make two runs over identical recorded inputs produce different
predictions, different scores and different verdicts, which would defeat the
byte-exact replay the project built in Phase 2 precisely so that closed-loop
behaviour could be debugged. Assumption A-5 named this as the extension replay
would need once learned components arrived; this is that extension.

Failure policy
--------------
A non-finite prediction raises rather than returning a command. NaN propagating
into the non-conformity score would make the comparison against the conformal
quantile false, which reads as PASS -- a fail-open in a gate input. Raising a
``FAIL_CLOSED`` error turns it into a VETO through the ordinary path.
"""

from __future__ import annotations

import hashlib
import math
from typing import TYPE_CHECKING, Final

import torch

from astra.contracts.actuation import ControlCommand, PredictedCommand
from astra.kernel.constants import FAST_STATE_FIELDS
from astra.kernel.enums import ContextClass, LayerId
from astra.kernel.errors import ConfigurationError, SafetyPathError
from astra.layers.l5_twin.network import TwinNetwork, physics_residual, state_features

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from astra.config.schema import TwinSettings
    from astra.contracts.actuation import ActuationSpace
    from astra.contracts.estimation import FastStateEstimate
    from astra.kernel.identifiers import ComponentId, TickId
    from astra.kernel.time import Clock

__all__ = ["PhysicsInformedTwin"]

_SPEED_INDEX: Final = FAST_STATE_FIELDS.index("speed")
_HEADING_INDEX: Final = FAST_STATE_FIELDS.index("heading")
_LATERAL_INDEX: Final = FAST_STATE_FIELDS.index("lateral_acceleration")

_ADAPTATION_LEARNING_RATE: Final = 1e-3
"""Step size for the FB2 output-layer update.

A property of the adaptation mechanism rather than an operating point: it is
small enough that a single 50-sample batch cannot move the twin far, which is
the behaviour the mechanism needs regardless of platform. Revisit only if
adaptation is observed to be too slow to track a real context change.
"""

_ADAPTATION_GRADIENT_CLIP: Final = 1.0
"""Maximum gradient norm per adaptation step.

Not a tuning knob -- it is what makes the step size mean anything. The physics
residual is expressed in metres per second squared and scaled by the platform's
control effectiveness, which is a number in the hundreds for a steering channel.
Its gradient is correspondingly large, and unclipped it drives the output layer
past the point of representable floats within a handful of steps. Clipping the
norm bounds how far one batch of executed outcomes can move the twin, which is
the guarantee FB2 needs: adaptation should track a drifting context, never
relocate the reference point that the statistical gate scores against.
"""


def _with_heads(state: dict[str, torch.Tensor]) -> dict[str, torch.Tensor]:
    """Migrate a pre-ADR-0019 checkpoint to the per-context head layout.

    Args:
        state: A loaded ``state_dict``.

    Returns:
        The same mapping if it already has heads; otherwise one in which the
        single ``output`` layer has been copied into every context's head.
    """
    if not any(name.startswith("output.") for name in state):
        return state
    migrated = {name: value for name, value in state.items() if not name.startswith("output.")}
    for context in ContextClass:
        for suffix in ("weight", "bias"):
            source = state.get(f"output.{suffix}")
            if source is not None:
                migrated[f"heads.{context.value}.{suffix}"] = source.clone()
    return migrated


class PhysicsInformedTwin:
    """The digital twin. Satisfies :class:`~astra.ports.pipeline.DynamicsPredictor`.

    Holds a small network, the configured control effectiveness, and a bounded
    history used to anchor online adaptation. Prediction is pure: it reads the
    state and touches no internal counter, so two calls with the same state
    return the same command and a replayed run reproduces its verdicts.
    """

    __slots__ = (
        "_anchor",
        "_anchored_context",
        "_buffer",
        "_clock",
        "_component",
        "_context",
        "_effectiveness",
        "_network",
        "_settings",
        "_space",
    )

    def __init__(
        self,
        *,
        settings: TwinSettings,
        space: ActuationSpace,
        component: ComponentId,
        clock: Clock,
    ) -> None:
        """Build the twin for one actuation space.

        Args:
            settings: The twin's configuration.
            space: The actuation space whose channels the twin predicts. Supplied
                by the adapter, so the layer never names a channel (NFR5).
            component: The L5 component identity stamped on every prediction.
            clock: The injected clock. Never ``time.time()``: a prediction's
                timestamp has to sit on the same timeline as the state that
                produced it, and replay rewinds that timeline.

        Raises:
            ConfigurationError: If the component is not an L5 component, or if
                the configured control-effectiveness row does not match the
                actuation space's dimension. The second is a genuine
                misconfiguration rather than a runtime fault: a row of the wrong
                length silently describes a different vehicle.
        """
        if component.layer is not LayerId.L5_PINN_TWIN:
            message = (
                f"the digital twin must be constructed with an L5 component, "
                f"got {component.layer.value}; a prediction attributed to another "
                f"layer would misdescribe the trust boundary in the evidence log"
            )
            raise ConfigurationError(message, layer=component.layer)

        effectiveness = tuple(settings.control_effectiveness)
        if len(effectiveness) != space.dimension:
            message = (
                f"twin.control_effectiveness has {len(effectiveness)} entries but the "
                f"actuation space has {space.dimension} channels {space.names}; the row "
                f"maps a command to the lateral acceleration it produces, so a length "
                f"mismatch describes a different platform"
            )
            raise ConfigurationError(
                message,
                layer=LayerId.L5_PINN_TWIN,
                context={"configured": len(effectiveness), "channels": list(space.names)},
            )

        self._settings = settings
        self._space = space
        self._component = component
        self._clock = clock

        torch.manual_seed(settings.seed)
        self._network = TwinNetwork(
            hidden_width=settings.hidden_width, command_dimension=space.dimension
        )
        self._network.eval()
        self._effectiveness = torch.tensor(effectiveness, dtype=torch.float32)
        self._buffer: list[tuple[tuple[float, ...], tuple[float, ...]]] = []
        self._context: ContextClass | None = None

    def predict(
        self,
        *,
        tick: TickId,
        state: FastStateEstimate,
        context: ContextClass | None = None,
    ) -> PredictedCommand:
        """Predict the command the modelled physics expects next.

        Args:
            tick: The control tick.
            state: The current fast state estimate.
            context: The operational context L3 classified this tick into, which
                selects the output head. ``None`` -- no classification was
                produced -- reads ``UNCLASSIFIED``'s head, the offline-trained
                twin that FB2 never writes to. Reading a *stale* context's head
                would be worse than reading the factory one, because it would be
                confidently conditioned on a place the vehicle may have left.

        Returns:
            ``pi_hat_{t+1}`` as a :class:`~astra.contracts.actuation.PredictedCommand`.

        Raises:
            SafetyPathError: If the state contains a non-finite value, or if the
                network produces one. Both fail closed: a NaN reaching the
                non-conformity score would make the comparison against the
                conformal quantile false, which the gate reads as PASS.
        """
        self._require_finite(tick, state.mean, what="state")
        features = state_features(
            state.mean,
            speed_index=_SPEED_INDEX,
            heading_index=_HEADING_INDEX,
            lateral_index=_LATERAL_INDEX,
        )
        with torch.no_grad():
            predicted = self._network(torch.tensor([features], dtype=torch.float32), context)
        values = tuple(float(value) for value in predicted[0])
        self._require_finite(tick, values, what="prediction")
        return PredictedCommand(
            tick=tick,
            predicted_at=self._clock.now(),
            command=ControlCommand(space=self._space, values=values),
            source=self._component,
        )

    @property
    def weights_digest(self) -> str:
        """Return a stable SHA-256 digest of the twin's current parameters.

        The counterpart of the configuration hash. A verdict is only traceable
        if a reader can tell *which* twin produced the prediction it rests on,
        and "the twin" is not a fixed thing: it ships as a checkpoint, and FB2
        moves it during a run. Recording the digest alongside the configuration
        hash makes an evidence record answer "under which model" as precisely as
        it already answers "under which configuration".

        Returns:
            A hex digest over every parameter in canonical name order.
        """
        digest = hashlib.sha256()
        for name, parameter in sorted(self._network.state_dict().items()):
            digest.update(name.encode("utf-8"))
            digest.update(parameter.detach().cpu().numpy().tobytes())
        return digest.hexdigest()

    def save_checkpoint(self, path: Path) -> None:
        """Write the twin's parameters to a checkpoint file.

        Args:
            path: Destination. Parent directories are created if absent.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        torch.save(self._network.state_dict(), path)

    def load_checkpoint(self, path: Path) -> None:
        """Load parameters from a checkpoint, replacing the seeded initialisation.

        A checkpoint written before ADR-0019 holds one ``output`` layer rather
        than a head per context. It is migrated by broadcasting that layer into
        every head, which is the semantically right migration and not merely a
        convenient one: the offline-trained twin *is* the common starting point
        that every context then adapts away from. Every twin trained by
        ``training/train_twin.py`` before 2 August 2026 loads unchanged and
        predicts identically until FB2 first runs.

        Args:
            path: The checkpoint to load.

        Raises:
            ConfigurationError: If the checkpoint does not match this twin's
                architecture. A shape mismatch means the checkpoint was trained
                for a different actuation space or hidden width, and loading it
                partially would leave a twin that predicts confidently from
                half-trained weights.
        """
        try:
            state = _with_heads(torch.load(path, map_location="cpu", weights_only=True))
            self._network.load_state_dict(state)
        except (RuntimeError, KeyError) as error:
            message = (
                f"the checkpoint at {path} does not match this twin's architecture: "
                f"{error}. A checkpoint trained for a different actuation space or hidden "
                f"width would leave a twin predicting confidently from half-trained weights"
            )
            raise ConfigurationError(
                message, layer=LayerId.L5_PINN_TWIN, context={"path": str(path)}
            ) from error
        self._network.eval()

    def adapt(
        self,
        *,
        applied: ControlCommand,
        measured: FastStateEstimate,
        context: ContextClass | None = None,
    ) -> None:
        """Record an executed outcome and update the twin when enough have arrived.

        Feedback loop FB2. Buffers the sample; once
        ``settings.adaptation_buffer`` have accumulated, takes several gradient
        steps on **this context's output head** and clears the buffer.

        A sample whose state or command is non-finite is discarded rather than
        raising. This is the cold path: a bad measurement here must not take
        down a tick that has already been decided, and the twin adapting from a
        corrupt sample would be worse than it not adapting at all.

        Args:
            applied: The command that was actually applied -- not the one
                proposed. Adapting on the proposal would teach the twin the
                policy's intent rather than the vehicle's response, which is
                exactly the coupling FB1 exists to remove from L2.
            measured: The state measured after applying it.
            context: The operational context this outcome was observed in, from
                L3's Mondrian classifier. It selects the head the update writes
                to, which is what makes forgetting structurally impossible
                (ADR-0019). ``None`` or
                :attr:`~astra.kernel.enums.ContextClass.UNCLASSIFIED` **does not
                adapt at all**: a twin that rewrote itself while it could not
                tell where it was would be the failure mode the architecture
                exists to prevent, and ``UNCLASSIFIED``'s head has a second job
                as the pristine offline reference.
        """
        if context is None or context is ContextClass.UNCLASSIFIED:
            return
        # Checked before the features are built, not after: `state_features`
        # takes the sine and cosine of the heading, and `math.sin(inf)` raises
        # rather than returning a NaN that a later guard could catch.
        if not all(math.isfinite(value) for value in (*measured.mean, *applied.values)):
            return

        features = state_features(
            measured.mean,
            speed_index=_SPEED_INDEX,
            heading_index=_HEADING_INDEX,
            lateral_index=_LATERAL_INDEX,
        )
        if context is not self._context:
            # Drop the partial buffer rather than consolidating across a
            # boundary. An update mixing two contexts teaches one head the
            # average of a highway and a rainstorm, which is a worse answer than
            # either and belongs to neither.
            self._buffer.clear()
        self._context = context

        sample = (features, applied.values)
        self._buffer.append(sample)

        if len(self._buffer) >= self._settings.adaptation_buffer:
            self._consolidate()
            self._buffer.clear()

    def _consolidate(self) -> None:
        """Take several gradient steps on the current context's head.

        The loss is command error plus the physics residual. There is no
        consolidation penalty and no Fisher information, because there is
        nothing left for them to protect: the update writes to one head, and the
        parameters every other context is read from are not in the optimiser.
        Forgetting is prevented by the shape of the network rather than by a
        term in the loss (ADR-0019).

        The shared trunk is frozen for the duration, which is what keeps the
        heads comparable -- moving it would silently re-specify the features
        every *other* context's head was fitted against, and reintroduce
        cross-context interference through the back door.
        """
        head = self._network.head(self._context)
        features = torch.tensor([row for row, _ in self._buffer], dtype=torch.float32)
        targets = torch.tensor([cmd for _, cmd in self._buffer], dtype=torch.float32)
        lateral = features[:, -1]

        # Kept so the update can be abandoned wholesale. An ill-conditioned batch
        # can drive a head to infinity in a few steps, and a twin holding NaN
        # weights does not fail loudly -- it predicts NaN, which the statistical
        # gate would compare against its quantile and read as a PASS. Adaptation
        # is the cold path, so refusing a divergent update costs a missed
        # adaptation and nothing else.
        restore = {name: parameter.detach().clone() for name, parameter in head.named_parameters()}

        for parameter in self._network.hidden.parameters():
            parameter.requires_grad_(False)

        self._network.train()
        optimiser = torch.optim.SGD(head.parameters(), lr=_ADAPTATION_LEARNING_RATE)
        for _ in range(self._settings.adaptation_steps):
            optimiser.zero_grad()
            predicted = self._network(features, self._context)
            loss = torch.mean((predicted - targets) ** 2)
            loss = loss + self._settings.physics_weight * physics_residual(
                predicted, lateral, self._effectiveness
            )
            loss.backward()  # type: ignore[no-untyped-call]
            torch.nn.utils.clip_grad_norm_(head.parameters(), _ADAPTATION_GRADIENT_CLIP)
            optimiser.step()

        self._network.eval()
        for parameter in self._network.hidden.parameters():
            parameter.requires_grad_(True)

        if not self._head_is_finite(head):
            with torch.no_grad():
                for name, parameter in head.named_parameters():
                    parameter.copy_(restore[name])

    @staticmethod
    def _head_is_finite(head: torch.nn.Module) -> bool:
        """Return whether every parameter of one head is finite.

        Args:
            head: The output layer just updated.

        Returns:
            ``True`` if it can still produce a usable prediction.
        """
        return all(bool(torch.isfinite(parameter).all()) for parameter in head.parameters())

    @staticmethod
    def _require_finite(tick: TickId, values: Sequence[float], *, what: str) -> None:
        """Refuse to continue with a non-finite vector.

        Args:
            tick: The control tick.
            values: The vector to check.
            what: ``"state"`` or ``"prediction"``, for the evidence record.

        Raises:
            SafetyPathError: If any entry is NaN or infinite.
        """
        offenders = [index for index, value in enumerate(values) if not math.isfinite(value)]
        if offenders:
            message = (
                f"the digital twin cannot produce a usable prediction from a non-finite "
                f"{what} at indices {offenders}; a NaN reaching the non-conformity score "
                f"makes the comparison against the conformal quantile false, which the "
                f"statistical gate would read as a PASS"
            )
            raise SafetyPathError(
                message,
                layer=LayerId.L5_PINN_TWIN,
                context={"tick": tick.value, "indices": offenders, "source": what},
            )
