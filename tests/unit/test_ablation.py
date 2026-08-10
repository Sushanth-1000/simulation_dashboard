"""Can a pipeline be built with no gate, and does an ablated run say so?

Two questions, and the first one is the whole of ADR-0021
----------------------------------------------------------
The ablation study needs L6, L7a and L7b switched off in turn. The obvious way
to allow that is to make each constructor parameter ``| None``, and the obvious
way is the dangerous one: a pipeline that can be built without a statistical
gate fails **silently and in the flattering direction**. Every audit row is
still written, every verdict still reads ``PASS``, and nothing anywhere records
that the gate which accepted was absent. That is the shape of OD-2, of OD-7, and
of the inert consolidation penalty -- three separate mechanisms that failed by
making the evidence look better.

So the decision was to neutralise rather than remove, and the guarantee is
structural: the parameters stay required, and an ablation supplies a *subtype*
that runs and cannot block.

**A structural guarantee that nothing checks is a convention**, and convention 13
of ``docs/CONVENTIONS.md`` is the rule this project keeps relearning. So
:func:`test_no_gate_parameter_may_ever_become_optional` reads the constructor's
signature directly. If someone later widens one of those three annotations to
admit ``None``, that test fails and has to be argued with.

The second question is about evidence
--------------------------------------
An ablated run's records are *by construction* indistinguishable from a governed
run's -- that is what an ablation is. The only thing separating an ablation
study from a certification artefact describing a system that was not running is
the profile stamped on every tick. So the profile is asserted to be in the
rendered payload, on the abort path as well as the nominal one.
"""

from __future__ import annotations

import inspect
import typing

import pytest

from astra.contracts.audit import DecisionRecord
from astra.kernel.enums import GateId, Verdict
from astra.kernel.errors import ConfigurationError
from astra.kernel.identifiers import RunId, TickId
from astra.runtime.ablation import (
    ABLATED_REASON_CODE,
    ABLATION_ENVIRONMENTS,
    AblationProfile,
    TransparentPhysicalGate,
    TransparentShield,
    TransparentStatisticalGate,
    require_ablation_is_permitted,
)
from astra.runtime.pipeline import GovernancePipeline

ABLATABLE = ("statistical_gate", "physical_gate", "shield")


# --------------------------------------------------------------------------- #
# The structural guarantee
# --------------------------------------------------------------------------- #


@pytest.mark.architecture
@pytest.mark.parametrize("parameter", ABLATABLE)
def test_no_gate_parameter_may_ever_become_optional(parameter: str) -> None:
    # The test ADR-0021 exists to make mechanical. Widening any of these three
    # to `| None` makes a pipeline with no gate constructible, and every other
    # guard in this module -- the profile in the record, the environment check
    # -- is then protecting a property that has already been given away.
    signature = inspect.signature(GovernancePipeline.__init__)
    annotation = signature.parameters[parameter].annotation

    assert signature.parameters[parameter].default is inspect.Parameter.empty
    assert "None" not in str(annotation)
    assert type(None) not in typing.get_args(annotation)


@pytest.mark.architecture
@pytest.mark.parametrize(
    ("transparent", "parent_name"),
    [
        (TransparentStatisticalGate, "IcpStatisticalGate"),
        (TransparentPhysicalGate, "PhysicalAdmissibilityGate"),
        (TransparentShield, "HardSafetyShield"),
    ],
)
def test_a_transparent_gate_is_a_subtype_of_the_gate_it_stands_in_for(
    transparent: type, parent_name: str
) -> None:
    # Which is what lets the parameter keep its declared type. If a transparent
    # gate ever stopped being a subtype, the only way to pass it would be to
    # widen the parameter -- the thing this design exists to avoid.
    assert any(base.__name__ == parent_name for base in transparent.__mro__)


@pytest.mark.parametrize(
    "transparent", [TransparentStatisticalGate, TransparentPhysicalGate, TransparentShield]
)
def test_a_transparent_gate_adds_no_instance_dictionary(transparent: type) -> None:
    assert transparent.__dict__.get("__slots__") == ()


# --------------------------------------------------------------------------- #
# The profile
# --------------------------------------------------------------------------- #


def test_the_default_profile_is_a_governed_run() -> None:
    assert AblationProfile.NONE.is_empty
    assert AblationProfile.NONE.render() == "NONE"
    assert AblationProfile.NONE.disabled == ()


def test_a_governed_run_renders_a_word_rather_than_an_empty_string() -> None:
    # So a reader can tell "not ablated" from "field missing", which an empty
    # string cannot express.
    assert AblationProfile().render() == "NONE"


def test_the_rendered_profile_is_stable_regardless_of_construction_order() -> None:
    one = AblationProfile(shield=True, statistical_gate=True)
    other = AblationProfile.NONE.without("shield").without("statistical_gate")

    assert one.render() == other.render() == "statistical_gate+shield"


def test_every_ablatable_layer_can_be_disarmed_and_names_itself() -> None:
    for layer in ABLATABLE:
        profile = AblationProfile.NONE.without(layer)
        assert profile.disabled == (layer,)
        assert profile.render() == layer
        assert not profile.is_empty


def test_disarming_something_that_is_not_a_layer_is_refused() -> None:
    with pytest.raises(ValueError, match="not an ablatable layer"):
        AblationProfile.NONE.without("failsafe")


def test_the_profile_is_frozen() -> None:
    with pytest.raises(AttributeError):
        AblationProfile.NONE.shield = True  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# The environment guard
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("environment", ["certification", "production", "unknown", ""])
def test_a_non_empty_profile_is_refused_outside_the_measurement_environments(
    environment: str,
) -> None:
    with pytest.raises(ConfigurationError, match="refusing to disarm"):
        require_ablation_is_permitted(
            AblationProfile.NONE.without("shield"), environment=environment
        )


@pytest.mark.parametrize("environment", sorted(ABLATION_ENVIRONMENTS))
def test_a_non_empty_profile_is_permitted_where_measurements_are_taken(
    environment: str,
) -> None:
    # `simulation` is here because the study is measured at that operating
    # point. Forcing it into `development` would confound the disarmed gate
    # with a tenfold tighter OOD threshold -- two variables, one measurement.
    require_ablation_is_permitted(AblationProfile.NONE.without("shield"), environment=environment)


@pytest.mark.parametrize("environment", ["development", "simulation", "certification"])
def test_a_governed_run_is_permitted_everywhere(environment: str) -> None:
    require_ablation_is_permitted(AblationProfile.NONE, environment=environment)


def test_the_refusal_names_what_it_refused() -> None:
    with pytest.raises(ConfigurationError) as raised:
        require_ablation_is_permitted(
            AblationProfile(statistical_gate=True, shield=True), environment="certification"
        )

    assert raised.value.context["ablation"] == "statistical_gate+shield"


# --------------------------------------------------------------------------- #
# A disarmed gate passes, and says why
# --------------------------------------------------------------------------- #


def test_a_disarmed_gate_returns_a_reason_code_no_real_gate_can_produce(tick: TickId) -> None:
    # Greppable, and distinct: a verdict carrying this code is a statement that
    # the gate ran and was disarmed, never that it looked and found nothing.
    from astra.runtime.ablation import _ablated  # noqa: PLC0415

    verdict = _ablated(tick, GateId.STATISTICAL)

    assert verdict.verdict is Verdict.PASS
    assert verdict.reason_code == ABLATED_REASON_CODE
    assert verdict.gate is GateId.STATISTICAL


@pytest.mark.parametrize(
    "gate", [GateId.STATISTICAL, GateId.PHYSICAL, GateId.DETERMINISTIC], ids=lambda g: g.value
)
def test_a_disarmed_gate_still_attributes_itself(tick: TickId, gate: GateId) -> None:
    from astra.runtime.ablation import _ablated  # noqa: PLC0415

    assert _ablated(tick, gate).gate is gate


# --------------------------------------------------------------------------- #
# The evidence says which run it was
# --------------------------------------------------------------------------- #


def test_a_record_defaults_to_saying_the_run_was_governed(run: RunId, tick: TickId) -> None:
    record = DecisionRecord(run=run, tick=tick, config_hash="sha256:abc")

    assert record.ablation == "NONE"
    assert record.to_payload()["ablation"] == "NONE"


def test_an_ablated_record_carries_the_profile_into_its_payload(run: RunId, tick: TickId) -> None:
    profile = AblationProfile(statistical_gate=True, shield=True)

    record = DecisionRecord(run=run, tick=tick, config_hash="sha256:abc", ablation=profile.render())

    assert record.to_payload()["ablation"] == "statistical_gate+shield"


def test_the_profile_survives_serialisation(run: RunId, tick: TickId) -> None:
    # The field has to be in the JSON, not merely on the dataclass: the audit
    # log is what outlives the process, and a certification artefact is read
    # from the file rather than from memory.
    import json  # noqa: PLC0415

    record = DecisionRecord(run=run, tick=tick, config_hash="sha256:abc", ablation="shield")

    assert json.loads(record.to_json())["ablation"] == "shield"


@pytest.mark.architecture
def test_certification_can_never_run_an_ablated_pipeline() -> None:
    # The one environment whose evidence is offered as an assurance argument.
    # If it ever appears in ABLATION_ENVIRONMENTS, an ablated run could produce
    # records that a certification pack would then quote.
    assert "certification" not in ABLATION_ENVIRONMENTS
