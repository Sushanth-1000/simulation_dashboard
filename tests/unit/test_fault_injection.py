"""Does the fault injector actually inject?

Why this file was written before anything used the injector
------------------------------------------------------------
A fault injector nobody has verified is worth less than no injector at all. It
produces a table headed *"faults the gates did not catch"* which is really a
table of faults that were never injected, and every row of it reads as evidence
that the system is fine.

That is the same failure this project has now been bitten by three times, and
each time the mechanism was different while the shape was identical:

- the fail-safe speed cap (OD-2) was recorded on every capped tick and reached
  no actuator -- a run held 17.2 m/s **in HALT** while every audit row agreed it
  had been capped;
- the consolidation penalty (E-28) was configured, documented, and bit-for-bit
  inert -- forgetting 0.038951 against 0.038972 unregularised;
- the OOD counter (OD-5) counted past its own ceiling for 1,508 ticks.

None was caught by the test suite, because in each case the code did exactly
what it said and the *composition* was wrong. What caught them was measuring the
mechanism against something that could disagree with it. So the assertions here
are deliberately not "the injector was called" or "the payload is a dict". They
are about the difference between what was **asked for** and what was
**achieved**, which is the only pair that can disagree.

The rule this file enforces
----------------------------
Every fault kind must be shown to change a reading it was pointed at, to leave
alone every reading it was not, and to report the size of the change it actually
made rather than the size it was configured with. ``FaultEpisode`` carries
``peak_absolute_error`` for exactly this reason: an injector that had silently
stopped injecting would still report its specification unchanged, and only the
measured peak would fall to zero.

The control that keeps this honest
-----------------------------------
:func:`test_a_clean_window_is_returned_byte_identical` is the one that would
still pass on an injector that did nothing at all -- so it is paired with
:func:`test_every_kind_reports_the_error_it_actually_injected`, which fails on
precisely that injector. Neither is sufficient alone. Together they say the
injector changes what it should and nothing else.
"""

from __future__ import annotations

import statistics

import pytest

from training.faults import (
    FaultChannel,
    FaultInjector,
    FaultKind,
    FaultSpec,
    bias,
    drift,
    dropout,
    noise_burst,
    stuck_at,
)

CLEAN = {"y": 0.25, "v": 13.0, "a": 0.4}
"""A representative clean reading: 0.25 m off centre at 13 m/s, gently turning."""

SIGMAS = {
    FaultChannel.POSITION_Y: 0.1,
    FaultChannel.SPEED: 0.01,
    FaultChannel.LATERAL_ACCELERATION: 0.04,
}
"""The declared sigmas, matching ``training.closed_loop.CHANNEL_SIGMAS``."""

SEED = 20260809


def build(*specs: FaultSpec) -> FaultInjector:
    return FaultInjector(specs, seed=SEED, sigmas=SIGMAS)


def published(
    injector: FaultInjector, tick: int, payload: dict[str, float] | None = None
) -> dict[str, float]:
    """Return the corrupted reading, having asserted one was published at all.

    ``corrupt`` returns ``None`` for a dropout, and a test that indexes that
    without saying so would fail with a ``TypeError`` several lines from the
    thing that went wrong.
    """
    result = injector.corrupt(CLEAN if payload is None else payload, tick=tick)
    assert result is not None
    return result


# --------------------------------------------------------------------------- #
# The specification refuses to be configured inert
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("kwargs", "because"),
    [
        (
            {
                "kind": FaultKind.BIAS,
                "first_tick": 10,
                "last_tick": 20,
                "magnitude": 0.0,
                "channel": FaultChannel.SPEED,
            },
            "a zero-magnitude bias would inject nothing",
        ),
        (
            {
                "kind": FaultKind.DRIFT,
                "first_tick": 10,
                "last_tick": 5,
                "magnitude": 1.0,
                "channel": FaultChannel.SPEED,
            },
            "the window ends before it starts",
        ),
        (
            {
                "kind": FaultKind.BIAS,
                "first_tick": -1,
                "last_tick": 20,
                "magnitude": 1.0,
                "channel": FaultChannel.SPEED,
            },
            "there is no tick before zero",
        ),
        (
            {
                "kind": FaultKind.DROPOUT,
                "first_tick": 10,
                "last_tick": 20,
                "channel": FaultChannel.SPEED,
            },
            "a dropout removes the whole reading, not one channel of it",
        ),
        (
            {
                "kind": FaultKind.STUCK_AT,
                "first_tick": 10,
                "last_tick": 20,
                "magnitude": 3.0,
                "channel": FaultChannel.SPEED,
            },
            "a frozen channel has no severity to be given",
        ),
        (
            {"kind": FaultKind.BIAS, "first_tick": 10, "last_tick": 20, "magnitude": 1.0},
            "a bias needs to know what it is biasing",
        ),
        (
            {
                "kind": FaultKind.NOISE_BURST,
                "first_tick": 10,
                "last_tick": 20,
                "magnitude": 1.0,
                "channel": FaultChannel.SPEED,
            },
            "a multiplier of one leaves the stream no worse than clean",
        ),
        (
            {
                "kind": FaultKind.BIAS,
                "first_tick": 10,
                "last_tick": 20,
                "magnitude": float("inf"),
                "channel": FaultChannel.SPEED,
            },
            "an infinite offset is a defect in the caller, not a fault model",
        ),
    ],
)
def test_an_inert_or_incoherent_specification_is_refused(
    kwargs: dict[str, object], because: str
) -> None:
    # An injector that does nothing must not be a quiet injector. It must be a
    # rejected one -- the failure is at construction or it is invisible.
    with pytest.raises(ValueError, match=r".+"):
        FaultSpec(**kwargs)  # type: ignore[arg-type]
    assert because  # the reason is the documentation for the case


def test_a_well_formed_specification_reports_its_own_window() -> None:
    spec = bias(FaultChannel.SPEED, first_tick=100, last_tick=199, offset=2.0)

    assert spec.tick_count == 100
    assert not spec.covers(99)
    assert spec.covers(100)
    assert spec.covers(199)
    assert not spec.covers(200)


# --------------------------------------------------------------------------- #
# Each kind corrupts what it names, the way it says it does
# --------------------------------------------------------------------------- #


def test_a_bias_offsets_exactly_its_channel_by_exactly_its_magnitude() -> None:
    injector = build(bias(FaultChannel.SPEED, first_tick=5, last_tick=7, offset=-3.0))

    faulted = published(injector, 6)

    assert faulted == {"y": 0.25, "v": 10.0, "a": 0.4}


def test_a_drift_ramps_from_nothing_to_its_final_magnitude() -> None:
    # The fault no per-tick threshold can see: at every tick the step is
    # 0.01 m, and after a hundred ticks the reading is a metre wrong.
    injector = build(drift(FaultChannel.POSITION_Y, first_tick=0, last_tick=100, final=1.0))

    assert published(injector, 0)["y"] == pytest.approx(0.25)
    assert published(injector, 50)["y"] == pytest.approx(0.75)
    assert published(injector, 100)["y"] == pytest.approx(1.25)


def test_a_stuck_channel_holds_the_value_it_froze_at_while_the_world_moves() -> None:
    # The reading stays fresh and well-formed the whole time, which is what
    # makes this invisible to a staleness rule.
    injector = build(stuck_at(FaultChannel.SPEED, first_tick=1, last_tick=3))

    published(injector, 1, {"y": 0.0, "v": 13.0, "a": 0.0})
    later = published(injector, 3, {"y": 0.0, "v": 20.0, "a": 0.0})

    assert later["v"] == 13.0


def test_a_noise_burst_inflates_the_stream_without_moving_the_declared_sigma() -> None:
    multiplier = 50.0
    injector = build(
        noise_burst(
            FaultChannel.LATERAL_ACCELERATION,
            first_tick=0,
            last_tick=999,
            sigma_multiplier=multiplier,
        )
    )

    samples = [published(injector, tick)["a"] for tick in range(1000)]
    injected = statistics.stdev(samples)
    declared = SIGMAS[FaultChannel.LATERAL_ACCELERATION]

    # Asserted on the sample standard deviation rather than on the range. The
    # range of n draws has a standard deviation of roughly half a sigma, so a
    # "six sigma" floor sits about one sigma from failing -- which is how a
    # deterministic test acquires a one-in-six chance of being wrong the day
    # someone changes the seed. The sample sigma over 1,000 draws is accurate
    # to about 2%, so a +/-20% band is nine of its own sigmas wide.
    assert injected == pytest.approx(declared * multiplier, rel=0.2)
    assert declared == 0.04  # and the number the filter was told has not moved


def test_a_dropout_publishes_nothing_at_all() -> None:
    injector = build(dropout(first_tick=4, last_tick=6))

    assert injector.corrupt(CLEAN, tick=3) == CLEAN
    assert injector.corrupt(CLEAN, tick=5) is None
    assert injector.corrupt(CLEAN, tick=7) == CLEAN


def test_a_dropout_suppresses_every_other_fault_on_the_same_tick() -> None:
    # A reading that was never published cannot also be biased. Counting it as
    # both would inflate the denominator every detection rate is taken over.
    injector = build(
        bias(FaultChannel.SPEED, first_tick=0, last_tick=10, offset=5.0),
        dropout(first_tick=4, last_tick=6),
    )

    for tick in range(11):
        injector.corrupt(CLEAN, tick=tick)

    bias_episode, dropout_episode = injector.episodes
    assert bias_episode.ticks_applied == 8  # eleven ticks less the three dropped
    assert dropout_episode.ticks_applied == 3
    assert dropout_episode.peak_absolute_error is None


def test_overlapping_faults_compose_in_the_order_they_were_given() -> None:
    # A sensor that drifts and then freezes is two specifications, not a sixth
    # fault kind.
    injector = build(
        bias(FaultChannel.SPEED, first_tick=0, last_tick=9, offset=1.0),
        bias(FaultChannel.SPEED, first_tick=5, last_tick=9, offset=2.0),
    )

    assert published(injector, 4)["v"] == pytest.approx(14.0)
    assert published(injector, 6)["v"] == pytest.approx(16.0)


# --------------------------------------------------------------------------- #
# Nothing happens where nothing was asked for
# --------------------------------------------------------------------------- #


def test_a_clean_window_is_returned_byte_identical() -> None:
    injector = build(bias(FaultChannel.SPEED, first_tick=100, last_tick=200, offset=5.0))

    assert injector.corrupt(CLEAN, tick=99) == CLEAN
    assert injector.corrupt(CLEAN, tick=201) == CLEAN


def test_a_fault_touches_no_channel_but_its_own() -> None:
    injector = build(bias(FaultChannel.SPEED, first_tick=0, last_tick=10, offset=5.0))

    faulted = published(injector, 5)

    assert faulted["y"] == CLEAN["y"]
    assert faulted["a"] == CLEAN["a"]


def test_an_injector_with_nothing_active_draws_no_randomness() -> None:
    # This is the property that makes `fault=None` and "an injector whose
    # window has not opened" the same run to the byte. If the injector drew
    # even one number per tick, every measurement-noise draw after it would
    # re-phase, and an ASTRA-versus-baseline comparison would differ in two
    # ways at once with no way to attribute the outcome to either.
    injector = build(
        noise_burst(FaultChannel.SPEED, first_tick=500, last_tick=600, sigma_multiplier=10.0)
    )
    before = injector._random.getstate()

    for tick in range(500):
        injector.corrupt(CLEAN, tick=tick)

    assert injector._random.getstate() == before


def test_the_injector_stream_is_disjoint_from_any_stream_seeded_the_same_way() -> None:
    import random  # noqa: PLC0415 - local, so the module-level namespace stays the injector's

    harness = random.Random(SEED)
    injector = build(
        noise_burst(FaultChannel.SPEED, first_tick=0, last_tick=99, sigma_multiplier=10.0)
    )

    assert injector._random.getstate() != harness.getstate()


def test_two_injectors_with_the_same_seed_agree_tick_for_tick() -> None:
    def run() -> list[float]:
        injector = build(
            noise_burst(FaultChannel.SPEED, first_tick=0, last_tick=49, sigma_multiplier=10.0)
        )
        return [published(injector, tick)["v"] for tick in range(50)]

    assert run() == run()


# --------------------------------------------------------------------------- #
# The injector reports what it did, not what it was asked to do
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "spec",
    [
        bias(FaultChannel.SPEED, first_tick=0, last_tick=9, offset=2.0),
        drift(FaultChannel.POSITION_Y, first_tick=0, last_tick=9, final=1.0),
        noise_burst(FaultChannel.SPEED, first_tick=0, last_tick=9, sigma_multiplier=20.0),
    ],
    ids=["bias", "drift", "noise_burst"],
)
def test_every_kind_reports_the_error_it_actually_injected(spec: FaultSpec) -> None:
    # The assertion that fails on an injector which has silently become a
    # no-op. `spec.magnitude` is intent and would survive that; the peak is
    # measured against the clean reading and would not.
    injector = build(spec)

    for tick in range(10):
        injector.corrupt(CLEAN, tick=tick)

    (episode,) = injector.episodes
    assert episode.ticks_applied == 10
    assert episode.peak_absolute_error is not None
    assert episode.peak_absolute_error > 0.0


def test_a_stuck_channel_reports_the_divergence_it_caused() -> None:
    injector = build(stuck_at(FaultChannel.SPEED, first_tick=0, last_tick=2))

    injector.corrupt({"y": 0.0, "v": 13.0, "a": 0.0}, tick=0)
    injector.corrupt({"y": 0.0, "v": 15.0, "a": 0.0}, tick=1)
    injector.corrupt({"y": 0.0, "v": 18.0, "a": 0.0}, tick=2)

    (episode,) = injector.episodes
    assert episode.peak_absolute_error == pytest.approx(5.0)


def test_a_window_that_falls_outside_the_run_reports_nothing_applied() -> None:
    # Not an error, and it must not read as one: this is how the control arm of
    # a comparison is built -- the same injector, the same seed, a window the
    # run never reaches.
    injector = build(bias(FaultChannel.SPEED, first_tick=10_000, last_tick=10_100, offset=5.0))

    for tick in range(100):
        injector.corrupt(CLEAN, tick=tick)

    (episode,) = injector.episodes
    assert episode.ticks_applied == 0
    assert episode.peak_absolute_error == 0.0
    assert not injector.is_active(50)


def test_the_ground_truth_label_agrees_with_the_windows_it_was_built_from() -> None:
    injector = build(
        bias(FaultChannel.SPEED, first_tick=10, last_tick=20, offset=1.0),
        dropout(first_tick=50, last_tick=52),
    )

    assert [tick for tick in range(60) if injector.is_active(tick)] == [
        *range(10, 21),
        *range(50, 53),
    ]
    assert injector.drops_reading(51)
    assert not injector.drops_reading(15)
