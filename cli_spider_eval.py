"""
CLI entry point for Spider 1 benchmark evaluation.

Usage
-----
    # Single-pass (no feedback loop)
    python cli_spider_eval.py --spider_path ./spider

    # With feedback/retry loop (static validation only)
    python cli_spider_eval.py --spider_path ./spider --feedback

    # With feedback/retry loop (static validation + SQLite execution errors)
    python cli_spider_eval.py --spider_path ./spider --exec-feedback

    # Compare both modes back-to-back
    python cli_spider_eval.py --spider_path ./spider --compare

Optional flags
--------------
    --limit N        Evaluate only the first N samples (default: all)
    --k K            Number of schema retrieval units (Top-K) (default: 15)
    --quiet          Suppress per-sample progress output
    --feedback       Enable validation + retry feedback loop
    --exec-feedback  Also retry on SQLite execution errors (implies --feedback)
    --compare        Run single-pass and feedback modes and print a comparison table
    --max-iter N     Total attempts per question in feedback mode (default: 4)
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
        "--k",
        type=_positive_int,
        default=15,
        metavar="K",
        help="Number of schema retrieval units (Top-K) retrieved per question (default: 15).",
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
        help="Enable the validation + retry feedback loop.",
    )
    parser.add_argument(
        "--exec-feedback",
        action="store_true",
        default=False,
        dest="exec_feedback",
        help="In the feedback loop, also execute each predicted query on the "
             "sample's SQLite database and retry on execution errors "
             "(implies --feedback).",
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        default=False,
        help="Run both single-pass and feedback modes and print a side-by-side comparison.",
    )
    parser.add_argument(
        "--max-iter",
        type=_positive_int,
        default=4,
        metavar="N",
        dest="max_iter",
        help="Total attempts per question in feedback mode, i.e. 1 initial "
             "attempt + N-1 retries (default: 4).",
    )
    args = parser.parse_args()
    if args.exec_feedback:
        args.feedback = True
    return args


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError(f"must be >= 1, got {value}")
    return number


def _mode_label(metrics: dict) -> str:
    if metrics["mode"] != "feedback":
        return "Single-pass"
    if metrics["execution_feedback"]:
        return "Feedback loop (static validation + SQLite execution)"
    return "Feedback loop (static validation)"


def _format_failures(metrics: dict) -> str:
    reasons = ", ".join(f"{kind}: {n}" for kind, n in metrics["failure_reasons"].items())
    return f"{metrics['inference_failures']}" + (f"  ({reasons})" if reasons else "")


def _print_results(metrics: dict) -> None:
    print(f"Mode:                {_mode_label(metrics)}")
    print(f"Retrieval K:         {metrics['k']}")
    if metrics["mode"] == "feedback":
        print(f"Max attempts:        {metrics['max_attempts']}")
    print(f"Total Samples:       {metrics['total']}")
    print(f"Exact Match:         {metrics['exact_match']:.2f}%")
    print(f"Execution Accuracy:  {metrics['execution_accuracy']:.2f}%")
    print(f"Inference failures:  {_format_failures(metrics)}")
    print(f"Skipped samples:     {metrics['skipped']}")
    print(f"LLM calls:           {metrics['llm_calls']}")
    if metrics["mode"] == "feedback":
        _print_feedback_diagnostics(metrics)


def _print_feedback_diagnostics(metrics: dict) -> None:
    fb = metrics["feedback"]
    em_delta = metrics["exact_match"] - fb["first_attempt_exact_match"]
    ex_delta = metrics["execution_accuracy"] - fb["first_attempt_execution_accuracy"]
    total = metrics["total"] or 1
    print()
    print("Feedback diagnostics (paired, same run)")
    print(f"  First-attempt EM / EX:  {fb['first_attempt_exact_match']:.2f}% / "
          f"{fb['first_attempt_execution_accuracy']:.2f}%  (= single-pass answer)")
    print(f"  Change from feedback:   {em_delta:+.2f} / {ex_delta:+.2f}")
    print(f"  Samples retried:        {fb['retried']} ({fb['retried'] / total:.2%})")
    print(f"    recovered:            {fb['recovered']}  (a retry passed the checks)")
    print(f"    exhausted:            {fb['exhausted']}  (no attempt passed the checks)")


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
    print(f"Retrieving Top-{args.k} schema units per question.")
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
            k=args.k,
            use_feedback_loop=False,
        )

        print()
        print("=" * 50)
        print("  Mode: Feedback loop" + (" + execution feedback" if args.exec_feedback else ""))
        print("=" * 50)
        metrics_fb = await run_spider_evaluation(
            samples=samples,
            spider_path=spider_path,
            verbose=not args.quiet,
            max_samples=args.limit,
            k=args.k,
            use_feedback_loop=True,
            feedback_max_iterations=args.max_iter,
            execution_feedback=args.exec_feedback,
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
        print(f"{'Inference failures':<26} {metrics_sp['inference_failures']:>12} {metrics_fb['inference_failures']:>12}")
        print(f"{'LLM calls':<26} {metrics_sp['llm_calls']:>12} {metrics_fb['llm_calls']:>12}")
        print("=" * 50)

        em_delta = metrics_fb["exact_match"] - metrics_sp["exact_match"]
        ex_delta = metrics_fb["execution_accuracy"] - metrics_sp["execution_accuracy"]
        sign = lambda v: f"+{v:.2f}" if v >= 0 else f"{v:.2f}"
        print(f"{'EM delta (feedback - single)':<26} {sign(em_delta):>25}")
        print(f"{'EX delta (feedback - single)':<26} {sign(ex_delta):>25}")
        print("(the deltas above compare two separate LLM runs and include sampling noise)")
        _print_feedback_diagnostics(metrics_fb)

    else:
        metrics = await run_spider_evaluation(
            samples=samples,
            spider_path=spider_path,
            verbose=not args.quiet,
            max_samples=args.limit,
            k=args.k,
            use_feedback_loop=args.feedback,
            feedback_max_iterations=args.max_iter,
            execution_feedback=args.exec_feedback,
        )

        print()
        print("Spider Evaluation Results")
        print("=========================")
        _print_results(metrics)


if __name__ == "__main__":
    asyncio.run(main())
