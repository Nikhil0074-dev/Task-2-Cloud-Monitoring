"""CSV uptime log + JSON alert-state persistence."""
import csv
import json
import os
import tempfile
from datetime import timedelta

from .timeutil import parse_iso, utc_now

CSV_FIELDS = ["timestamp", "name", "url", "status_code", "latency_ms", "success", "error"]


def _ensure_dir(path: str) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)


def _row(result: dict) -> dict:
    return {
        "timestamp": result["timestamp"],
        "name": result["name"],
        "url": result["url"],
        "status_code": "" if result["status_code"] is None else result["status_code"],
        "latency_ms": f"{result['latency_ms']:.2f}",
        "success": "true" if result["success"] else "false",
        "error": result.get("error", ""),
    }


def append_results(path: str, results) -> int:
    """Append results to the CSV log, writing the header for new files."""
    results = list(results)
    _ensure_dir(path)
    new_file = not os.path.exists(path) or os.path.getsize(path) == 0
    with open(path, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        if new_file:
            writer.writeheader()
        for r in results:
            writer.writerow(_row(r))
    return len(results)


def read_results(path: str) -> list:
    """Read the CSV log back into typed result dictionaries."""
    if not os.path.exists(path):
        return []
    out = []
    with open(path, "r", newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                out.append({
                    "timestamp": row["timestamp"],
                    "name": row["name"],
                    "url": row["url"],
                    "status_code": int(row["status_code"]) if row["status_code"] else None,
                    "latency_ms": float(row["latency_ms"]),
                    "success": row["success"].strip().lower() == "true",
                    "error": row.get("error", "") or "",
                })
            except (KeyError, ValueError, AttributeError):
                continue  # skip corrupt rows rather than crash the monitor
    return out


def prune_results(path: str, retention_days: float, now=None) -> int:
    """Drop rows older than ``retention_days``; returns the number removed."""
    rows = read_results(path)
    if not rows:
        return 0
    cutoff = (now or utc_now()) - timedelta(days=retention_days)
    kept = [r for r in rows if parse_iso(r["timestamp"]) >= cutoff]
    removed = len(rows) - len(kept)
    if removed:
        tmp = path + ".tmp"
        if os.path.exists(tmp):
            os.unlink(tmp)
        try:
            append_results(tmp, kept)
            if not kept:  # keep a header-only file so appends stay consistent
                append_results(tmp, [])
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
    return removed


def load_state(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(path: str, state: dict) -> None:
    """Atomically persist alert state (write temp file, then rename)."""
    _ensure_dir(path)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
