import io
import os

import pytest

from cloudmon import alerts as A
from tests.conftest import result

TH = {"latency_warning_ms": 300, "latency_critical_ms": 900, "consecutive_failures": 1,
      "uptime_min_percent": 80, "uptime_window_checks": 10, "uptime_min_checks": 5}


def t(sec):
    return f"2026-01-01T00:{sec // 60:02d}:{sec % 60:02d}.000Z"


# ---------------- evaluate_check ----------------
def test_healthy_check_no_alert():
    st, al = A.evaluate_check(result(ts=t(0)), None, TH)
    assert al == [] and st["status"] == A.STATUS_OK


def test_down_alert_is_immediate_with_default_threshold():
    st, al = A.evaluate_check(result(ok=False, status=503, error="Unexpected status 503", ts=t(0)), None, TH)
    assert len(al) == 1
    assert (al[0].severity, al[0].kind) == (A.CRITICAL, "DOWN")
    assert "DOWN" in al[0].message and "503" in al[0].message
    assert st["status"] == A.STATUS_DOWN


def test_down_alert_is_not_repeated():
    st, _ = A.evaluate_check(result(ok=False, ts=t(0)), None, TH)
    st, al = A.evaluate_check(result(ok=False, ts=t(5)), st, TH)
    st, al2 = A.evaluate_check(result(ok=False, ts=t(10)), st, TH)
    assert al == [] and al2 == []
    assert st["consecutive_failures"] == 3


def test_consecutive_failure_threshold_delays_alert():
    th = dict(TH, consecutive_failures=3)
    st, a1 = A.evaluate_check(result(ok=False, ts=t(0)), None, th)
    st, a2 = A.evaluate_check(result(ok=False, ts=t(5)), st, th)
    assert a1 == [] and a2 == [] and st["status"] == A.STATUS_OK
    st, a3 = A.evaluate_check(result(ok=False, ts=t(10)), st, th)
    assert len(a3) == 1 and a3[0].kind == "DOWN" and "3 consecutive" in a3[0].message


def test_blip_below_threshold_resets_silently():
    th = dict(TH, consecutive_failures=3)
    st, _ = A.evaluate_check(result(ok=False, ts=t(0)), None, th)
    st, al = A.evaluate_check(result(ts=t(5)), st, th)
    assert al == [] and st["consecutive_failures"] == 0 and st["first_failure"] is None


def test_recovery_alert_reports_downtime():
    st, _ = A.evaluate_check(result(ok=False, ts=t(0)), None, TH)
    st, _ = A.evaluate_check(result(ok=False, ts=t(60)), st, TH)
    st, al = A.evaluate_check(result(ts=t(125)), st, TH)
    assert len(al) == 1 and al[0].severity == A.RECOVERY and al[0].kind == "RECOVERED"
    assert "2m 05s" in al[0].message
    assert al[0].details["downtime_seconds"] == 125
    assert st["status"] == A.STATUS_OK


def test_slow_warning_then_critical_then_normal():
    st, al = A.evaluate_check(result(latency=400, ts=t(0)), None, TH)
    assert [a.kind for a in al] == ["SLOW_WARNING"] and al[0].severity == A.WARNING
    st, al = A.evaluate_check(result(latency=450, ts=t(5)), st, TH)
    assert al == []  # still warning, no repeat
    st, al = A.evaluate_check(result(latency=1000, ts=t(10)), st, TH)
    assert [a.kind for a in al] == ["SLOW_CRITICAL"] and al[0].severity == A.CRITICAL
    st, al = A.evaluate_check(result(latency=1200, ts=t(15)), st, TH)
    assert al == []
    st, al = A.evaluate_check(result(latency=100, ts=t(20)), st, TH)
    assert [a.kind for a in al] == ["RECOVERED"] and "back to normal" in al[0].message
    assert st["status"] == A.STATUS_OK


def test_critical_to_warning_is_quiet():
    st, _ = A.evaluate_check(result(latency=1000, ts=t(0)), None, TH)
    st, al = A.evaluate_check(result(latency=400, ts=t(5)), st, TH)
    assert al == [] and st["status"] == A.STATUS_SLOW_WARNING


def test_latency_exactly_on_threshold_alerts():
    _, al = A.evaluate_check(result(latency=300, ts=t(0)), None, TH)
    assert al and al[0].kind == "SLOW_WARNING"
    _, al = A.evaluate_check(result(latency=900, ts=t(0)), None, TH)
    assert al and al[0].kind == "SLOW_CRITICAL"


def test_recovery_from_down_into_slow_emits_both():
    st, _ = A.evaluate_check(result(ok=False, ts=t(0)), None, TH)
    st, al = A.evaluate_check(result(latency=1000, ts=t(30)), st, TH)
    assert [a.kind for a in al] == ["RECOVERED", "SLOW_CRITICAL"]
    assert st["status"] == A.STATUS_SLOW_CRITICAL


def test_failure_while_slow_goes_down():
    st, _ = A.evaluate_check(result(latency=400, ts=t(0)), None, TH)
    st, al = A.evaluate_check(result(ok=False, ts=t(5)), st, TH)
    assert al[0].kind == "DOWN"


def test_evaluate_does_not_mutate_input_state():
    prev = A.new_state(t(0))
    snapshot = dict(prev)
    A.evaluate_check(result(ok=False, ts=t(1)), prev, TH)
    assert prev == snapshot


def test_old_state_without_new_keys_is_tolerated():
    st, al = A.evaluate_check(result(ts=t(0)), {"status": "ok"}, TH)
    assert al == [] and "uptime_breach" in st


# ---------------- evaluate_uptime ----------------
def history(pattern):
    return [result(ok=c == "1", ts=t(i)) for i, c in enumerate(pattern)]


def test_uptime_needs_minimum_samples():
    st, al = A.evaluate_uptime("svc", "u", history("0000"), A.new_state(t(0)), TH, t(10))
    assert al == []


def test_uptime_breach_alerts_once_then_recovers():
    st = A.new_state(t(0))
    st, al = A.evaluate_uptime("svc", "u", history("1110000000"), st, TH, t(20))  # 30%
    assert len(al) == 1 and al[0].kind == "UPTIME_LOW" and al[0].details["uptime_percent"] == 30.0
    st, al = A.evaluate_uptime("svc", "u", history("11100000001"), st, TH, t(21))
    assert al == []  # no repeat while breached (window of last 10 => 20%)
    st, al = A.evaluate_uptime("svc", "u", history("1111111111"), st, TH, t(30))
    assert len(al) == 1 and al[0].kind == "UPTIME_RECOVERED" and not st["uptime_breach"]


def test_uptime_ok_no_alert():
    _, al = A.evaluate_uptime("svc", "u", history("1111111111"), A.new_state(t(0)), TH, t(20))
    assert al == []


def test_uptime_window_only_considers_latest_checks():
    # 10 old failures followed by 10 successes; window=10 -> 100%
    _, al = A.evaluate_uptime("svc", "u", history("0" * 10 + "1" * 10), A.new_state(t(0)), TH, t(40))
    assert al == []


# ---------------- delivery ----------------
def sample_alert(sev=A.CRITICAL, kind="DOWN"):
    return A.Alert(sev, kind, "Web", "http://x", "Web is DOWN", "2026-01-01T00:00:00.000Z", {"k": 1})


def test_console_plain_output():
    buf = io.StringIO()
    A.send_console(sample_alert(), buf)
    out = buf.getvalue()
    assert out.startswith("[ALERT CRITICAL]") and "Web is DOWN" in out and "\033" not in out


def test_console_color_when_forced(monkeypatch):
    monkeypatch.setenv("FORCE_COLOR", "1")
    buf = io.StringIO()
    A.send_console(sample_alert(), buf)
    assert "\033[1;31m" in buf.getvalue()


def test_console_defaults_to_stdout(capsys):
    A.send_console(sample_alert(A.WARNING, "SLOW_WARNING"))
    assert "[ALERT WARNING]" in capsys.readouterr().out


def test_alert_title_and_dict():
    a = sample_alert()
    assert a.title == "[CRITICAL] Web: DOWN"
    assert a.to_dict()["details"] == {"k": 1}


def test_webhook_payload_shape():
    p = A.webhook_payload(sample_alert())
    assert p["text"] == p["content"] and "Web is DOWN" in p["text"]
    assert p["alert"]["kind"] == "DOWN"


def test_send_webhook_success(hook):
    A.send_webhook(sample_alert(), hook.url)
    assert len(hook.payloads) == 1 and hook.payloads[0]["alert"]["endpoint"] == "Web"


def test_send_webhook_retries_then_succeeds(hook):
    hook.fail_codes = [500]
    A.send_webhook(sample_alert(), hook.url, attempts=2, backoff=0)
    assert len(hook.payloads) == 1


def test_send_webhook_gives_up(hook):
    hook.fail_codes = [500, 500]
    with pytest.raises(RuntimeError, match="after 2 attempt"):
        A.send_webhook(sample_alert(), hook.url, attempts=2, backoff=0)


def test_send_webhook_unreachable():
    from demo.mock_servers import free_port
    with pytest.raises(RuntimeError, match="failed"):
        A.send_webhook(sample_alert(), f"http://127.0.0.1:{free_port()}/h", attempts=1, timeout=1)


def test_send_webhook_without_url():
    with pytest.raises(ValueError):
        A.send_webhook(sample_alert(), "")


EMAIL_CFG = {"smtp_host": "smtp.test", "smtp_port": 587, "use_tls": True, "from": "a@x.io",
             "to": ["b@x.io", "c@x.io"], "username_env": "U", "password_env": "P"}


class FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port, self.sent, self.tls, self.login_args = host, port, [], False, None
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        self.tls = True

    def login(self, u, p):
        self.login_args = (u, p)

    def send_message(self, m):
        self.sent.append(m)


def test_email_sent_with_tls_and_login():
    FakeSMTP.instances.clear()
    A.send_email(sample_alert(), EMAIL_CFG, env={"U": "user", "P": "pw"}, smtp_factory=FakeSMTP)
    smtp = FakeSMTP.instances[0]
    assert (smtp.host, smtp.port, smtp.tls, smtp.login_args) == ("smtp.test", 587, True, ("user", "pw"))
    msg = smtp.sent[0]
    assert msg["Subject"] == "[CRITICAL] Web: DOWN" and msg["To"] == "b@x.io, c@x.io"
    assert "Web is DOWN" in msg.get_content() and "k: 1" in msg.get_content()


def test_email_without_credentials_skips_login():
    FakeSMTP.instances.clear()
    A.send_email(sample_alert(), dict(EMAIL_CFG, use_tls=False), env={}, smtp_factory=FakeSMTP)
    smtp = FakeSMTP.instances[0]
    assert smtp.login_args is None and smtp.tls is False


def test_email_requires_settings():
    with pytest.raises(ValueError):
        A.send_email(sample_alert(), {"smtp_host": ""}, env={})


def test_dispatch_all_channels(hook):
    buf = io.StringIO()
    FakeSMTP.instances.clear()
    cfg = {"console": True, "webhook": {"enabled": True, "url": hook.url, "attempts": 1},
           "email": dict(EMAIL_CFG, enabled=True)}
    d = A.dispatch([sample_alert()], cfg, env={}, stream=buf, smtp_factory=FakeSMTP, backoff=0)
    assert {x["channel"] for x in d} == {"console", "webhook", "email"} and all(x["ok"] for x in d)
    assert len(hook.payloads) == 1 and len(FakeSMTP.instances[0].sent) == 1 and "ALERT" in buf.getvalue()


def test_dispatch_webhook_url_from_env(hook):
    cfg = {"console": False, "webhook": {"enabled": True, "url": "", "url_env": "MYHOOK", "attempts": 1}}
    d = A.dispatch([sample_alert()], cfg, env={"MYHOOK": hook.url}, backoff=0)
    assert d == [{"alert": "[CRITICAL] Web: DOWN", "channel": "webhook", "ok": True, "error": ""}]


def test_dispatch_failure_is_isolated():
    buf = io.StringIO()
    cfg = {"console": True, "webhook": {"enabled": True, "url": "", "url_env": "NOPE"},
           "email": {"enabled": True, "smtp_host": ""}}
    d = A.dispatch([sample_alert()], cfg, env={}, stream=buf, backoff=0)
    by = {x["channel"]: x for x in d}
    assert by["console"]["ok"] and not by["webhook"]["ok"] and not by["email"]["ok"]
    assert "ALERT" in buf.getvalue()


def test_dispatch_nothing_enabled():
    assert A.dispatch([sample_alert()], {"console": False, "webhook": {"enabled": False}}, env={}) == []
    assert A.dispatch([], {"console": True}, env={}) == []
