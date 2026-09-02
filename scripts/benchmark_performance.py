#!/usr/bin/env python3
"""Repeatable foreground performance checks for Memory Harbor."""

import argparse
import importlib.util
import json
from pathlib import Path
import statistics
import time


ROOT = Path(__file__).resolve().parents[1]
HARBOR_SCRIPT = ROOT / "skills/codex-memory-harbor/scripts/harbor.py"
SPEC = importlib.util.spec_from_file_location("harbor", HARBOR_SCRIPT)
harbor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(harbor)


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, int(len(ordered) * fraction) - 1))]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--codex-home", default="~/.codex")
    parser.add_argument("--query", default="强约束")
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--recall-p95-budget-ms", type=float, default=25.0)
    parser.add_argument("--scan", action="store_true")
    parser.add_argument("--scan-budget-seconds", type=float, default=5.0)
    args = parser.parse_args()
    home = Path(args.codex_home).expanduser().absolute()

    # Warm schema/page cache once, then measure the foreground local-index path.
    harbor.recall_search(home, args.query, 20)
    samples = []
    for _ in range(max(1, args.iterations)):
        started = time.perf_counter()
        harbor.recall_search(home, args.query, 20)
        samples.append((time.perf_counter() - started) * 1000)
    result = {
        "query": args.query,
        "iterations": len(samples),
        "recall_ms": {
            "p50": round(statistics.median(samples), 3),
            "p95": round(percentile(samples, 0.95), 3),
            "max": round(max(samples), 3),
            "budget_p95": args.recall_p95_budget_ms,
        },
        "catalog_bytes": harbor.catalog_path(home).stat().st_size if harbor.catalog_path(home).exists() else 0,
    }
    passed = result["recall_ms"]["p95"] <= args.recall_p95_budget_ms
    if args.scan:
        started = time.perf_counter()
        snapshot = harbor.scan(home, 30)
        elapsed = time.perf_counter() - started
        result["scan"] = {
            "seconds": round(elapsed, 3),
            "sessions": len(snapshot["sessions"]),
            "budget_seconds": args.scan_budget_seconds,
        }
        passed = passed and elapsed <= args.scan_budget_seconds
    result["passed"] = passed
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
