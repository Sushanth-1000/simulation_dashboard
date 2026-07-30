"""Layered configuration resolution, and the hash that makes a run attributable.

Resolution order
----------------
Lowest precedence first:

1. **Packaged defaults** -- ``config/astra.defaults.toml``. Non-safety values
   only: log levels, paths, filter rates.
2. **Environment file** -- ``config/environments/<environment>.toml``. The
   operating point. ``certification.toml`` is the one a safety engineer edits.
3. **Environment variables** -- ``ASTRA_*``, nested with ``__``. Deployment
   overrides, and the mechanism CI uses to vary a single threshold without
   editing a reviewed file.

Merging is a *deep* merge of the mappings: an environment file that sets one
threshold in a section inherits the rest of that section from the defaults
rather than replacing it wholesale. Shallow merging would mean a file touching
one field silently discarded every sibling default -- a quiet way to lose a
safety-relevant value.

Why the configuration hash exists
---------------------------------
Every decision record carries a hash of the resolved configuration. Without it,
a number in a report is unattributable: two runs can produce different verdicts
from identical code because one ran with a tighter epsilon, and nothing in the
evidence would say so. The hash is computed over the fully resolved settings in
canonical form, so it changes if and only if an operating point changed. It is
short-form SHA-256 -- long enough to be collision-free in practice for the
number of configurations a project produces, short enough to read in a log line.
"""

from __future__ import annotations

import hashlib
import json
import os
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from pydantic import ValidationError

from astra.config.schema import AstraSettings
from astra.kernel.constants import CONFIG_SCHEMA_VERSION
from astra.kernel.errors import ConfigurationError, SchemaVersionError

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "DEFAULTS_FILENAME",
    "ENVIRONMENTS_DIRECTORY",
    "ResolvedConfiguration",
    "config_hash",
    "default_config_root",
    "load_settings",
]

DEFAULTS_FILENAME: Final = "astra.defaults.toml"
"""Name of the packaged, non-safety default file."""

ENVIRONMENTS_DIRECTORY: Final = "environments"
"""Directory under the config root holding one file per environment."""

_ENV_PREFIX: Final = "ASTRA_"
_ENV_NESTED_DELIMITER: Final = "__"
_HASH_LENGTH: Final = 16


class ResolvedConfiguration:
    """A frozen configuration together with the provenance of how it was resolved.

    The provenance is not decoration. When a safety engineer asks why a run used
    a particular epsilon, the answer is a list of the files and overrides that
    contributed, in order -- and that answer has to survive into the evidence
    archive alongside the hash.

    Attributes:
        settings: The validated, frozen settings.
        sources: The contributing sources, lowest precedence first.
        hash: The short SHA-256 digest of the resolved configuration.
    """

    __slots__ = ("_hash", "_settings", "_sources")

    def __init__(self, settings: AstraSettings, sources: tuple[str, ...]) -> None:
        """Initialise the resolved configuration.

        Args:
            settings: The validated settings.
            sources: Human-readable descriptions of each contributing source, in
                increasing order of precedence.
        """
        self._settings = settings
        self._sources = sources
        self._hash = config_hash(settings)

    @property
    def settings(self) -> AstraSettings:
        """Return the frozen settings."""
        return self._settings

    @property
    def sources(self) -> tuple[str, ...]:
        """Return the contributing sources, lowest precedence first."""
        return self._sources

    @property
    def hash(self) -> str:
        """Return the short digest stamped on every decision record."""
        return self._hash


def default_config_root() -> Path:
    """Return the repository's ``config/`` directory.

    Resolved relative to this module rather than the working directory, so that
    ``astra doctor`` reports the same configuration regardless of where it is
    invoked from.

    Returns:
        The path to the configuration root. May not exist, which the loader
        reports as a configuration error rather than assuming.
    """
    return Path(__file__).resolve().parents[3] / "config"


def _read_toml(path: Path) -> dict[str, Any]:
    """Read and parse one TOML file.

    Args:
        path: The file to read.

    Returns:
        The parsed mapping.

    Raises:
        ConfigurationError: If the file cannot be read or is not valid TOML.
            Both are startup failures: a configuration that could not be fully
            read is one the system has no basis to run under.
    """
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except OSError as error:
        message = f"cannot read configuration file {path}"
        raise ConfigurationError(message, context={"path": str(path)}) from error
    except tomllib.TOMLDecodeError as error:
        message = f"configuration file {path} is not valid TOML: {error}"
        raise ConfigurationError(message, context={"path": str(path)}) from error


def _deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Merge two configuration mappings, recursing into nested sections.

    Args:
        base: The lower-precedence mapping.
        override: The higher-precedence mapping.

    Returns:
        A new mapping in which ``override`` wins per leaf key, and nested
        sections are merged rather than replaced.
    """
    merged = dict(base)
    for key, value in override.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(existing, value)
        else:
            merged[key] = value
    return merged


def _coerce_scalar(raw: str) -> Any:  # noqa: ANN401 - deliberately returns a TOML scalar
    """Interpret an environment-variable string as a TOML-ish scalar.

    Environment variables are strings, but the schema expects numbers and
    booleans. Parsing here keeps that coercion in one reviewable place rather
    than relying on each field's validator to accept strings.

    Args:
        raw: The raw environment value.

    Returns:
        A ``bool``, ``int``, ``float`` or the original string.
    """
    lowered = raw.strip().lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        return raw


def _environment_overrides() -> dict[str, Any]:
    """Collect ``ASTRA_*`` environment variables into a nested mapping.

    ``ASTRA_GATE__SIGNIFICANCE_EPSILON=0.05`` becomes
    ``{"gate": {"significance_epsilon": 0.05}}``.

    Returns:
        The nested override mapping, empty if no variables are set.
    """
    overrides: dict[str, Any] = {}
    for name, raw in os.environ.items():
        if not name.startswith(_ENV_PREFIX):
            continue
        path = name[len(_ENV_PREFIX) :].lower().split(_ENV_NESTED_DELIMITER)
        cursor = overrides
        for part in path[:-1]:
            nested = cursor.setdefault(part, {})
            if not isinstance(nested, dict):
                # A scalar already occupies this position, e.g. both ASTRA_GATE
                # and ASTRA_GATE__MMD_WINDOW are set. The nested key wins and
                # the scalar is discarded: a bare section name is not a settable
                # value in this schema, so it could only ever have been a
                # mistake, whereas the nested name addresses a real field.
                nested = {}
                cursor[part] = nested
            cursor = nested
        cursor[path[-1]] = _coerce_scalar(raw)
    return overrides


def config_hash(settings: AstraSettings) -> str:
    """Return the short digest identifying a resolved configuration.

    Computed over the settings serialised in canonical form -- sorted keys,
    fixed separators -- so it depends on the *values* and not on the order they
    happened to be written in. Two runs share a hash if and only if they ran
    under the same operating point.

    Args:
        settings: The resolved settings.

    Returns:
        The first :data:`_HASH_LENGTH` hex characters of the SHA-256 digest.
    """
    canonical = json.dumps(settings.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:_HASH_LENGTH]


def load_settings(
    *,
    environment: str | None = None,
    config_root: Path | None = None,
    include_environment_variables: bool = True,
) -> ResolvedConfiguration:
    """Resolve, validate and freeze the configuration for a run.

    Args:
        environment: Which environment file to layer on. Defaults to
            ``ASTRA_ENVIRONMENT`` and then to ``development``.
        config_root: The configuration directory. Defaults to
            :func:`default_config_root`.
        include_environment_variables: Whether to apply ``ASTRA_*`` overrides.
            Turned off by tests that need a hermetic configuration.

    Returns:
        The frozen settings with their provenance and hash.

    Raises:
        ConfigurationError: If a file is missing or malformed, or if validation
            fails -- most importantly when a safety threshold with no default
            was not supplied (assumption A-4).
    """
    root = config_root if config_root is not None else default_config_root()
    resolved_environment = (
        environment or os.environ.get(f"{_ENV_PREFIX}ENVIRONMENT") or "development"
    )

    sources: list[str] = []
    merged: dict[str, Any] = {}

    defaults_path = root / DEFAULTS_FILENAME
    if defaults_path.is_file():
        merged = _deep_merge(merged, _read_toml(defaults_path))
        sources.append(str(defaults_path))

    environment_path = root / ENVIRONMENTS_DIRECTORY / f"{resolved_environment}.toml"
    if not environment_path.is_file():
        message = (
            f"no configuration file for environment {resolved_environment!r} at {environment_path}"
        )
        raise ConfigurationError(
            message,
            context={"environment": resolved_environment, "path": str(environment_path)},
        )
    merged = _deep_merge(merged, _read_toml(environment_path))
    sources.append(str(environment_path))

    if include_environment_variables:
        overrides = _environment_overrides()
        # `environment` selects the file; it is not itself a settings override.
        overrides.pop("environment", None)
        if overrides:
            merged = _deep_merge(merged, overrides)
            sources.append(f"{_ENV_PREFIX}* environment variables")

    merged.setdefault("environment", resolved_environment)

    try:
        settings = AstraSettings.model_validate(merged)
    except ValidationError as error:
        failures = [
            {"field": ".".join(str(part) for part in item["loc"]), "problem": item["msg"]}
            for item in error.errors()
        ]
        context: dict[str, Any] = {
            "environment": resolved_environment,
            "sources": sources,
            "errors": failures,
        }
        # A schema-version mismatch gets its own error class and its own
        # message. It is a categorically different failure from a missing
        # threshold -- the file is not merely incomplete, it was written against
        # a different contract -- and reporting it as "a safety threshold may be
        # missing" would send a reader looking for the wrong problem.
        if any(failure["field"] == "schema_version" for failure in failures):
            message = (
                f"configuration for environment {resolved_environment!r} declares an "
                f"unsupported schema version; this build requires {CONFIG_SCHEMA_VERSION}"
            )
            raise SchemaVersionError(message, context=context) from error
        message = (
            f"configuration for environment {resolved_environment!r} is invalid; "
            f"a required safety threshold may be missing (see assumption A-4)"
        )
        raise ConfigurationError(message, context=context) from error

    return ResolvedConfiguration(settings=settings, sources=tuple(sources))
