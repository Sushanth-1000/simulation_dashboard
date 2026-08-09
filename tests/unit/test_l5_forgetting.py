"""Does adapting the twin to rain destroy what it knew about the highway?

This is the test `PENDING.md` P3.1 says to write **before** wiring FB2 into the
tick loop, and the reason is worth restating: without it you cannot tell
adaptation from destruction. A twin that has forgotten the highway does not fail
loudly. It predicts confidently and wrongly, the non-conformity score
``|pi_prop - pi_hat| / sigma`` is computed against a wrong reference, and two
gates then reason carefully about a number that means nothing.

What this file measured, and what changed because of it
-------------------------------------------------------
It was written on 6 August 2026 against an elastic-weight-consolidation penalty,
and it found three things in order.

1. The configured ``ewc_lambda`` was not weak, it was **bit-for-bit inert** --
   forgetting 0.038951 against 0.038972 unregularised.
2. The cause was the anchor, re-taken on every buffer flush, so the penalty
   resisted the last twenty samples and permitted unlimited total drift
   (ADR-0018).
3. With that fixed, the penalty still only ever acted as a **brake**: across
   every lambda from 0 to 1e5 the ratio of forgetting to learning was constant
   to three significant figures. It could not have been otherwise. Adaptation
   touched a single 16x2 readout that both contexts used in full, so there was
   no disjoint subspace for a Fisher-weighted penalty to protect.

ADR-0019 replaced the penalty with **one output head per**
:class:`~astra.kernel.enums.ContextClass`. Forgetting is now prevented by the
shape of the network: adapting in the rain writes to the rain head, and the
parameters the highway is read from are not in the optimiser. The assertions
below are therefore *exact* -- the highway prediction after a rainstorm must be
unchanged to the bit, not merely close.

The control that keeps this honest
----------------------------------
An exact-equality test would also pass on a twin that adapted nothing at all, so
:func:`test_forgetting_is_real_when_one_head_serves_both_contexts` feeds the same
rain through the *highway* head -- which is precisely the pre-ADR-0019 behaviour,
reproduced by mislabelling rather than by keeping old code around. It still
destroys the highway, by a factor of 159. That number is what the structure now
prevents.

Where the experiment starts
---------------------------
FB2 trains only an output head, on top of a hidden trunk it freezes. That is the
right design -- adaptation should adjust a trained twin, not retrain one -- but
it means an experiment starting from seeded random weights measures something
the mechanism was never meant to do. Measured on the way to writing this: from
random initialisation, 2,400 samples moved the parameters 0.14 in norm and left
the error at 0.094, converged and useless. So each trial **pre-trains the whole
network on the highway first**, exactly as ``training/train_twin.py`` does with
Adam over both layers, and only then hands over to FB2.

The two contexts
----------------
"Highway" and "rain" are two different mappings from motion to command: the same
lateral acceleration is produced by a larger steering command on a slippery road.
Both are linear and exactly learnable by an output head, which is deliberate -- a
context the network cannot represent would make every result a statement about
capacity rather than about interference.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import pytest
import torch

from astra.config.schema import TwinSettings
from astra.contracts.actuation import ActuationChannel, ActuationSpace, ControlCommand
from astra.contracts.estimation import FastStateEstimate
from astra.kernel.enums import ContextClass, LayerId
from astra.kernel.identifiers import ComponentId, TickId
from astra.kernel.matrix import SymmetricMatrix
from astra.kernel.time import Instant, ManualClock, Timeline
from astra.layers.l5_twin.network import TwinNetwork, physics_residual, state_features
from astra.layers.l5_twin.twin import PhysicsInformedTwin

COMPONENT = ComponentId(LayerId.L5_PINN_TWIN)
EFFECTIVENESS = (0.0, 120.0)
"""Channel 0 does not steer; channel 1 produces 120 m/s^2 per unit. Matches the
two-channel space below and the wider twin tests."""

SAMPLES_PER_CONTEXT = 240
"""Enough for several consolidations at a buffer of 20, so the penalty is
exercised repeatedly rather than once. Forgetting is cumulative; a single update
would understate it in both arms equally and shrink the gap the tests measure."""

BUFFER = 20
PRETRAIN_EPOCHS = 6_000
"""Full-batch Adam epochs for the offline twin. `train_twin.py` uses 3,000 on a
harder corpus; this one is linear and converges well inside that."""
RAIN_SAMPLES = 4_000
"""How much rain FB2 gets. Far more than the 240 the offline stage sees, because
FB2 is deliberately slow: SGD at 1e-3 with gradients clipped to norm 1, so a
single step moves the parameters by at most 1e-3 and a context change worth
several tenths needs thousands of them."""
PROBE_COUNT = 40
"""Held-out highway states the error is measured on. Drawn from the same
generator as the training states but at different phases, so this measures
recall of the *mapping* rather than memorisation of the exact rows."""


def _space() -> ActuationSpace:
    return ActuationSpace(
        (
            ActuationChannel(name="throttle", lower=0.0, upper=1.0, unit="1"),
            ActuationChannel(name="steer", lower=-0.5, upper=0.5, unit="rad"),
        )
    )


@dataclass(frozen=True, slots=True)
class Context:
    """A driving context: how much steering this road needs for a given turn.

    Attributes:
        name: For failure messages.
        klass: The Mondrian context class, which is also EWC's task boundary.
        steer_gain: Command per unit of lateral acceleration. Rain needs more of
            it for the same cornering, which is the whole content of the shift.
        throttle: The longitudinal channel, constant within a context.
    """

    name: str
    steer_gain: float
    throttle: float
    klass: ContextClass

    def command(self, lateral: float) -> tuple[float, ...]:
        """Return the command this context produces for a lateral acceleration.

        Args:
            lateral: The lateral acceleration the vehicle is experiencing.

        Returns:
            A two-channel command.
        """
        return (self.throttle, self.steer_gain * lateral)


HIGHWAY = Context(
    name="highway", steer_gain=1.0 / 120.0, throttle=0.6, klass=ContextClass.HIGHWAY_CLEAR
)
RAIN = Context(name="rain", steer_gain=2.5 / 120.0, throttle=0.25, klass=ContextClass.RAIN_NIGHT)
"""Rain needs 2.5x the steering and a quarter less throttle. Large enough that
forgetting is unmistakable when it happens, and physically the right direction:
less grip, more input for the same result."""


def _settings() -> TwinSettings:
    return TwinSettings(
        physics_weight=1.0,
        control_effectiveness=list(EFFECTIVENESS),
        hidden_width=16,
        adaptation_buffer=BUFFER,
        adaptation_steps=10,
        seed=11,
    )


def _twin() -> PhysicsInformedTwin:
    return PhysicsInformedTwin(
        settings=_settings(),
        space=_space(),
        component=COMPONENT,
        clock=ManualClock(Instant(0, Timeline.MANUAL)),
    )


def _state(index: int, *, phase: float = 0.0) -> FastStateEstimate:
    # A vehicle cornering gently back and forth at a steady speed. Deterministic
    # rather than random: A-5 wants runs byte-reproducible, and a seeded RNG here
    # would add a second source of variation between the two arms.
    lateral = 2.0 * math.sin(0.11 * index + phase)
    heading = 0.4 * math.sin(0.07 * index + phase)
    return FastStateEstimate(
        tick=TickId(index),
        valid_at=Instant(1_000 * (index + 1), Timeline.MANUAL),
        mean=(0.0, 0.0, 22.0, heading, lateral),
        covariance=SymmetricMatrix.from_diagonal([1.0, 1.0, 0.25, 0.1, 0.5]),
    )


def _pretrain(context: Context, path: Path) -> None:
    """Train a twin offline on one context and write it to a checkpoint.

    Mirrors ``training/train_twin.py``: Adam over the *whole* network, full
    batch, against the same data-plus-physics loss. This is the twin FB2 is
    supposed to receive, and building it here rather than reusing
    ``var/twin/synthetic.pt`` keeps the ground truth known -- the shipped
    checkpoint was trained on the plant's dynamics, not on a context this test
    can score against.

    Args:
        context: The context to learn.
        path: Where to write the checkpoint.
    """
    torch.manual_seed(11)
    network = TwinNetwork(hidden_width=16, command_dimension=len(EFFECTIVENESS))
    rows = [_state(index) for index in range(SAMPLES_PER_CONTEXT)]
    features = torch.tensor(
        [
            state_features(state.mean, speed_index=2, heading_index=3, lateral_index=4)
            for state in rows
        ],
        dtype=torch.float32,
    )
    targets = torch.tensor([context.command(state.mean[-1]) for state in rows], dtype=torch.float32)
    lateral = features[:, -1]
    effectiveness = torch.tensor(EFFECTIVENESS, dtype=torch.float32)

    optimiser = torch.optim.Adam(network.parameters(), lr=1e-2)
    for _ in range(PRETRAIN_EPOCHS):
        optimiser.zero_grad()
        predicted = network(features)
        loss = torch.mean((predicted - targets) ** 2)
        loss = loss + physics_residual(predicted, lateral, effectiveness)
        loss.backward()  # type: ignore[no-untyped-call]
        optimiser.step()

    network.seed_heads_from()
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(network.state_dict(), path)


def _drive(
    twin: PhysicsInformedTwin,
    context: Context,
    *,
    count: int,
    labelled: ContextClass | None = None,
) -> None:
    """Feed one context's worth of executed outcomes through ``adapt``.

    Args:
        twin: The twin to adapt.
        context: The context whose dynamics the samples come from.
        count: How many samples.
        labelled: The context to *tell* the twin it is in. Defaults to the
            truthful one; the control test passes the wrong one deliberately, to
            reproduce a single head serving two contexts.
    """
    space = _space()
    for index in range(count):
        state = _state(index)
        twin.adapt(
            applied=ControlCommand(values=context.command(state.mean[-1]), space=space),
            measured=state,
            context=labelled or context.klass,
        )


def _error_on(
    twin: PhysicsInformedTwin, context: Context, *, through: ContextClass | None = None
) -> float:
    """Return the twin's mean absolute command error in a context.

    Args:
        twin: The twin to probe.
        context: The context whose mapping is the ground truth.
        through: Which head to read. Defaults to the context's own. The
            shared-head control reads everything through one head, which is the
            whole point of it -- measuring the rain through an untouched rain
            head would report no change and make the comparison vacuous.

    Returns:
        Mean absolute error over held-out states, across both channels.
    """
    total = 0.0
    for index in range(PROBE_COUNT):
        # Phase-shifted: different states, same underlying mapping.
        state = _state(index, phase=1.7)
        predicted = twin.predict(
            tick=TickId(index), state=state, context=through or context.klass
        ).command.values
        expected = context.command(state.mean[-1])
        total += sum(abs(p - e) for p, e in zip(predicted, expected, strict=True))
    return total / (PROBE_COUNT * len(EFFECTIVENESS))


@dataclass(frozen=True, slots=True)
class Trial:
    """One highway-then-rain experiment.

    Attributes:
        highway_before: Highway error after loading the offline twin.
        highway_after: Highway error after then adapting to rain.
        rain_before: Rain error before adapting -- a highway twin judged on rain.
            The baseline plasticity is measured against, because "rain error
            0.18" means nothing until you know it started at 0.18.
        rain_after: Rain error after adapting to rain.
    """

    highway_before: float
    highway_after: float
    rain_before: float
    rain_after: float

    @property
    def forgetting(self) -> float:
        """Return how much highway accuracy was lost, in absolute error."""
        return self.highway_after - self.highway_before

    @property
    def learned(self) -> float:
        """Return how much rain accuracy was gained, in absolute error."""
        return self.rain_before - self.rain_after

    @property
    def gap_closed(self) -> float:
        """Return the fraction of the context change FB2 actually learned."""
        return self.learned / self.rain_before

    @property
    def interference(self) -> float:
        """Return highway accuracy lost per unit of rain accuracy gained.

        The scale-free statement of catastrophic interference, and deliberately
        not a bare error threshold: how well the offline stage happened to
        converge changes every absolute number here but leaves this one alone.
        """
        return self.forgetting / self.learned


def _trial(checkpoint: Path, *, labelled: ContextClass | None = None) -> Trial:
    """Start from a highway-trained twin, adapt it to rain, measure both.

    Args:
        checkpoint: A twin already trained on the highway.
        labelled: The context to tell the twin the rain belongs to. ``None``
            tells it the truth; the control test lies, to put both contexts
            through one head.

    Returns:
        The trial's four numbers.
    """
    twin = _twin()
    twin.load_checkpoint(checkpoint)
    highway_before = _error_on(twin, HIGHWAY)
    rain_before = _error_on(twin, RAIN, through=labelled)
    _drive(twin, RAIN, count=RAIN_SAMPLES, labelled=labelled)
    return Trial(
        highway_before=highway_before,
        highway_after=_error_on(twin, HIGHWAY),
        rain_before=rain_before,
        rain_after=_error_on(twin, RAIN, through=labelled),
    )


@pytest.fixture(scope="module")
def highway_twin(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A twin trained offline on the highway, shared by every trial."""
    path = tmp_path_factory.mktemp("twin") / "highway.pt"
    _pretrain(HIGHWAY, path)
    return path


@pytest.fixture(scope="module")
def separated(highway_twin: Path) -> Trial:
    """Rain adapted into the rain head, as ADR-0019 intends."""
    return _trial(highway_twin)


@pytest.fixture(scope="module")
def shared_head(highway_twin: Path) -> Trial:
    """Rain adapted into the *highway* head -- the pre-ADR-0019 behaviour."""
    return _trial(highway_twin, labelled=HIGHWAY.klass)


# --------------------------------------------------------------------------- #
# The experiment is meaningful before anything is concluded from it
# --------------------------------------------------------------------------- #


def test_the_offline_twin_knows_the_highway(separated: Trial) -> None:
    # Everything below is a statement about a highway error. If the twin never
    # knew the highway, they are all statements about noise.
    assert separated.highway_before < 0.01, (
        f"the offline twin did not learn the highway ({separated.highway_before:.6f} "
        "mean absolute error); nothing downstream of this measures forgetting"
    )


def test_the_two_contexts_are_actually_different() -> None:
    # If highway and rain demanded similar commands, adapting to one would fit
    # the other for free and every arm would look protected.
    separation = sum(
        abs(h - r) for h, r in zip(HIGHWAY.command(2.0), RAIN.command(2.0), strict=True)
    )

    assert separation > 0.3, "the contexts are too alike to distinguish forgetting from noise"


def test_forgetting_is_real_when_one_head_serves_both_contexts(shared_head: Trial) -> None:
    # THE control, and the reason the exact-equality assertion below is worth
    # anything: it would also pass on a twin that adapted nothing at all.
    # Driving the same rain through the highway head is exactly what the code did
    # before ADR-0019, reproduced by mislabelling the context rather than by
    # keeping the old implementation around to rot.
    #
    # Stated as interference rather than as an error bound: the shared head must
    # give up a substantial part of the highway for what it gains in rain. That
    # framing survives the offline stage converging better or worse on a given
    # day, which a bare "highway error exceeds X" does not. Measured: 0.85 --
    # nearly a unit of highway lost per unit of rain gained.
    assert shared_head.interference > 0.5, (
        f"a shared head lost {shared_head.forgetting:.4f} of highway accuracy while "
        f"gaining {shared_head.learned:.4f} of rain, an interference ratio of "
        f"{shared_head.interference:.2f}; the experiment is not provoking "
        "catastrophic forgetting, so it cannot show that anything prevents it"
    )


def test_fb2_moves_a_trained_twin_toward_a_new_context(separated: Trial) -> None:
    # The other half of the premise. Worth reading directly: FB2 closes about a
    # fifth of the gap over 4,000 samples, which is 200 seconds of driving at
    # 20 Hz. It is slow. It is not inert, which is all this premise needs.
    assert separated.gap_closed > 0.10, (
        f"FB2 closed only {separated.gap_closed:.1%} of the context change "
        f"({separated.rain_before:.4f} -> {separated.rain_after:.4f}); with no "
        "adaptation there is no forgetting to prevent and nothing here means anything"
    )


# --------------------------------------------------------------------------- #
# The result
# --------------------------------------------------------------------------- #


def test_adapting_to_rain_leaves_the_highway_bit_for_bit_unchanged(separated: Trial) -> None:
    # THE test, and the whole content of ADR-0019. Not "forgetting is small" --
    # exactly zero, because the parameters the highway is read from were never in
    # the optimiser. An approximate assertion would leave room for a future
    # change to reintroduce cross-context interference and still pass.
    assert separated.highway_after == separated.highway_before, (
        f"the highway moved by {separated.forgetting:.3e} while the twin adapted to "
        "rain. Forgetting is supposed to be structurally impossible here, so any "
        "change at all means something is writing across heads -- check that the "
        "shared trunk is still frozen during adaptation"
    )
    assert separated.interference == 0.0


def test_the_separated_head_learns_at_least_as_well_as_a_shared_one(
    separated: Trial, shared_head: Trial
) -> None:
    # Zero forgetting bought at the price of learning would be FB2 switched off
    # with extra steps. The point of structure over a penalty is that it costs
    # nothing in plasticity: the rain head sees exactly the same gradients it
    # would have if it were the only head.
    assert separated.gap_closed >= shared_head.gap_closed * 0.99, (
        f"separating the heads closed {separated.gap_closed:.1%} of the gap against "
        f"{shared_head.gap_closed:.1%} shared; structure is supposed to prevent "
        "interference without slowing adaptation, which is exactly what the elastic "
        "penalty it replaced could not do"
    )
