"""Tests for logging configuration."""

import logging

import pytest

from odin import log
from odin.log import HealthCheckFilter


@pytest.mark.parametrize("path", ["/health", "/health?verbose=true"])
def test_health_check_filter_suppresses_health(path: str) -> None:
    """Health check requests are filtered out of the access log."""
    f = HealthCheckFilter()
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        0,
        f'127.0.0.1 - "GET {path} HTTP/1.1" 200',
        (),
        None,
    )
    assert f.filter(record) is False


@pytest.mark.parametrize("path", ["/", "/profile", "/profile/stream"])
def test_health_check_filter_passes_other_routes(path: str) -> None:
    """Non-health requests pass through the access log filter."""
    f = HealthCheckFilter()
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        0,
        f'127.0.0.1 - "GET {path} HTTP/1.1" 200',
        (),
        None,
    )
    assert f.filter(record) is True


def test_setup_installs_health_check_filter_on_uvicorn_access() -> None:
    """log.setup() attaches HealthCheckFilter to the uvicorn.access logger."""
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.filters = [
        f for f in access_logger.filters if not isinstance(f, HealthCheckFilter)
    ]

    log.setup()

    assert any(isinstance(f, HealthCheckFilter) for f in access_logger.filters)


def test_setup_does_not_install_duplicate_health_check_filter() -> None:
    """Calling log.setup() repeatedly leaves only one HealthCheckFilter installed."""
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.filters = [
        f for f in access_logger.filters if not isinstance(f, HealthCheckFilter)
    ]

    log.setup()
    log.setup()

    health_filters = [f for f in access_logger.filters if isinstance(f, HealthCheckFilter)]
    assert len(health_filters) == 1
