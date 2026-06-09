"""
Mobile-Agent runner for a multimodal chat-completions endpoint.

Example:
    python run_agent.py --model-config model_config.json
"""

import argparse
from pathlib import Path

from agent_io import AdbTools
from agent import run_agent_loop
from logs import make_task_log_dirs, enable_dual_logging
from llm_client import DEFAULT_MODEL_CONFIG_PATH, create_llm_client


def parse_args():
    parser = argparse.ArgumentParser(
        description="Mobile-Agent runner for a multimodal chat-completions endpoint."
    )
    parser.add_argument("--model-config", dest="model_config", type=str, default=DEFAULT_MODEL_CONFIG_PATH, help="Path to model config JSON.")
    parser.add_argument(
        "--system-prompt",
        dest="system_prompt",
        type=str,
        default="",
        help="System prompt content for the agent.",
    )
    parser.add_argument(
        "--system-prompt-path",
        dest="system_prompt_path",
        type=str,
        default=None,
        help="Path to a system prompt markdown file.",
    )
    parser.add_argument(
        "--task-prompt",
        dest="task_prompt",
        type=str,
        default="",
        help="Task prompt content for the agent.",
    )
    parser.add_argument(
        "--task-prompt-path",
        dest="task_prompt_path",
        type=str,
        default=None,
        help="Path to a task prompt markdown file.",
    )
    parser.add_argument(
        "--max-steps",
        dest="max_steps",
        type=int,
        default=80)
    parser.add_argument(
        "--history-length",
        dest="history_n",
        type=int,
        default=4,
        help="Number of previous screenshot turns to include.",
    )
    parser.add_argument(
        "--trace-dir",
        dest="trace_dir",
        type=str,
        default=None,
        help="Optional task root directory override.",
    )
    parser.add_argument(
        "--llm-trace-dir",
        dest="llm_trace_dir",
        type=str,
        default=None,
        help="Optional directory for LLM request/response trace logs.",
    )
    return parser.parse_args()

def load_prompt_arg(prompt: str, prompt_path: str | None, label: str) -> str:
    if prompt_path:
        return Path(prompt_path).read_text(encoding="utf-8").strip()
    if prompt:
        return prompt
    raise SystemExit(f"Missing {label}: provide --{label.replace('_', '-')} or --{label.replace('_', '-')}-path.")

def run_agent():
    args = parse_args()
    log_dirs = make_task_log_dirs(args.trace_dir)
    log_file_path = enable_dual_logging(log_dirs["task_root"])
    print(f"[TASK ROOT] {log_dirs['task_root']}")
    print(f"[LOG FILE] {log_file_path}")

    llm_trace_dir = args.llm_trace_dir or log_dirs["llm_tracer_dir"]
    vlm = create_llm_client(
        config_path=args.model_config,
        llm_trace_dir=llm_trace_dir,
    )

    system_prompt = load_prompt_arg(args.system_prompt, args.system_prompt_path, "system_prompt")
    task_prompt = load_prompt_arg(args.task_prompt, args.task_prompt_path, "task_prompt")
    adb_tools = AdbTools()

    run_agent_loop(
        max_steps=args.max_steps,
        task_root=log_dirs["task_root"],
        screenshot_dir=log_dirs["screenshot_dir"],
        anno_dir=log_dirs["screenshot_anno_dir"],
        system_prompt=system_prompt,
        task_prompt=task_prompt,
        history_n=args.history_n,
        adb_tools=adb_tools,
        vlm=vlm,
    )

    print("\n[DONE] Agent execution finished.")


if __name__ == "__main__":
    run_agent()
