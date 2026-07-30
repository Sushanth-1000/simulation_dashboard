"""Shared fixtures.

Everything here is deterministic on purpose. A safety-critical codebase whose
test suite depends on wall-clock time, random identifiers or the ambient
environment produces flaky results, and a flaky safety test is worse than an
absent one: it trains the team to re-run rather than to investigate.

So: the clock is a :class:`~astra.kernel.time.ManualClock` that only moves when
a test moves it, the run identifier is fixed, and the configuration fixtures
never read ``ASTRA_*`` environment variables.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from astra.config.loader import load_settings
from astra.contracts.actuation import ActuationChannel, ActuationSpace
from astra.kernel.enums import LayerId
from astra.kernel.identifiers import ComponentId, RunId, TickId
from astra.kernel.matrix import SymmetricMatrix
from astra.kernel.time import Instant, ManualClock, Timeline
from astra.observability.audit import JsonlAuditSink

if TYPE_CHECKING:
    from collections.abc import Iterator

    from astra.config.loader import ResolvedConfiguration

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CONFIG_ROOT = REPOSITORY_ROOT / "config"


@pytest.fixture
def clock() -> ManualClock:
    """A clock that advances only when a test advances it."""
    return ManualClock(Instant(0, Timeline.MANUAL))


@pytest.fixture
def now() -> Instant:
    """A fixed instant on the manual timeline."""
    return Instant(1_000_000_000, Timeline.MANUAL)


@pytest.fixture
def run() -> RunId:
    """A fixed run identifier, so records are byte-stable across runs."""
    return RunId("run-testfixture01")


@pytest.fixture
def tick() -> TickId:
    """A fixed tick identifier."""
    return TickId(42)


@pytest.fixture
def rcm_component() -> ComponentId:
    """The L9 component identity, the only one permitted to issue commands."""
    return ComponentId(LayerId.L9_RCM)


@pytest.fixture
def proposer_component() -> ComponentId:
    """The L4 Core-A component identity."""
    return ComponentId(LayerId.L4_CORE_A_CMDP)


@pytest.fixture
def twin_component() -> ComponentId:
    """The L5 digital-twin component identity."""
    return ComponentId(LayerId.L5_PINN_TWIN)


@pytest.fixture
def actuation_space() -> ActuationSpace:
    """A two-channel actuation space standing in for a vehicle's command space.

    Deliberately not the real automotive space: the pipeline is domain
    independent, and a test that assumed throttle/brake/steer would be asserting
    a property of one adapter rather than of the core.
    """
    return ActuationSpace(
        (
            ActuationChannel(name="throttle", lower=0.0, upper=1.0, unit="1"),
            ActuationChannel(name="steer", lower=-0.5, upper=0.5, unit="rad"),
        )
    )


@pytest.fixture
def identity_covariance() -> SymmetricMatrix:
    """A well-conditioned 5x5 covariance for the fast state."""
    return SymmetricMatrix.from_diagonal([1.0, 1.0, 0.25, 0.1, 0.5])


@pytest.fixture
def certified_at() -> datetime:
    """A fixed certification instant, timezone-aware as the contract requires."""
    return datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
def expires_at() -> datetime:
    """A fixed expiry instant, strictly after certification."""
    return datetime(2027, 1, 1, tzinfo=UTC)


@pytest.fixture
def settings() -> ResolvedConfiguration:
    """The development configuration, resolved without environment overrides.

    Hermetic: ``include_environment_variables=False`` means a developer with
    ``ASTRA_*`` set in their shell gets the same result as CI.
    """
    return load_settings(
        environment="development",
        config_root=CONFIG_ROOT,
        include_environment_variables=False,
    )


@pytest.fixture
def audit_sink(run: RunId, tmp_path: Path) -> Iterator[JsonlAuditSink]:
    """An audit sink writing into a temporary directory, closed after the test."""
    sink = JsonlAuditSink(run=run, directory=tmp_path, queue_size=256)
    try:
        yield sink
    finally:
        sink.close()
