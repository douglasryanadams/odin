"""Valkey-backed per-backend search metrics: latency, error rate, result counts.

Counters reset daily (UTC), the same convention `odin.store` uses for rate
limits, so old buckets expire on their own rather than growing without bound.
"""

import datetime
from dataclasses import dataclass

from valkey.asyncio import Valkey

from odin.search.aggregator import BackendOutcome, MetricsRecorder


def _today_utc() -> str:
    return datetime.datetime.now(datetime.UTC).date().isoformat()


def _end_of_day_utc() -> int:
    now = datetime.datetime.now(datetime.UTC)
    tomorrow = (now + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(tomorrow.timestamp())


def _counter_key(name: str, field: str) -> str:
    return f"metrics:search:{name}:{_today_utc()}:{field}"


async def record_backend_outcome(client: Valkey, outcome: BackendOutcome) -> None:
    """Increment today's call/outcome/latency/result counters for one backend.

    Every counter gets the same absolute end-of-day expiry set on every write
    (not just the first), mirroring `store.record_query` — cheap and simpler
    than tracking which write was first.
    """
    eod = _end_of_day_utc()
    keys_and_amounts = [
        (_counter_key(outcome.name, "calls"), 1),
        (_counter_key(outcome.name, "latency_ms"), round(outcome.elapsed_seconds * 1000)),
        (_counter_key(outcome.name, "results"), outcome.result_count),
    ]
    if outcome.outcome != "success":
        field = "errors" if outcome.outcome == "error" else "timeouts"
        keys_and_amounts.append((_counter_key(outcome.name, field), 1))
    for key, amount in keys_and_amounts:
        await client.incrby(key, amount)
        await client.expireat(key, eod)


async def _get_count(client: Valkey, key: str) -> int:
    val = await client.get(key)
    return int(val) if val else 0


@dataclass(frozen=True)
class BackendMetrics:
    """Today's aggregated outcome for one backend."""

    name: str
    calls: int
    errors: int
    timeouts: int
    error_rate: float
    avg_latency_ms: float
    avg_result_count: float


async def get_backend_metrics(client: Valkey, name: str) -> BackendMetrics:
    """Read today's counters for a backend and compute derived rates."""
    calls = await _get_count(client, _counter_key(name, "calls"))
    errors = await _get_count(client, _counter_key(name, "errors"))
    timeouts = await _get_count(client, _counter_key(name, "timeouts"))
    latency_total = await _get_count(client, _counter_key(name, "latency_ms"))
    results_total = await _get_count(client, _counter_key(name, "results"))
    if calls == 0:
        return BackendMetrics(
            name=name,
            calls=0,
            errors=0,
            timeouts=0,
            error_rate=0.0,
            avg_latency_ms=0.0,
            avg_result_count=0.0,
        )
    return BackendMetrics(
        name=name,
        calls=calls,
        errors=errors,
        timeouts=timeouts,
        error_rate=(errors + timeouts) / calls,
        avg_latency_ms=latency_total / calls,
        avg_result_count=results_total / calls,
    )


def make_recorder(client: Valkey) -> MetricsRecorder:
    """Bind a recorder to a Valkey client, suitable for SearchAggregator.record_outcome."""

    async def _record(outcome: BackendOutcome) -> None:
        await record_backend_outcome(client, outcome)

    return _record
