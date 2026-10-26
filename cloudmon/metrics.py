"""Pure functions computing uptime %, latency percentiles and incidents."""
import math
from collections import Counter, OrderedDict

from .timeutil import parse_iso


def percentile(values, pct: float):
    """Nearest-rank percentile. Returns None for an empty list."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100.0 * len(ordered)))
    return ordered[min(rank, len(ordered)) - 1]


def uptime_percent(results):
    """Percentage of successful checks (None when there are no checks)."""
    results = list(results)
    if not results:
        return None
    return 100.0 * sum(1 for r in results if r["success"]) / len(results)


def find_incidents(results):
    """Group consecutive failed checks of ONE endpoint into incidents."""
    incidents = []
    current = None
    last_ts = None
    for r in results:
        if not r["success"]:
            if current is None:
                current = {"name": r["name"], "start": r["timestamp"], "end": None,
                           "failed_checks": 0, "error": r["error"], "ongoing": True}
            current["failed_checks"] += 1
            current["error"] = r["error"] or current["error"]
            last_ts = r["timestamp"]
        elif current is not None:
            current["end"] = r["timestamp"]
            current["ongoing"] = False
            current["duration_seconds"] = (parse_iso(r["timestamp"]) - parse_iso(current["start"])).total_seconds()
            incidents.append(current)
            current = None
    if current is not None:
        current["duration_seconds"] = (parse_iso(last_ts) - parse_iso(current["start"])).total_seconds()
        incidents.append(current)
    return incidents


def compute_stats(results, order=None, recent=100):
    """Per-endpoint statistics keyed by endpoint name (ordered)."""
    grouped = OrderedDict()
    for name in (order or []):
        grouped[name] = []
    for r in results:
        grouped.setdefault(r["name"], []).append(r)

    stats = OrderedDict()
    for name, rs in grouped.items():
        if not rs:
            continue
        rs = sorted(rs, key=lambda r: r["timestamp"])
        ok_lat = [r["latency_ms"] for r in rs if r["success"]]
        last = rs[-1]
        stats[name] = {
            "name": name,
            "url": last["url"],
            "total": len(rs),
            "up": sum(1 for r in rs if r["success"]),
            "down": sum(1 for r in rs if not r["success"]),
            "uptime_pct": uptime_percent(rs),
            "avg_latency_ms": (sum(ok_lat) / len(ok_lat)) if ok_lat else None,
            "min_latency_ms": min(ok_lat) if ok_lat else None,
            "max_latency_ms": max(ok_lat) if ok_lat else None,
            "p95_latency_ms": percentile(ok_lat, 95),
            "last_status_code": last["status_code"],
            "last_success": last["success"],
            "last_check": last["timestamp"],
            "first_check": rs[0]["timestamp"],
            "status_counts": dict(Counter(str(r["status_code"] or "ERR") for r in rs)),
            "incidents": find_incidents(rs),
            "recent": rs[-recent:],
        }
    return stats
