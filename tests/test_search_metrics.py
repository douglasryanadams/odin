"""Tests for Valkey-backed per-backend search metrics."""

from unittest.mock import AsyncMock, patch

import pytest

from odin.search import metrics
from odin.search.aggregator import BackendOutcome


@pytest.fixture
def valkey() -> AsyncMock:
    client = AsyncMock()
    client.get.return_value = None
    client.incrby.return_value = 1
    return client


async def test_record_backend_outcome_increments_calls_latency_and_results_on_success(
    valkey: AsyncMock,
) -> None:
    outcome = BackendOutcome(name="brave", elapsed_seconds=0.25, outcome="success", result_count=5)
    with patch("odin.search.metrics._today_utc", return_value="2024-01-01"):
        await metrics.record_backend_outcome(valkey, outcome)

    calls = {c.args[0]: c.args[1] for c in valkey.incrby.call_args_list}
    assert calls["metrics:search:brave:2024-01-01:calls"] == 1
    assert calls["metrics:search:brave:2024-01-01:latency_ms"] == 250
    assert calls["metrics:search:brave:2024-01-01:results"] == 5
    assert "metrics:search:brave:2024-01-01:errors" not in calls
    assert "metrics:search:brave:2024-01-01:timeouts" not in calls
    assert valkey.expireat.call_count == len(calls)


async def test_record_backend_outcome_increments_error_counter_on_error(
    valkey: AsyncMock,
) -> None:
    outcome = BackendOutcome(name="brave", elapsed_seconds=0.1, outcome="error", result_count=0)
    with patch("odin.search.metrics._today_utc", return_value="2024-01-01"):
        await metrics.record_backend_outcome(valkey, outcome)

    keys = [c.args[0] for c in valkey.incrby.call_args_list]
    assert "metrics:search:brave:2024-01-01:errors" in keys
    assert "metrics:search:brave:2024-01-01:timeouts" not in keys


async def test_record_backend_outcome_increments_timeout_counter_on_timeout(
    valkey: AsyncMock,
) -> None:
    outcome = BackendOutcome(name="brave", elapsed_seconds=30.0, outcome="timeout", result_count=0)
    with patch("odin.search.metrics._today_utc", return_value="2024-01-01"):
        await metrics.record_backend_outcome(valkey, outcome)

    keys = [c.args[0] for c in valkey.incrby.call_args_list]
    assert "metrics:search:brave:2024-01-01:timeouts" in keys
    assert "metrics:search:brave:2024-01-01:errors" not in keys


async def test_get_backend_metrics_computes_rates_from_stored_counters(valkey: AsyncMock) -> None:
    # order read in get_backend_metrics: calls, errors, timeouts, latency_ms, results
    valkey.get.side_effect = [b"10", b"1", b"1", b"2000", b"50"]
    result = await metrics.get_backend_metrics(valkey, "brave")

    assert result.calls == 10
    assert result.errors == 1
    assert result.timeouts == 1
    assert result.error_rate == 0.2
    assert result.avg_latency_ms == 200.0
    assert result.avg_result_count == 5.0


async def test_get_backend_metrics_returns_zeros_when_no_calls_recorded(valkey: AsyncMock) -> None:
    valkey.get.return_value = None
    result = await metrics.get_backend_metrics(valkey, "brave")

    assert result.calls == 0
    assert result.error_rate == 0.0
    assert result.avg_latency_ms == 0.0
    assert result.avg_result_count == 0.0


async def test_make_recorder_binds_client_and_records_outcome(valkey: AsyncMock) -> None:
    outcome = BackendOutcome(name="brave", elapsed_seconds=0.1, outcome="success", result_count=1)
    recorder = metrics.make_recorder(valkey)

    await recorder(outcome)

    keys = [c.args[0] for c in valkey.incrby.call_args_list]
    assert any(key.startswith("metrics:search:brave:") and key.endswith(":calls") for key in keys)
