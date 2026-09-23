"""In-process Prometheus counters and histograms.

Deliberately dependency free: ``prometheus_client`` would be the obvious choice,
but the app already renders ``/metrics`` by hand and only needs counters plus a
few histograms. Keeping it to ~120 lines means no new dependency, no registry
lifecycle, and the numbers are readable in a test.

Counters are process-local, which is exactly what Prometheus expects from a
scrape target — it computes rates itself. Multi-worker deployments get one
series per process; that is normal and the aggregation happens in PromQL.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from collections.abc import Iterator

# Histogram buckets in seconds, tuned for a relay hop (Telegram round trip)
LATENCY_BUCKETS: tuple[float, ...] = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

_lock = threading.Lock()
_counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
_histograms: dict[str, dict[tuple[tuple[str, str], ...], list[float]]] = defaultdict(
    lambda: defaultdict(lambda: [0.0] * (len(LATENCY_BUCKETS) + 1))
)
_sums: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
_counts: dict[tuple[str, tuple[tuple[str, str], ...]], int] = defaultdict(int)

_HELP: dict[str, str] = {}
_TYPE: dict[str, str] = {}


def _key(labels: dict[str, str] | None) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((labels or {}).items()))


def _render_labels(labels: tuple[tuple[str, str], ...]) -> str:
    if not labels:
        return ""
    body = ",".join(f'{name}="{value}"' for name, value in labels)
    return "{" + body + "}"


def declare(name: str, kind: str, help_text: str) -> None:
    """Register help/type so the scrape output is self describing."""
    _HELP[name] = help_text
    _TYPE[name] = kind


def incr(name: str, labels: dict[str, str] | None = None, amount: float = 1.0) -> None:
    with _lock:
        _counters[(name, _key(labels))] += amount


def observe(name: str, seconds: float, labels: dict[str, str] | None = None) -> None:
    """Record a duration into a histogram."""
    key = _key(labels)
    with _lock:
        buckets = _histograms[name][key]
        for index, upper in enumerate(LATENCY_BUCKETS):
            if seconds <= upper:
                buckets[index] += 1
        buckets[-1] += 1  # +Inf
        _sums[(name, key)] += seconds
        _counts[(name, key)] += 1


def counter_value(name: str, labels: dict[str, str] | None = None) -> float:
    with _lock:
        return _counters[(name, _key(labels))]


def histogram_count(name: str, labels: dict[str, str] | None = None) -> int:
    with _lock:
        return _counts[(name, _key(labels))]


def reset() -> None:
    """Clear everything — used between tests."""
    with _lock:
        _counters.clear()
        _histograms.clear()
        _sums.clear()
        _counts.clear()


def render() -> str:
    """Prometheus text exposition format."""
    lines: list[str] = []
    with _lock:
        counters = sorted(_counters.items())
        histograms = {name: dict(buckets) for name, buckets in _histograms.items()}
        sums = dict(_sums)
        counts = dict(_counts)

    # a counter key is (name, labels), so take the first element of each key
    counter_names = {key[0] for key, _ in counters}
    for name in sorted(counter_names | set(histograms)):
        if name in _HELP:
            lines.append(f"# HELP {name} {_HELP[name]}")
        kind = _TYPE.get(name, "histogram" if name in histograms else "counter")
        lines.append(f"# TYPE {name} {kind}")

        if name in histograms:
            for labels, buckets in sorted(histograms[name].items()):
                cumulative = 0.0
                for index, upper in enumerate(LATENCY_BUCKETS):
                    cumulative = buckets[index]
                    lines.append(
                        f'{name}_bucket{{le="{upper:g}"{_inner(labels)}}} {cumulative:g}'
                    )
                lines.append(
                    f'{name}_bucket{{le="+Inf"{_inner(labels)}}} {buckets[-1]:g}'
                )
                lines.append(f"{name}_sum{_render_labels(labels)} {sums[(name, labels)]:g}")
                lines.append(f"{name}_count{_render_labels(labels)} {counts[(name, labels)]:d}")
        else:
            for (metric_name, labels), value in counters:
                if metric_name != name:
                    continue
                lines.append(f"{name}{_render_labels(labels)} {value:g}")

    lines.append("")
    return "\n".join(lines)


def _inner(labels: tuple[tuple[str, str], ...]) -> str:
    """`,foo="bar"` for use inside an existing brace list."""
    if not labels:
        return ""
    return "," + ",".join(f'{name}="{value}"' for name, value in labels)


def snapshot() -> Iterator[tuple[str, dict[str, str], float]]:
    """Every counter as ``(name, labels, value)`` — handy in tests."""
    with _lock:
        items = list(_counters.items())
    for (name, labels), value in items:
        yield name, dict(labels), value


# ---------------------------------------------------------------------------
# declarations
# ---------------------------------------------------------------------------
declare(
    "soulchat_relay_total",
    "counter",
    "Relayed private messages by outcome (ok, duplicate, not_writer, ...)",
)
declare(
    "soulchat_relay_duration_seconds",
    "histogram",
    "Time spent relaying one private message",
)
declare(
    "soulchat_telegram_calls_total",
    "counter",
    "Telegram API calls by method and result",
)
declare(
    "soulchat_archive_media_bytes_total",
    "counter",
    "Media bytes bundled into archives",
)
declare(
    "soulchat_archive_media_skipped_total",
    "counter",
    "Media files that could not be bundled into an archive",
)