from __future__ import annotations

import argparse
from pathlib import Path

from evals.runner import run_suite


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Frontline offline evaluations")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run", help="grade reviewed fixture traces")
    run_parser.add_argument(
        "--output",
        type=Path,
        default=Path("/tmp/frontline-evals"),
        help="report destination (default: /tmp/frontline-evals)",
    )
    args = parser.parse_args()

    if args.command == "run":
        evals_dir = Path(__file__).resolve().parent
        report = run_suite(evals_dir, args.output)
        summary = report["summary"]
        print(
            f"offline fixture evaluation: {summary['passed']}/"
            f"{summary['scenarios']} scenarios passed"
        )
        print(f"reports: {args.output / 'report.md'} and {args.output / 'report.json'}")
        return 0 if summary["failed"] == 0 else 1

    return 2


if __name__ == "__main__":
    raise SystemExit(main())

