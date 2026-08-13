"""What is this vehicle actually certified for? Measure it, do not assume it.

The question, and who asks it
------------------------------
An integrator putting this software on their vehicle needs one thing before
anything else: **the list of operating contexts it is fit for on their platform,
and the list it is not.** Today that list is an assumption. Four calibration
profiles are seeded by :func:`~astra.runtime.assembly.seed_profiles` with
centroids someone chose, and nothing has ever checked that a given vehicle can
reach them.

OD-11 is the reason this matters rather than being tidy-up. NFR5 claims a second
platform costs only an adapter; measured against a warehouse AGV, that is
**partly false** -- the gates transfer and the composition root does not
(E-72 - E-75). "Which contexts does this platform actually work in" is exactly
the question that finding leaves open, and it is the integrator's, not this
repository's, to answer for their own vehicle.

So this is a **commissioning procedure**: drive the platform through the
certified context set, one context at a time, and emit a certificate saying what
held.

What it produces, and why three verdicts rather than two
----------------------------------------------------------
``CERTIFIED``
    RCM found and held an admissible profile, the vehicle stayed inside its
    corridor, and the fail-safe machine stayed out of HALT. The context is
    covered.

``BOUNDED``
    **No profile matched -- and the vehicle kept driving anyway**, inside the
    narrowed exploration envelope, in its corridor, never halting. This is the
    architecture's distinguishing behaviour and collapsing it into "fail" would
    throw away the whole selling point. It is a *weaker* certificate, not a
    failure: the vehicle is safe here and is not calibrated here.

``UNFIT``
    The vehicle halted, stopped, or left its corridor. The integrator must not
    operate in this context.

A binary certified/uncertified answer would report ``BOUNDED`` as a failure,
which is both wrong and the opposite of the point.

The trap this measurement already fell into once
--------------------------------------------------
**Two of the five signature components are not settable.** ``ego_speed`` is
measured from the vehicle and normalised by the legal limit; ``sensor_reliability``
is derived from frame health. Only ``visibility``, ``traffic_dynamicity`` and
``road_complexity`` come from :class:`~astra.runtime.pipeline.ColdPathContext`.

So a context cannot be "set" to a profile's centroid -- only three of its five
components can. E-82 records what happens when that is forgotten: a signature
that *looks* like clear highway on the supplied components sits in permanent
``SAFE_EXPLORATION``, because the policy holds 12.5 m/s of a 33.3 m/s limit and
therefore reports **0.375** against ``HIGHWAY_CLEAR``'s centroid of **0.8**.

**That is not a defect in this script -- it is the finding.** A profile whose
centroid a platform cannot physically reach is a profile that platform is not
certified for, however well its road conditions match, and a commissioning test
whose whole job is to discover that must not paper over it. Each row therefore
reports the *realised* ego-speed component beside the profile's own, so an
unreachable profile names its own reason.

Usage::

    uv run python -m benchmarks.commissioning
    uv run python -m benchmarks.commissioning --ticks 600
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

from astra.config.loader import load_settings
from astra.kernel.enums import ArbitrationOutcome, ContextClass, FailSafeState
from astra.kernel.units import Probability
from astra.layers.l4_proposer.learned import LearnedPolicy
from astra.runtime.pipeline import ColdPathContext
from training.closed_loop import CORPUS, ENVIRONMENT, TWIN, TickSample, drive_closed_loop
from training.environment import EnvironmentSpec

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["CONTEXTS", "Certificate", "Context", "commission"]

_DEFAULT_TICKS = 400
_DEFAULT_SEED = 20260811
_DEFAULT_POLICY = Path("var/policy/synthetic.pt")
_DEFAULT_OUTPUT = Path("var/commissioning")

_PERIOD_TICKS = 20
"""Arbitration period. Short enough that a 400-tick run re-evaluates twenty times."""

_SETTLE_TICKS = 50
"""Ticks excluded from the deviation statistic and from the corridor verdict.

``EnvironmentSpec.initial_offset_m`` starts the vehicle up to **1 m off centre
deliberately**, so tick 0 carries a large deviation on every run by
construction. Measured, the peak deviation across all five contexts was
**0.426 m at tick 0, identical in every row** -- a number that says nothing
about the platform and makes five different outcomes look the same.

Judging a platform UNFIT for its own rig's initial condition would be wrong, so
the settle window is excluded from the verdict as well as from the report. The
window is generous: the arbitration period is 20 ticks, so 50 covers the first
two evaluations as well as the correction.
"""

_CERTIFIED_HOLD = 0.5
"""Fraction of ticks a profile must hold for the context to be CERTIFIED.

**Added after the first run on a second platform, which exposed the verdict as
too lenient.** With weaker brakes and 20% less steering bite, ``urban_clear``
matched on some ticks and spent **360 of 400 in exploration** -- and was
reported CERTIFIED, because the original rule asked only whether a profile had
*ever* matched.

A context where the vehicle is inside the narrowed envelope for nine ticks in
ten is a context it is not calibrated for, whatever happened on the tenth. A
majority is the weakest defensible bar and it is deliberately not tuned finer:
a threshold chosen to make a particular platform pass would be fitted to that
platform.
"""

_STOPPED_MPS = 0.5
"""Below this the vehicle counts as stopped rather than slowed.

The exploration envelope caps speed and LIMP caps it harder, so a low speed is
not by itself a failure. Half a metre per second is walking pace and no
lane-keeping policy holds a lane there."""


@dataclass(frozen=True, slots=True)
class Context:
    """One operating context to commission the platform in.

    Attributes:
        name: How the row is labelled.
        supplied: ``(visibility, traffic_dynamicity, road_complexity)`` -- the
            three components a deployment supplies. The other two are measured.
        expects: The profile this context is aimed at, or ``None`` for a context
            deliberately outside every certified centroid.
    """

    name: str
    supplied: tuple[float, float, float]
    expects: ContextClass | None


#: The four seeded profiles' road conditions, plus one context no profile covers.
#:
#: The triples are lifted from ``seed_profiles`` in ``runtime/assembly.py`` --
#: components 0, 2 and 4 of each centroid, which are the three a deployment can
#: supply. They are **not** re-derived here: a commissioning test that invented
#: its own idea of what a profile's context is would certify against a fiction.
CONTEXTS: tuple[Context, ...] = (
    Context("highway_clear", (0.9, 0.3, 0.2), ContextClass.HIGHWAY_CLEAR),
    Context("urban_clear", (0.85, 0.7, 0.7), ContextClass.URBAN_CLEAR),
    Context("rain_night", (0.35, 0.5, 0.5), ContextClass.RAIN_NIGHT),
    Context("degraded_sensor", (0.6, 0.5, 0.5), ContextClass.DEGRADED_SENSOR),
    # No profile covers this, deliberately -- `seed_profiles` omits a tunnel and
    # says why. It is the control arm: a platform that cannot produce BOUNDED
    # here has lost the architecture's distinguishing behaviour, and the
    # certificate should say so rather than only listing what passed.
    Context("tunnel", (0.05, 0.7, 0.95), None),
)


@dataclass(frozen=True, slots=True)
class Certificate:
    """What one context did on this platform.

    Attributes:
        context: Which row.
        verdict: ``CERTIFIED``, ``BOUNDED`` or ``UNFIT``.
        reason: Why that verdict, in one phrase. **Present even when the verdict
            is CERTIFIED**: a certificate that only explains its failures leaves
            a reader unable to check its successes.
        active_profile: The profile RCM held for most of the run.
        matched: Whether any tick reached an outcome other than exploration.
        exploring: Ticks in ``SAFE_EXPLORATION``.
        vetoed: Ticks whose aggregate verdict was blocking.
        veto_rate: ``vetoed / ticks``.
        max_absolute_deviation_m: The worst lane deviation reached **after the
            settle window**. See :data:`_SETTLE_TICKS` for why the first fifty
            ticks are excluded from this and from the verdict.
        final_speed_mps: Speed on the last tick.
        worst_failsafe: The most escalated posture reached.
        realised_ego_speed: The ego-speed signature component the vehicle
            actually produced, averaged. **Compare against
            ``profile_ego_speed``**: a large gap is why a profile did not match,
            and it is a property of the platform and policy rather than of the
            road (E-82).
        profile_ego_speed: The centroid's ego-speed component, or ``None`` for a
            context no profile covers.
        ticks: How many ticks ran.
    """

    context: str
    verdict: str
    reason: str
    active_profile: str
    matched: bool
    exploring: int
    vetoed: int
    veto_rate: float
    max_absolute_deviation_m: float
    final_speed_mps: float
    worst_failsafe: str
    realised_ego_speed: float
    profile_ego_speed: float | None
    ticks: int


#: The seeded centroids' ego-speed component, by context class. Lifted from
#: ``seed_profiles`` for the same reason ``CONTEXTS`` is.
_PROFILE_EGO_SPEED: dict[ContextClass, float] = {
    ContextClass.HIGHWAY_CLEAR: 0.8,
    ContextClass.URBAN_CLEAR: 0.35,
    ContextClass.RAIN_NIGHT: 0.5,
    ContextClass.DEGRADED_SENSOR: 0.4,
}

_ESCALATION = (
    FailSafeState.NOMINAL,
    FailSafeState.DEGRADED,
    FailSafeState.LIMP,
    FailSafeState.HALT,
)


def _cold_path(supplied: tuple[float, float, float]) -> ColdPathContext:
    """Return the cold-path context for one set of supplied components.

    Args:
        supplied: ``(visibility, traffic_dynamicity, road_complexity)``.

    Returns:
        The context RCM evaluates the knowledge base against.
    """
    settings = load_settings(environment=ENVIRONMENT, include_environment_variables=False).settings
    return ColdPathContext(
        period_ticks=_PERIOD_TICKS,
        trust_threshold=settings.arbitration.trust_threshold_tau,
        divergence_limit=settings.arbitration.divergence_limit_delta,
        platform="synthetic-prototype",
        legal_speed_limit=settings.shield.legal_speed_limit,
        visibility=Probability(supplied[0]),
        traffic_dynamicity=Probability(supplied[1]),
        road_complexity=Probability(supplied[2]),
    )


def _unfit_reason(
    *,
    worst: FailSafeState,
    final_speed: float,
    max_deviation: float,
    corridor: float,
) -> str | None:
    """Return why this run is UNFIT, or ``None`` if it is not.

    Ordered worst-first, so a run that both halted and left its corridor reports
    the halt rather than whichever check happens to run first.

    Args:
        worst: The most escalated fail-safe posture.
        final_speed: Speed on the last tick.
        max_deviation: The worst lane deviation after the settle window.
        corridor: The lane half-width the deviation is judged against.

    Returns:
        The disqualifying phrase, or ``None``.
    """
    if worst is FailSafeState.HALT:
        return "reached HALT, which is terminal"
    if final_speed < _STOPPED_MPS:
        return f"stopped, final speed {final_speed:.2f} m/s"
    if max_deviation > corridor:
        return f"left the corridor, peak {max_deviation:.3f} m > {corridor:.2f} m"
    return None


def _judge(
    *,
    matched: bool,
    exploring: int,
    ticks: int,
    worst: FailSafeState,
    final_speed: float,
    max_deviation: float,
    corridor: float,
) -> tuple[str, str]:
    """Resolve the verdict and the phrase that explains it.

    Args:
        matched: Whether any tick reached a non-exploration outcome.
        exploring: Ticks in exploration.
        ticks: Total ticks.
        worst: The most escalated fail-safe posture.
        final_speed: Speed on the last tick.
        max_deviation: The worst lane deviation after the settle window.
        corridor: The lane half-width the deviation is judged against.

    Returns:
        The verdict and its one-phrase reason.
    """
    unfit = _unfit_reason(
        worst=worst,
        final_speed=final_speed,
        max_deviation=max_deviation,
        corridor=corridor,
    )
    if unfit is not None:
        return "UNFIT", unfit
    if not matched:
        return "BOUNDED", "no profile matched; drove inside the exploration envelope"
    held = ticks - exploring
    if ticks and held / ticks < _CERTIFIED_HOLD:
        return "BOUNDED", (
            f"a profile matched but held only {held} of {ticks} ticks; the rest was exploration"
        )
    if exploring:
        return "CERTIFIED", f"profile held, {exploring} of {ticks} ticks in exploration"
    return "CERTIFIED", "profile held throughout"


def commission(
    *,
    context: Context,
    ticks: int,
    seed: int,
    policy: LearnedPolicy | None,
    spec: EnvironmentSpec,
) -> Certificate:
    """Drive one context and reduce it to a certificate.

    Args:
        context: The context to commission in.
        ticks: How many control ticks.
        seed: Plant and sensor-noise seed.
        policy: The proposer.
        spec: The platform.

    Returns:
        What held, and what did not.
    """
    settings = load_settings(environment=ENVIRONMENT, include_environment_variables=False).settings
    corridor = float(settings.shield.lateral_corridor_half_width_m)
    legal_limit = float(settings.shield.legal_speed_limit)

    exploring = 0
    matched = False
    worst = 0
    peak_deviation = 0.0
    speeds: list[float] = []
    profiles: dict[str, int] = {}

    def watch(sample: TickSample) -> None:
        nonlocal exploring, matched, worst, peak_deviation
        if sample.tick >= _SETTLE_TICKS:
            peak_deviation = max(peak_deviation, abs(sample.lane_deviation_m))
        speeds.append(sample.speed_mps)
        arbitration = sample.record.arbitration
        if arbitration is not None:
            if arbitration.outcome is ArbitrationOutcome.SAFE_EXPLORATION:
                exploring += 1
            else:
                matched = True
            name = arbitration.active_profile.name
            profiles[name] = profiles.get(name, 0) + 1
        failsafe = sample.record.failsafe
        if failsafe is not None:
            worst = max(worst, _ESCALATION.index(failsafe.state))

    result = drive_closed_loop(
        policy=policy,
        ticks=ticks,
        seed=seed,
        spec=spec,
        observer=watch,
        cold_path=_cold_path(context.supplied),
    )

    # The ego-speed component as the signature builder computes it: the vehicle's
    # own speed normalised by the legal limit, clamped into [0, 1].
    realised = min(1.0, (sum(speeds) / len(speeds)) / legal_limit) if speeds else 0.0
    verdict, reason = _judge(
        matched=matched,
        exploring=exploring,
        ticks=result.ticks,
        worst=_ESCALATION[worst],
        final_speed=result.final_speed_mps,
        max_deviation=peak_deviation,
        corridor=corridor,
    )
    # When nothing matched, the 'active' profile is simply the one the
    # arbitrator started with and never replaced. Reporting it as though it
    # were held on merit is the kind of thing a certificate must not do.
    held = (
        (max(profiles, key=lambda name: profiles[name]) if profiles else "-")
        if matched
        else "none matched"
    )

    return Certificate(
        context=context.name,
        verdict=verdict,
        reason=reason,
        active_profile=held,
        matched=matched,
        exploring=exploring,
        vetoed=result.vetoed,
        veto_rate=result.vetoed / result.ticks if result.ticks else 0.0,
        max_absolute_deviation_m=peak_deviation,
        final_speed_mps=result.final_speed_mps,
        worst_failsafe=_ESCALATION[worst].name,
        realised_ego_speed=realised,
        profile_ego_speed=(
            None if context.expects is None else _PROFILE_EGO_SPEED[context.expects]
        ),
        ticks=result.ticks,
    )


def render(certificates: Sequence[Certificate]) -> list[str]:
    """Return the certificate, as lines.

    Args:
        certificates: One per context, in ``CONTEXTS`` order.

    Returns:
        Lines to print.
    """
    lines = [
        "",
        "  COMMISSIONING CERTIFICATE",
        "",
        (
            f"  {'context':<17}{'verdict':>10}{'profile held':>18}{'explore':>9}"
            f"{'veto':>7}{'settled dev':>13}{'ego now/req':>14}"
        ),
        (
            f"  {'-' * 17}{'-' * 9:>10}{'-' * 17:>18}{'-' * 8:>9}"
            f"{'-' * 6:>7}{'-' * 12:>13}{'-' * 13:>14}"
        ),
    ]
    for certificate in certificates:
        required = (
            "  -"
            if certificate.profile_ego_speed is None
            else f"{certificate.profile_ego_speed:.2f}"
        )
        lines.append(
            f"  {certificate.context:<17}{certificate.verdict:>10}"
            f"{certificate.active_profile:>18}{certificate.exploring:>9}"
            f"{certificate.vetoed:>7}{certificate.max_absolute_deviation_m:>13.3f}"
            f"{certificate.realised_ego_speed:>9.2f}/{required:>4}"
        )
    lines.append("")
    lines.extend(
        f"  {certificate.context:<17} {certificate.verdict:<10} {certificate.reason}"
        for certificate in certificates
    )
    lines.extend(
        [
            "",
            "  CERTIFIED  a profile matched and held; the context is covered.",
            "  BOUNDED    no profile matched and the vehicle drove anyway, inside",
            "             the exploration envelope. A weaker certificate, not a",
            "             failure -- it is what this architecture exists to do.",
            "  UNFIT      halted, stopped, or left the corridor. Do not operate.",
            "",
            "  'settled dev' is the peak lane deviation after the first 50 ticks.",
            "  The plant starts up to 1 m off centre by design, so tick 0 carries",
            "  0.426 m on every run and would make five outcomes look identical.",
            "",
            "  'ego now/req' is the realised ego-speed signature component against",
            "  the profile's centroid. A large gap is why a profile did not match,",
            "  and it is a property of the platform and policy, not of the road.",
        ]
    )
    return lines


def run(
    *, ticks: int, seed: int, policy_path: Path, output: Path, spec: EnvironmentSpec
) -> list[Certificate]:
    """Commission every context and write the certificate.

    Args:
        ticks: Control ticks per context.
        seed: Shared seed, so contexts differ only in their conditions.
        policy_path: The trained proposer checkpoint.
        output: Directory for ``certificate.json``.
        spec: The platform under commission.

    Returns:
        One certificate per context.
    """
    resolved = load_settings(environment=ENVIRONMENT, include_environment_variables=False)
    policy = LearnedPolicy.load(policy_path)
    certificates = [
        commission(context=context, ticks=ticks, seed=seed, policy=policy, spec=spec)
        for context in CONTEXTS
    ]

    output.mkdir(parents=True, exist_ok=True)
    (output / "certificate.json").write_text(
        json.dumps(
            {
                # A certificate is about a specific build, and saying so is the
                # difference between an artefact and a screenshot. Same argument
                # as ADR-0021's per-tick ablation stamp.
                "config_hash": resolved.hash,
                "ticks": ticks,
                "seed": seed,
                "platform": {
                    "steer_effectiveness": spec.steer_effectiveness,
                    "acceleration_authority_mps2": spec.acceleration_authority_mps2,
                    "braking_authority_mps2": spec.braking_authority_mps2,
                },
                "certificates": [asdict(certificate) for certificate in certificates],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return certificates


def main(argv: list[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Command-line arguments, or ``None`` for ``sys.argv``.

    Returns:
        Zero unless an input artefact is missing, or a context came back UNFIT.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ticks", "-n", type=int, default=_DEFAULT_TICKS)
    parser.add_argument("--seed", type=int, default=_DEFAULT_SEED)
    parser.add_argument("--policy", type=Path, default=_DEFAULT_POLICY)
    parser.add_argument("--output", "-o", type=Path, default=_DEFAULT_OUTPUT)
    parser.add_argument(
        "--steer-effectiveness",
        type=float,
        default=None,
        help="commission a different platform's steering gain",
    )
    parser.add_argument("--braking-authority", type=float, default=None)
    arguments = parser.parse_args(argv)

    for artefact in (TWIN, CORPUS, arguments.policy):
        if not artefact.exists():
            print(f"missing {artefact}; see docs/EVIDENCE.md for how to regenerate it")
            return 1

    spec = EnvironmentSpec()
    if arguments.steer_effectiveness is not None:
        spec = replace(spec, steer_effectiveness=arguments.steer_effectiveness)
    if arguments.braking_authority is not None:
        spec = replace(spec, braking_authority_mps2=arguments.braking_authority)

    certificates = run(
        ticks=arguments.ticks,
        seed=arguments.seed,
        policy_path=arguments.policy,
        output=arguments.output,
        spec=spec,
    )
    for line in render(certificates):
        print(line)
    print(f"\n  certificate: {arguments.output / 'certificate.json'}")

    unfit = [c.context for c in certificates if c.verdict == "UNFIT"]
    if unfit:
        print(f"\n  UNFIT: {', '.join(unfit)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
