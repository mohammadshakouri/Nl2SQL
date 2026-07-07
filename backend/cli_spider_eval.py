"""
CLI entry point for Spider 1 benchmark evaluation.

Usage
-----
    # Single-pass (no feedback loop)
    python cli_spider_eval.py --spider_path ./spider

    # With feedback/retry loop (same as production endpoint)
    python cli_spider_eval.py --spider_path ./spider --feedback

    # Compare both modes back-to-back
    python cli_spider_eval.py --spider_path ./spider --compare

Optional flags
--------------
    --limit N        Evaluate only the first N samples (default: all)
    --quiet          Suppress per-sample progress output
    --feedback       Enable validation + retry feedback loop
    --compare        Run both modes sequentially and print a comparison table
    --max-iter N     Max retry iterations when feedback is enabled (default: 4)
"""

import argparse
import asyncio
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from app.spider_eval.spider_loader import load_spider_dev
from app.spider_eval.spider_runner import run_spider_evaluation


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate NL2SQL pipeline on the Spider 1 benchmark."
    )
    parser.add_argument(
        "--spider_path",
        required=True,
        help="Root directory of the Spider dataset (must contain dev.json, "
             "tables.json and database/).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Evaluate only the first N samples (default: all).",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        default=False,
        help="Suppress per-sample progress lines.",
    )
    parser.add_argument(
        "--feedback",
        action="store_true",
        default=False,
        help="Enable the validation + retry feedback loop (mirrors production endpoint).",
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        default=False,
        help="Run both single-pass and feedback modes and print a side-by-side comparison.",
    )
    parser.add_argument(
        "--max-iter",
        type=int,
        default=4,
        metavar="N",
        dest="max_iter",
        help="Max retry iterations when --feedback is enabled (default: 4).",
    )
    return parser.parse_args()


def _print_results(metrics: dict) -> None:
    mode_label = "Feedback loop" if metrics["mode"] == "feedback" else "Single-pass"
    print(f"Mode:                {mode_label}")
    print(f"Total Samples:       {metrics['total']}")
    print(f"Exact Match:         {metrics['exact_match']:.2f}%")
    print(f"Execution Accuracy:  {metrics['execution_accuracy']:.2f}%")


async def main() -> None:
    args = parse_args()

    spider_path = os.path.abspath(args.spider_path)
    if not os.path.isdir(spider_path):
        print(f"ERROR: spider_path does not exist or is not a directory: {spider_path}")
        sys.exit(1)

    print(f"Loading Spider dev set from: {spider_path}")
    samples = load_spider_dev(spider_path)
    print(f"Loaded {len(samples)} samples.")
    if args.limit:
        print(f"Limiting evaluation to first {args.limit} samples.")
    print()

    if args.compare:
        # --- Single-pass run ---
        print("=" * 50)
        print("  Mode: Single-pass (no feedback)")
        print("=" * 50)
        metrics_sp = await run_spider_evaluation(
            samples=samples,
            spider_path=spider_path,
            verbose=not args.quiet,
            max_samples=args.limit,
            use_feedback_loop=False,
        )

        print()
        print("=" * 50)
        print("  Mode: Feedback loop")
        print("=" * 50)
        metrics_fb = await run_spider_evaluation(
            samples=samples,
            spider_path=spider_path,
            verbose=not args.quiet,
            max_samples=args.limit,
            use_feedback_loop=True,
            feedback_max_iterations=args.max_iter,
        )

        # Side-by-side comparison
        print()
        print("Spider Evaluation – Comparison")
        print("=" * 50)
        print(f"{'Metric':<26} {'Single-pass':>12} {'Feedback':>12}")
        print("-" * 50)
        print(f"{'Total Samples':<26} {metrics_sp['total']:>12} {metrics_fb['total']:>12}")
        print(f"{'Exact Match (%)':<26} {metrics_sp['exact_match']:>12.2f} {metrics_fb['exact_match']:>12.2f}")
        print(f"{'Execution Accuracy (%)':<26} {metrics_sp['execution_accuracy']:>12.2f} {metrics_fb['execution_accuracy']:>12.2f}")
        print("=" * 50)

        em_delta = metrics_fb["exact_match"] - metrics_sp["exact_match"]
        ex_delta = metrics_fb["execution_accuracy"] - metrics_sp["execution_accuracy"]
        sign = lambda v: f"+{v:.2f}" if v >= 0 else f"{v:.2f}"
        print(f"{'EM delta (feedback - single)':<26} {sign(em_delta):>25}")
        print(f"{'EX delta (feedback - single)':<26} {sign(ex_delta):>25}")

    else:
        metrics = await run_spider_evaluation(
            samples=samples,
            spider_path=spider_path,
            verbose=not args.quiet,
            max_samples=args.limit,
            use_feedback_loop=args.feedback,
            feedback_max_iterations=args.max_iter,
        )

        print()
        print("Spider Evaluation Results")
        print("=========================")
        _print_results(metrics)


if __name__ == "__main__":
    asyncio.run(main())
