import json
from datetime import timedelta

from cloudmon import storage
from cloudmon.timeutil import to_iso, utc_now
from tests.conftest import result


def test_append_and_read_roundtrip(tmp_path):
    p = str(tmp_path / "d" / "log.csv")  # parent dir is created
    rows = [result("a", True, 12.345), result("b", False, 3000.0, status=0, error="Timeout after 10s")]
    assert storage.append_results(p, rows) == 2
    back = storage.read_results(p)
    assert back[0]["latency_ms"] == 12.35 or back[0]["latency_ms"] == 12.34  # 2-decimal formatting
    assert back[0]["success"] is True and back[0]["status_code"] == 200
    assert back[1]["success"] is False and back[1]["status_code"] is None
    assert back[1]["error"] == "Timeout after 10s"


def test_header_written_once(tmp_path):
    p = str(tmp_path / "log.csv")
    storage.append_results(p, [result()])
    storage.append_results(p, [result()])
    lines = open(p).read().strip().splitlines()
    assert lines[0] == ",".join(storage.CSV_FIELDS)
    assert len(lines) == 3


def test_error_with_comma_and_quote_survives(tmp_path):
    p = str(tmp_path / "log.csv")
    storage.append_results(p, [result(ok=False, error='bad, "quoted" thing')])
    assert storage.read_results(p)[0]["error"] == 'bad, "quoted" thing'


def test_read_missing_file_is_empty(tmp_path):
    assert storage.read_results(str(tmp_path / "none.csv")) == []


def test_corrupt_rows_are_skipped(tmp_path):
    p = tmp_path / "log.csv"
    p.write_text(",".join(storage.CSV_FIELDS) + "\n"
                 "2026-01-01T00:00:00.000Z,a,http://x,200,notanumber,true,\n"
                 "2026-01-01T00:00:01.000Z,a,http://x,200,10.00,true,\n")
    rows = storage.read_results(str(p))
    assert len(rows) == 1 and rows[0]["latency_ms"] == 10.0


def test_prune_removes_only_old_rows(tmp_path):
    p = str(tmp_path / "log.csv")
    old = to_iso(utc_now() - timedelta(days=40))
    new = to_iso(utc_now() - timedelta(days=1))
    storage.append_results(p, [result(ts=old), result(ts=new)])
    assert storage.prune_results(p, 30) == 1
    rows = storage.read_results(p)
    assert len(rows) == 1 and rows[0]["timestamp"] == new


def test_prune_nothing_to_remove(tmp_path):
    p = str(tmp_path / "log.csv")
    storage.append_results(p, [result(ts=to_iso(utc_now()))])
    assert storage.prune_results(p, 30) == 0
    assert storage.prune_results(str(tmp_path / "missing.csv"), 30) == 0


def test_prune_all_rows_keeps_header(tmp_path):
    p = str(tmp_path / "log.csv")
    storage.append_results(p, [result(ts=to_iso(utc_now() - timedelta(days=90)))])
    assert storage.prune_results(p, 30) == 1
    assert open(p).read().strip() == ",".join(storage.CSV_FIELDS)
    storage.append_results(p, [result(ts=to_iso(utc_now()))])
    assert len(storage.read_results(p)) == 1


def test_state_roundtrip_and_atomicity(tmp_path):
    p = str(tmp_path / "s" / "state.json")
    storage.save_state(p, {"a": {"status": "down"}})
    assert storage.load_state(p) == {"a": {"status": "down"}}
    assert [f.name for f in (tmp_path / "s").iterdir()] == ["state.json"]  # no temp files left


def test_load_state_missing_or_corrupt(tmp_path):
    assert storage.load_state(str(tmp_path / "x.json")) == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{nope")
    assert storage.load_state(str(bad)) == {}
    lst = tmp_path / "list.json"
    lst.write_text(json.dumps([1]))
    assert storage.load_state(str(lst)) == {}
