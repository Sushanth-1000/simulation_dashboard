"""Unit tests for the configuration schema and the layered loader.

The property that matters most here is assumption A-4: a safety threshold with
no defensible default must make the system refuse to start, and the refusal must
name every field that is missing.
"""

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from astra.config.loader import (
    DEFAULTS_FILENAME,
    ENVIRONMENTS_DIRECTORY,
    config_hash,
    default_config_root,
    load_settings,
)
from astra.config.schema import (
    AstraSettings,
    FailSafeSettings,
    GateSettings,
    ShieldSettings,
)
from astra.kernel.constants import CONFIG_SCHEMA_VERSION
from astra.kernel.enums import SensorModality
from astra.kernel.errors import ConfigurationError, SchemaVersionError

if TYPE_CHECKING:
    from astra.config.loader import ResolvedConfiguration

CONFIG_ROOT = Path(__file__).resolve().parents[2] / "config"

# The safety thresholds `certification.toml` deliberately leaves absent. Every
# one of them must be named by the error that loading that environment raises.
CERTIFICATION_MISSING_FIELDS = frozenset(
    {
        "estimation.innovation_gate_gamma",
        "estimation.fast_process_noise",
        "estimation.slow_process_noise",
        "trust.coverage_level",
        "trust.highway_speed_boundary_kmh",
        "twin.physics_weight",
        "twin.control_effectiveness",
        "gate.significance_epsilon",
        "gate.mmd_threshold",
        "gate.shift_epsilon_multiplier",
        "physical.max_lateral_jerk_mps3",
        "physical.admissible_divergence_mps2",
        "shield.legal_speed_limit_kmh",
        "shield.friction_margin",
        "shield.minimum_stopping_distance_m",
        "shield.assured_clear_distance_m",
        "shield.lateral_corridor_half_width_m",
        "failsafe.ood_threshold_degraded",
        "failsafe.ood_threshold_limp",
        "failsafe.ood_threshold_halt",
        "failsafe.degraded_speed_cap_kmh",
        "failsafe.limp_speed_cap_kmh",
        "failsafe.integrity_threshold_degraded",
        "failsafe.integrity_threshold_limp",
        "failsafe.integrity_threshold_halt",
        "failsafe.integrity_tolerated_faults",
        "failsafe.critical_modalities",
        "arbitration.trust_threshold_tau",
        "arbitration.divergence_limit_delta",
    }
)

# A defaults file carrying only values that are safe to default, and an
# environment file carrying every safety threshold. Written into `tmp_path` so
# that the layering tests state their own inputs rather than depending on the
# repository's files staying the shape they are today.
SYNTHETIC_DEFAULTS = """
schema_version = 1

[sensing]
staleness_budget_ms = 50.0

[estimation]
fast_rate_hz = 20.0
slow_rate_hz = 1.0

[trust]
ensemble_size = 10
minimum_calibration_samples = 500

[gate]
mmd_window = 100

[observability]
log_directory = "var/runs"
log_level = "INFO"
audit_queue_size = 10000
fsync_each_record = false
"""

SYNTHETIC_ENVIRONMENT = """
schema_version = 1

[estimation]
innovation_gate_gamma = 9.0
fast_process_noise = [0.05, 0.05, 0.10, 0.01, 0.50]
slow_process_noise = [1e-5, 1e-6, 1e-5]

[trust]
coverage_level = 0.95
highway_speed_boundary_kmh = 70.0

[twin]
physics_weight = 1.0
control_effectiveness = [0.0, 0.0, 120.0]

[gate]
significance_epsilon = 0.05
mmd_threshold = 0.10
shift_epsilon_multiplier = 2.0

[physical]
max_lateral_jerk_mps3 = 12.0
admissible_divergence_mps2 = 4.0

[shield]
legal_speed_limit_kmh = 50.0
friction_margin = 0.85
minimum_stopping_distance_m = 2.0
assured_clear_distance_m = 60.0
lateral_corridor_half_width_m = 1.75

[failsafe]
ood_threshold_degraded = 3
ood_threshold_limp = 6
ood_threshold_halt = 10
degraded_speed_cap_kmh = 40.0
limp_speed_cap_kmh = 20.0
integrity_threshold_degraded = 2
integrity_threshold_limp = 4
integrity_threshold_halt = 8
integrity_tolerated_faults = 0
critical_modalities = ["CAMERA", "LIDAR", "IMU", "GPS", "RADAR"]

[arbitration]
trust_threshold_tau = 0.60
divergence_limit_delta = 0.25

[observability]
log_level = "DEBUG"
"""


def _write_config_root(
    root: Path,
    *,
    defaults: str = SYNTHETIC_DEFAULTS,
    environment: str = SYNTHETIC_ENVIRONMENT,
    name: str = "development",
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / DEFAULTS_FILENAME).write_text(defaults, encoding="utf-8")
    environments = root / ENVIRONMENTS_DIRECTORY
    environments.mkdir(parents=True, exist_ok=True)
    (environments / f"{name}.toml").write_text(environment, encoding="utf-8")
    return root


def _load_synthetic(root: Path) -> ResolvedConfiguration:
    return load_settings(
        environment="development",
        config_root=root,
        include_environment_variables=False,
    )


@pytest.fixture
def hermetic_environ(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Remove every ambient ``ASTRA_*`` variable so overrides are test-owned."""
    for name in [name for name in os.environ if name.startswith("ASTRA_")]:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


# --------------------------------------------------------------------------- #
# A-4 -- a missing safety threshold is a startup failure
# --------------------------------------------------------------------------- #


def test_loading_the_certification_environment_raises_because_thresholds_are_absent() -> None:
    with pytest.raises(ConfigurationError):
        load_settings(
            environment="certification",
            config_root=CONFIG_ROOT,
            include_environment_variables=False,
        )


def test_the_certification_failure_names_every_missing_safety_threshold() -> None:
    with pytest.raises(ConfigurationError) as raised:
        load_settings(
            environment="certification",
            config_root=CONFIG_ROOT,
            include_environment_variables=False,
        )

    reported = {item["field"] for item in raised.value.context["errors"]}
    assert reported == CERTIFICATION_MISSING_FIELDS


def test_the_certification_failure_reports_every_missing_field_as_required() -> None:
    with pytest.raises(ConfigurationError) as raised:
        load_settings(
            environment="certification",
            config_root=CONFIG_ROOT,
            include_environment_variables=False,
        )

    assert all(item["problem"] == "Field required" for item in raised.value.context["errors"])


def test_the_certification_failure_records_the_environment_and_its_sources() -> None:
    with pytest.raises(ConfigurationError) as raised:
        load_settings(
            environment="certification",
            config_root=CONFIG_ROOT,
            include_environment_variables=False,
        )

    context = raised.value.context
    assert context["environment"] == "certification"
    assert context["sources"] == [
        str(CONFIG_ROOT / DEFAULTS_FILENAME),
        str(CONFIG_ROOT / ENVIRONMENTS_DIRECTORY / "certification.toml"),
    ]


def test_constructing_gate_settings_without_the_significance_epsilon_fails() -> None:
    with pytest.raises(ValidationError):
        GateSettings(mmd_threshold=0.1)  # type: ignore[call-arg]


def test_constructing_astra_settings_without_the_gate_section_fails() -> None:
    with pytest.raises(ValidationError):
        AstraSettings.model_validate(
            {
                "schema_version": CONFIG_SCHEMA_VERSION,
                "environment": "development",
                "estimation": {"innovation_gate_gamma": 9.0},
                "trust": {"coverage_level": 0.95, "highway_speed_boundary_kmh": 70.0},
                "shield": {
                    "legal_speed_limit_kmh": 50.0,
                    "friction_margin": 0.85,
                    "minimum_stopping_distance_m": 2.0,
                    "assured_clear_distance_m": 60.0,
                    "lateral_corridor_half_width_m": 1.75,
                },
                "failsafe": {
                    "ood_threshold_degraded": 3,
                    "ood_threshold_limp": 6,
                    "ood_threshold_halt": 10,
                    "degraded_speed_cap_kmh": 40.0,
                    "limp_speed_cap_kmh": 20.0,
                    "integrity_threshold_degraded": 2,
                    "integrity_threshold_limp": 4,
                    "integrity_threshold_halt": 8,
                    "integrity_tolerated_faults": 0,
                    "critical_modalities": ["CAMERA", "LIDAR", "IMU", "GPS", "RADAR"],
                },
                "arbitration": {"trust_threshold_tau": 0.6, "divergence_limit_delta": 0.25},
            }
        )


def test_constructing_shield_settings_without_a_single_bound_fails() -> None:
    with pytest.raises(ValidationError):
        ShieldSettings(legal_speed_limit_kmh=50.0, friction_margin=0.85)  # type: ignore[call-arg]


# --------------------------------------------------------------------------- #
# Layering
# --------------------------------------------------------------------------- #


def test_a_value_present_only_in_the_defaults_survives_the_environment_layer(
    tmp_path: Path,
) -> None:
    resolved = _load_synthetic(_write_config_root(tmp_path / "config"))

    assert resolved.settings.observability.log_directory == "var/runs"
    assert resolved.settings.trust.minimum_calibration_samples == 500


def test_a_value_set_in_the_environment_file_overrides_the_default(tmp_path: Path) -> None:
    resolved = _load_synthetic(_write_config_root(tmp_path / "config"))

    assert resolved.settings.observability.log_level == "DEBUG"


def test_both_layers_are_recorded_as_sources_in_precedence_order(tmp_path: Path) -> None:
    root = _write_config_root(tmp_path / "config")

    resolved = _load_synthetic(root)

    assert resolved.sources == (
        str(root / DEFAULTS_FILENAME),
        str(root / ENVIRONMENTS_DIRECTORY / "development.toml"),
    )


def test_an_environment_file_setting_one_key_keeps_the_sibling_defaults_of_that_section(
    tmp_path: Path,
) -> None:
    root = _write_config_root(
        tmp_path / "config",
        environment=SYNTHETIC_ENVIRONMENT.replace(
            '[observability]\nlog_level = "DEBUG"',
            '[observability]\nlog_level = "WARNING"',
        ),
    )

    observability = _load_synthetic(root).settings.observability

    assert observability.log_level == "WARNING"
    assert observability.log_directory == "var/runs"
    assert observability.audit_queue_size == 10000
    assert observability.fsync_each_record is False


def test_a_deep_merge_keeps_a_default_in_a_section_the_environment_file_also_touches(
    tmp_path: Path,
) -> None:
    resolved = _load_synthetic(_write_config_root(tmp_path / "config"))

    assert resolved.settings.gate.significance_epsilon == 0.05
    assert resolved.settings.gate.mmd_window == 100


def test_the_repository_development_environment_inherits_the_packaged_defaults(
    settings: ResolvedConfiguration,
) -> None:
    assert settings.settings.sensing.staleness_budget_ms == 50.0
    assert settings.settings.gate.mmd_window == 100
    assert settings.settings.observability.log_level == "DEBUG"


def test_the_default_config_root_points_at_the_repository_configuration_directory() -> None:
    assert default_config_root() == CONFIG_ROOT


# --------------------------------------------------------------------------- #
# ASTRA_* environment variables
# --------------------------------------------------------------------------- #


def test_a_nested_astra_environment_variable_overrides_the_environment_file(
    tmp_path: Path, hermetic_environ: pytest.MonkeyPatch
) -> None:
    root = _write_config_root(tmp_path / "config")
    hermetic_environ.setenv("ASTRA_GATE__SIGNIFICANCE_EPSILON", "0.01")

    resolved = load_settings(
        environment="development", config_root=root, include_environment_variables=True
    )

    assert resolved.settings.gate.significance_epsilon == 0.01


def test_an_environment_variable_override_is_recorded_as_a_source(
    tmp_path: Path, hermetic_environ: pytest.MonkeyPatch
) -> None:
    root = _write_config_root(tmp_path / "config")
    hermetic_environ.setenv("ASTRA_GATE__SIGNIFICANCE_EPSILON", "0.01")

    resolved = load_settings(
        environment="development", config_root=root, include_environment_variables=True
    )

    assert resolved.sources[-1] == "ASTRA_* environment variables"


def test_an_environment_variable_string_is_coerced_to_the_scalar_the_schema_expects(
    tmp_path: Path, hermetic_environ: pytest.MonkeyPatch
) -> None:
    root = _write_config_root(tmp_path / "config")
    hermetic_environ.setenv("ASTRA_OBSERVABILITY__FSYNC_EACH_RECORD", "true")
    hermetic_environ.setenv("ASTRA_OBSERVABILITY__AUDIT_QUEUE_SIZE", "64")
    hermetic_environ.setenv("ASTRA_OBSERVABILITY__LOG_LEVEL", "ERROR")

    observability = load_settings(
        environment="development", config_root=root, include_environment_variables=True
    ).settings.observability

    assert observability.fsync_each_record is True
    assert observability.audit_queue_size == 64
    assert observability.log_level == "ERROR"


def test_the_environment_variable_selecting_the_environment_is_not_itself_an_override(
    tmp_path: Path, hermetic_environ: pytest.MonkeyPatch
) -> None:
    root = _write_config_root(tmp_path / "config")
    hermetic_environ.setenv("ASTRA_ENVIRONMENT", "development")

    resolved = load_settings(config_root=root, include_environment_variables=True)

    assert resolved.settings.environment == "development"
    assert resolved.sources[-1] == str(root / ENVIRONMENTS_DIRECTORY / "development.toml")


def test_a_nested_override_wins_over_a_scalar_variable_naming_the_same_section(
    tmp_path: Path, hermetic_environ: pytest.MonkeyPatch
) -> None:
    root = _write_config_root(tmp_path / "config")
    hermetic_environ.setenv("ASTRA_GATE", "0.5")
    hermetic_environ.setenv("ASTRA_GATE__MMD_WINDOW", "25")

    resolved = load_settings(
        environment="development", config_root=root, include_environment_variables=True
    )

    assert resolved.settings.gate.mmd_window == 25
    assert resolved.settings.gate.significance_epsilon == 0.05


def test_environment_variables_are_ignored_when_they_are_excluded(
    tmp_path: Path, hermetic_environ: pytest.MonkeyPatch
) -> None:
    root = _write_config_root(tmp_path / "config")
    hermetic_environ.setenv("ASTRA_GATE__SIGNIFICANCE_EPSILON", "0.99")

    resolved = load_settings(
        environment="development", config_root=root, include_environment_variables=False
    )

    assert resolved.settings.gate.significance_epsilon == 0.05
    assert "ASTRA_* environment variables" not in resolved.sources


# --------------------------------------------------------------------------- #
# The configuration hash
# --------------------------------------------------------------------------- #


def test_the_configuration_hash_is_stable_across_two_loads_of_the_same_files(
    tmp_path: Path,
) -> None:
    root = _write_config_root(tmp_path / "config")

    assert _load_synthetic(root).hash == _load_synthetic(root).hash


def test_the_configuration_hash_of_a_settings_object_is_reproducible(
    settings: ResolvedConfiguration,
) -> None:
    assert config_hash(settings.settings) == config_hash(settings.settings)
    assert settings.hash == config_hash(settings.settings)


def test_the_configuration_hash_changes_when_a_single_operating_point_changes(
    tmp_path: Path,
) -> None:
    baseline = _load_synthetic(_write_config_root(tmp_path / "baseline"))
    tightened = _load_synthetic(
        _write_config_root(
            tmp_path / "tightened",
            environment=SYNTHETIC_ENVIRONMENT.replace(
                "significance_epsilon = 0.05", "significance_epsilon = 0.01"
            ),
        )
    )

    assert baseline.hash != tightened.hash


def test_the_configuration_hash_changes_when_a_non_safety_value_changes(
    tmp_path: Path,
) -> None:
    baseline = _load_synthetic(_write_config_root(tmp_path / "baseline"))
    relocated = _load_synthetic(
        _write_config_root(
            tmp_path / "relocated",
            defaults=SYNTHETIC_DEFAULTS.replace(
                'log_directory = "var/runs"', 'log_directory = "var/other"'
            ),
        )
    )

    assert baseline.hash != relocated.hash


def test_two_different_repository_environments_hash_differently() -> None:
    development = load_settings(
        environment="development",
        config_root=CONFIG_ROOT,
        include_environment_variables=False,
    )
    simulation = load_settings(
        environment="simulation",
        config_root=CONFIG_ROOT,
        include_environment_variables=False,
    )

    assert development.hash != simulation.hash


def test_the_configuration_hash_is_a_short_hexadecimal_digest(
    settings: ResolvedConfiguration,
) -> None:
    assert len(settings.hash) == 16
    assert all(character in "0123456789abcdef" for character in settings.hash)


# --------------------------------------------------------------------------- #
# Immutability and strictness
# --------------------------------------------------------------------------- #


def test_a_resolved_section_cannot_be_mutated_after_load(settings: ResolvedConfiguration) -> None:
    with pytest.raises(ValidationError):
        settings.settings.gate.significance_epsilon = 0.42


def test_the_top_level_settings_object_cannot_be_mutated_after_load(
    settings: ResolvedConfiguration,
) -> None:
    with pytest.raises(ValidationError):
        settings.settings.environment = "certification"


def test_an_unknown_key_in_a_section_is_a_startup_failure(tmp_path: Path) -> None:
    root = _write_config_root(
        tmp_path / "config",
        environment=SYNTHETIC_ENVIRONMENT.replace(
            "[gate]\nsignificance_epsilon",
            "[gate]\nsignificence_epsilon = 0.05\nsignificance_epsilon",
        ),
    )

    with pytest.raises(ConfigurationError) as raised:
        _load_synthetic(root)

    assert any(
        item["field"] == "gate.significence_epsilon" for item in raised.value.context["errors"]
    )


def test_an_unknown_key_passed_directly_to_a_section_is_refused() -> None:
    with pytest.raises(ValidationError):
        GateSettings(significance_epsilon=0.05, mmd_threshold=0.1, mmd_windwo=100)  # type: ignore[call-arg]


def test_a_configuration_declaring_a_different_schema_version_is_refused(tmp_path: Path) -> None:
    root = _write_config_root(
        tmp_path / "config",
        environment=SYNTHETIC_ENVIRONMENT.replace("schema_version = 1", "schema_version = 99"),
    )

    with pytest.raises(ConfigurationError) as raised:
        _load_synthetic(root)

    assert any(item["field"] == "schema_version" for item in raised.value.context["errors"])


def test_a_schema_version_mismatch_raises_the_specific_schema_version_error(
    tmp_path: Path,
) -> None:
    # A file written against a different contract is a categorically different
    # failure from an incomplete one, and must not be reported as a possibly
    # missing safety threshold.
    root = _write_config_root(
        tmp_path / "config",
        environment=SYNTHETIC_ENVIRONMENT.replace("schema_version = 1", "schema_version = 99"),
    )

    with pytest.raises(SchemaVersionError) as raised:
        _load_synthetic(root)

    assert raised.value.code == "ASTRA-CFG-002"
    assert "schema version" in str(raised.value)
    assert "safety threshold" not in str(raised.value)


def test_a_missing_threshold_is_not_reported_as_a_schema_version_error(
    tmp_path: Path,
) -> None:
    root = _write_config_root(
        tmp_path / "config",
        environment=SYNTHETIC_ENVIRONMENT.replace("significance_epsilon = 0.05", ""),
    )

    with pytest.raises(ConfigurationError) as raised:
        _load_synthetic(root)

    assert not isinstance(raised.value, SchemaVersionError)
    assert "A-4" in str(raised.value)


def test_the_repository_files_declare_the_schema_version_this_build_supports(
    settings: ResolvedConfiguration,
) -> None:
    assert settings.settings.schema_version == CONFIG_SCHEMA_VERSION


# --------------------------------------------------------------------------- #
# The fail-safe threshold ordering validator
# --------------------------------------------------------------------------- #


def test_strictly_increasing_fail_safe_thresholds_are_accepted() -> None:
    failsafe = FailSafeSettings(
        ood_threshold_degraded=3,
        ood_threshold_limp=6,
        ood_threshold_halt=10,
        degraded_speed_cap_kmh=40.0,
        limp_speed_cap_kmh=20.0,
        integrity_threshold_degraded=2,
        integrity_threshold_limp=4,
        integrity_threshold_halt=8,
        integrity_tolerated_faults=0,
        critical_modalities=(
            SensorModality.CAMERA,
            SensorModality.LIDAR,
            SensorModality.IMU,
            SensorModality.GPS,
            SensorModality.RADAR,
        ),
    )

    assert failsafe.ood_threshold_degraded < failsafe.ood_threshold_limp
    assert failsafe.ood_threshold_limp < failsafe.ood_threshold_halt


@pytest.mark.parametrize(
    ("degraded", "limp", "halt"),
    [
        (6, 3, 10),
        (3, 10, 6),
        (10, 6, 3),
        (3, 3, 10),
        (3, 6, 6),
    ],
)
def test_out_of_order_fail_safe_thresholds_are_refused(degraded: int, limp: int, halt: int) -> None:
    with pytest.raises(ValidationError):
        FailSafeSettings(
            ood_threshold_degraded=degraded,
            ood_threshold_limp=limp,
            ood_threshold_halt=halt,
            degraded_speed_cap_kmh=40.0,
            limp_speed_cap_kmh=20.0,
            integrity_threshold_degraded=2,
            integrity_threshold_limp=4,
            integrity_threshold_halt=8,
            integrity_tolerated_faults=0,
            critical_modalities=(
                SensorModality.CAMERA,
                SensorModality.LIDAR,
                SensorModality.IMU,
                SensorModality.GPS,
                SensorModality.RADAR,
            ),
        )


def test_out_of_order_fail_safe_thresholds_in_a_file_are_a_startup_failure(
    tmp_path: Path,
) -> None:
    root = _write_config_root(
        tmp_path / "config",
        environment=SYNTHETIC_ENVIRONMENT.replace(
            "ood_threshold_limp = 6", "ood_threshold_limp = 1"
        ),
    )

    with pytest.raises(ConfigurationError) as raised:
        _load_synthetic(root)

    assert any(
        item["field"] == "failsafe.ood_threshold_halt" for item in raised.value.context["errors"]
    )


# --------------------------------------------------------------------------- #
# SI unit accessors
# --------------------------------------------------------------------------- #


def test_the_staleness_budget_is_exposed_in_seconds(settings: ResolvedConfiguration) -> None:
    assert settings.settings.sensing.staleness_budget == pytest.approx(0.05)


def test_the_legal_speed_limit_is_exposed_in_metres_per_second(
    settings: ResolvedConfiguration,
) -> None:
    assert settings.settings.shield.legal_speed_limit == pytest.approx(50.0 / 3.6)


def test_the_minimum_stopping_distance_is_exposed_in_metres(
    settings: ResolvedConfiguration,
) -> None:
    assert settings.settings.shield.minimum_stopping_distance == pytest.approx(2.0)


def test_the_degraded_and_limp_speed_caps_are_exposed_in_metres_per_second(
    settings: ResolvedConfiguration,
) -> None:
    failsafe = settings.settings.failsafe

    assert failsafe.degraded_speed_cap == pytest.approx(40.0 / 3.6)
    assert failsafe.limp_speed_cap == pytest.approx(20.0 / 3.6)


def test_the_exploration_steering_limit_is_exposed_in_radians(
    settings: ResolvedConfiguration,
) -> None:
    assert settings.settings.arbitration.exploration_steering_limit == pytest.approx(
        math.radians(15.0)
    )


def test_the_tick_period_is_the_reciprocal_of_the_fast_filter_rate(
    settings: ResolvedConfiguration,
) -> None:
    estimation = settings.settings.estimation

    assert estimation.fast_rate == pytest.approx(20.0)
    assert estimation.slow_rate == pytest.approx(1.0)
    assert estimation.tick_period == pytest.approx(0.05)


def test_the_coverage_level_is_exposed_as_a_probability(settings: ResolvedConfiguration) -> None:
    assert settings.settings.trust.coverage == pytest.approx(0.95)


# --------------------------------------------------------------------------- #
# Unreadable and malformed files
# --------------------------------------------------------------------------- #


def test_a_missing_environment_file_is_a_startup_failure() -> None:
    with pytest.raises(ConfigurationError) as raised:
        load_settings(
            environment="no_such_environment",
            config_root=CONFIG_ROOT,
            include_environment_variables=False,
        )

    assert raised.value.context["environment"] == "no_such_environment"


def test_a_missing_configuration_root_is_a_startup_failure(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError):
        load_settings(
            environment="development",
            config_root=tmp_path / "absent",
            include_environment_variables=False,
        )


def test_a_malformed_environment_file_is_a_startup_failure(tmp_path: Path) -> None:
    root = _write_config_root(tmp_path / "config", environment="[gate\nthis is not = = toml\n")

    with pytest.raises(ConfigurationError) as raised:
        _load_synthetic(root)

    assert raised.value.context["path"] == str(root / ENVIRONMENTS_DIRECTORY / "development.toml")


def test_a_malformed_defaults_file_is_a_startup_failure(tmp_path: Path) -> None:
    root = _write_config_root(tmp_path / "config", defaults="schema_version = = 1\n")

    with pytest.raises(ConfigurationError) as raised:
        _load_synthetic(root)

    assert raised.value.context["path"] == str(root / DEFAULTS_FILENAME)
