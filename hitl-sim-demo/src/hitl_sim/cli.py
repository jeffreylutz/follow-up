"""Command-line entry point: run a scenario and emit logs + a summary.

    hitl-sim list
    hitl-sim run hard_over --log out.csv
    hitl-sim run all --outdir logs/
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .scenarios import SCENARIOS


def _run_one(name: str, outdir: Path | None) -> dict[str, object]:
    scenario = SCENARIOS[name]
    loop = scenario.build()
    rec = loop.run(scenario.duration_s)
    summary = rec.summary()
    summary["scenario"] = name
    summary["expected_safe_state"] = scenario.expect_safe_state
    summary["matched_expectation"] = summary["reached_safe_state"] == scenario.expect_safe_state
    if outdir is not None:
        outdir.mkdir(parents=True, exist_ok=True)
        rec.to_csv(outdir / f"{name}.csv")
        rec.to_jsonl(outdir / f"{name}.jsonl")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hitl-sim", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="list available scenarios")

    run = sub.add_parser("run", help="run a scenario (or 'all')")
    run.add_argument("scenario", help="scenario name, or 'all'")
    run.add_argument("--log", type=Path, help="write a CSV log for a single scenario")
    run.add_argument("--outdir", type=Path, help="directory for per-scenario CSV+JSONL logs")

    args = parser.parse_args(argv)

    if args.cmd == "list":
        for name, sc in SCENARIOS.items():
            print(f"{name:14s} {sc.description}")
        return 0

    # cmd == run
    names = list(SCENARIOS) if args.scenario == "all" else [args.scenario]
    if args.scenario != "all" and args.scenario not in SCENARIOS:
        print(f"unknown scenario: {args.scenario}", file=sys.stderr)
        print(f"available: {', '.join(SCENARIOS)}", file=sys.stderr)
        return 2

    all_ok = True
    for name in names:
        summary = _run_one(name, args.outdir)
        all_ok &= bool(summary["matched_expectation"])
        print(json.dumps(summary))

    # Single-scenario --log convenience (a standalone CSV, separate from --outdir).
    if args.log and len(names) == 1:
        scenario = SCENARIOS[names[0]]
        scenario.build().run(scenario.duration_s).to_csv(args.log)

    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
