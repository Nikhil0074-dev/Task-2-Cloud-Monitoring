import pytest

from demo.mock_servers import MockServer, WebhookReceiver
from cloudmon.config import build_config


@pytest.fixture()
def server():
    with MockServer() as s:
        yield s


@pytest.fixture()
def hook():
    with WebhookReceiver() as h:
        yield h


@pytest.fixture()
def make_cfg(tmp_path):
    """Build a validated config whose storage lives in tmp_path."""
    def _make(endpoints, **overrides):
        raw = {
            "interval_seconds": 0.05,
            "timeout_seconds": 2,
            "alerts": {"console": True, "webhook": {"enabled": False}},
            "thresholds": {"latency_warning_ms": 300, "latency_critical_ms": 900,
                           "consecutive_failures": 1, "uptime_min_percent": 50,
                           "uptime_window_checks": 100, "uptime_min_checks": 5},
            "endpoints": endpoints,
        }
        for k, v in overrides.items():
            if isinstance(v, dict) and isinstance(raw.get(k), dict):
                raw[k].update(v)
            else:
                raw[k] = v
        return build_config(raw), str(tmp_path)
    return _make


def result(name="svc", ok=True, latency=100.0, status=200, ts="2026-01-01T00:00:00.000Z", error=""):
    return {"timestamp": ts, "name": name, "url": f"http://x/{name}",
            "status_code": status if status != 0 else None,
            "latency_ms": latency, "success": ok, "error": error}
