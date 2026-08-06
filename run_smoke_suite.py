"""Command-line runner for screenshot-only action-space smoke tasks."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from llm_client import DEFAULT_MODEL_CONFIG_PATH, create_llm_client, load_model_config
from smoke_runner import (
    SCENARIO_IDS,
    SmokeScenarioError,
    default_scenario_paths,
    load_scenario,
    run_scenario,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run screenshot-only smoke probes for the mobile action space."
    )
    parser.add_argument(
        "--model-config",
        default=DEFAULT_MODEL_CONFIG_PATH,
        help="Path to an OpenAI-compatible model configuration JSON file.",
    )
    parser.add_argument(
        "--system-prompt-path",
        default="system_prompt.md",
        help="Shared production system prompt used by every smoke task.",
    )
    parser.add_argument(
        "--task",
        choices=[*SCENARIO_IDS, "all"],
        default="all",
        help="Smoke task to run, or all tasks.",
    )
    parser.add_argument(
        "--mode",
        choices=["quick", "qualify"],
        default="quick",
        help="quick runs once; qualify runs three times and requires two passes.",
    )
    parser.add_argument(
        "--trace-dir",
        default=None,
        help="Directory for smoke reports and model traces.",
    )
    return parser.parse_args()


def _default_trace_dir() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path("tasks/smoke/runs") / stamp


def _print_result(result: dict[str, Any], repetition: int) -> None:
    status = "PASS" if result["passed"] else "FAIL"
    category = result.get("failure_category") or ""
    print(
        f"{status:4} {result['task']:<22} repetition={repetition} "
        f"turns={result['turns']} {category} {result.get('message', '')}"
    )


def run_suite(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    config = load_model_config(args.model_config)
    system_prompt = Path(args.system_prompt_path).read_text(encoding="utf-8").strip()
    scenario_paths = default_scenario_paths()
    selected = list(SCENARIO_IDS) if args.task == "all" else [args.task]
    repetitions = 3 if args.mode == "qualify" else 1
    trace_root = Path(args.trace_dir) if args.trace_dir else _default_trace_dir()
    trace_root.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    for task_id in selected:
        scenario = load_scenario(scenario_paths[task_id])
        for repetition in range(1, repetitions + 1):
            task_trace_dir = trace_root / task_id / f"repetition_{repetition}" / "llm-tracer"
            task_trace_dir.mkdir(parents=True, exist_ok=True)
            vlm = create_llm_client(
                config_path=args.model_config,
                llm_trace_dir=str(task_trace_dir),
            )
            result = run_scenario(scenario, system_prompt, vlm)
            result["repetition"] = repetition
            results.append(result)
            _print_result(result, repetition)

    task_verdicts: dict[str, bool] = {}
    for task_id in selected:
        task_results = [item for item in results if item["task"] == task_id]
        passes = sum(1 for item in task_results if item["passed"])
        task_verdicts[task_id] = passes >= (2 if repetitions == 3 else 1)

    summary = {
        "suite": "action_space_smoke",
        "mode": args.mode,
        "model": config["model_name"],
        "selected_tasks": selected,
        "repetitions": repetitions,
        "task_verdicts": task_verdicts,
        "passed": all(task_verdicts.values()),
        "results": results,
    }
    summary_path = trace_root / "smoke_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Summary: {summary_path}")
    print("Overall:", "PASS" if summary["passed"] else "FAIL")
    if summary["passed"]:
        return 0, summary
    if any(item.get("failure_category") == "infrastructure" for item in results):
        return 2, summary
    return 1, summary


def main() -> int:
    args = parse_args()
    try:
        exit_code, _ = run_suite(args)
        return exit_code
    except SmokeScenarioError as exc:
        print(f"[FIXTURE ERROR] {exc}")
        return 2
    except (OSError, KeyError, ValueError, TypeError) as exc:
        print(f"[CONFIG ERROR] {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
