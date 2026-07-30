"""Structured diagnostic logging that cannot block a tick.

Diagnostic logging is not audit logging
---------------------------------------
These are two different systems on purpose. The audit sink in
:mod:`astra.observability.audit` produces certification evidence: it is
schema-versioned, append-only and complete from tick zero. This module produces
*diagnostics*: what an engineer reads while debugging. A component that is
silent here may still be emitting ``SAFETY_CRITICAL`` audit records, which is
why :class:`~astra.kernel.enums.EventSeverity` deliberately does not reuse the
``logging`` module's levels.

Why a queue handler
-------------------
``logging``'s standard handlers write synchronously. A ``StreamHandler`` to a
pipe that nobody is draining blocks; a ``FileHandler`` on a busy disk blocks.
Either one inside a tick violates SI-8 and the 10 ms end-to-end budget. So the
only handler attached to the ASTRA logger is a :class:`~logging.handlers.QueueHandler`,
and a :class:`~logging.handlers.QueueListener` on a background thread owns every
handler that actually performs I/O.

Why JSON output
---------------
Diagnostic logs from a run get read alongside that run's audit records, often by
a script rather than a human. Emitting structured JSON means the two can be
joined on run and tick without a log-parsing regex, and it means the correlation
context is carried as fields rather than embedded in prose.

The no-f-string rule
--------------------
``logger.info("tick %s", tick)`` rather than ``logger.info(f"tick {tick}")``.
The lazy form pays the formatting cost only if a handler actually emits the
record; the f-string pays it always, on the hot path, including when the level
is filtered out. The ``G`` lint rule enforces this project-wide.
"""

from __future__ import annotations

import atexit
import json
import logging
import logging.handlers
import queue
from typing import TYPE_CHECKING, Any, Final, override

from astra.observability.context import current_component, current_run, current_tick

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = [
    "ASTRA_LOGGER_NAME",
    "CorrelationFilter",
    "JsonLogFormatter",
    "configure_logging",
    "get_logger",
    "shutdown_logging",
]

ASTRA_LOGGER_NAME: Final = "astra"
"""Root of the ASTRA logger hierarchy. Every module logs beneath it."""

_LOG_QUEUE_SIZE: Final = 4096

# Attributes `logging` puts on every record. Anything not in this set was added
# by a caller as structured context and is forwarded into the JSON payload.
_STANDARD_RECORD_ATTRIBUTES: Final[frozenset[str]] = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
        "taskName",
        "astra_run",
        "astra_tick",
        "astra_component",
    }
)

_listener: logging.handlers.QueueListener | None = None


class CorrelationFilter(logging.Filter):
    """Attaches the current run, tick and component to every record.

    A filter rather than an adapter or a formatter detail, so that correlation
    is applied once at the logger and no call site has to remember to pass it.
    """

    @override
    def filter(self, record: logging.LogRecord) -> bool:
        """Attach correlation identifiers to the record.

        Args:
            record: The record being emitted.

        Returns:
            ``True`` always -- this filter enriches records, it does not
            suppress them.
        """
        run = current_run()
        tick = current_tick()
        component = current_component()
        record.astra_run = run.value if run is not None else None
        record.astra_tick = tick.value if tick is not None else None
        record.astra_component = str(component) if component is not None else None
        return True


class JsonLogFormatter(logging.Formatter):
    """Renders a record as one JSON object per line."""

    @override
    def format(self, record: logging.LogRecord) -> str:
        """Render the record.

        Args:
            record: The record to render.

        Returns:
            A single-line JSON document carrying the message, the correlation
            identifiers and any structured context the caller supplied.
        """
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "run": getattr(record, "astra_run", None),
            "tick": getattr(record, "astra_tick", None),
            "component": getattr(record, "astra_component", None),
        }
        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _STANDARD_RECORD_ATTRIBUTES and not key.startswith("_")
        }
        if extras:
            payload["context"] = {key: _as_json_scalar(value) for key, value in extras.items()}
        if record.exc_info is not None:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, separators=(",", ":"), ensure_ascii=False, default=str)


def _as_json_scalar(value: object) -> object:
    """Reduce a structured-context value to something JSON can carry.

    Args:
        value: The value a caller attached to a log record.

    Returns:
        The value if it is already a JSON scalar, otherwise its string form.
    """
    if isinstance(value, bool | int | float | str) or value is None:
        return value
    return str(value)


def configure_logging(
    *,
    level: str = "INFO",
    handlers: Iterable[logging.Handler] | None = None,
) -> None:
    """Install the non-blocking logging pipeline for the ASTRA logger.

    Idempotent: calling it a second time tears down the previous listener first,
    so a test that reconfigures logging does not accumulate handlers and
    duplicate every record.

    Args:
        level: The diagnostic level for the ASTRA logger hierarchy.
        handlers: The handlers that perform the actual I/O, owned by the
            background listener. Defaults to a single stderr handler with the
            JSON formatter.
    """
    shutdown_logging()

    sink_handlers: tuple[logging.Handler, ...]
    if handlers is None:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(JsonLogFormatter())
        sink_handlers = (stream_handler,)
    else:
        sink_handlers = tuple(handlers)

    log_queue: queue.Queue[logging.LogRecord] = queue.Queue(maxsize=_LOG_QUEUE_SIZE)
    queue_handler = logging.handlers.QueueHandler(log_queue)
    queue_handler.addFilter(CorrelationFilter())

    logger = logging.getLogger(ASTRA_LOGGER_NAME)
    logger.setLevel(level)
    logger.handlers.clear()
    logger.addHandler(queue_handler)
    # ASTRA's records are structured and go to its own handlers; letting them
    # also reach the root logger would emit every record twice whenever an
    # application configured `basicConfig`.
    logger.propagate = False

    global _listener  # noqa: PLW0603 - module-level listener is the lifetime being managed
    _listener = logging.handlers.QueueListener(
        log_queue, *sink_handlers, respect_handler_level=True
    )
    _listener.start()
    atexit.register(shutdown_logging)


def shutdown_logging() -> None:
    """Stop the background listener and detach ASTRA's handlers.

    Idempotent, and safe to call when logging was never configured.
    """
    global _listener  # noqa: PLW0603 - module-level listener is the lifetime being managed
    if _listener is not None:
        _listener.stop()
        _listener = None
    logging.getLogger(ASTRA_LOGGER_NAME).handlers.clear()


def get_logger(name: str) -> logging.Logger:
    """Return a logger beneath the ASTRA hierarchy.

    Args:
        name: Usually ``__name__``. A name already inside the hierarchy is
            returned as-is; anything else is nested beneath it, so no ASTRA
            module can accidentally log outside the configured pipeline.

    Returns:
        The logger.
    """
    if name == ASTRA_LOGGER_NAME or name.startswith(f"{ASTRA_LOGGER_NAME}."):
        return logging.getLogger(name)
    return logging.getLogger(f"{ASTRA_LOGGER_NAME}.{name}")
