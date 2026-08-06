"""Does adapting the twin to rain destroy what it knew about the highway?

This is the test `PENDING.md` P3.1 says to write **before** wiring FB2 into the
tick loop, and the reason is worth restating: without it you cannot tell
adaptation from destruction. A twin that has forgotten the highway does not fail
loudly. It predicts confidently and wrongly, the non-conformity score
``|pi_prop - pi_hat| / sigma`` is computed against a wrong reference, and two
gates then reason carefully about a number that means nothing.

Why this is a comparison and not a threshold
--------------------------------------------
The obvious test is *"highway error after adapting to rain must stay below X"*.
That test is worthless, because X gets chosen until the test passes and then
measures nothing but the choice. RK-5 already records that EWC **may fail** to
prevent forgetting, so the question is not "is the error small" but "does the
penalty do anything at all".

So every test here runs the identical experiment twice, at the configured
``ewc_lambda`` and at zero, from the same seed, and compares. Lambda zero is not
a hypothetical: it is precisely what a lambda too small to matter reduces to, and
that is the defect P3.1 names --

    *EWC is inert at the configured lambda. Do not ship a value that does
    nothing while the configuration implies it does something.*

A pair of runs that forget equally means the configured value is decoration.

Where the experiment starts
---------------------------
FB2 trains **only the output layer**, on top of a hidden layer it freezes. That
is the right design -- adaptation should adjust a trained twin, not retrain one --
but it means an experiment that starts from seeded random weights is measuring
something the mechanism was never meant to do. Measured on the way to writing
this: from random initialisation, 2,400 samples of one context moved the output
layer's parameters by 0.14 in norm and left the error at 0.094, converged and
useless. So each trial below **pre-trains the whole network on the highway
first**, exactly as ``training/train_twin.py`` does with Adam over both layers,
and only then hands over to FB2. That is where a real twin starts.

The two contexts
----------------
"Highway" and "rain" are two different mappings from motion to command: the same
lateral acceleration is produced by a larger steering command on a slippery road.
That is what a context change *is* for this twin, whose input is
``(v, sin psi, cos psi, a_lat)`` and whose output is a command. Both are linear
and exactly learnable by the output layer, which is deliberate -- a context the
network cannot represent would make every result a statement about capacity
rather than about consolidation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import pytest
import torch

from astra.config.loader import load_settings
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
PRETRAIN_EPOCHS = 4_000
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


def _settings(ewc_lambda: float) -> TwinSettings:
    return TwinSettings(
        physics_weight=1.0,
        ewc_lambda=ewc_lambda,
        control_effectiveness=list(EFFECTIVENESS),
        hidden_width=16,
        adaptation_buffer=BUFFER,
        adaptation_steps=10,
        fisher_sample_count=120,
        seed=11,
    )


def _twin(ewc_lambda: float) -> PhysicsInformedTwin:
    return PhysicsInformedTwin(
        settings=_settings(ewc_lambda),
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

    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(network.state_dict(), path)


def _drive(twin: PhysicsInformedTwin, context: Context, *, count: int) -> None:
    """Feed one context's worth of executed outcomes through ``adapt``."""
    space = _space()
    for index in range(count):
        state = _state(index)
        twin.adapt(
            applied=ControlCommand(values=context.command(state.mean[-1]), space=space),
            measured=state,
            context=context.klass,
        )


def _error_on(twin: PhysicsInformedTwin, context: Context) -> float:
    """Return the twin's mean absolute command error in a context.

    Args:
        twin: The twin to probe.
        context: The context whose mapping is the ground truth.

    Returns:
        Mean absolute error over held-out states, across both channels.
    """
    total = 0.0
    for index in range(PROBE_COUNT):
        # Phase-shifted: different states, same underlying mapping.
        state = _state(index, phase=1.7)
        predicted = twin.predict(tick=TickId(index), state=state).command.values
        expected = context.command(state.mean[-1])
        total += sum(abs(p - e) for p, e in zip(predicted, expected, strict=True))
    return total / (PROBE_COUNT * len(EFFECTIVENESS))


@dataclass(frozen=True, slots=True)
class Trial:
    """One highway-then-rain experiment.

    Attributes:
        ewc_lambda: The penalty strength this trial ran at.
        highway_before: Highway error after learning the highway.
        highway_after: Highway error after then adapting to rain.
        rain_before: Rain error *before* adapting -- a highway twin judged on
            rain. The baseline plasticity is measured against, because "rain
            error 0.18" means nothing until you know it started at 0.18.
        rain_after: Rain error after adapting to rain.
    """

    ewc_lambda: float
    highway_before: float
    highway_after: float
    rain_before: float
    rain_after: float

    @property
    def forgetting(self) -> float:
        """Return how much highway accuracy was lost, in absolute error."""
        return self.highway_after - self.highway_before

    @property
    def gap_closed(self) -> float:
        """Return the fraction of the context change FB2 actually learned."""
        return (self.rain_before - self.rain_after) / self.rain_before


def _trial(ewc_lambda: float, checkpoint: Path) -> Trial:
    """Start from a highway-trained twin, adapt it to rain, measure both.

    Args:
        ewc_lambda: The penalty strength.
        checkpoint: A twin already trained on the highway.

    Returns:
        The trial's four numbers.
    """
    twin = _twin(ewc_lambda)
    twin.load_checkpoint(checkpoint)
    highway_before = _error_on(twin, HIGHWAY)
    rain_before = _error_on(twin, RAIN)
    _drive(twin, RAIN, count=RAIN_SAMPLES)
    return Trial(
        ewc_lambda=ewc_lambda,
        highway_before=highway_before,
        highway_after=_error_on(twin, HIGHWAY),
        rain_before=rain_before,
        rain_after=_error_on(twin, RAIN),
    )


@pytest.fixture(scope="module")
def highway_twin(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A twin trained offline on the highway, shared by both arms.

    One checkpoint for both trials, so the only difference between them is the
    penalty. Re-training per arm would put a second source of variation between
    numbers whose difference is the entire result.
    """
    path = tmp_path_factory.mktemp("twin") / "highway.pt"
    _pretrain(HIGHWAY, path)
    return path


@pytest.fixture(scope="module")
def unregularised(highway_twin: Path) -> Trial:
    """The control arm: no penalty at all."""
    return _trial(0.0, highway_twin)


@pytest.fixture(scope="module")
def configured(highway_twin: Path) -> Trial:
    """The shipped arm, at whatever ``simulation.toml`` sets."""
    resolved = load_settings(environment="simulation", include_environment_variables=False)
    return _trial(float(resolved.settings.twin.ewc_lambda), highway_twin)


# --------------------------------------------------------------------------- #
# The experiment is meaningful before anything is concluded from it
# --------------------------------------------------------------------------- #


def test_the_offline_twin_knows_the_highway(unregularised: Trial) -> None:
    # Every result below is a difference between two highway errors. If the twin
    # never knew the highway, both are the error of an untrained network and the
    # comparison is between two kinds of noise.
    assert unregularised.highway_before < 0.05, (
        f"the twin did not learn the highway ({unregularised.highway_before:.4f} "
        "mean absolute error); nothing downstream of this measures forgetting"
    )


def test_fb2_moves_a_trained_twin_toward_a_new_context(unregularised: Trial) -> None:
    # The other half of the premise, and a measurement worth reading directly:
    # an unregularised twin closes about a fifth of the gap over 4,000 samples,
    # which is 200 seconds of driving at 20 Hz. FB2 is slow. It is not, however,
    # inert, which is all this premise needs.
    assert unregularised.gap_closed > 0.10, (
        f"FB2 closed only {unregularised.gap_closed:.1%} of the context change "
        f"even unregularised ({unregularised.rain_before:.4f} -> "
        f"{unregularised.rain_after:.4f}); with no adaptation there is no "
        "forgetting to prevent and nothing below means anything"
    )


def test_the_two_contexts_are_actually_different() -> None:
    # If highway and rain demanded similar commands, adapting to one would fit
    # the other for free and every arm would look regularised.
    separation = sum(
        abs(h - r) for h, r in zip(HIGHWAY.command(2.0), RAIN.command(2.0), strict=True)
    )

    assert separation > 0.3, "the contexts are too alike to distinguish forgetting from noise"


def test_forgetting_happens_without_the_penalty(unregularised: Trial) -> None:
    # The defect this whole file exists to detect, demonstrated in the arm that
    # should show it. If an unregularised twin did not forget, EWC would have
    # nothing to do and a passing comparison would prove nothing.
    # A ratio, not an absolute bound. "Forgetting exceeds 0.05" is a number
    # chosen without knowing the scale; what makes forgetting catastrophic is
    # that it is enormous *relative to how well the twin knew the task*, and the
    # offline twin knows the highway to 2.5e-4. Measured: 159x.
    assert unregularised.highway_after > unregularised.highway_before * 20.0, (
        f"an unregularised twin went from {unregularised.highway_before:.6f} to "
        f"{unregularised.highway_after:.6f} highway error, only "
        f"{unregularised.highway_after / unregularised.highway_before:.1f}x; the "
        "experiment is not provoking catastrophic forgetting, so it cannot show "
        "that anything prevents it"
    )


# --------------------------------------------------------------------------- #
# The result
# --------------------------------------------------------------------------- #


def test_the_configured_lambda_is_not_inert(configured: Trial, unregularised: Trial) -> None:
    # THE test. P3.1: "Do not ship a value that does nothing while the
    # configuration implies it does something." A configured penalty that forgets
    # as much as no penalty at all is a comment, not a mechanism -- and worse
    # than no penalty, because the configuration claims protection that a reader
    # will believe.
    assert configured.forgetting < unregularised.forgetting * 0.75, (
        f"ewc_lambda={configured.ewc_lambda:g} forgets {configured.forgetting:.4f} "
        f"against {unregularised.forgetting:.4f} unregularised -- the penalty is "
        "inert at the configured value. Either raise it until this passes or "
        "rescale the term; do not relax this bound."
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "OPEN, measured 2 August 2026: the penalty is a brake, not a consolidator. "
        "Across lambda from 0 to 1e5 the ratio of forgetting to gap-closed is "
        "constant to three significant figures -- 0.00184, 0.00184, 0.00186, "
        "0.00186, 0.00194 -- so EWC buys nothing here that a smaller learning "
        "rate would not buy equally. Structural rather than a tuning miss: FB2 "
        "adapts a 16->2 linear readout and both contexts use all of it, so there "
        "is no disjoint parameter subspace for a Fisher-weighted penalty to "
        "exploit. RK-5 anticipated exactly this. Recorded as P3.1a; the candidate "
        "answer is a per-ContextClass output head, which makes forgetting "
        "structurally impossible instead of penalised. Do not delete this test "
        "to make the suite green -- it is the statement of the defect."
    ),
)
def test_the_penalty_protects_the_old_context_more_than_it_blocks_the_new(
    configured: Trial, unregularised: Trial
) -> None:
    # What "consolidation" actually claims: that the penalty is *selective*, and
    # gives up less plasticity than it buys in retention. A penalty that scales
    # both down together is a speed dial with a misleading name.
    retention_gain = unregularised.forgetting / max(configured.forgetting, 1e-9)
    plasticity_cost = unregularised.gap_closed / max(configured.gap_closed, 1e-9)

    assert retention_gain > plasticity_cost * 1.5, (
        f"at ewc_lambda={configured.ewc_lambda:g} forgetting improved "
        f"{retention_gain:.2f}x while adaptation slowed {plasticity_cost:.2f}x; "
        "the penalty is not distinguishing the highway's parameters from the "
        "rain's, it is slowing every parameter down"
    )


def test_the_highway_is_still_usable_after_the_rain(configured: Trial) -> None:
    # What the shipped value has to deliver even if the mechanism is only a
    # brake. The twin's prediction is the right operand of every ICP score, so
    # what survives has to be good enough to compute one against.
    assert configured.highway_after < 0.01, (
        f"highway error after adapting to rain is {configured.highway_after:.4f}; "
        "a twin this wrong makes both gates reason about a meaningless number"
    )


def test_the_shipped_lambda_still_permits_some_adaptation(configured: Trial) -> None:
    # The other side of the brake. A lambda that stopped FB2 entirely would be
    # the loop switched off with extra steps -- and switching it off is a
    # decision to take deliberately, in configuration a reader can see, not one
    # to arrive at because a penalty was set too high.
    assert configured.gap_closed > 0.0, (
        f"at ewc_lambda={configured.ewc_lambda:g} the twin learned nothing at all "
        f"about the new context ({configured.rain_before:.4f} -> "
        f"{configured.rain_after:.4f}); FB2 is off"
    )
