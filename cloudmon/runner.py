"""Orchestration: run checks, persist, evaluate thresholds, alert, report."""
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from . import alerts as alerts_mod
from . import storage
from .checker import check_endpoint
from .config import get_thresholds, resolve_path
from .report import write_reports

LOGGER_NAME = "cloudmon"


@dataclass
class RunOutcome:
    results: list = field(default_factory=list)
    alerts: list = field(default_factory=list)
    deliveries: list = field(default_factory=list)
    reports: dict = field(default_factory=dict)

    @property
    def any_down(self) -> bool:
        return any(not r["success"] for r in self.results)


def setup_logging(log_file: str, console: bool = True, verbose: bool = False, stream=None) -> logging.Logger:
    """Structured log lines to ``log_file`` (UTC) and, optionally, the console."""
    logger = logging.getLogger(LOGGER_NAME)
    for h in list(logger.handlers):
        logger.removeHandler(h)
        h.close()
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.propagate = False
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", datefmt="%Y-%m-%dT%H:%M:%SZ")
    fmt.converter = time.gmtime
    os.makedirs(os.path.dirname(os.path.abspath(log_file)), exist_ok=True)
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    if console:
        ch = logging.StreamHandler(stream or sys.stdout)
        ch.setFormatter(fmt)
        logger.addHandler(ch)
    return logger


def parse_simulate(value):
    """``None``/'' -> None, 'all' -> 'all', 'a,b' -> {'a','b'}."""
    if value is None:
        return None
    value = str(value).strip()
    if not value:
        return None
    if value.lower() == "all":
        return "all"
    names = {n.strip() for n in value.split(",") if n.strip()}
    return names or None


def _is_simulated(simulate, name: str) -> bool:
    return simulate == "all" or (isinstance(simulate, (set, frozenset)) and name in simulate)


def run_checks(cfg: dict, simulate=None) -> list:
    endpoints = cfg["endpoints"]
    timeout = cfg["timeout_seconds"]
    workers = max(1, min(int(cfg["max_workers"]), len(endpoints)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(check_endpoint, ep, timeout, _is_simulated(simulate, ep["name"]))
                   for ep in endpoints]
        return [f.result() for f in futures]  # preserves configured order


def _log_result(logger, r):
    status = r["status_code"] if r["status_code"] is not None else "-"
    msg = (f"check name=\"{r['name']}\" status={status} latency_ms={r['latency_ms']:.2f} "
           f"result={'UP' if r['success'] else 'DOWN'}")
    if r["error"]:
        msg += f" error=\"{r['error']}\""
    logger.log(logging.INFO if r["success"] else logging.WARNING, msg)


def run_once(cfg: dict, base_dir: str = ".", simulate=None, logger=None, env=None,
             stream=None, smtp_factory=None, backoff: float = 1.0) -> RunOutcome:
    """Execute one monitoring round and return everything that happened."""
    logger = logger or logging.getLogger(LOGGER_NAME)
    st = cfg["storage"]
    csv_path = resolve_path(base_dir, st["csv"])
    state_path = resolve_path(base_dir, st["state"])
    reports_dir = resolve_path(base_dir, st["reports_dir"])

    results = run_checks(cfg, simulate)
    for r in results:
        _log_result(logger, r)
    storage.append_results(csv_path, results)
    removed = storage.prune_results(csv_path, st["retention_days"])
    if removed:
        logger.info(f"retention pruned {removed} row(s) older than {st['retention_days']} days")
    history = storage.read_results(csv_path)

    state = storage.load_state(state_path)
    new_alerts = []
    for ep, r in zip(cfg["endpoints"], results):
        th = get_thresholds(cfg, ep)
        ep_state, ep_alerts = alerts_mod.evaluate_check(r, state.get(ep["name"]), th)
        ep_history = [h for h in history if h["name"] == ep["name"]]
        ep_state, up_alerts = alerts_mod.evaluate_uptime(
            ep["name"], ep["url"], ep_history, ep_state, th, r["timestamp"])
        state[ep["name"]] = ep_state
        new_alerts.extend(ep_alerts + up_alerts)
    storage.save_state(state_path, state)

    for a in new_alerts:
        level = logging.ERROR if a.severity == alerts_mod.CRITICAL else (
            logging.WARNING if a.severity == alerts_mod.WARNING else logging.INFO)
        logger.log(level, f"alert severity={a.severity} kind={a.kind} endpoint=\"{a.endpoint}\" msg=\"{a.message}\"")

    deliveries = alerts_mod.dispatch(new_alerts, cfg["alerts"], env=env, stream=stream,
                                     smtp_factory=smtp_factory, backoff=backoff)
    for d in deliveries:
        if not d["ok"]:
            logger.error(f"alert delivery failed channel={d['channel']} alert=\"{d['alert']}\" error=\"{d['error']}\"")

    reports = write_reports(history, reports_dir, order=[e["name"] for e in cfg["endpoints"]],
                            warn_ms=cfg["thresholds"]["latency_warning_ms"])
    up = sum(1 for r in results if r["success"])
    logger.info(f"run complete checks={len(results)} up={up} down={len(results) - up} alerts={len(new_alerts)}")
    return RunOutcome(results, new_alerts, deliveries, reports)


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def run_loop(cfg: dict, base_dir: str = ".", simulate=None, logger=None, max_iterations=None,
             sleep=None, **kwargs):
    """Run :func:`run_once` forever (or ``max_iterations`` times) every interval."""
    sleep = sleep or _sleep  # resolved at call time so it can be patched
    outcomes = []
    i = 0
    while max_iterations is None or i < max_iterations:
        started = time.monotonic()
        outcomes.append(run_once(cfg, base_dir, simulate, logger, **kwargs))
        i += 1
        if max_iterations is not None and i >= max_iterations:
            break
        sleep(max(0.0, cfg["interval_seconds"] - (time.monotonic() - started)))
    return outcomes
