#!/usr/bin/env python3
"""End-to-end demonstration against a LOCAL mock stack (no internet needed).

It runs 40 real monitoring rounds (0.5 s apart) against three mock services
while injecting failures:

  rounds  9-10  Auth Service   slow (400 ms)   -> SLOW_WARNING, then recovery
  rounds 13-20  Payments API   HTTP 503        -> DOWN (CRITICAL), UPTIME_LOW, then recovery
  rounds 24-26  Auth Service   slow (1000 ms)  -> SLOW_CRITICAL, then recovery
  rounds 30-33  Web Frontend   connection drop -> DOWN (CRITICAL), then recovery

Outputs (overwritten on every run):
  data/uptime_log.csv, data/state.json, logs/monitor.log, reports/*,
  docs/captured/console_output.txt, webhook_payloads.json, emails/*.eml
"""
import io
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["FORCE_COLOR"] = "1"

from cloudmon.config import build_config  # noqa: E402
from cloudmon.runner import run_once, setup_logging  # noqa: E402
from demo.mock_servers import MockServer, WebhookReceiver  # noqa: E402

ROUNDS = 40
INTERVAL = 0.5

# (first_round, last_round, service, mode, delay_ms)
FAULTS = [
    (9, 10, "auth", "slow", 400),
    (13, 20, "payments", "down", 0),
    (24, 26, "auth", "slow", 1000),
    (30, 33, "web", "drop", 0),
]


class Tee(io.TextIOBase):
    """Write to the real stdout and keep a copy."""

    def __init__(self):
        self.buffer = io.StringIO()

    def write(self, s):
        sys.__stdout__.write(s)
        self.buffer.write(s)
        return len(s)

    def flush(self):
        sys.__stdout__.flush()

    def isatty(self):
        return False


class FakeSMTP:
    """Captures e-mails instead of contacting a real mail server."""
    sent = []

    def __init__(self, host, port, timeout=None):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        pass

    def login(self, u, p):
        pass

    def send_message(self, msg):
        FakeSMTP.sent.append(msg)


def main():
    for rel in ("data", "logs", "reports", "docs/captured"):
        shutil.rmtree(os.path.join(ROOT, rel), ignore_errors=True)
    os.makedirs(os.path.join(ROOT, "docs", "captured", "emails"))

    with MockServer() as srv, WebhookReceiver() as hook:
        cfg = build_config({
            "interval_seconds": INTERVAL,
            "timeout_seconds": 3,
            "thresholds": {"latency_warning_ms": 300, "latency_critical_ms": 800,
                           "consecutive_failures": 1, "uptime_min_percent": 95,
                           "uptime_window_checks": 100, "uptime_min_checks": 10},
            "alerts": {
                "console": True,
                "webhook": {"enabled": True, "url": hook.url, "attempts": 2},
                "email": {"enabled": True, "smtp_host": "smtp.example.com", "smtp_port": 587,
                          "use_tls": True, "from": "uptime-bot@example.com",
                          "to": ["oncall@example.com"]},
            },
            "endpoints": [
                {"name": "Web Frontend", "url": srv.url("web")},
                {"name": "Payments API", "url": srv.url("payments")},
                {"name": "Auth Service", "url": srv.url("auth")},
            ],
        })
        tee = Tee()
        logger = setup_logging(os.path.join(ROOT, "logs", "monitor.log"), console=True, stream=tee)
        print("$ python monitor.py --interval 0.5   # demo against local mock services", file=tee)
        import time
        for rnd in range(1, ROUNDS + 1):
            for first, last, svc, mode, delay in FAULTS:
                if rnd == first:
                    srv.set_mode(svc, mode, delay)
                    logger.warning(f"[demo] injecting fault: {svc} -> {mode} {delay or ''}".rstrip())
                if rnd == last + 1:
                    srv.set_mode(svc, "up")
                    logger.info(f"[demo] fault cleared: {svc}")
            run_once(cfg, ROOT, logger=logger, stream=tee, smtp_factory=FakeSMTP, backoff=0.1)
            time.sleep(INTERVAL)

        payloads = list(hook.payloads)

    with open(os.path.join(ROOT, "docs", "captured", "console_output.txt"), "w", encoding="utf-8") as fh:
        fh.write(tee.buffer.getvalue())
    with open(os.path.join(ROOT, "docs", "captured", "webhook_payloads.json"), "w", encoding="utf-8") as fh:
        json.dump(payloads, fh, indent=2, ensure_ascii=False)
    for i, msg in enumerate(FakeSMTP.sent, 1):
        with open(os.path.join(ROOT, "docs", "captured", "emails", f"{i:02d}.eml"), "wb") as fh:
            fh.write(bytes(msg))
    print(f"\nDemo finished: {ROUNDS} rounds, {len(payloads)} webhook notifications, {len(FakeSMTP.sent)} e-mails captured.")


if __name__ == "__main__":
    main()
