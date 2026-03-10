"""
Vibe Coding Agent Orchestrator
CLI entry point.

Usage:
    python -m orchestrator.main run --title "My Task" --description "Build a..."
    python -m orchestrator.main resume
    python -m orchestrator.main status
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from orchestrator.config import get_config
from orchestrator.models import PipelineContext, PipelineState, Task
from orchestrator.pipeline import Pipeline
from orchestrator.utils import get_logger, read_log

logger = get_logger("vibe.main")


def cmd_run(args: argparse.Namespace) -> int:
    """Start a new pipeline run."""
    cfg = get_config()
    try:
        cfg.validate()
    except ValueError as exc:
        logger.error("%s", exc)
        return 1

    task = Task(title=args.title, description=args.description)
    pipeline = Pipeline()

    logger.info("Starting new pipeline for task: %s", task.title)
    ctx = pipeline.run(task)

    _print_summary(ctx)
    return 0 if ctx.state == PipelineState.COMPLETED else 1


def cmd_resume(args: argparse.Namespace) -> int:
    """Resume a paused/failed pipeline."""
    cfg = get_config()
    try:
        cfg.validate()
    except ValueError as exc:
        logger.error("%s", exc)
        return 1

    pipeline = Pipeline()
    try:
        ctx = pipeline.resume()
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        return 1

    _print_summary(ctx)
    return 0 if ctx.state == PipelineState.COMPLETED else 1


def cmd_status(args: argparse.Namespace) -> int:
    """Print current pipeline status."""
    cfg = get_config()
    state_path = Path(cfg.state_file)
    if not state_path.exists():
        print("No pipeline state found. Run 'python -m orchestrator.main run' first.")
        return 1

    ctx = PipelineContext.from_json(state_path.read_text(encoding="utf-8"))
    print(f"\n{'='*50}")
    print("Vibe Coding Pipeline Status")
    print(f"{'='*50}")
    if ctx.task:
        print(f"Task     : {ctx.task.title}")
        print(f"Task ID  : {ctx.task.id}")
    print(f"State    : {ctx.state.value}")
    print(f"Iteration: {ctx.iteration} / {ctx.max_iterations}")
    if ctx.qa_verdict:
        print(f"QA Verdict: {ctx.qa_verdict.value}")
    print(f"\nHistory ({len(ctx.history)} entries):")
    for entry in ctx.history[-10:]:
        print(f"  [{entry['timestamp']}] {entry['agent']:10s} | {entry['step']:25s} | {entry['summary']}")
    print(f"{'='*50}\n")
    return 0


def _print_summary(ctx: PipelineContext) -> None:
    """Print a human-friendly pipeline summary."""
    print(f"\n{'='*60}")
    print("Vibe Coding Pipeline Summary")
    print(f"{'='*60}")
    print(f"Final State : {ctx.state.value.upper()}")
    if ctx.task:
        print(f"Task        : {ctx.task.title}")
    print(f"Iterations  : {ctx.iteration}")
    if ctx.qa_verdict:
        print(f"QA Verdict  : {ctx.qa_verdict.value}")
    print(f"\nLog files written to: {get_config().logs_dir}/")
    print(f"{'='*60}\n")

    if ctx.state == PipelineState.COMPLETED:
        print("✅ Pipeline COMPLETED successfully!")
    elif ctx.state == PipelineState.FAILED:
        print("❌ Pipeline FAILED. Check logs for details.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Vibe Coding Agent Orchestrator – automated multi-agent development pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Start a new pipeline
  python -m orchestrator.main run \\
    --title "Build a REST API" \\
    --description "Create a FastAPI application with user authentication"

  # Resume an interrupted pipeline
  python -m orchestrator.main resume

  # Check current status
  python -m orchestrator.main status
""",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # run
    run_parser = subparsers.add_parser("run", help="Start a new pipeline")
    run_parser.add_argument("--title", required=True, help="Short task title")
    run_parser.add_argument(
        "--description", required=True, help="Detailed task description"
    )
    run_parser.set_defaults(func=cmd_run)

    # resume
    resume_parser = subparsers.add_parser("resume", help="Resume a paused pipeline")
    resume_parser.set_defaults(func=cmd_resume)

    # status
    status_parser = subparsers.add_parser("status", help="Print pipeline status")
    status_parser.set_defaults(func=cmd_status)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
