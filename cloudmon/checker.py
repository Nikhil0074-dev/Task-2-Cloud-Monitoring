"""Health check of a single HTTP endpoint."""
import time

import requests

from .timeutil import utc_now_iso

USER_AGENT = "cloudmon/1.0 (+uptime-monitor)"


def _result(ts, endpoint, status_code, latency_ms, success, error):
    return {
        "timestamp": ts,
        "name": endpoint["name"],
        "url": endpoint["url"],
        "status_code": status_code,
        "latency_ms": round(float(latency_ms), 2),
        "success": bool(success),
        "error": error,
    }


def _short(text: str, limit: int = 200) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def check_endpoint(endpoint: dict, timeout: float = 10.0, simulate_down: bool = False) -> dict:
    """Probe ``endpoint`` once and return a result dictionary.

    Latency is measured with a monotonic clock (``time.perf_counter``) and is
    always reported in **milliseconds** with two decimals. The function never
    raises for network problems - those are reported as ``success=False``.
    """
    ts = utc_now_iso()
    expected = endpoint.get("expected_status") or [200]
    if not isinstance(expected, list):
        expected = [expected]

    if simulate_down:
        return _result(ts, endpoint, 503, 0.0, False, "SIMULATED_DOWNTIME")

    method = str(endpoint.get("method", "GET")).upper()
    start = time.perf_counter()
    try:
        resp = requests.request(
            method,
            endpoint["url"],
            timeout=timeout,
            headers={"User-Agent": USER_AGENT},
            allow_redirects=True,
        )
        latency_ms = (time.perf_counter() - start) * 1000.0
        status = resp.status_code
        if status not in expected:
            return _result(ts, endpoint, status, latency_ms, False,
                           f"Unexpected status {status} (expected {expected})")
        needle = endpoint.get("expected_text")
        if needle and needle not in resp.text:
            return _result(ts, endpoint, status, latency_ms, False,
                           f"Response body does not contain expected text {needle!r}")
        return _result(ts, endpoint, status, latency_ms, True, "")
    except requests.exceptions.Timeout:
        latency_ms = (time.perf_counter() - start) * 1000.0
        return _result(ts, endpoint, None, latency_ms, False, f"Timeout after {timeout}s")
    except requests.exceptions.RequestException as exc:
        latency_ms = (time.perf_counter() - start) * 1000.0
        return _result(ts, endpoint, None, latency_ms, False,
                       f"{type(exc).__name__}: {_short(exc)}")
