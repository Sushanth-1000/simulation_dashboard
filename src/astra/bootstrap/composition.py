"""The composition root: the one place that knows how ASTRA is assembled.

Why a composition root
----------------------
Every layer depends on abstractions -- a :class:`~astra.kernel.time.Clock`, an
:class:`~astra.ports.infrastructure.EventSink`, a
:class:`~astra.ports.infrastructure.ProfileRepository` -- and none of them
constructs a concrete one. If they did, the CARLA adapter would be reachable
from the safety island, the audit sink could not be swapped for a test double,
and replay would be impossible because a layer could read the real clock.

Concentrating construction here keeps that discipline enforceable: this is the
only module permitted to name a concrete implementation, so a review of *one*
file establishes what the running system is made of.

What this module deliberately does not do
-----------------------------------------
It assembles **only what exists**. Phase 1 has no layers, so
:class:`AstraRuntime` holds configuration, a clock, an audit sink and the
verified invariant catalogue -- and nothing that pretends to be a pipeline. A
placeholder ``L2`` that returns zeros would be worse than an absent one: it
would let integration code be written against behaviour no real filter will
have, and the resulting mismatch would surface during closed-loop integration,
the stage the roadmap protects with slack precisely because it does not
compress.

Startup order is a safety property
----------------------------------
The order below is chosen, not incidental:

1. **Configuration first**, and frozen. Nothing may run under an operating point
   that has not been fully validated -- a missing safety threshold must stop the
   system before the vehicle moves (A-4).
2. **Invariant catalogue verified next.** If the safety argument is malformed,
   there is no point starting the machinery it constrains.
3. **Clock**, so every subsequent timestamp comes from one substitutable source.
4. **Audit sink last**, because it is the only step that touches the filesystem
   and the only one that starts a thread. Anything that fails before this point
   fails without leaving a partial evidence directory behind.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from astra.config.loader import load_settings
from astra.invariants.catalogue import SEPARATION_INVARIANTS
from astra.kernel.constants import CONFIG_SCHEMA_VERSION
from astra.kernel.errors import ConfigurationError, InvariantViolationError
from astra.kernel.identifiers import RunId
from astra.kernel.time import SystemClock
from astra.observability.audit import JsonlAuditSink
from astra.observability.logging import configure_logging, get_logger

if TYPE_CHECKING:
    from types import TracebackType

    from astra.config.loader import ResolvedConfiguration
    from astra.config.schema import AstraSettings
    from astra.kernel.time import Clock

__all__ = ["AstraRuntime", "build_runtime", "verify_invariant_catalogue"]

_EXPECTED_INVARIANT_COUNT = 10

_logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class AstraRuntime:
    """An assembled ASTRA runtime: everything Phase 1 can legitimately provide.

    Frozen, because the composition of a running system is not something a
    component may alter. Swapping a clock or an audit sink mid-run would break
    both replay determinism and the completeness of the evidence archive.

    Attributes:
        run: The identity of this run. The only random identifier in the system;
            supplied explicitly when replaying a recorded run.
        configuration: The resolved, frozen configuration with its provenance
            and hash.
        clock: The single time source. No component reads time any other way.
        audit_sink: The evidence sink for this run.
    """

    run: RunId
    configuration: ResolvedConfiguration
    clock: Clock
    audit_sink: JsonlAuditSink

    @property
    def settings(self) -> AstraSettings:
        """Return the frozen settings.

        Returns:
            The validated configuration this runtime was built with.
        """
        return self.configuration.settings

    @property
    def config_hash(self) -> str:
        """Return the configuration hash stamped on every decision record.

        Returns:
            The short digest identifying this run's operating point.
        """
        return self.configuration.hash

    def close(self) -> None:
        """Release the runtime's resources and complete the evidence archive.

        Flushes and closes the audit sink so a run's evidence is whole even when
        the process is stopping. Idempotent.
        """
        self.audit_sink.close()

    def __enter__(self) -> AstraRuntime:
        """Enter the runtime's scope.

        Returns:
            This runtime.
        """
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the runtime on scope exit, including on an exception path.

        Args:
            exc_type: The exception type, if the block raised.
            exc_value: The exception, if the block raised.
            traceback: The traceback, if the block raised.
        """
        self.close()


def verify_invariant_catalogue() -> None:
    """Check that the safety argument is present and well formed.

    Run at startup, before any machinery the invariants constrain. The checks
    are structural rather than behavioural -- this cannot prove the invariants
    hold, only that the catalogue that declares them has not been depopulated,
    duplicated or stripped of its enforcement mechanisms. That is worth doing
    because a safety argument silently reduced to nine entries, or to entries
    with empty mechanisms, would still print convincingly.

    Raises:
        InvariantViolationError: If the catalogue is the wrong size, contains a
            duplicate identifier, or contains an entry with an empty statement
            or mechanism.
    """
    if len(SEPARATION_INVARIANTS) != _EXPECTED_INVARIANT_COUNT:
        message = (
            f"the separation invariant catalogue declares {len(SEPARATION_INVARIANTS)} "
            f"invariants, expected {_EXPECTED_INVARIANT_COUNT}"
        )
        raise InvariantViolationError(message, context={"declared": len(SEPARATION_INVARIANTS)})

    identifiers = [entry.identifier for entry in SEPARATION_INVARIANTS]
    if len(identifiers) != len(set(identifiers)):
        message = "the separation invariant catalogue contains a duplicate identifier"
        raise InvariantViolationError(message, context={"identifiers": identifiers})

    for entry in SEPARATION_INVARIANTS:
        if not entry.statement or not entry.mechanism:
            message = (
                f"{entry.identifier} has no statement or no enforcement mechanism; "
                f"an invariant without either is not part of a safety argument"
            )
            raise InvariantViolationError(message, context={"identifier": entry.identifier})


def build_runtime(
    *,
    environment: str | None = None,
    config_root: Path | None = None,
    run: RunId | None = None,
    log_directory: Path | None = None,
) -> AstraRuntime:
    """Assemble a runtime, in the startup order the safety argument requires.

    Args:
        environment: Which environment configuration to load. Defaults to
            ``ASTRA_ENVIRONMENT``, then ``development``.
        config_root: The configuration directory. Defaults to the repository's.
        run: The run identity. Generated when omitted; supplied explicitly to
            replay a recorded run under its original identity.
        log_directory: Root for the run's evidence directory. Defaults to the
            configured ``observability.log_directory``.

    Returns:
        The assembled runtime. The caller owns its lifetime and must close it,
        preferably by using it as a context manager.

    Raises:
        ConfigurationError: If the configuration is missing, malformed, or
            omits a required safety threshold (A-4).
        InvariantViolationError: If the invariant catalogue does not verify.
        AdapterError: If the evidence directory cannot be opened.
    """
    configuration = load_settings(environment=environment, config_root=config_root)
    settings = configuration.settings

    if settings.schema_version != CONFIG_SCHEMA_VERSION:
        message = (
            f"configuration declares schema version {settings.schema_version}, "
            f"this build requires {CONFIG_SCHEMA_VERSION}"
        )
        raise ConfigurationError(message, context={"declared": settings.schema_version})

    verify_invariant_catalogue()

    configure_logging(level=settings.observability.log_level)

    resolved_run = run if run is not None else RunId.generate()
    clock = SystemClock()
    directory = (
        log_directory if log_directory is not None else Path(settings.observability.log_directory)
    )
    audit_sink = JsonlAuditSink(
        run=resolved_run,
        directory=directory,
        queue_size=settings.observability.audit_queue_size,
        fsync_each_record=settings.observability.fsync_each_record,
    )

    _logger.info(
        "runtime assembled",
        extra={
            "run": resolved_run.value,
            "environment": settings.environment,
            "config_hash": configuration.hash,
            "audit_log": str(audit_sink.path),
        },
    )

    return AstraRuntime(
        run=resolved_run,
        configuration=configuration,
        clock=clock,
        audit_sink=audit_sink,
    )
