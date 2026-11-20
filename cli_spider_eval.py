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

    # A paid run: pick the model, then continue it if it is interrupted
    python cli_spider_eval.py --spider_path ./spider --model MODEL --tag full
    python cli_spider_eval.py --spider_path ./spider --resume runs/<run_dir>

Optional flags
--------------
    --limit N        Evaluate only the first N samples (default: all)
    --k K            Number of schema retrieval units (Top-K) (default: 15)
    --quiet          Suppress per-sample progress output
    --feedback       Enable validation + retry feedback loop
    --exec-feedback  Also retry on SQLite execution errors (implies --feedback)
    --compare        Run single-pass and feedback modes and print a comparison table
    --max-iter N     Total attempts per question in feedback mode (default: 4)

Model and logging flags
-----------------------
    --model NAME     Model for the active provider (OpenAI, or Ollama if USE_LOCAL_LLM)
    --temperature T  Sampling temperature, or "default" to omit it (for models
                     that reject the parameter)
    --reasoning-effort E
                     OpenAI reasoning_effort (e.g. low), or "default" to omit it
    --out-dir DIR    Where run directories are created (default: runs)
    --tag TEXT       Suffix for the run directory name
    --resume DIR     Continue the run in DIR: finished samples are kept, samples
                     that failed on infrastructure errors are re-run. Settings
                     are taken from the run's manifest.
    --rebuild-index  Re-embed all schema units instead of reusing Chroma
                     collections from earlier runs
    --no-preflight   Skip the one-call check of the model/credentials

Every run writes runs/<run_dir>/ (manifest.json, samples.jsonl, brief.jsonl,
schema_units.json, console.txt); see docs/run-log-format.md. Verify a run with:
    python -m app.spider_eval.run_log check runs/<run_dir>
"""

import argparse
import asyncio
import json
import os
import signal
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from app.nl2sql_chain import configure_llm, get_llm_settings
from app.spider_eval.llm_io import preflight
from app.spider_eval.run_log import RunLog, StdoutCapture
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
        default=None,
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
        default=None,
        metavar="N",
        dest="max_iter",
        help="Total attempts per question in feedback mode, i.e. 1 initial "
             "attempt + N-1 retries (default: 4).",
    )
    parser.add_argument(
        "--model",
        default=None,
        metavar="NAME",
        help="Model name for the active provider (default: the one in nl2sql_chain.py).",
    )
    parser.add_argument(
        "--temperature",
        type=_temperature,
        default=_NOT_GIVEN,
        metavar="T",
        help='Sampling temperature, or "default" to omit the parameter.',
    )
    parser.add_argument(
        "--reasoning-effort",
        type=_reasoning_effort,
        default=_NOT_GIVEN,
        metavar="E",
        dest="reasoning_effort",
        help='OpenAI reasoning_effort value (default: the one in nl2sql_chain.py), '
             'or "default" to omit the parameter. Ignored for Ollama.',
    )
    parser.add_argument(
        "--out-dir",
        default="runs",
        metavar="DIR",
        dest="out_dir",
        help="Directory in which run directories are created (default: runs).",
    )
    parser.add_argument(
        "--tag",
        default=None,
        metavar="TEXT",
        help="Suffix for the run directory name.",
    )
    parser.add_argument(
        "--resume",
        default=None,
        metavar="RUN_DIR",
        help="Continue the run in RUN_DIR (settings are taken from its manifest).",
    )
    parser.add_argument(
        "--rebuild-index",
        action="store_true",
        default=False,
        dest="rebuild_index",
        help="Re-embed all schema units instead of reusing existing Chroma collections.",
    )
    parser.add_argument(
        "--no-preflight",
        action="store_true",
        default=False,
        dest="no_preflight",
        help="Skip the single test call made to the LLM before the run.",
    )
    args = parser.parse_args()
    if args.exec_feedback:
        args.feedback = True
    return args


_NOT_GIVEN = object()


def _temperature(value: str):
    if value.lower() == "default":
        return None
    return float(value)


def _reasoning_effort(value: str):
    return None if value.lower() == "default" else value


def _llm_line(llm) -> str:
    line = f"LLM: {llm.provider} / {llm.model}  temperature={llm.temperature}"
    if llm.provider == "openai":
        line += f"  reasoning_effort={llm.reasoning_effort}"
    return line


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
    print(f"Tokens:              {_format_tokens(metrics['tokens'])}")
    if metrics["mode"] == "feedback":
        _print_feedback_diagnostics(metrics)
    print(f"Run log:             {metrics['run_dir']}")


def _format_tokens(tokens: dict) -> str:
    parts = [f"{name.replace('_tokens', '')}: {tokens[name]:,}"
             for name in ("prompt_tokens", "completion_tokens", "reasoning_tokens", "cached_tokens", "total_tokens")
             if name in tokens]
    missing = tokens.get("samples_without_usage", 0)
    if missing:
        parts.append(f"(no usage reported for {missing} samples)")
    return ", ".join(parts) if parts else "not reported by the provider"


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


def _apply_resume_settings(args: argparse.Namespace) -> None:
    """With --resume, the run's own manifest decides the settings."""
    manifest_path = os.path.join(args.resume, "manifest.json")
    if not os.path.isfile(manifest_path):
        print(f"ERROR: not a run directory (no manifest.json): {args.resume}")
        sys.exit(1)
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)
    config, llm = manifest["config"], manifest["llm"]

    saved = {
        "k": config["k"],
        "feedback": config["mode"] == "feedback",
        "exec_feedback": bool(config.get("execution_feedback")),
        "max_iter": config.get("max_attempts"),
        "model": llm["model"],
    }
    given = {
        "k": args.k, "model": args.model,
        "max_iter": args.max_iter if saved["feedback"] else None,
        "feedback": args.feedback or None, "exec_feedback": args.exec_feedback or None,
    }
    for name, value in given.items():
        if value is not None and value != saved[name]:
            print(f"ERROR: --{name.replace('_', '-')} {value!r} contradicts the run being resumed "
                  f"({saved[name]!r}). Omit it: --resume takes its settings from the manifest.")
            sys.exit(1)
    if args.temperature is not _NOT_GIVEN and args.temperature != llm["temperature"]:
        print(f"ERROR: --temperature contradicts the run being resumed ({llm['temperature']!r}).")
        sys.exit(1)
    if args.reasoning_effort is not _NOT_GIVEN and args.reasoning_effort != llm.get("reasoning_effort"):
        print(f"ERROR: --reasoning-effort contradicts the run being resumed ({llm.get('reasoning_effort')!r}).")
        sys.exit(1)

    args.k = saved["k"]
    args.feedback = saved["feedback"]
    args.exec_feedback = saved["exec_feedback"]
    args.max_iter = saved["max_iter"]
    args.model = saved["model"]
    args.temperature = llm["temperature"]
    args.reasoning_effort = llm.get("reasoning_effort")


async def _run_one(
    args: argparse.Namespace, samples, spider_path: str, feedback: bool, prelude: str
) -> dict:
    """One logged run (a new run directory, or the one being resumed)."""
    mode = "feedback" if feedback else "single-pass"
    if args.resume:
        run_log = RunLog.resume(args.resume, prelude=prelude)
    else:
        run_log = RunLog.create(
            args.out_dir, mode, get_llm_settings().model, args.k, args.tag, prelude=prelude
        )
    try:
        metrics = await run_spider_evaluation(
            samples=samples,
            spider_path=spider_path,
            verbose=not args.quiet,
            max_samples=args.limit,
            k=args.k,
            use_feedback_loop=feedback,
            feedback_max_iterations=args.max_iter,
            execution_feedback=args.exec_feedback if feedback else False,
            run_log=run_log,
            resume=bool(args.resume),
            rebuild_index=args.rebuild_index,
            argv=sys.argv,
        )
        print()
        print("Spider Evaluation Results")
        print("=========================")
        _print_results(metrics)
        _warn_infrastructure_failures(metrics)
        return metrics
    finally:
        run_log.close()


def _warn_infrastructure_failures(metrics: dict) -> None:
    infra = sum(metrics["failure_reasons"].get(kind, 0)
                for kind in ("llm_error", "retrieval_error", "internal_error"))
    if infra or metrics["skipped"]:
        print()
        print(f"WARNING: {infra} sample(s) failed on infrastructure errors and {metrics['skipped']} "
              "were skipped; they count against the metrics above.")
        print(f"         Re-run only those with:  python cli_spider_eval.py --spider_path <path> "
              f"--resume {metrics['run_dir']}")


async def main() -> None:
    capture = StdoutCapture()   # so the run's console.txt also holds the output printed before it exists
    try:
        args, samples, spider_path = await _prepare()
    finally:
        prelude = capture.stop()
    await _run(args, samples, spider_path, prelude)


async def _prepare():
    """Parse arguments, configure the LLM, load the dataset and run the preflight call."""
    args = parse_args()

    if args.resume and args.compare:
        print("ERROR: --resume cannot be combined with --compare.")
        sys.exit(1)
    if args.resume:
        _apply_resume_settings(args)
    args.k = args.k or 15
    args.max_iter = args.max_iter or 4

    configure_llm(
        model=args.model,
        **({} if args.temperature is _NOT_GIVEN else {"temperature": args.temperature}),
        **({} if args.reasoning_effort is _NOT_GIVEN else {"reasoning_effort": args.reasoning_effort}),
    )
    llm = get_llm_settings()

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
    print(_llm_line(llm))

    if not args.no_preflight:
        call = await preflight()
        if call.error:
            print(f"ERROR: preflight call to {llm.provider} / {llm.model} failed: {call.error}")
            print("       Nothing was run. Fix the model name / credentials / parameters, "
                  "or pass --no-preflight to skip this check.")
            sys.exit(1)
        print(f"Preflight OK: {call.latency_ms:.0f} ms, reply {call.text.strip()[:40]!r}, "
              f"usage {call.usage}")
        if llm.provider == "openai" and not call.usage:
            print("WARNING: the endpoint reported no token usage, so the run log cannot show "
                  "token counts or cost.")
    print()
    return args, samples, spider_path


async def _run(args: argparse.Namespace, samples, spider_path: str, prelude: str) -> None:
    if args.compare:
        # --- Single-pass run ---
        print("=" * 50)
        print("  Mode: Single-pass (no feedback)")
        print("=" * 50)
        metrics_sp = await _run_one(args, samples, spider_path, False, prelude)

        print()
        print("=" * 50)
        print("  Mode: Feedback loop" + (" + execution feedback" if args.exec_feedback else ""))
        print("=" * 50)
        metrics_fb = await _run_one(args, samples, spider_path, True, prelude)

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
        await _run_one(args, samples, spider_path, args.feedback, prelude)


def _terminate_as_interrupt(signum, frame) -> None:
    raise KeyboardInterrupt


if __name__ == "__main__":
    # Treat SIGTERM like Ctrl-C so an interrupted run still closes its log cleanly.
    try:
        signal.signal(signal.SIGTERM, _terminate_as_interrupt)
    except (ValueError, OSError):
        pass
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted. The run log is intact; continue it with --resume <run_dir>.")
        sys.exit(130)
