import pytest

from cloudmon.metrics import compute_stats, find_incidents, percentile, uptime_percent
from tests.conftest import result


def test_percentile():
    assert percentile([], 95) is None
    assert percentile([5], 95) == 5
    assert percentile(list(range(1, 101)), 95) == 95
    assert percentile([10, 20, 30, 40], 50) == 20
    assert percentile([3, 1, 2], 100) == 3


def test_uptime_percent():
    assert uptime_percent([]) is None
    assert uptime_percent([result(ok=True), result(ok=True), result(ok=False), result(ok=True)]) == 75.0
    assert uptime_percent([result(ok=False)]) == 0.0


def test_incident_closed_and_ongoing():
    rs = [result(ts="2026-01-01T00:00:00.000Z"),
          result(ok=False, ts="2026-01-01T00:01:00.000Z", error="e1"),
          result(ok=False, ts="2026-01-01T00:02:00.000Z", error="e2"),
          result(ts="2026-01-01T00:03:00.000Z"),
          result(ok=False, ts="2026-01-01T00:04:00.000Z", error="e3"),
          result(ok=False, ts="2026-01-01T00:04:30.000Z", error="e3")]
    inc = find_incidents(rs)
    assert len(inc) == 2
    assert inc[0]["ongoing"] is False and inc[0]["failed_checks"] == 2
    assert inc[0]["duration_seconds"] == 120 and inc[0]["error"] == "e2"
    assert inc[1]["ongoing"] is True and inc[1]["duration_seconds"] == 30 and inc[1]["end"] is None


def test_no_incidents():
    assert find_incidents([result(), result()]) == []


def test_compute_stats():
    rs = [result("a", True, 100, ts="2026-01-01T00:00:00.000Z"),
          result("a", True, 300, ts="2026-01-01T00:01:00.000Z"),
          result("a", False, 5, status=503, ts="2026-01-01T00:02:00.000Z", error="x"),
          result("b", True, 50, ts="2026-01-01T00:00:00.000Z")]
    st = compute_stats(rs, order=["b", "a", "never"])
    assert list(st) == ["b", "a"]  # configured order, empty endpoints omitted
    a = st["a"]
    assert (a["total"], a["up"], a["down"]) == (3, 2, 1)
    assert a["uptime_pct"] == pytest.approx(66.6667, abs=1e-3)
    assert a["avg_latency_ms"] == 200 and a["min_latency_ms"] == 100 and a["max_latency_ms"] == 300
    assert a["last_success"] is False and a["last_status_code"] == 503
    assert a["status_counts"] == {"200": 2, "503": 1}
    assert len(a["incidents"]) == 1


def test_stats_all_failed_has_no_latency():
    st = compute_stats([result(ok=False, status=0)])
    s = st["svc"]
    assert s["avg_latency_ms"] is None and s["p95_latency_ms"] is None
    assert s["status_counts"] == {"ERR": 1}


def test_recent_window_limited():
    rs = [result(ts=f"2026-01-01T00:{i // 60:02d}:{i % 60:02d}.000Z") for i in range(30)]
    assert len(compute_stats(rs, recent=10)["svc"]["recent"]) == 10
