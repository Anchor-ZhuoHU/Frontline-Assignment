from __future__ import annotations

import argparse
import os
from pathlib import Path

from evals.live import OpenAIChatModel, OpenAIHTTPTransport
from evals.runner import run_live_suite, run_suite


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Frontline offline evaluations")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser(
        "run", help="run and grade deterministic scripted conversations"
    )
    run_parser.add_argument(
        "--output",
        type=Path,
        default=Path("/tmp/frontline-evals"),
        help="report destination (default: /tmp/frontline-evals)",
    )
    run_parser.add_argument("--live", action="store_true", help="opt in to live GPT-4.1 calls")
    run_parser.add_argument("--runs", type=int, default=3, help="live runs per scenario")
    run_parser.add_argument("--k", type=int, default=2, help="k for live pass^k")
    args = parser.parse_args()

    if args.command == "run":
        evals_dir = Path(__file__).resolve().parent
        if args.live:
            transport = OpenAIHTTPTransport(os.getenv("OPENAI_API_KEY", ""))
            report = run_live_suite(
                evals_dir, args.output, lambda: OpenAIChatModel(transport), args.runs, args.k
            )
        else:
            report = run_suite(evals_dir, args.output)
        summary = report["summary"]
        if args.live:
            print(
                f"live evaluation: {summary['passed']}/{summary['runs']} runs passed; "
                f"pass^{args.k}={summary['pass_at_k']:.4f}"
            )
        else:
            print(
                f"offline scripted evaluation: {summary['passed']}/"
                f"{summary['scenarios']} scenarios passed"
            )
        print(f"reports: {args.output / 'report.md'} and {args.output / 'report.json'}")
        return 0 if summary["failed"] == 0 else 1

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
