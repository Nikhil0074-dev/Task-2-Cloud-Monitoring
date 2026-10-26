import io
import logging

import pytest

from cloudmon import runner, storage
from cloudmon.runner import parse_simulate, run_loop, run_once, setup_logging


def endpoints(server):
    return [{"name": "Web", "url": server.url("web")}, {"name": "API", "url": server.url("api")}]


def test_parse_simulate():
    assert parse_simulate(None) is None and parse_simulate("") is None and parse_simulate("  ,, ") is None
    assert parse_simulate("ALL") == "all"
    assert parse_simulate("A, B") == {"A", "B"}


def test_healthy_round_logs_and_no_alerts(server, make_cfg):
    cfg, base = make_cfg(endpoints(server))
    out = run_once(cfg, base, stream=io.StringIO())
    assert len(out.results) == 2 and out.alerts == [] and not out.any_down
    rows = storage.read_results(f"{base}/data/uptime_log.csv")
    assert [r["name"] for r in rows] == ["Web", "API"] and all(r["success"] for r in rows)
    assert all(r["latency_ms"] > 0 for r in rows)
    assert "uptime_report.md" in out.reports["markdown"]
    assert (storage.load_state(f"{base}/data/state.json"))["Web"]["status"] == "ok"


def test_detects_real_downtime_and_alerts_immediately(server, make_cfg, hook):
    cfg, base = make_cfg(endpoints(server), alerts={"webhook": {"enabled": True, "url": hook.url, "attempts": 1}})
    buf = io.StringIO()
    run_once(cfg, base, stream=buf)
    server.set_mode("api", "down")
    out = run_once(cfg, base, stream=buf)
    assert out.any_down
    kinds = [(a.endpoint, a.kind) for a in out.alerts]
    assert ("API", "DOWN") in kinds and ("Web", "DOWN") not in kinds
    assert len(hook.payloads) == 1 and hook.payloads[0]["alert"]["kind"] == "DOWN"
    assert "[ALERT CRITICAL]" in buf.getvalue()
    assert all(d["ok"] for d in out.deliveries)


def test_no_duplicate_alert_then_recovery(server, make_cfg):
    cfg, base = make_cfg(endpoints(server))
    server.set_mode("api", "down")
    first = run_once(cfg, base, stream=io.StringIO())
    second = run_once(cfg, base, stream=io.StringIO())
    assert [a.kind for a in first.alerts if a.endpoint == "API"] == ["DOWN"]
    assert [a.kind for a in second.alerts if a.endpoint == "API"] == []
    server.set_mode("api", "up")
    third = run_once(cfg, base, stream=io.StringIO())
    assert [a.kind for a in third.alerts if a.endpoint == "API"] == ["RECOVERED"]


def test_state_persists_between_runs(server, make_cfg):
    cfg, base = make_cfg(endpoints(server))
    server.set_mode("web", "down")
    run_once(cfg, base, stream=io.StringIO())
    # brand-new call (as a fresh GitHub Actions job would be) must not re-alert
    out = run_once(cfg, base, stream=io.StringIO())
    assert out.alerts == []


def test_latency_alerts(server, make_cfg):
    cfg, base = make_cfg(endpoints(server))
    server.set_mode("web", "slow", delay_ms=400)
    out = run_once(cfg, base, stream=io.StringIO())
    assert [(a.endpoint, a.kind) for a in out.alerts] == [("Web", "SLOW_WARNING")]
    server.set_mode("web", "slow", delay_ms=1000)
    out = run_once(cfg, base, stream=io.StringIO())
    assert [(a.endpoint, a.kind) for a in out.alerts] == [("Web", "SLOW_CRITICAL")]


def test_simulated_downtime_all(server, make_cfg):
    cfg, base = make_cfg(endpoints(server))
    out = run_once(cfg, base, simulate="all", stream=io.StringIO())
    assert sorted(a.endpoint for a in out.alerts) == ["API", "Web"]
    assert all(r["error"] == "SIMULATED_DOWNTIME" for r in out.results)


def test_simulated_downtime_selected(server, make_cfg):
    cfg, base = make_cfg(endpoints(server))
    out = run_once(cfg, base, simulate={"API"}, stream=io.StringIO())
    assert [a.endpoint for a in out.alerts] == ["API"]


def test_uptime_alert_through_runner(server, make_cfg):
    cfg, base = make_cfg([{"name": "Web", "url": server.url("web")}],
                         thresholds={"uptime_min_percent": 90, "uptime_min_checks": 3, "consecutive_failures": 5})
    for _ in range(2):
        run_once(cfg, base, stream=io.StringIO())
    out = run_once(cfg, base, simulate="all", stream=io.StringIO())  # 2/3 up = 66%
    assert [a.kind for a in out.alerts] == ["UPTIME_LOW"]


def test_per_endpoint_threshold_override_used(server, make_cfg):
    eps = [{"name": "Web", "url": server.url("web"), "thresholds": {"latency_warning_ms": 50, "latency_critical_ms": 100}}]
    cfg, base = make_cfg(eps)
    server.set_mode("web", "slow", delay_ms=120)
    out = run_once(cfg, base, stream=io.StringIO())
    assert out.alerts[0].kind == "SLOW_CRITICAL"


def test_webhook_failure_is_logged_not_fatal(server, make_cfg, caplog):
    from demo.mock_servers import free_port
    cfg, base = make_cfg(endpoints(server), alerts={"webhook": {
        "enabled": True, "url": f"http://127.0.0.1:{free_port()}/h", "attempts": 1}})
    server.set_mode("web", "down")
    with caplog.at_level(logging.INFO, logger="cloudmon"):
        out = run_once(cfg, base, stream=io.StringIO(), backoff=0)
    assert any(not d["ok"] and d["channel"] == "webhook" for d in out.deliveries)
    assert "alert delivery failed" in caplog.text
    assert "run complete" in caplog.text


def test_retention_pruning_in_run(server, make_cfg):
    cfg, base = make_cfg([{"name": "Web", "url": server.url("web")}])
    csv_path = f"{base}/data/uptime_log.csv"
    from tests.conftest import result
    storage.append_results(csv_path, [result("Web", ts="2020-01-01T00:00:00.000Z")])
    run_once(cfg, base, stream=io.StringIO())
    rows = storage.read_results(csv_path)
    assert len(rows) == 1 and rows[0]["timestamp"] > "2025"


def test_check_log_lines_written(server, make_cfg, tmp_path):
    cfg, base = make_cfg(endpoints(server))
    log = tmp_path / "x" / "monitor.log"
    logger = setup_logging(str(log), console=False)
    server.set_mode("api", "down")
    run_once(cfg, base, logger=logger, stream=io.StringIO())
    text = log.read_text()
    assert 'check name="Web" status=200 latency_ms=' in text and "result=UP" in text
    assert 'name="API" status=503' in text and "result=DOWN" in text
    assert "WARNING" in text and "alert severity=CRITICAL kind=DOWN" in text
    assert "run complete checks=2 up=1 down=1 alerts=1" in text
    assert text.splitlines()[0][:4].isdigit() and "Z " in text.splitlines()[0]


def test_setup_logging_is_idempotent(tmp_path):
    for _ in range(3):
        lg = setup_logging(str(tmp_path / "l.log"), console=True, stream=io.StringIO())
    assert len(lg.handlers) == 2


def test_run_loop_runs_n_times_and_sleeps(server, make_cfg):
    cfg, base = make_cfg(endpoints(server))
    sleeps = []
    outs = run_loop(cfg, base, max_iterations=3, sleep=sleeps.append, stream=io.StringIO())
    assert len(outs) == 3 and len(sleeps) == 2 and all(0 <= s <= cfg["interval_seconds"] for s in sleeps)
    assert len(storage.read_results(f"{base}/data/uptime_log.csv")) == 6


def test_results_keep_configured_order(server, make_cfg):
    server.set_mode("web", "slow", delay_ms=200)
    cfg, _ = make_cfg(endpoints(server))
    assert [r["name"] for r in runner.run_checks(cfg)] == ["Web", "API"]
