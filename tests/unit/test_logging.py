"""Unit tests for the non-blocking structured logging pipeline.

Every test in this file runs under an autouse fixture that tears the pipeline
down again. A leaked :class:`~logging.handlers.QueueListener` would keep a
background thread alive and leave handlers attached to the ``astra`` logger,
which is exactly the kind of cross-test contamination that turns an unrelated
failure into an afternoon of debugging.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import sys
from typing import TYPE_CHECKING

import pytest

from astra.kernel.enums import LayerId
from astra.kernel.identifiers import ComponentId
from astra.observability.context import run_scope, tick_scope
from astra.observability.logging import (
    ASTRA_LOGGER_NAME,
    CorrelationFilter,
    JsonLogFormatter,
    configure_logging,
    get_logger,
    shutdown_logging,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from astra.kernel.identifiers import RunId, TickId

SHADOW = ComponentId(LayerId.L9_RCM, "shadow")


@pytest.fixture(autouse=True)
def _restored_astra_logger() -> Iterator[None]:
    """Restore the ``astra`` logger exactly as it was, whatever the test did."""
    logger = logging.getLogger(ASTRA_LOGGER_NAME)
    level = logger.level
    propagate = logger.propagate
    handlers = list(logger.handlers)
    try:
        yield
    finally:
        shutdown_logging()
        logger.handlers[:] = handlers
        logger.setLevel(level)
        logger.propagate = propagate


def _record(message: str = "epsilon tightened to %s", **extras: object) -> logging.LogRecord:
    record = logging.LogRecord(
        name="astra.gate",
        level=logging.WARNING,
        pathname=__file__,
        lineno=17,
        msg=message,
        args=(0.01,),
        exc_info=None,
    )
    for key, value in extras.items():
        setattr(record, key, value)
    return record


def _correlation(record: logging.LogRecord) -> dict[str, object]:
    # Read through `__dict__` rather than as attributes: the keys are added by
    # the filter, so a missing one must surface as a failure, not as a default.
    return {key: record.__dict__[key] for key in ("astra_run", "astra_tick", "astra_component")}


# --------------------------------------------------------------------------- #
# configure_logging
# --------------------------------------------------------------------------- #


def test_configure_logging_installs_exactly_one_handler_on_the_astra_logger() -> None:
    configure_logging()

    assert len(logging.getLogger(ASTRA_LOGGER_NAME).handlers) == 1


def test_the_only_installed_handler_is_a_queue_handler() -> None:
    configure_logging()

    (handler,) = logging.getLogger(ASTRA_LOGGER_NAME).handlers

    assert isinstance(handler, logging.handlers.QueueHandler)


def test_the_installed_queue_handler_carries_the_correlation_filter() -> None:
    configure_logging()

    (handler,) = logging.getLogger(ASTRA_LOGGER_NAME).handlers

    assert any(isinstance(filter_, CorrelationFilter) for filter_ in handler.filters)


def test_the_astra_logger_does_not_propagate_to_the_root_logger() -> None:
    configure_logging()

    assert logging.getLogger(ASTRA_LOGGER_NAME).propagate is False


def test_configure_logging_applies_the_requested_level() -> None:
    configure_logging(level="DEBUG")

    assert logging.getLogger(ASTRA_LOGGER_NAME).level == logging.DEBUG


def test_configuring_logging_twice_does_not_duplicate_handlers() -> None:
    configure_logging()
    first = list(logging.getLogger(ASTRA_LOGGER_NAME).handlers)
    configure_logging()
    second = list(logging.getLogger(ASTRA_LOGGER_NAME).handlers)

    assert len(second) == 1
    assert second[0] is not first[0]


def test_configure_logging_accepts_caller_supplied_sink_handlers() -> None:
    sink = logging.handlers.BufferingHandler(capacity=8)

    configure_logging(handlers=[sink])

    assert len(logging.getLogger(ASTRA_LOGGER_NAME).handlers) == 1


# --------------------------------------------------------------------------- #
# shutdown_logging
# --------------------------------------------------------------------------- #


def test_shutdown_logging_clears_every_handler_from_the_astra_logger() -> None:
    configure_logging()

    shutdown_logging()

    assert logging.getLogger(ASTRA_LOGGER_NAME).handlers == []


def test_shutdown_logging_is_safe_when_logging_was_never_configured() -> None:
    shutdown_logging()
    shutdown_logging()

    assert logging.getLogger(ASTRA_LOGGER_NAME).handlers == []


# --------------------------------------------------------------------------- #
# get_logger
# --------------------------------------------------------------------------- #


def test_get_logger_nests_an_arbitrary_module_name_under_the_astra_hierarchy() -> None:
    assert get_logger("shield").name == "astra.shield"
    assert get_logger("astra_extras.plugin").name == "astra.astra_extras.plugin"


def test_get_logger_returns_a_name_already_inside_the_hierarchy_unchanged() -> None:
    assert get_logger("astra.gate.icp").name == "astra.gate.icp"


def test_get_logger_returns_the_hierarchy_root_itself_unchanged() -> None:
    assert get_logger(ASTRA_LOGGER_NAME).name == ASTRA_LOGGER_NAME


# --------------------------------------------------------------------------- #
# JsonLogFormatter
# --------------------------------------------------------------------------- #


def test_the_formatter_emits_one_valid_json_document() -> None:
    rendered = JsonLogFormatter().format(_record())

    assert "\n" not in rendered
    assert isinstance(json.loads(rendered), dict)


def test_the_formatter_carries_the_level_logger_and_interpolated_message() -> None:
    payload = json.loads(JsonLogFormatter().format(_record()))

    assert payload["level"] == "WARNING"
    assert payload["logger"] == "astra.gate"
    assert payload["message"] == "epsilon tightened to 0.01"


def test_the_formatter_always_carries_the_correlation_keys_even_when_unbound() -> None:
    payload = json.loads(JsonLogFormatter().format(_record()))

    assert payload["run"] is None
    assert payload["tick"] is None
    assert payload["component"] is None


def test_the_formatter_carries_the_correlation_values_the_filter_attached(
    run: RunId, tick: TickId
) -> None:
    record = _record()
    with run_scope(run), tick_scope(tick, SHADOW):
        CorrelationFilter().filter(record)

    payload = json.loads(JsonLogFormatter().format(record))

    assert payload["run"] == run.value
    assert payload["tick"] == tick.value
    assert payload["component"] == "L9_RCM/shadow"


def test_structured_context_passed_as_extra_appears_under_the_context_key() -> None:
    payload = json.loads(
        JsonLogFormatter().format(_record(gate="STATISTICAL", alpha=0.05, vetoed=True))
    )

    assert payload["context"] == {"gate": "STATISTICAL", "alpha": 0.05, "vetoed": True}


def test_a_non_scalar_context_value_is_reduced_to_its_string_form() -> None:
    payload = json.loads(JsonLogFormatter().format(_record(component=SHADOW)))

    assert payload["context"] == {"component": "L9_RCM/shadow"}


def test_a_record_with_no_structured_context_carries_no_context_key() -> None:
    payload = json.loads(JsonLogFormatter().format(_record()))

    assert "context" not in payload


def test_the_formatter_renders_an_exception_when_the_record_carries_one() -> None:
    try:
        raise ZeroDivisionError  # noqa: TRY301 - a real traceback is the point
    except ZeroDivisionError:
        record = _record()
        record.exc_info = sys.exc_info()

    payload = json.loads(JsonLogFormatter().format(record))

    assert "ZeroDivisionError" in payload["exception"]


# --------------------------------------------------------------------------- #
# CorrelationFilter
# --------------------------------------------------------------------------- #


def test_the_correlation_filter_never_suppresses_a_record() -> None:
    assert CorrelationFilter().filter(_record()) is True


def test_the_correlation_filter_attaches_the_keys_as_nulls_outside_every_scope() -> None:
    record = _record()

    CorrelationFilter().filter(record)

    assert _correlation(record) == {
        "astra_run": None,
        "astra_tick": None,
        "astra_component": None,
    }


def test_the_correlation_filter_attaches_the_run_and_tick_in_scope(
    run: RunId, tick: TickId
) -> None:
    record = _record()

    with run_scope(run), tick_scope(tick):
        CorrelationFilter().filter(record)

    assert _correlation(record) == {
        "astra_run": run.value,
        "astra_tick": tick.value,
        "astra_component": None,
    }


def test_the_correlation_filter_attaches_the_component_bound_by_the_run_scope(
    run: RunId,
) -> None:
    record = _record()

    with run_scope(run, ComponentId(LayerId.L9_RCM)):
        CorrelationFilter().filter(record)

    assert _correlation(record)["astra_component"] == "L9_RCM/primary"


def test_the_correlation_filter_reflects_the_scope_at_the_moment_it_ran(
    run: RunId, tick: TickId
) -> None:
    inside = _record()
    outside = _record()

    with run_scope(run), tick_scope(tick):
        CorrelationFilter().filter(inside)
    CorrelationFilter().filter(outside)

    assert _correlation(inside)["astra_run"] == run.value
    assert _correlation(outside)["astra_run"] is None
