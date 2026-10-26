#!/usr/bin/env python3
"""Cloud monitoring CLI.

Examples
--------
  python monitor.py --once                       # one round (cron / GitHub Actions)
  python monitor.py                              # loop forever at interval_seconds
  python monitor.py --once --simulate-down       # force every endpoint to look DOWN
  python monitor.py --once --simulate-down "Example Site,GitHub API"
  python monitor.py --report-only                # rebuild reports from the CSV log
"""
import argparse
import os
import sys

from cloudmon import __version__
from cloudmon.config import ConfigError, load_config, resolve_path
from cloudmon.report import write_reports
from cloudmon.runner import parse_simulate, run_loop, run_once, setup_logging
from cloudmon.storage import read_results

HERE = os.path.dirname(os.path.abspath(__file__))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Health checks, uptime logs and automated alerting.")
    p.add_argument("--config", default=os.path.join(HERE, "config.json"), help="path to config.json")
    p.add_argument("--once", action="store_true", help="run a single round and exit")
    p.add_argument("--interval", type=float, help="override interval_seconds (loop mode)")
    p.add_argument("--simulate-down", nargs="?", const="all", default=None, metavar="NAMES",
                   help="simulate downtime for 'all' (default) or comma-separated endpoint names")
    p.add_argument("--report-only", action="store_true", help="regenerate reports from the CSV log and exit")
    p.add_argument("--fail-on-down", action="store_true",
                   help="exit with status 1 if any check failed (turns a GitHub Actions run red)")
    p.add_argument("--verbose", action="store_true", help="debug logging")
    p.add_argument("--version", action="version", version=f"cloudmon {__version__}")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    base_dir = os.path.dirname(os.path.abspath(args.config))
    if args.interval is not None:
        if args.interval <= 0:
            print("Configuration error: --interval must be > 0", file=sys.stderr)
            return 2
        cfg["interval_seconds"] = args.interval

    if args.report_only:
        results = read_results(resolve_path(base_dir, cfg["storage"]["csv"]))
        paths = write_reports(results, resolve_path(base_dir, cfg["storage"]["reports_dir"]),
                              order=[e["name"] for e in cfg["endpoints"]],
                              warn_ms=cfg["thresholds"]["latency_warning_ms"])
        print(f"Reports written: {paths['markdown']}, {paths['html']}")
        return 0

    logger = setup_logging(resolve_path(base_dir, cfg["storage"]["log_file"]), verbose=args.verbose)
    simulate = parse_simulate(args.simulate_down)
    if simulate:
        logger.warning(f"SIMULATION ACTIVE: forcing downtime for {simulate}")

    try:
        if args.once:
            outcome = run_once(cfg, base_dir, simulate, logger)
            return 1 if (args.fail_on_down and outcome.any_down) else 0
        logger.info(f"monitoring {len(cfg['endpoints'])} endpoint(s) every {cfg['interval_seconds']}s - Ctrl+C to stop")
        run_loop(cfg, base_dir, simulate, logger)
    except KeyboardInterrupt:
        logger.info("stopped by user")
    return 0


if __name__ == "__main__":
    sys.exit(main())
