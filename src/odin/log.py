"""Logging configuration."""

from __future__ import annotations

import logging
import os
import sys
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from loguru import Record


class _InterceptHandler(logging.Handler):
    """Route stdlib logging records through loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        """Forward a stdlib log record to loguru."""
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = logging.currentframe(), 2
        while frame is not None and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def _odin_only_at_debug(record: Record) -> bool:
    """Pass DEBUG/TRACE only for odin modules; WARNING+ always passes."""
    if record["level"].no < logging.WARNING:
        name = record["name"] or ""
        return name.startswith(("odin", "__main__"))
    return True


class HealthCheckFilter(logging.Filter):
    """Drop uvicorn access log entries for the /health endpoint."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Return False for /health access log records, True otherwise."""
        return "/health" not in record.getMessage()


def setup() -> None:
    """Configure loguru and intercept stdlib logging."""
    level = os.getenv("LOG_LEVEL", "INFO")
    logger.remove()
    logger.add(sys.stderr, level=level, colorize=True, filter=_odin_only_at_debug)
    logging.basicConfig(handlers=[_InterceptHandler()], level=0, force=True)

    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, HealthCheckFilter) for f in access_logger.filters):
        access_logger.addFilter(HealthCheckFilter())
