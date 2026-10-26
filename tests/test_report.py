from cloudmon import report
from cloudmon.metrics import compute_stats
from tests.conftest import result


def sample():
    return [result("Web", True, 100, ts="2026-01-01T00:00:00.000Z"),
            result("Web", False, 5, status=503, ts="2026-01-01T00:01:00.000Z", error="boom | pipe"),
            result("Web", True, 300, ts="2026-01-01T00:02:00.000Z"),
            result("<b>API</b>", True, 50, ts="2026-01-01T00:00:00.000Z")]


def test_markdown_contents():
    md = report.render_markdown(compute_stats(sample()), "NOW")
    assert "# Uptime Report" in md and "NOW" in md
    assert "| Web | 3 | 66.67% |" in md
    assert "resolved" in md and "boom \\| pipe" in md  # pipe escaped inside table
    assert "503: 1" in md


def test_markdown_empty():
    assert "No checks recorded yet" in report.render_markdown({})


def test_markdown_without_incidents():
    md = report.render_markdown(compute_stats([result()]))
    assert "No incidents recorded." in md


def test_html_escapes_and_structure():
    h = report.render_html(compute_stats(sample()), "NOW", warn_ms=250)
    assert h.startswith("<!DOCTYPE html>") and "Uptime Dashboard" in h
    assert "<b>API</b>" not in h and "&lt;b&gt;API&lt;/b&gt;" in h
    assert "s-down" in h and "s-slow" in h and "s-up" in h
    assert "<svg" in h and "Incident history" in h and "resolved" in h


def test_html_marks_ongoing_down():
    rs = [result(ts="2026-01-01T00:00:00.000Z"), result(ok=False, status=503, ts="2026-01-01T00:01:00.000Z", error="x")]
    h = report.render_html(compute_stats(rs))
    assert "b-down" in h and "ONGOING" in h


def test_html_empty():
    assert "No checks recorded yet" in report.render_html({})


def test_sparkline_edge_cases():
    assert "<svg" in report._sparkline([])
    assert "<circle" in report._sparkline([result()])
    assert "<polyline" in report._sparkline([result(), result(latency=200)])
    assert "<rect" in report._sparkline([result(ok=False)])


def test_write_reports(tmp_path):
    paths = report.write_reports(sample(), str(tmp_path / "out"), order=["Web", "<b>API</b>"])
    assert open(paths["markdown"]).read().startswith("# Uptime Report")
    assert "<html" in open(paths["html"]).read()
