"""Unit tests for L9's hot path, shadow execution and the divergence index."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from astra.contracts.actuation import (
    ActuationChannel,
    ActuationSpace,
    CommandOrigin,
    ControlCommand,
    ProposedCommand,
)
from astra.contracts.assurance import FailSafeSnapshot, GateVerdict, SafetyVerdict, TrustAssessment
from astra.contracts.estimation import FastStateEstimate
from astra.contracts.governance import (
    ArbitrationDecision,
    CalibrationProfile,
    ProfileFieldHistory,
    RuntimeContextSignature,
)
from astra.kernel.enums import (
    ArbitrationOutcome,
    ContextClass,
    FailSafeState,
    GateId,
    LayerId,
    Verdict,
)
from astra.kernel.errors import ConfigurationError, SafetyPathError
from astra.kernel.identifiers import ComponentId, ProfileId, TickId
from astra.kernel.matrix import SymmetricMatrix
from astra.kernel.time import Instant, ManualClock, Timeline
from astra.kernel.units import MetresPerSecond, Probability
from astra.layers.l9_rcm.arbiter import (
    SHADOW_PATIENCE,
    FallbackController,
    RuntimeCalibrationManager,
)
from astra.layers.l9_rcm.knowledge_base import SearchWeights
from astra.layers.l9_rcm.shadow import MINIMUM_SHADOW_SAMPLES, ShadowExecution
from astra.ports.pipeline import CalibrationArbiter

if TYPE_CHECKING:
    from collections.abc import Sequence

AT = Instant(1_000, Timeline.MANUAL)
NOW = datetime(2026, 7, 1, tzinfo=UTC)
CERTIFIED = datetime(2025, 1, 1, tzinfo=UTC)
LATER = datetime(2027, 7, 1, tzinfo=UTC)
PLATFORM = "astra-reference-vehicle"
WEIGHTS = SearchWeights(similarity=1.0, validation=1.0, history=0.5, risk=0.25)

SPACE = ActuationSpace(
    (
        ActuationChannel(name="throttle", lower=0.0, upper=1.0, unit="1"),
        ActuationChannel(name="steer", lower=-0.5, upper=0.5, unit="rad"),
    )
)
# The adapter's job: the envelope encoded as narrowed channel bounds, because
# this layer may not know which channel is steering.
EXPLORATION_SPACE = ActuationSpace(
    (
        ActuationChannel(name="throttle", lower=0.0, upper=0.3, unit="1"),
        ActuationChannel(name="steer", lower=-0.26, upper=0.26, unit="rad"),
    )
)


class _StubFallback:
    def __init__(self, values: tuple[float, ...] = (0.1, 0.0)) -> None:
        self.values = values
        self.calls = 0

    def command(self) -> Sequence[float]:
        self.calls += 1
        return self.values


def _profile(
    name: str = "highway_clear",
    *,
    centroid: tuple[float, ...] = (0.5, 0.5, 0.5, 0.5, 0.5),
    context: ContextClass = ContextClass.HIGHWAY_CLEAR,
    validation: float = 1.0,
    passed: bool = True,
) -> CalibrationProfile:
    return CalibrationProfile(
        profile_id=ProfileId(name=name, version=1),
        context_class=context,
        centroid=centroid,
        covariance=SymmetricMatrix.from_diagonal([0.04] * 5),
        quantile_table=(0.1, 0.3, 0.7, 1.2),
        coverage_level=Probability(0.95),
        validation_fraction=Probability(validation),
        validation_passed=passed,
        max_speed=MetresPerSecond(30.0),
        checksum="0" * 64,
        platform=PLATFORM,
        certified_at=CERTIFIED,
        expires_at=LATER,
        field_history=ProfileFieldHistory(),
    )


def _verdict(*verdicts: Verdict) -> SafetyVerdict:
    gates = (GateId.STATISTICAL, GateId.PHYSICAL, GateId.DETERMINISTIC)
    return SafetyVerdict(
        tick=TickId(1),
        gate_verdicts=tuple(
            GateVerdict(tick=TickId(1), gate=gate, verdict=verdict, reason_code="TEST")
            for gate, verdict in zip(gates, verdicts, strict=False)
        ),
    )


def _failsafe(speed_cap: float | None = None) -> FailSafeSnapshot:
    return FailSafeSnapshot(
        tick=TickId(1),
        state=FailSafeState.NOMINAL if speed_cap is None else FailSafeState.DEGRADED,
        ood_counter=0,
        speed_cap=None if speed_cap is None else MetresPerSecond(speed_cap),
    )


def _trust() -> TrustAssessment:
    return TrustAssessment(
        tick=TickId(1),
        trust_index=Probability(0.9),
        context_class=ContextClass.HIGHWAY_CLEAR,
        class_conditional_quantile=0.5,
        coverage_target=Probability(0.95),
        calibration_sample_count=500,
        is_calibrated=True,
    )


def _proposal(values: tuple[float, ...] = (0.5, 0.2)) -> ProposedCommand:
    return ProposedCommand(
        tick=TickId(1),
        proposed_at=AT,
        command=ControlCommand(space=SPACE, values=values),
        origin=CommandOrigin.PROPOSED,
        source=ComponentId(LayerId.L4_CORE_A_CMDP),
    )


JERK_REASON = "LATERAL_JERK_EXCEEDS_LIMIT"
STEER_EFFECTIVENESS = 10.0
JERK_LIMIT = 8.0
TICK_PERIOD = 0.05
# The step the bound permits per tick: 8.0 m/s^3 over 0.05 s.
PERMITTED_STEP = JERK_LIMIT * TICK_PERIOD


class _StubProjector:
    """Puts the target on the steer channel, as the automotive adapter does.

    The test space is (throttle, steer) rather than the automotive
    (throttle, brake, steer), so the cap withdraws propulsion and has no brake
    channel to apply. That is the point of the seam: the projector knows the
    platform and the arbitrator does not.
    """

    def with_lateral_acceleration(
        self, values: Sequence[float], target: float
    ) -> tuple[float, ...]:
        return (float(values[0]), target / STEER_EFFECTIVENESS)

    def with_speed_cap(
        self, values: Sequence[float], *, current_speed: float, cap: float
    ) -> tuple[float, ...]:
        if current_speed <= cap:
            return tuple(float(value) for value in values)
        return (0.0, float(values[1]))


def _fast_state(speed: float = 0.0) -> FastStateEstimate:
    """A state carrying only the field the speed cap reads."""
    return FastStateEstimate(
        tick=TickId(1),
        valid_at=AT,
        mean=(0.0, 0.0, speed, 0.0, 0.0),
        covariance=SymmetricMatrix.from_diagonal([1.0, 1.0, 1.0, 1.0, 1.0]),
    )


def _jerk_verdict(*, current: float, proposed: float) -> SafetyVerdict:
    """A physical-gate VETO carrying the evidence rate limiting reads."""
    jerk = abs(proposed - current) / TICK_PERIOD
    return SafetyVerdict(
        tick=TickId(1),
        gate_verdicts=(
            GateVerdict(
                tick=TickId(1),
                gate=GateId.PHYSICAL,
                verdict=Verdict.VETO,
                reason_code=JERK_REASON,
                evidence=(
                    ("proposed_lateral_acceleration_mps2", proposed),
                    ("current_lateral_acceleration_mps2", current),
                    ("demanded_jerk_mps3", jerk),
                    ("max_lateral_jerk_mps3", JERK_LIMIT),
                ),
            ),
        ),
    )


def _arbiter(
    *,
    fallback: _StubFallback | None = None,
    profiles: list[CalibrationProfile] | None = None,
    active: CalibrationProfile | None = None,
    rate_limiting: bool = False,
    projector: bool | None = None,
) -> RuntimeCalibrationManager:
    resolved_active = active or _profile()
    return RuntimeCalibrationManager(
        component=ComponentId(LayerId.L9_RCM),
        space=SPACE,
        clock=ManualClock(Instant(0, Timeline.MANUAL)),
        fallback=fallback or _StubFallback(),
        profiles=profiles if profiles is not None else [resolved_active],
        weights=WEIGHTS,
        active=resolved_active,
        projector=_StubProjector() if (rate_limiting if projector is None else projector) else None,
        rate_limited_reasons=frozenset({JERK_REASON}) if rate_limiting else frozenset(),
    )


# --------------------------------------------------------------------------- #
# The rule that shapes the layer: always a command
# --------------------------------------------------------------------------- #


def test_the_arbiter_satisfies_the_calibration_arbiter_port() -> None:
    assert isinstance(_arbiter(), CalibrationArbiter)


def test_the_stub_fallback_satisfies_the_fallback_protocol() -> None:
    assert isinstance(_StubFallback(), FallbackController)


@pytest.mark.parametrize(
    "verdicts",
    [
        (Verdict.PASS, Verdict.PASS, Verdict.PASS),
        (Verdict.PASS, Verdict.VETO, Verdict.PASS),
        (Verdict.VETO, Verdict.VETO, Verdict.VETO),
        (),
    ],
)
def test_every_verdict_still_produces_a_command(verdicts: tuple[Verdict, ...]) -> None:
    # Including the empty verdict set, which merges to VETO. A vehicle that
    # stops receiving commands does not become safe.
    issued = _arbiter().issue(
        tick=TickId(1),
        proposal=_proposal(),
        verdict=_verdict(*verdicts),
        failsafe=_failsafe(),
        trust=_trust(),
        state=_fast_state(),
    )

    assert issued.command.is_admissible()


def test_a_blocked_tick_hands_over_to_the_fallback_controller() -> None:
    fallback = _StubFallback((0.2, -0.1))

    issued = _arbiter(fallback=fallback).issue(
        tick=TickId(1),
        proposal=_proposal(),
        verdict=_verdict(Verdict.VETO),
        failsafe=_failsafe(),
        trust=_trust(),
        state=_fast_state(),
    )

    assert issued.origin is CommandOrigin.FALLBACK_PID
    assert issued.command.values == (0.2, -0.1)
    assert fallback.calls == 1


def test_a_passing_tick_issues_the_proposal_unmodified() -> None:
    issued = _arbiter().issue(
        tick=TickId(1),
        proposal=_proposal((0.5, 0.2)),
        verdict=_verdict(Verdict.PASS),
        failsafe=_failsafe(),
        trust=_trust(),
        state=_fast_state(),
    )

    assert issued.origin is CommandOrigin.PROPOSED
    assert issued.command.values == (0.5, 0.2)


def test_a_fail_safe_cap_withdraws_propulsion_above_the_ceiling() -> None:
    # What replaced `test_a_fail_safe_cap_is_recorded_in_the_origin`, which was
    # honestly named and asserted only that a label appeared. The cap was one
    # branch among four and clamped exactly as the uncapped branch did, so the
    # label described a bit-identical vector. Measured: a 100,000-tick run held
    # 17.2 m/s in HALT, whose cap is 0.0 m/s, with 99,000 ticks recorded capped.
    issued = _arbiter(projector=True).issue(
        tick=TickId(1),
        proposal=_proposal((0.5, 0.2)),
        verdict=_verdict(Verdict.PASS),
        failsafe=_failsafe(speed_cap=5.0),
        trust=_trust(),
        state=_fast_state(speed=20.0),
    )

    assert issued.origin is CommandOrigin.SPEED_CAPPED
    assert issued.command.values[0] == pytest.approx(0.0)


def test_a_cap_the_vehicle_is_within_changes_nothing_and_says_so() -> None:
    # The control, and the property that makes the origin mean something: below
    # the ceiling the command passes through and is *not* labelled capped. A cap
    # is a ceiling, not a target.
    issued = _arbiter(projector=True).issue(
        tick=TickId(1),
        proposal=_proposal((0.5, 0.2)),
        verdict=_verdict(Verdict.PASS),
        failsafe=_failsafe(speed_cap=30.0),
        trust=_trust(),
        state=_fast_state(speed=20.0),
    )

    assert issued.origin is CommandOrigin.PROPOSED
    assert issued.command.values[0] == pytest.approx(0.5)


def test_the_cap_binds_on_a_blocked_tick_too() -> None:
    # THE test the old ordering could not pass. The cap used to be reached only
    # after the blocking branch returned, so in HALT -- where every tick is
    # blocked -- it was never consulted at all. HALT's cap is 0.0 m/s.
    fallback = _StubFallback((0.9, 0.0))
    issued = _arbiter(fallback=fallback, projector=True).issue(
        tick=TickId(1),
        proposal=_proposal(),
        verdict=_verdict(Verdict.VETO),
        failsafe=_failsafe(speed_cap=0.0),
        trust=_trust(),
        state=_fast_state(speed=17.2),
    )

    assert issued.origin is CommandOrigin.SPEED_CAPPED
    assert issued.command.values[0] == pytest.approx(0.0)
    assert fallback.calls == 1, "the fallback still governed; the cap shaped what it produced"


def test_the_cap_binds_inside_the_exploration_envelope_too() -> None:
    arbiter = _arbiter(projector=True)
    arbiter.engage_exploration(EXPLORATION_SPACE)

    issued = arbiter.issue(
        tick=TickId(1),
        proposal=_proposal((0.3, 0.2)),
        verdict=_verdict(Verdict.PASS),
        failsafe=_failsafe(speed_cap=5.0),
        trust=_trust(),
        state=_fast_state(speed=20.0),
    )

    assert issued.origin is CommandOrigin.SPEED_CAPPED
    assert issued.command.values[0] == pytest.approx(0.0)


def test_without_a_projector_the_cap_cannot_be_enforced_and_is_not_claimed() -> None:
    # Fail to the honest label rather than to a false one. Enforcing a cap in
    # m/s on a throttle vector needs platform knowledge; absent it, the command
    # is whatever the regimes chose and is not labelled capped.
    issued = _arbiter(projector=False).issue(
        tick=TickId(1),
        proposal=_proposal((0.5, 0.2)),
        verdict=_verdict(Verdict.PASS),
        failsafe=_failsafe(speed_cap=5.0),
        trust=_trust(),
        state=_fast_state(speed=20.0),
    )

    assert issued.origin is CommandOrigin.PROPOSED


def test_the_issuer_is_always_l9() -> None:
    # SI-7. The contract refuses anything else at construction, so this pins
    # that the arbiter stamps its own identity rather than the proposer's.
    issued = _arbiter().issue(
        tick=TickId(1),
        proposal=_proposal(),
        verdict=_verdict(Verdict.PASS),
        failsafe=_failsafe(),
        trust=_trust(),
        state=_fast_state(),
    )

    assert issued.issuer.layer is LayerId.L9_RCM


def test_an_arbiter_built_with_a_non_l9_component_is_refused() -> None:
    with pytest.raises(ConfigurationError, match="L9"):
        RuntimeCalibrationManager(
            component=ComponentId(LayerId.L4_CORE_A_CMDP),
            space=SPACE,
            clock=ManualClock(Instant(0, Timeline.MANUAL)),
            fallback=_StubFallback(),
            profiles=[_profile()],
            weights=WEIGHTS,
            active=_profile(),
        )


# --------------------------------------------------------------------------- #
# Clamping: the seam between a permissive proposal and a strict issue
# --------------------------------------------------------------------------- #


def test_an_inadmissible_proposal_is_clamped_rather_than_refused() -> None:
    # The gates saw the raw proposal; the actuators must not. IssuedCommand
    # would reject an out-of-bounds vector, so this is the last chance.
    issued = _arbiter().issue(
        tick=TickId(1),
        proposal=_proposal((9.0, -9.0)),
        verdict=_verdict(Verdict.PASS),
        failsafe=_failsafe(),
        trust=_trust(),
        state=_fast_state(),
    )

    assert issued.command.values == (1.0, -0.5)
    assert issued.command.is_admissible()


def test_a_fallback_command_out_of_bounds_is_also_clamped() -> None:
    issued = _arbiter(fallback=_StubFallback((5.0, 5.0))).issue(
        tick=TickId(1),
        proposal=_proposal(),
        verdict=_verdict(Verdict.VETO),
        failsafe=_failsafe(),
        trust=_trust(),
        state=_fast_state(),
    )

    assert issued.command.is_admissible()


def test_a_fallback_returning_the_wrong_width_fails_closed() -> None:
    # There is no deeper fallback than the fallback.
    with pytest.raises(SafetyPathError, match="deeper fallback"):
        _arbiter(fallback=_StubFallback((0.1, 0.2, 0.3))).issue(
            tick=TickId(1),
            proposal=_proposal(),
            verdict=_verdict(Verdict.VETO),
            failsafe=_failsafe(),
            trust=_trust(),
            state=_fast_state(),
        )


# --------------------------------------------------------------------------- #
# Bounded safe exploration
# --------------------------------------------------------------------------- #


def test_exploration_clamps_to_the_restricted_space() -> None:
    arbiter = _arbiter()
    arbiter.engage_exploration(EXPLORATION_SPACE)

    issued = arbiter.issue(
        tick=TickId(1),
        proposal=_proposal((0.9, 0.45)),
        verdict=_verdict(Verdict.PASS),
        failsafe=_failsafe(),
        trust=_trust(),
        state=_fast_state(),
    )

    assert issued.origin is CommandOrigin.EXPLORATION_BOUNDED
    assert issued.command.values == (0.3, 0.26)


def test_a_blocking_verdict_outranks_exploration() -> None:
    # ADR-0016, and the reversal of the behaviour this test used to pin. The old
    # ordering made a veto advisory whenever the envelope was engaged: measured
    # over 100,000 ticks, 99,808 of them issued the proposal under a blocking
    # verdict, because at the shipped operating point exploration is engaged
    # almost always.
    #
    # Exploration no longer needs to out-rank anything. The verdicts it used to
    # override were L6 objecting on a calibration it does not hold for the
    # context; L6 abstains there now, so there is no veto left to work around --
    # and any veto that *does* survive came from a gate whose bounds are
    # configuration, and is as true inside the envelope as outside it.
    fallback = _StubFallback()
    arbiter = _arbiter(fallback=fallback)
    arbiter.engage_exploration(EXPLORATION_SPACE)

    issued = arbiter.issue(
        tick=TickId(1),
        proposal=_proposal(),
        verdict=_verdict(Verdict.VETO),
        failsafe=_failsafe(),
        trust=_trust(),
        state=_fast_state(),
    )

    assert issued.origin is CommandOrigin.FALLBACK_PID
    assert fallback.calls == 1


# --------------------------------------------------------------------------- #
# Rate limiting -- ADR-0017, breaking the veto latch
# --------------------------------------------------------------------------- #


def test_a_jerk_veto_issues_the_largest_step_the_bound_permits() -> None:
    # THE test. The fallback commands zero steering, so under a sustained veto
    # the achieved lateral acceleration is pinned at zero and every correction
    # is a step too large from there -- a deadlock no proposer can escape,
    # because a proposal only moves the achieved value if it is executed.
    fallback = _StubFallback()
    arbiter = _arbiter(fallback=fallback, rate_limiting=True)

    issued = arbiter.issue(
        tick=TickId(1),
        proposal=_proposal((0.5, 0.2)),
        verdict=_jerk_verdict(current=0.0, proposed=2.0),
        failsafe=_failsafe(),
        trust=_trust(),
        state=_fast_state(),
    )

    assert issued.origin is CommandOrigin.RATE_LIMITED
    assert fallback.calls == 0
    # 0.0 + 8.0 * 0.05 = 0.4 m/s^2, on the steer channel at effectiveness 10.
    assert issued.command.values[1] == pytest.approx(PERMITTED_STEP / STEER_EFFECTIVENESS)


def test_the_step_never_overshoots_the_proposal() -> None:
    # A proposal already inside the bound is reached exactly, not passed. Without
    # the min() the limiter would oscillate around its target for ever.
    arbiter = _arbiter(rate_limiting=True)

    issued = arbiter.issue(
        tick=TickId(1),
        proposal=_proposal((0.5, 0.2)),
        verdict=_jerk_verdict(current=0.0, proposed=0.1),
        failsafe=_failsafe(),
        trust=_trust(),
        state=_fast_state(),
    )

    assert issued.command.values[1] == pytest.approx(0.1 / STEER_EFFECTIVENESS)


def test_the_step_follows_the_sign_of_the_correction() -> None:
    arbiter = _arbiter(rate_limiting=True)

    issued = arbiter.issue(
        tick=TickId(1),
        proposal=_proposal((0.5, -0.2)),
        verdict=_jerk_verdict(current=0.0, proposed=-2.0),
        failsafe=_failsafe(),
        trust=_trust(),
        state=_fast_state(),
    )

    assert issued.command.values[1] == pytest.approx(-PERMITTED_STEP / STEER_EFFECTIVENESS)


def test_repeated_steps_converge_on_the_proposal() -> None:
    # The property that actually breaks the latch: the achieved acceleration
    # advances by the permitted step each tick, so a correction that is
    # inadmissible now becomes admissible after a few of them, without any gate
    # being overridden on any tick.
    arbiter = _arbiter(rate_limiting=True)
    current = 0.0
    target = 2.0

    for _ in range(10):
        issued = arbiter.issue(
            tick=TickId(1),
            proposal=_proposal((0.5, 0.2)),
            verdict=_jerk_verdict(current=current, proposed=target),
            failsafe=_failsafe(),
            trust=_trust(),
            state=_fast_state(),
        )
        current = issued.command.values[1] * STEER_EFFECTIVENESS

    assert current == pytest.approx(target)


def test_a_veto_from_any_other_gate_falls_back_rather_than_ratcheting() -> None:
    # Rate limiting answers a bound on *rate*. Approaching a command the
    # deterministic shield refused would arrive at it a few ticks later, which
    # is worse than refusing it outright because it looks like compliance.
    fallback = _StubFallback()
    arbiter = _arbiter(fallback=fallback, rate_limiting=True)
    verdict = SafetyVerdict(
        tick=TickId(1),
        gate_verdicts=(
            *_jerk_verdict(current=0.0, proposed=2.0).gate_verdicts,
            GateVerdict(
                tick=TickId(1),
                gate=GateId.DETERMINISTIC,
                verdict=Verdict.VETO,
                reason_code="SPEED_EXCEEDS_LEGAL_LIMIT",
            ),
        ),
    )

    issued = arbiter.issue(
        tick=TickId(1),
        proposal=_proposal(),
        verdict=verdict,
        failsafe=_failsafe(),
        trust=_trust(),
        state=_fast_state(),
    )

    assert issued.origin is CommandOrigin.FALLBACK_PID
    assert fallback.calls == 1


def test_an_arbiter_without_a_projector_keeps_the_old_behaviour() -> None:
    # Rate limiting needs platform knowledge the layer may not have. Absent it,
    # the fallback governs -- which is what every run before ADR-0017 did.
    fallback = _StubFallback()
    arbiter = _arbiter(fallback=fallback, rate_limiting=False)

    issued = arbiter.issue(
        tick=TickId(1),
        proposal=_proposal(),
        verdict=_jerk_verdict(current=0.0, proposed=2.0),
        failsafe=_failsafe(),
        trust=_trust(),
        state=_fast_state(),
    )

    assert issued.origin is CommandOrigin.FALLBACK_PID
    assert fallback.calls == 1


def test_evidence_missing_the_keys_rate_limiting_needs_falls_back() -> None:
    # Fail to the answer that needs no argument. If the gate's evidence ever
    # stops carrying these, rate limiting must go quiet rather than guess.
    fallback = _StubFallback()
    arbiter = _arbiter(fallback=fallback, rate_limiting=True)
    verdict = SafetyVerdict(
        tick=TickId(1),
        gate_verdicts=(
            GateVerdict(
                tick=TickId(1),
                gate=GateId.PHYSICAL,
                verdict=Verdict.VETO,
                reason_code=JERK_REASON,
                evidence=(("something_else", 1.0),),
            ),
        ),
    )

    issued = arbiter.issue(
        tick=TickId(1),
        proposal=_proposal(),
        verdict=verdict,
        failsafe=_failsafe(),
        trust=_trust(),
        state=_fast_state(),
    )

    assert issued.origin is CommandOrigin.FALLBACK_PID
    assert fallback.calls == 1


def test_exploration_still_governs_a_tick_no_gate_blocked() -> None:
    # The control for the test above. Without it, "a veto outranks exploration"
    # would also be satisfied by an arbiter that had stopped exploring at all --
    # which is exactly how bounded safe exploration would become dead code.
    fallback = _StubFallback()
    arbiter = _arbiter(fallback=fallback)
    arbiter.engage_exploration(EXPLORATION_SPACE)

    issued = arbiter.issue(
        tick=TickId(1),
        proposal=_proposal(),
        verdict=_verdict(Verdict.PASS),
        failsafe=_failsafe(),
        trust=_trust(),
        state=_fast_state(),
    )

    assert issued.origin is CommandOrigin.EXPLORATION_BOUNDED
    assert fallback.calls == 0


def test_leaving_exploration_restores_the_nominal_space() -> None:
    arbiter = _arbiter()
    arbiter.engage_exploration(EXPLORATION_SPACE)
    engaged = arbiter.is_exploring
    arbiter.exit_exploration()

    issued = arbiter.issue(
        tick=TickId(1),
        proposal=_proposal((0.9, 0.45)),
        verdict=_verdict(Verdict.PASS),
        failsafe=_failsafe(),
        trust=_trust(),
        state=_fast_state(),
    )

    assert engaged
    assert not arbiter.is_exploring
    assert issued.command.values == (0.9, 0.45)


def test_an_exploration_space_with_different_channels_is_refused() -> None:
    # A different channel set is a different platform, not a narrower envelope.
    other = ActuationSpace((ActuationChannel(name="rudder", lower=-1.0, upper=1.0, unit="rad"),))

    with pytest.raises(ConfigurationError, match="different platform"):
        _arbiter().engage_exploration(other)


# --------------------------------------------------------------------------- #
# The cold path: arbitration outcomes
# --------------------------------------------------------------------------- #


def _signature(
    components: tuple[float, ...] = (0.5, 0.5, 0.5, 0.5, 0.5),
) -> RuntimeContextSignature:
    return RuntimeContextSignature(
        tick=TickId(1), components=tuple(Probability(v) for v in components)
    )


def _arbitrate(arbiter: RuntimeCalibrationManager, **overrides: object) -> ArbitrationDecision:
    return arbiter.arbitrate(
        tick=TickId(1),
        signature=overrides.get("signature", _signature()),  # type: ignore[arg-type]
        threshold=overrides.get("threshold", 0.5),  # type: ignore[arg-type]
        divergence_limit=overrides.get("divergence_limit", 0.2),  # type: ignore[arg-type]
        platform=PLATFORM,
        now=NOW,
    )


def test_the_active_profile_remaining_best_yields_continue() -> None:
    assert _arbitrate(_arbiter()).outcome is ArbitrationOutcome.CONTINUE


def test_no_admissible_candidate_yields_safe_exploration() -> None:
    # The tunnel scenario: every candidate fails the admissibility conjunction.
    invalid = _profile("failed_certification", passed=False)
    arbiter = _arbiter(profiles=[invalid], active=invalid)

    assert _arbitrate(arbiter).outcome is ArbitrationOutcome.SAFE_EXPLORATION


def test_a_better_candidate_stages_rather_than_switching() -> None:
    active = _profile("highway_clear", centroid=(0.9,) * 5)
    better = _profile("urban_clear", centroid=(0.5,) * 5, context=ContextClass.URBAN_CLEAR)
    arbiter = _arbiter(profiles=[active, better], active=active)

    decision = _arbitrate(arbiter)

    assert decision.outcome is ArbitrationOutcome.SHADOW_EXECUTION
    assert decision.candidate_profile is not None
    assert decision.candidate_profile.name == "urban_clear"
    assert arbiter.active_profile.profile_id.name == "highway_clear"


def test_a_switch_commits_only_after_the_divergence_index_clears() -> None:
    active = _profile("highway_clear", centroid=(0.9,) * 5)
    better = _profile("urban_clear", centroid=(0.5,) * 5, context=ContextClass.URBAN_CLEAR)
    arbiter = _arbiter(profiles=[active, better], active=active)

    _arbitrate(arbiter)  # opens the staging period
    assert arbiter.shadow is not None
    for _ in range(MINIMUM_SHADOW_SAMPLES):
        arbiter.shadow.observe(active=Verdict.PASS, candidate=Verdict.PASS)

    decision = _arbitrate(arbiter)

    assert decision.outcome is ArbitrationOutcome.SWITCH_COMMITTED
    assert arbiter.active_profile.profile_id.name == "urban_clear"


def test_sustained_disagreement_rolls_back_rather_than_committing() -> None:
    active = _profile("highway_clear", centroid=(0.9,) * 5)
    better = _profile("urban_clear", centroid=(0.5,) * 5, context=ContextClass.URBAN_CLEAR)
    arbiter = _arbiter(profiles=[active, better], active=active)

    _arbitrate(arbiter)
    assert arbiter.shadow is not None
    for _ in range(SHADOW_PATIENCE):
        arbiter.shadow.observe(active=Verdict.PASS, candidate=Verdict.VETO)

    decision = _arbitrate(arbiter)

    assert decision.outcome is ArbitrationOutcome.ROLLBACK
    assert arbiter.active_profile.profile_id.name == "highway_clear"
    assert decision.calibration_divergence_index == pytest.approx(1.0)


def test_a_staging_period_in_progress_keeps_reporting_shadow_execution() -> None:
    active = _profile("highway_clear", centroid=(0.9,) * 5)
    better = _profile("urban_clear", centroid=(0.5,) * 5, context=ContextClass.URBAN_CLEAR)
    arbiter = _arbiter(profiles=[active, better], active=active)

    _arbitrate(arbiter)
    assert arbiter.shadow is not None
    arbiter.shadow.observe(active=Verdict.PASS, candidate=Verdict.PASS)

    assert _arbitrate(arbiter).outcome is ArbitrationOutcome.SHADOW_EXECUTION


# --------------------------------------------------------------------------- #
# The divergence index itself
# --------------------------------------------------------------------------- #


def test_the_index_measures_disagreement_not_closeness() -> None:
    shadow = ShadowExecution()
    for _ in range(3):
        shadow.observe(active=Verdict.PASS, candidate=Verdict.PASS)
    shadow.observe(active=Verdict.PASS, candidate=Verdict.VETO)

    assert shadow.divergence_index == pytest.approx(0.25)


def test_insufficient_evidence_is_not_clearance() -> None:
    # A CDI computed from three ticks is noise. Committing on it would produce
    # an evidence record saying divergence was checked and cleared.
    shadow = ShadowExecution()
    for _ in range(MINIMUM_SHADOW_SAMPLES - 1):
        shadow.observe(active=Verdict.PASS, candidate=Verdict.PASS)

    assert shadow.divergence_index == 0.0
    assert not shadow.has_cleared(0.2)

    shadow.observe(active=Verdict.PASS, candidate=Verdict.PASS)
    assert shadow.has_cleared(0.2)


def test_an_empty_staging_period_reports_zero_divergence_but_does_not_clear() -> None:
    shadow = ShadowExecution()

    assert shadow.divergence_index == 0.0
    assert shadow.sample_count == 0
    assert not shadow.has_cleared(0.5)


@pytest.mark.parametrize("limit", [1.0, 1.5, -0.1, math.nan])
def test_a_divergence_limit_outside_the_half_open_unit_interval_is_refused(
    limit: float,
) -> None:
    # At 1 or above a candidate that disagreed on every command would commit.
    shadow = ShadowExecution()

    with pytest.raises(ConfigurationError):
        shadow.has_cleared(limit)
