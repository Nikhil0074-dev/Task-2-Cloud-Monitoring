"""Uptime report (Markdown) and dashboard (self-contained HTML)."""
import html
import os

from .metrics import compute_stats
from .timeutil import format_duration, utc_now_iso


def _fmt_ms(value):
    return "-" if value is None else f"{value:.2f}"


def _fmt_pct(value):
    return "-" if value is None else f"{value:.2f}%"


def _all_incidents(stats):
    incidents = [i for s in stats.values() for i in s["incidents"]]
    return sorted(incidents, key=lambda i: i["start"], reverse=True)


def render_markdown(stats, generated_at=None, recent_rows=10) -> str:
    generated_at = generated_at or utc_now_iso()
    lines = ["# Uptime Report", "", f"_Generated: {generated_at}_", ""]
    if not stats:
        return "\n".join(lines + ["No checks recorded yet.", ""])

    lines += ["## Availability & latency", "",
              "| Endpoint | Checks | Uptime | Avg ms | p95 ms | Max ms | Last status | Last check (UTC) |",
              "|---|---:|---:|---:|---:|---:|:---:|---|"]
    for s in stats.values():
        state = "UP" if s["last_success"] else "DOWN"
        lines.append(
            f"| {s['name']} | {s['total']} | {_fmt_pct(s['uptime_pct'])} | {_fmt_ms(s['avg_latency_ms'])} | "
            f"{_fmt_ms(s['p95_latency_ms'])} | {_fmt_ms(s['max_latency_ms'])} | "
            f"{state} ({s['last_status_code'] or 'ERR'}) | {s['last_check']} |")

    incidents = _all_incidents(stats)
    lines += ["", "## Incidents", ""]
    if incidents:
        lines += ["| Endpoint | Started (UTC) | Duration | Failed checks | Status | Cause |",
                  "|---|---|---:|---:|:---:|---|"]
        for i in incidents:
            status = "ONGOING" if i["ongoing"] else "resolved"
            cause = (i["error"] or "-").replace("|", "\\|")
            lines.append(f"| {i['name']} | {i['start']} | {format_duration(i['duration_seconds'])} | "
                         f"{i['failed_checks']} | {status} | {cause} |")
    else:
        lines.append("No incidents recorded.")

    lines += ["", "## Status codes", "", "| Endpoint | Distribution |", "|---|---|"]
    for s in stats.values():
        dist = ", ".join(f"{code}: {n}" for code, n in sorted(s["status_counts"].items()))
        lines.append(f"| {s['name']} | {dist} |")
    lines.append("")
    return "\n".join(lines)


_CSS = """
:root{--bg:#f6f7f9;--card:#fff;--text:#1f2933;--muted:#6b7785;--line:#e3e7ec;--ok:#2e9e5b;--warn:#e0a526;--bad:#d64545;--accent:#2f6fed}
*{box-sizing:border-box}body{margin:0;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;background:var(--bg);color:var(--text)}
header{padding:20px 32px;background:#14213d;color:#fff}header h1{margin:0;font-size:22px}header p{margin:4px 0 0;color:#b8c1d6;font-size:13px}
main{padding:24px 32px;max-width:1100px;margin:0 auto}
.cards{display:flex;gap:16px;flex-wrap:wrap;margin-bottom:20px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px 18px}
.kpi{flex:1 1 200px}.kpi .label{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}.kpi .value{font-size:28px;font-weight:700;margin-top:4px}
.ep{margin-bottom:16px}.ep h2{margin:0;font-size:17px;display:flex;align-items:center;gap:10px}.ep .url{color:var(--muted);font-size:12px;margin:2px 0 12px;word-break:break-all}
.badge{font-size:11px;font-weight:700;padding:3px 9px;border-radius:999px;color:#fff}.b-up{background:var(--ok)}.b-down{background:var(--bad)}
.stats{display:flex;gap:26px;flex-wrap:wrap;margin-bottom:12px}.stats div span{display:block;font-size:11px;color:var(--muted);text-transform:uppercase}.stats div b{font-size:16px}
.strip{display:flex;flex-wrap:wrap;gap:2px;margin:8px 0}.strip i{display:block;width:7px;height:18px;border-radius:2px}
.s-up{background:var(--ok)}.s-slow{background:var(--warn)}.s-down{background:var(--bad)}
svg{width:100%;height:70px;display:block;background:#fafbfc;border:1px solid var(--line);border-radius:6px}
h3{margin:26px 0 10px;font-size:15px}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden;font-size:13px}
th,td{padding:8px 12px;text-align:left;border-bottom:1px solid var(--line)}th{background:#f0f2f5;font-size:11px;text-transform:uppercase;color:var(--muted)}
td.r,th.r{text-align:right}.ok{color:var(--ok);font-weight:600}.bad{color:var(--bad);font-weight:600}
footer{color:var(--muted);font-size:12px;text-align:center;padding:20px}
"""


def _sparkline(recent, width=1000, height=70):
    n = len(recent)
    if n == 0:
        return f'<svg viewBox="0 0 {width} {height}" preserveAspectRatio="none"></svg>'
    lats = [r["latency_ms"] for r in recent if r["success"]]
    top = max(lats) if lats else 1.0
    top = max(top, 1.0) * 1.1
    step = width / max(n - 1, 1) if n > 1 else 0
    parts = [f'<svg viewBox="0 0 {width} {height}" preserveAspectRatio="none" role="img" aria-label="latency chart">']
    pts = []
    for idx, r in enumerate(recent):
        x = idx * step if n > 1 else width / 2
        if not r["success"]:
            parts.append(f'<rect x="{max(x - 4, 0):.1f}" y="0" width="8" height="{height}" fill="#d64545" opacity="0.35"/>')
            continue
        y = height - 6 - (r["latency_ms"] / top) * (height - 12)
        pts.append(f"{x:.1f},{y:.1f}")
    if len(pts) > 1:
        parts.append(f'<polyline points="{" ".join(pts)}" fill="none" stroke="#2f6fed" stroke-width="2" vector-effect="non-scaling-stroke"/>')
    elif len(pts) == 1:
        cx, cy = pts[0].split(",")
        parts.append(f'<circle cx="{cx}" cy="{cy}" r="3" fill="#2f6fed"/>')
    parts.append("</svg>")
    return "".join(parts)


def render_html(stats, generated_at=None, warn_ms=None) -> str:
    generated_at = generated_at or utc_now_iso()
    e = html.escape
    out = ["<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>",
           "<meta name='viewport' content='width=device-width, initial-scale=1'>",
           "<title>Uptime Dashboard</title><style>", _CSS, "</style></head><body>",
           f"<header><h1>Uptime Dashboard</h1><p>Generated {e(generated_at)} (UTC)</p></header><main>"]
    if not stats:
        out.append("<div class='card'>No checks recorded yet.</div></main></body></html>")
        return "".join(out)

    total = sum(s["total"] for s in stats.values())
    up = sum(s["up"] for s in stats.values())
    overall = 100.0 * up / total if total else None
    all_lat = [s["avg_latency_ms"] for s in stats.values() if s["avg_latency_ms"] is not None]
    avg_lat = sum(all_lat) / len(all_lat) if all_lat else None
    down_now = sum(1 for s in stats.values() if not s["last_success"])
    ongoing = sum(1 for i in _all_incidents(stats) if i["ongoing"])
    out.append("<div class='cards'>")
    for label, value in (("Overall uptime", _fmt_pct(overall)),
                         ("Endpoints", str(len(stats))),
                         ("Avg latency (ms)", _fmt_ms(avg_lat)),
                         ("Down right now", str(down_now)),
                         ("Open incidents", str(ongoing))):
        out.append(f"<div class='card kpi'><div class='label'>{e(label)}</div><div class='value'>{e(value)}</div></div>")
    out.append("</div>")

    for s in stats.values():
        badge = "<span class='badge b-up'>UP</span>" if s["last_success"] else "<span class='badge b-down'>DOWN</span>"
        out.append(f"<div class='card ep'><h2>{e(s['name'])} {badge}</h2><div class='url'>{e(s['url'])}</div>")
        out.append("<div class='stats'>")
        for label, value in (("Uptime", _fmt_pct(s["uptime_pct"])), ("Checks", str(s["total"])),
                             ("Avg ms", _fmt_ms(s["avg_latency_ms"])), ("p95 ms", _fmt_ms(s["p95_latency_ms"])),
                             ("Max ms", _fmt_ms(s["max_latency_ms"])),
                             ("Last status", str(s["last_status_code"] or "ERR"))):
            out.append(f"<div><span>{e(label)}</span><b>{e(value)}</b></div>")
        out.append("</div><div class='strip' title='Availability of the most recent checks'>")
        for r in s["recent"]:
            if not r["success"]:
                cls = "s-down"
            elif warn_ms is not None and r["latency_ms"] >= warn_ms:
                cls = "s-slow"
            else:
                cls = "s-up"
            tip = f"{r['timestamp']} - {r['status_code'] or 'ERR'} - {r['latency_ms']:.0f} ms"
            out.append(f"<i class='{cls}' title='{e(tip)}'></i>")
        out.append("</div>")
        out.append(_sparkline(s["recent"]))
        out.append("</div>")

    incidents = _all_incidents(stats)
    out.append("<h3>Incident history</h3>")
    if incidents:
        out.append("<table><tr><th>Endpoint</th><th>Started (UTC)</th><th class='r'>Duration</th>"
                   "<th class='r'>Failed checks</th><th>Status</th><th>Cause</th></tr>")
        for i in incidents:
            status = "<span class='bad'>ONGOING</span>" if i["ongoing"] else "<span class='ok'>resolved</span>"
            out.append(f"<tr><td>{e(i['name'])}</td><td>{e(i['start'])}</td>"
                       f"<td class='r'>{e(format_duration(i['duration_seconds']))}</td>"
                       f"<td class='r'>{i['failed_checks']}</td><td>{status}</td><td>{e(i['error'] or '-')}</td></tr>")
        out.append("</table>")
    else:
        out.append("<div class='card'>No incidents recorded.</div>")

    recent_all = sorted((r for s in stats.values() for r in s["recent"]),
                        key=lambda r: r["timestamp"], reverse=True)[:12]
    out.append("<h3>Most recent checks</h3><table><tr><th>Time (UTC)</th><th>Endpoint</th>"
               "<th class='r'>Status</th><th class='r'>Latency (ms)</th><th>Result</th></tr>")
    for r in recent_all:
        res = "<span class='ok'>UP</span>" if r["success"] else f"<span class='bad'>DOWN</span> {e(r['error'])}"
        out.append(f"<tr><td>{e(r['timestamp'])}</td><td>{e(r['name'])}</td>"
                   f"<td class='r'>{e(str(r['status_code'] or 'ERR'))}</td>"
                   f"<td class='r'>{r['latency_ms']:.2f}</td><td>{res}</td></tr>")
    out.append("</table></main><footer>Generated by cloudmon</footer></body></html>")
    return "".join(out)


def write_reports(results, out_dir, order=None, generated_at=None, warn_ms=None) -> dict:
    """Write ``uptime_report.md`` and ``dashboard.html`` into ``out_dir``."""
    os.makedirs(out_dir, exist_ok=True)
    stats = compute_stats(results, order=order)
    md_path = os.path.join(out_dir, "uptime_report.md")
    html_path = os.path.join(out_dir, "dashboard.html")
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(render_markdown(stats, generated_at))
    with open(html_path, "w", encoding="utf-8") as fh:
        fh.write(render_html(stats, generated_at, warn_ms))
    return {"markdown": md_path, "html": html_path}
