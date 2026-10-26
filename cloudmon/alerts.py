"""Threshold evaluation (state machine) and alert delivery channels."""
import copy
import os
import smtplib
import sys
import time
from dataclasses import asdict, dataclass, field
from email.message import EmailMessage

import requests

from .metrics import uptime_percent
from .timeutil import format_duration, parse_iso

STATUS_OK = "ok"
STATUS_SLOW_WARNING = "slow_warning"
STATUS_SLOW_CRITICAL = "slow_critical"
STATUS_DOWN = "down"

CRITICAL, WARNING, RECOVERY = "CRITICAL", "WARNING", "RECOVERY"

_COLORS = {CRITICAL: "\033[1;31m", WARNING: "\033[1;33m", RECOVERY: "\033[1;32m"}
_ICONS = {CRITICAL: "\U0001F534", WARNING: "\U0001F7E1", RECOVERY: "\U0001F7E2"}
_RESET = "\033[0m"


@dataclass
class Alert:
    severity: str
    kind: str
    endpoint: str
    url: str
    message: str
    timestamp: str
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def title(self) -> str:
        return f"[{self.severity}] {self.endpoint}: {self.kind}"


# --------------------------------------------------------------------------
# Threshold evaluation
# --------------------------------------------------------------------------
def new_state(timestamp: str) -> dict:
    return {
        "status": STATUS_OK,
        "consecutive_failures": 0,
        "first_failure": None,
        "since": timestamp,
        "uptime_breach": False,
    }


def classify_latency(latency_ms: float, th: dict) -> str:
    if latency_ms >= th["latency_critical_ms"]:
        return STATUS_SLOW_CRITICAL
    if latency_ms >= th["latency_warning_ms"]:
        return STATUS_SLOW_WARNING
    return STATUS_OK


def evaluate_check(result: dict, prev_state, th: dict):
    """Compare one check result against thresholds.

    Alerts fire on *state transitions* only, so a long outage produces one
    DOWN alert (not one per check) followed by one RECOVERED alert.
    Returns ``(new_state, [Alert, ...])``.
    """
    ts = result["timestamp"]
    state = copy.deepcopy(prev_state) if prev_state else new_state(ts)
    for key, value in new_state(ts).items():
        state.setdefault(key, value)
    prev_status = state["status"]
    alerts = []

    def make(severity, kind, message, **details):
        return Alert(severity, kind, result["name"], result["url"], message, ts, details)

    if not result["success"]:
        state["consecutive_failures"] += 1
        if state["first_failure"] is None:
            state["first_failure"] = ts
        failures = state["consecutive_failures"]
        if failures >= th["consecutive_failures"] and prev_status != STATUS_DOWN:
            state["status"], state["since"] = STATUS_DOWN, ts
            reason = result["error"] or "check failed"
            alerts.append(make(
                CRITICAL, "DOWN",
                f"{result['name']} is DOWN: {reason} "
                f"(status={result['status_code'] or 'n/a'}, {failures} consecutive failed check(s))",
                status_code=result["status_code"], error=result["error"],
                consecutive_failures=failures, latency_ms=result["latency_ms"]))
        return state, alerts

    # ---- successful check -------------------------------------------------
    effective_prev = prev_status
    if prev_status == STATUS_DOWN:
        downtime = (parse_iso(ts) - parse_iso(state["first_failure"] or state["since"])).total_seconds()
        alerts.append(make(
            RECOVERY, "RECOVERED",
            f"{result['name']} is back UP after {format_duration(downtime)} of downtime "
            f"(status={result['status_code']}, {result['latency_ms']:.0f} ms)",
            downtime_seconds=downtime, status_code=result["status_code"],
            latency_ms=result["latency_ms"]))
        effective_prev = STATUS_OK
    state["consecutive_failures"] = 0
    state["first_failure"] = None

    level = classify_latency(result["latency_ms"], th)
    if level == STATUS_SLOW_CRITICAL and effective_prev != STATUS_SLOW_CRITICAL:
        alerts.append(make(
            CRITICAL, "SLOW_CRITICAL",
            f"{result['name']} latency {result['latency_ms']:.0f} ms exceeded the critical "
            f"threshold of {th['latency_critical_ms']} ms",
            latency_ms=result["latency_ms"], threshold_ms=th["latency_critical_ms"]))
    elif level == STATUS_SLOW_WARNING and effective_prev == STATUS_OK:
        alerts.append(make(
            WARNING, "SLOW_WARNING",
            f"{result['name']} latency {result['latency_ms']:.0f} ms exceeded the warning "
            f"threshold of {th['latency_warning_ms']} ms",
            latency_ms=result["latency_ms"], threshold_ms=th["latency_warning_ms"]))
    elif level == STATUS_OK and effective_prev in (STATUS_SLOW_WARNING, STATUS_SLOW_CRITICAL):
        alerts.append(make(
            RECOVERY, "RECOVERED",
            f"{result['name']} latency back to normal ({result['latency_ms']:.0f} ms)",
            latency_ms=result["latency_ms"]))

    if level != prev_status:
        state["status"], state["since"] = level, ts
    return state, alerts


def evaluate_uptime(name: str, url: str, history, state: dict, th: dict, timestamp: str):
    """Alert when rolling uptime % crosses ``uptime_min_percent``."""
    state = copy.deepcopy(state)
    window = list(history)[-int(th["uptime_window_checks"]):]
    alerts = []
    if len(window) < th["uptime_min_checks"]:
        return state, alerts
    pct = uptime_percent(window)
    if pct < th["uptime_min_percent"] and not state.get("uptime_breach"):
        state["uptime_breach"] = True
        alerts.append(Alert(
            WARNING, "UPTIME_LOW", name, url,
            f"{name} uptime {pct:.2f}% over the last {len(window)} checks is below "
            f"the minimum of {th['uptime_min_percent']}%",
            timestamp, {"uptime_percent": round(pct, 2), "window": len(window),
                        "threshold_percent": th["uptime_min_percent"]}))
    elif pct >= th["uptime_min_percent"] and state.get("uptime_breach"):
        state["uptime_breach"] = False
        alerts.append(Alert(
            RECOVERY, "UPTIME_RECOVERED", name, url,
            f"{name} uptime recovered to {pct:.2f}% over the last {len(window)} checks "
            f"(minimum {th['uptime_min_percent']}%)",
            timestamp, {"uptime_percent": round(pct, 2), "window": len(window),
                        "threshold_percent": th["uptime_min_percent"]}))
    return state, alerts


# --------------------------------------------------------------------------
# Delivery channels
# --------------------------------------------------------------------------
def format_alert_text(alert: Alert) -> str:
    return f"{alert.title}\n{alert.message}\nURL: {alert.url}\nTime: {alert.timestamp}"


def send_console(alert: Alert, stream=None) -> None:
    stream = stream or sys.stdout
    use_color = bool(os.environ.get("FORCE_COLOR")) or (
        hasattr(stream, "isatty") and stream.isatty() and not os.environ.get("NO_COLOR"))
    prefix = f"[ALERT {alert.severity}]"
    line = f"{prefix} {alert.timestamp} {alert.endpoint} ({alert.kind}) - {alert.message}"
    if use_color:
        line = f"{_COLORS.get(alert.severity, '')}{prefix}{_RESET}" + line[len(prefix):]
    print(line, file=stream)
    stream.flush()


def webhook_payload(alert: Alert) -> dict:
    """Payload compatible with Slack (``text``) and Discord (``content``) webhooks."""
    text = f"{_ICONS.get(alert.severity, '')} *{alert.title}*\n{alert.message}\n<{alert.url}>"
    return {"text": text, "content": text, "alert": alert.to_dict()}


def send_webhook(alert: Alert, url: str, attempts: int = 2, timeout: float = 10.0,
                 backoff: float = 1.0) -> None:
    """POST the alert as JSON; retries on network errors / non-2xx responses."""
    if not url:
        raise ValueError("webhook URL not configured")
    attempts = max(1, int(attempts))
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            resp = requests.post(url, json=webhook_payload(alert), timeout=timeout)
            if 200 <= resp.status_code < 300:
                return
            last_error = f"HTTP {resp.status_code}"
        except requests.exceptions.RequestException as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        if attempt < attempts:
            time.sleep(backoff)
    raise RuntimeError(f"webhook delivery failed after {attempts} attempt(s): {last_error}")


def build_email(alert: Alert, email_cfg: dict) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = alert.title
    msg["From"] = email_cfg["from"]
    msg["To"] = ", ".join(email_cfg["to"])
    body = format_alert_text(alert)
    if alert.details:
        body += "\n\nDetails:\n" + "\n".join(f"  {k}: {v}" for k, v in sorted(alert.details.items()))
    msg.set_content(body)
    return msg


def send_email(alert: Alert, email_cfg: dict, env=None, smtp_factory=None) -> None:
    env = os.environ if env is None else env
    if not email_cfg.get("smtp_host") or not email_cfg.get("to") or not email_cfg.get("from"):
        raise ValueError("email alerting needs smtp_host, from and to")
    factory = smtp_factory or smtplib.SMTP
    msg = build_email(alert, email_cfg)
    with factory(email_cfg["smtp_host"], int(email_cfg["smtp_port"]), timeout=15) as smtp:
        if email_cfg.get("use_tls", True):
            smtp.starttls()
        user = env.get(email_cfg.get("username_env", "SMTP_USERNAME"))
        password = env.get(email_cfg.get("password_env", "SMTP_PASSWORD"))
        if user and password:
            smtp.login(user, password)
        smtp.send_message(msg)


def dispatch(alerts, alerts_cfg: dict, env=None, stream=None, smtp_factory=None, backoff: float = 1.0):
    """Deliver every alert on every enabled channel.

    One failing channel never prevents the others (or the monitor itself)
    from working; failures are returned as delivery records.
    """
    env = os.environ if env is None else env
    deliveries = []

    def record(alert, channel, ok, error=""):
        deliveries.append({"alert": alert.title, "channel": channel, "ok": ok, "error": error})

    wh = alerts_cfg.get("webhook", {})
    wh_url = (wh.get("url") or env.get(wh.get("url_env", "ALERT_WEBHOOK_URL"), "")) if wh.get("enabled") else ""
    for alert in alerts:
        if alerts_cfg.get("console", True):
            try:
                send_console(alert, stream)
                record(alert, "console", True)
            except Exception as exc:  # pragma: no cover - defensive
                record(alert, "console", False, str(exc))
        if wh.get("enabled"):
            try:
                send_webhook(alert, wh_url, attempts=wh.get("attempts", 2), backoff=backoff)
                record(alert, "webhook", True)
            except Exception as exc:
                record(alert, "webhook", False, str(exc))
        if alerts_cfg.get("email", {}).get("enabled"):
            try:
                send_email(alert, alerts_cfg["email"], env=env, smtp_factory=smtp_factory)
                record(alert, "email", True)
            except Exception as exc:
                record(alert, "email", False, str(exc))
    return deliveries
