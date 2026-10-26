import json

import pytest

from cloudmon.config import ConfigError, build_config, get_thresholds, load_config

EP = {"name": "a", "url": "https://example.com"}


def test_defaults_are_merged():
    cfg = build_config({"endpoints": [dict(EP)]})
    assert cfg["interval_seconds"] == 300
    assert cfg["thresholds"]["latency_warning_ms"] == 800
    assert cfg["alerts"]["webhook"]["url_env"] == "ALERT_WEBHOOK_URL"
    assert cfg["endpoints"][0]["expected_status"] == [200]
    assert cfg["endpoints"][0]["method"] == "GET"


def test_shipped_config_is_valid():
    cfg = load_config("config.json")
    assert len(cfg["endpoints"]) == 3


def test_expected_status_normalised_from_int_and_list():
    cfg = build_config({"endpoints": [dict(EP, expected_status=204),
                                      {"name": "b", "url": "http://b.io", "expected_status": [200, 301]}]})
    assert cfg["endpoints"][0]["expected_status"] == [204]
    assert cfg["endpoints"][1]["expected_status"] == [200, 301]


def test_per_endpoint_threshold_override():
    cfg = build_config({"endpoints": [dict(EP, thresholds={"latency_warning_ms": 50, "latency_critical_ms": 90})]})
    th = get_thresholds(cfg, cfg["endpoints"][0])
    assert th["latency_warning_ms"] == 50
    assert th["consecutive_failures"] == 1  # inherited


@pytest.mark.parametrize("raw, fragment", [
    ({}, "At least one endpoint"),
    ({"endpoints": []}, "At least one endpoint"),
    ({"endpoints": ["x"]}, "must be an object"),
    ({"endpoints": [{"url": "https://a.com"}]}, "name is required"),
    ({"endpoints": [{"name": "a", "url": "ftp://a.com"}]}, "valid http(s) URL"),
    ({"endpoints": [{"name": "a", "url": "not a url"}]}, "valid http(s) URL"),
    ({"endpoints": [EP, EP]}, "Duplicate endpoint name"),
    ({"endpoints": [dict(EP, expected_status=999)]}, "expected_status"),
    ({"endpoints": [dict(EP, method="POST")]}, "GET or HEAD"),
    ({"endpoints": [EP], "thresholds": {"latency_warning_ms": 900, "latency_critical_ms": 100}}, "lower than"),
    ({"endpoints": [EP], "thresholds": {"consecutive_failures": 0}}, "consecutive_failures"),
    ({"endpoints": [EP], "thresholds": {"uptime_min_percent": 101}}, "uptime_min_percent"),
    ({"endpoints": [EP], "timeout_seconds": "ten"}, "timeout_seconds"),
    ({"endpoints": [EP], "interval_seconds": 0}, "interval_seconds"),
    ({"endpoints": [dict(EP, thresholds={"latency_warning_ms": 5000})]}, "lower than"),
])
def test_invalid_configs_raise(raw, fragment):
    with pytest.raises(ConfigError) as exc:
        build_config(raw)
    assert fragment in str(exc.value)


def test_root_must_be_object():
    with pytest.raises(ConfigError):
        build_config([])


def test_load_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(str(tmp_path / "nope.json"))


def test_load_bad_json(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{oops")
    with pytest.raises(ConfigError, match="not valid JSON"):
        load_config(str(p))


def test_load_valid_file(tmp_path):
    p = tmp_path / "ok.json"
    p.write_text(json.dumps({"endpoints": [EP]}))
    assert load_config(str(p))["endpoints"][0]["name"] == "a"
