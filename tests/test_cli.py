import json

import monitor
from cloudmon import storage


def write_cfg(tmp_path, server, **extra):
    cfg = {"interval_seconds": 0.05, "timeout_seconds": 2,
           "alerts": {"console": True, "webhook": {"enabled": False}},
           "endpoints": [{"name": "Web", "url": server.url("web")}]}
    cfg.update(extra)
    p = tmp_path / "config.json"
    p.write_text(json.dumps(cfg))
    return str(p)


def test_once_success_writes_artifacts(tmp_path, server, capsys):
    p = write_cfg(tmp_path, server)
    assert monitor.main(["--config", p, "--once"]) == 0
    out = capsys.readouterr().out
    assert 'check name="Web" status=200' in out and "run complete" in out
    assert (tmp_path / "data" / "uptime_log.csv").exists()
    assert (tmp_path / "logs" / "monitor.log").exists()
    assert (tmp_path / "reports" / "dashboard.html").exists()


def test_fail_on_down_exit_code(tmp_path, server, capsys):
    p = write_cfg(tmp_path, server)
    server.set_mode("web", "down")
    assert monitor.main(["--config", p, "--once"]) == 0
    assert monitor.main(["--config", p, "--once", "--fail-on-down"]) == 1
    server.set_mode("web", "up")
    assert monitor.main(["--config", p, "--once", "--fail-on-down"]) == 0


def test_simulate_down_flag(tmp_path, server, capsys):
    p = write_cfg(tmp_path, server)
    code = monitor.main(["--config", p, "--once", "--simulate-down", "--fail-on-down"])
    out = capsys.readouterr().out
    assert code == 1 and "SIMULATION ACTIVE" in out and "[ALERT CRITICAL]" in out


def test_simulate_down_named_only(tmp_path, server, capsys):
    p = write_cfg(tmp_path, server)
    assert monitor.main(["--config", p, "--once", "--simulate-down", "Nothing", "--fail-on-down"]) == 0


def test_bad_config_exit_2(tmp_path, capsys):
    bad = tmp_path / "c.json"
    bad.write_text("{}")
    assert monitor.main(["--config", str(bad), "--once"]) == 2
    assert "Configuration error" in capsys.readouterr().err
    assert monitor.main(["--config", str(tmp_path / "missing.json"), "--once"]) == 2


def test_bad_interval_exit_2(tmp_path, server, capsys):
    assert monitor.main(["--config", write_cfg(tmp_path, server), "--interval", "0", "--once"]) == 2


def test_report_only(tmp_path, server, capsys):
    p = write_cfg(tmp_path, server)
    monitor.main(["--config", p, "--once"])
    (tmp_path / "reports" / "uptime_report.md").unlink()
    assert monitor.main(["--config", p, "--report-only"]) == 0
    assert (tmp_path / "reports" / "uptime_report.md").exists()
    assert "Reports written" in capsys.readouterr().out


def test_loop_mode_stops_on_keyboard_interrupt(tmp_path, server, monkeypatch, capsys):
    p = write_cfg(tmp_path, server)
    calls = {"n": 0}

    def fake_sleep(_):
        calls["n"] += 1
        if calls["n"] >= 2:
            raise KeyboardInterrupt

    monkeypatch.setattr("cloudmon.runner._sleep", fake_sleep)
    assert monitor.main(["--config", p]) == 0
    out = capsys.readouterr().out
    assert "monitoring 1 endpoint(s)" in out and "stopped by user" in out
    assert len(storage.read_results(str(tmp_path / "data" / "uptime_log.csv"))) == 2


def test_interval_override(tmp_path, server, monkeypatch):
    p = write_cfg(tmp_path, server)
    seen = []

    def fake_sleep(s):
        seen.append(s)
        raise KeyboardInterrupt

    monkeypatch.setattr("cloudmon.runner._sleep", fake_sleep)
    monitor.main(["--config", p, "--interval", "7"])
    assert seen and 6 < seen[0] <= 7


def test_version(capsys):
    import pytest
    with pytest.raises(SystemExit) as e:
        monitor.main(["--version"])
    assert e.value.code == 0 and "cloudmon" in capsys.readouterr().out
