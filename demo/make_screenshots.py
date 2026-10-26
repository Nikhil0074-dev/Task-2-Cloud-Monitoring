#!/usr/bin/env python3
"""Render screenshots from the REAL artifacts produced by demo/run_demo.py.

Requires: playwright (+ `playwright install chromium`).
 - console / log / test screenshots : real captured text rendered in a terminal-style page
 - webhook / e-mail screenshots     : the real captured payloads / .eml files rendered
                                      in a Slack-style card / mail-client-style page
 - dashboard screenshot             : the generated reports/dashboard.html itself
"""
import email
import glob
import html
import json
import os
import re
import subprocess
import sys

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "screenshots")
CAP = os.path.join(ROOT, "docs", "captured")

TERM_CSS = """
body{margin:0;background:#1e1f26;font-family:'DejaVu Sans Mono',monospace}
.win{width:1180px;background:#1e1f26}
.bar{background:#2d2f3a;padding:10px 14px;display:flex;gap:8px;align-items:center;color:#9aa0b4;font:12px sans-serif}
.dot{width:12px;height:12px;border-radius:50%;display:inline-block}
pre{margin:0;padding:16px 18px;color:#d6d9e5;font-size:13px;line-height:1.5;white-space:pre-wrap;word-break:break-all}
.r{color:#ff5f56;font-weight:bold}.y{color:#ffbd2e;font-weight:bold}.g{color:#27c93f;font-weight:bold}.d{color:#7d8399}.c{color:#6cb6ff}
"""


def ansi_to_html(text):
    text = html.escape(text)
    text = text.replace("\x1b[1;31m", "<span class=r>").replace("\x1b[1;33m", "<span class=y>")
    text = text.replace("\x1b[1;32m", "<span class=g>").replace("\x1b[0m", "</span>")
    text = re.sub(r"\x1b\[[0-9;]*m", "", text)
    text = re.sub(r"(result=DOWN)", r"<span class=r>\1</span>", text)
    text = re.sub(r"(result=UP)", r"<span class=g>\1</span>", text)
    text = re.sub(r"^(\$ .*)$", r"<span class=c>\1</span>", text, flags=re.M)
    return text


def terminal_page(title, body_html):
    return (f"<html><head><meta charset='utf-8'><style>{TERM_CSS}</style></head><body><div class=win>"
            f"<div class=bar><span class=dot style='background:#ff5f56'></span><span class=dot style='background:#ffbd2e'></span>"
            f"<span class=dot style='background:#27c93f'></span><span style='margin-left:10px'>{html.escape(title)}</span></div>"
            f"<pre>{body_html}</pre></div></body></html>")


def shot(page, content, name, width=1180, url=None, full=True):
    if url:
        page.goto(url)
    else:
        page.set_content(content)
    page.set_viewport_size({"width": width, "height": 400})
    page.wait_for_timeout(200)
    path = os.path.join(OUT, name)
    el = page.query_selector(".win") if not url else None
    if el:
        el.screenshot(path=path)
    else:
        page.screenshot(path=path, full_page=full)
    print("wrote", path)


def console_shot(page):
    lines = open(os.path.join(CAP, "console_output.txt"), encoding="utf-8").read().splitlines()
    keep = [lines[0]] + [l for l in lines[1:] if "[ALERT" in l]
    shot(page, terminal_page("Terminal - alerts raised during the simulated outage", ansi_to_html("\n".join(keep))),
         "01_console_alerts.png")


def webhook_shot(page):
    payloads = json.load(open(os.path.join(CAP, "webhook_payloads.json"), encoding="utf-8"))
    picks, seen = [], set()
    for p in payloads:
        key = (p["alert"]["kind"], p["alert"]["endpoint"])
        if p["alert"]["kind"] not in seen:
            seen.add(p["alert"]["kind"])
            picks.append(p)
    picks.sort(key=lambda p: p["alert"]["timestamp"])
    colors = {"CRITICAL": "#e01e5a", "WARNING": "#ecb22e", "RECOVERY": "#2eb67d"}
    cards = []
    for p in picks:
        a = p["alert"]
        text = re.sub(r"^[^\w*]+", "", p["text"].split("\n")[0]).replace("*", "")
        msg = html.escape(a["message"])
        cards.append(
            f"<div class=msg><div class=av>UB</div><div class=body><div class=hd><b>Uptime Bot</b> <span class=app>APP</span>"
            f" <span class=ts>{html.escape(a['timestamp'][11:19])} UTC</span></div>"
            f"<div class=att style='border-left-color:{colors[a['severity']]}'><div class=t>{html.escape(text)}</div>"
            f"<div>{msg}</div><div class=u>{html.escape(a['url'])}</div></div></div></div>")
    css = ("body{margin:0;background:#fff;font-family:Lato,'Helvetica Neue',Arial,sans-serif;color:#1d1c1d}"
           ".win{width:900px;background:#fff;border:1px solid #ddd}.top{background:#3f0e40;color:#fff;padding:12px 18px;font-weight:700}"
           ".chan{padding:10px 18px;border-bottom:1px solid #ddd;font-weight:700}.msg{display:flex;gap:10px;padding:12px 18px}"
           ".av{width:36px;height:36px;border-radius:5px;background:#4a154b;color:#fff;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:13px;flex:none}"
           ".hd{font-size:15px}.app{background:#e8e8e8;font-size:10px;padding:1px 4px;border-radius:3px;color:#555}.ts{color:#888;font-size:12px}"
           ".att{border-left:4px solid;margin-top:5px;padding:2px 12px;font-size:14px;line-height:1.45}.t{font-weight:700;margin-bottom:2px}"
           ".u{color:#1264a3;font-size:13px;margin-top:3px}")
    page_html = (f"<html><head><meta charset='utf-8'><style>{css}</style></head><body><div class=win>"
                 f"<div class=top>Workspace</div><div class=chan># ops-alerts</div>{''.join(cards)}</div></body></html>")
    shot(page, page_html, "02_webhook_notifications.png", width=900)


def email_shot(page):
    files = sorted(glob.glob(os.path.join(CAP, "emails", "*.eml")))
    chosen = None
    for f in files:
        m = email.message_from_binary_file(open(f, "rb"))
        if "DOWN" in m["Subject"] and "Payments" in m["Subject"]:
            chosen = m
            break
    chosen = chosen or email.message_from_binary_file(open(files[0], "rb"))
    body = chosen.get_payload(decode=True).decode("utf-8")
    css = ("body{margin:0;background:#f1f3f4;font-family:Arial,sans-serif;color:#202124}.win{width:820px;background:#fff;border:1px solid #dadce0}"
           ".sub{font-size:20px;padding:18px 22px 8px}.meta{padding:0 22px 12px;font-size:13px;color:#5f6368;border-bottom:1px solid #eee;line-height:1.6}"
           "pre{margin:0;padding:18px 22px;font:13px/1.5 'DejaVu Sans Mono',monospace;white-space:pre-wrap}"
           ".tag{background:#fce8e6;color:#c5221f;font-size:11px;padding:2px 8px;border-radius:4px;margin-left:8px}")
    page_html = (f"<html><head><meta charset='utf-8'><style>{css}</style></head><body><div class=win>"
                 f"<div class=sub>{html.escape(chosen['Subject'])}<span class=tag>Inbox</span></div>"
                 f"<div class=meta><b>From:</b> {html.escape(chosen['From'])}<br><b>To:</b> {html.escape(chosen['To'])}</div>"
                 f"<pre>{html.escape(body)}</pre></div></body></html>")
    shot(page, page_html, "03_email_alert.png", width=820)


def dashboard_shot(page):
    url = "file://" + os.path.join(ROOT, "reports", "dashboard.html")
    page.set_viewport_size({"width": 1180, "height": 900})
    page.goto(url)
    page.wait_for_timeout(300)
    path = os.path.join(OUT, "04_dashboard.png")
    page.screenshot(path=path, full_page=True)
    print("wrote", path)


def logs_shot(page):
    csv_lines = open(os.path.join(ROOT, "data", "uptime_log.csv"), encoding="utf-8").read().splitlines()
    log_lines = open(os.path.join(ROOT, "logs", "monitor.log"), encoding="utf-8").read().splitlines()
    idx = next(i for i, l in enumerate(log_lines) if "result=DOWN" in l)
    start = max(0, idx - 4)
    seg = [l for l in log_lines[start:start + 16]]
    down_csv = [l for l in csv_lines if ",false," in l][:4]
    body = ("$ head -n 8 data/uptime_log.csv\n" + "\n".join(csv_lines[:8]) +
            "\n\n$ grep ',false,' data/uptime_log.csv | head -n 4\n" + "\n".join(down_csv) +
            "\n\n$ sed -n '%d,%dp' logs/monitor.log\n" % (start + 1, start + len(seg)) + "\n".join(seg))
    shot(page, terminal_page("Sample uptime log files", ansi_to_html(body)), "05_uptime_logs.png")


def tests_shot(page):
    proc = subprocess.run([sys.executable, "-m", "pytest", "-v", "--no-header", "-p", "no:cacheprovider"],
                          cwd=ROOT, capture_output=True, text=True, timeout=240)
    lines = proc.stdout.splitlines()
    summary = lines[-1]
    body = "$ python -m pytest -v\n" + "\n".join(lines[:22]) + "\n   ...\n" + "\n".join(lines[-14:])
    body = html.escape(body).replace("PASSED", "<span class=g>PASSED</span>")
    body = re.sub(r"^(\$ .*)$", r"<span class=c>\1</span>", body, flags=re.M)
    shot(page, terminal_page(f"Unit tests - {summary.strip('= ')}", body), "06_unit_tests.png")
    return proc.returncode


def main():
    os.makedirs(OUT, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(device_scale_factor=1.5)
        console_shot(page)
        webhook_shot(page)
        email_shot(page)
        dashboard_shot(page)
        logs_shot(page)
        rc = tests_shot(page)
        browser.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
