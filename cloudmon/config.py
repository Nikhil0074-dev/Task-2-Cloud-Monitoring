"""Configuration loading, defaults and validation."""
import copy
import json
import os
from urllib.parse import urlparse


class ConfigError(ValueError):
    """Raised when the configuration file is missing or invalid."""


DEFAULT_CONFIG = {
    "interval_seconds": 300,
    "timeout_seconds": 10,
    "max_workers": 8,
    "thresholds": {
        "latency_warning_ms": 800,
        "latency_critical_ms": 2000,
        "consecutive_failures": 1,
        "uptime_min_percent": 99.0,
        "uptime_window_checks": 100,
        "uptime_min_checks": 10,
    },
    "alerts": {
        "console": True,
        "webhook": {
            "enabled": False,
            "url": "",
            "url_env": "ALERT_WEBHOOK_URL",
            "attempts": 2,
        },
        "email": {
            "enabled": False,
            "smtp_host": "",
            "smtp_port": 587,
            "use_tls": True,
            "from": "",
            "to": [],
            "username_env": "SMTP_USERNAME",
            "password_env": "SMTP_PASSWORD",
        },
    },
    "storage": {
        "csv": "data/uptime_log.csv",
        "state": "data/state.json",
        "log_file": "logs/monitor.log",
        "reports_dir": "reports",
        "retention_days": 30,
    },
    "endpoints": [],
}


def deep_merge(base: dict, override: dict) -> dict:
    """Return ``base`` recursively updated with ``override`` (inputs untouched)."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _number(value, label, minimum=None, maximum=None, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{label} must be a number, got {value!r}")
    if integer and int(value) != value:
        raise ConfigError(f"{label} must be a whole number, got {value!r}")
    if minimum is not None and value < minimum:
        raise ConfigError(f"{label} must be >= {minimum}, got {value!r}")
    if maximum is not None and value > maximum:
        raise ConfigError(f"{label} must be <= {maximum}, got {value!r}")
    return value


def validate_thresholds(th: dict, label: str = "thresholds") -> None:
    _number(th["latency_warning_ms"], f"{label}.latency_warning_ms", minimum=1)
    _number(th["latency_critical_ms"], f"{label}.latency_critical_ms", minimum=1)
    if th["latency_warning_ms"] >= th["latency_critical_ms"]:
        raise ConfigError(f"{label}.latency_warning_ms must be lower than latency_critical_ms")
    _number(th["consecutive_failures"], f"{label}.consecutive_failures", minimum=1, integer=True)
    _number(th["uptime_min_percent"], f"{label}.uptime_min_percent", minimum=0, maximum=100)
    _number(th["uptime_window_checks"], f"{label}.uptime_window_checks", minimum=1, integer=True)
    _number(th["uptime_min_checks"], f"{label}.uptime_min_checks", minimum=1, integer=True)


def _normalize_expected(value, label):
    if value is None:
        return [200]
    values = value if isinstance(value, list) else [value]
    if not values:
        raise ConfigError(f"{label}.expected_status must not be empty")
    out = []
    for v in values:
        _number(v, f"{label}.expected_status", minimum=100, maximum=599, integer=True)
        out.append(int(v))
    return out


def build_config(raw: dict) -> dict:
    """Merge ``raw`` onto the defaults, validate and normalise it."""
    if not isinstance(raw, dict):
        raise ConfigError("Configuration root must be a JSON object")
    cfg = deep_merge(DEFAULT_CONFIG, raw)

    _number(cfg["interval_seconds"], "interval_seconds", minimum=0.01)
    _number(cfg["timeout_seconds"], "timeout_seconds", minimum=0.01)
    _number(cfg["max_workers"], "max_workers", minimum=1, integer=True)
    validate_thresholds(cfg["thresholds"])

    endpoints = cfg["endpoints"]
    if not isinstance(endpoints, list) or not endpoints:
        raise ConfigError("At least one endpoint must be configured under 'endpoints'")

    seen = set()
    for i, ep in enumerate(endpoints):
        label = f"endpoints[{i}]"
        if not isinstance(ep, dict):
            raise ConfigError(f"{label} must be an object")
        name = ep.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ConfigError(f"{label}.name is required")
        if name in seen:
            raise ConfigError(f"Duplicate endpoint name: {name!r}")
        seen.add(name)
        url = ep.get("url")
        parsed = urlparse(url) if isinstance(url, str) else None
        if not parsed or parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ConfigError(f"{label}.url must be a valid http(s) URL, got {url!r}")
        ep["expected_status"] = _normalize_expected(ep.get("expected_status"), label)
        method = str(ep.get("method", "GET")).upper()
        if method not in ("GET", "HEAD"):
            raise ConfigError(f"{label}.method must be GET or HEAD")
        ep["method"] = method
        if "thresholds" in ep:
            if not isinstance(ep["thresholds"], dict):
                raise ConfigError(f"{label}.thresholds must be an object")
            validate_thresholds(deep_merge(cfg["thresholds"], ep["thresholds"]), f"{label}.thresholds")
    return cfg


def load_config(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except FileNotFoundError:
        raise ConfigError(f"Config file not found: {path}")
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Config file {path} is not valid JSON: {exc}")
    return build_config(raw)


def get_thresholds(cfg: dict, endpoint: dict) -> dict:
    """Global thresholds overlaid with the endpoint's own overrides."""
    return deep_merge(cfg["thresholds"], endpoint.get("thresholds", {}))


def resolve_path(base_dir: str, relative: str) -> str:
    return relative if os.path.isabs(relative) else os.path.join(base_dir, relative)
