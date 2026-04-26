"""Logging configuration."""

import logging
import os
import sys

from loguru import logger


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


def setup() -> None:
    """Configure loguru and intercept stdlib logging."""
    level = os.getenv("LOG_LEVEL", "INFO")
    logger.remove()
    logger.add(sys.stderr, level=level, colorize=True)
    logging.basicConfig(handlers=[_InterceptHandler()], level=0, force=True)
