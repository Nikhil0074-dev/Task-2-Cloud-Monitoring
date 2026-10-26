import re

from cloudmon.checker import check_endpoint
from demo.mock_servers import free_port


def ep(url, **kw):
    return dict({"name": "t", "url": url, "expected_status": [200]}, **kw)


def test_healthy_endpoint(server):
    r = check_endpoint(ep(server.url("a")), timeout=3)
    assert r["success"] is True
    assert r["status_code"] == 200
    assert r["error"] == ""
    assert isinstance(r["latency_ms"], float) and 0 < r["latency_ms"] < 1000
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z", r["timestamp"])


def test_latency_is_reported_in_milliseconds(server):
    server.set_mode("slow", "slow", delay_ms=250)
    r = check_endpoint(ep(server.url("slow")), timeout=3)
    assert r["success"]
    assert 240 <= r["latency_ms"] < 1500  # ~250 ms, clearly not seconds or microseconds
    assert r["latency_ms"] == round(r["latency_ms"], 2)


def test_http_503_is_failure(server):
    server.set_mode("a", "down")
    r = check_endpoint(ep(server.url("a")), timeout=3)
    assert not r["success"] and r["status_code"] == 503
    assert "Unexpected status 503" in r["error"]


def test_status_in_expected_list_is_success(server):
    r = check_endpoint(ep(server.base() + "/status/204", expected_status=[200, 204]), timeout=3)
    assert r["success"] and r["status_code"] == 204


def test_404_is_failure(server):
    r = check_endpoint(ep(server.base() + "/nothing"), timeout=3)
    assert not r["success"] and r["status_code"] == 404


def test_timeout_is_failure(server):
    server.set_mode("slow", "slow", delay_ms=1500)
    r = check_endpoint(ep(server.url("slow")), timeout=0.3)
    assert not r["success"]
    assert r["status_code"] is None
    assert "Timeout" in r["error"]
    assert r["latency_ms"] >= 250


def test_connection_refused_is_failure():
    r = check_endpoint(ep(f"http://127.0.0.1:{free_port()}/"), timeout=2)
    assert not r["success"] and r["status_code"] is None
    assert "ConnectionError" in r["error"]


def test_dropped_connection_is_failure(server):
    server.set_mode("x", "drop")
    r = check_endpoint(ep(server.url("x")), timeout=3)
    assert not r["success"] and r["status_code"] is None
    assert r["error"]


def test_dns_failure_is_failure():
    r = check_endpoint(ep("http://no-such-host.invalid/"), timeout=3)
    assert not r["success"] and r["status_code"] is None


def test_expected_text_present(server):
    r = check_endpoint(ep(server.base() + "/text", expected_text="hello world"), timeout=3)
    assert r["success"]


def test_expected_text_missing(server):
    r = check_endpoint(ep(server.base() + "/text", expected_text="goodbye"), timeout=3)
    assert not r["success"] and r["status_code"] == 200
    assert "expected text" in r["error"]


def test_head_method(server):
    r = check_endpoint(ep(server.url("h"), method="HEAD"), timeout=3)
    assert r["success"] and r["status_code"] == 200


def test_simulated_downtime_makes_no_network_call():
    r = check_endpoint(ep("http://no-such-host.invalid/"), simulate_down=True)
    assert not r["success"] and r["status_code"] == 503
    assert r["error"] == "SIMULATED_DOWNTIME"


def test_scalar_expected_status_tolerated(server):
    r = check_endpoint({"name": "t", "url": server.url("a"), "expected_status": 200}, timeout=3)
    assert r["success"]
