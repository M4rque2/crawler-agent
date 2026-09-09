"""
Mobile-Agent runner for a multimodal chat-completions endpoint.

Example:
    python run_agent.py --model-config model_config.json
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import time
from pathlib import Path
from typing import Any

from agent_io import (
    AdbTools,
    annotate_screenshot,
    append_extract_output,
    execute_action,
    format_turn_response,
    parse_turn_response,
    rescale_coordinates,
)
from context_manager import build_collection_memory, build_messages, load_task_prompt_arg
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
        default=6,
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


def prepare_device_for_task(adb_tools: Any) -> None:
    print("[PREFLIGHT] Checking device state...")
    initial_state = adb_tools.get_device_state()
    print(
        "[PREFLIGHT] Initial state: "
        f"screen_on={initial_state['screen_on']}, locked={initial_state['locked']}"
    )

    adb_tools.wake_if_needed()
    unlocked = adb_tools.unlock_if_needed(max_attempts=3)
    if not unlocked:
        print("[WARN] Device may still be locked after swipe attempts.")

    adb_tools.go_home_default_page()

    final_state = adb_tools.get_device_state()
    print(
        "[PREFLIGHT] Final state: "
        f"screen_on={final_state['screen_on']}, locked={final_state['locked']}"
    )


def run_agent_loop(
    *,
    max_steps: int,
    task_root: str,
    screenshot_dir: str,
    anno_dir: str,
    system_prompt: str,
    task_prompt: list[dict[str, str]],
    history_n: int,
    adb_tools: Any,
    vlm: Any,
) -> None:
    prepare_device_for_task(adb_tools)

    history = []
    output_jsonl_path = os.path.join(task_root, "output.jsonl")
    last_screenshot_path: str | None = None
    pending_feedback: str | None = None
    last_expectation: str | None = None

    for step_id in range(max_steps):
        print(f"\n{'=' * 50}\nSTEP {step_id}\n{'=' * 50}")

        if pending_feedback is not None:
            feedback = pending_feedback
            pending_feedback = None
            current_screenshot_path = last_screenshot_path
        else:
            current_screenshot_path = os.path.join(screenshot_dir, f"screenshot_{step_id}.png")
            if not adb_tools.get_screenshot(current_screenshot_path):
                print("[ERROR] Failed to capture screenshot. Retrying...")
                time.sleep(1)
                continue
            last_screenshot_path = current_screenshot_path
            feedback = None

        turn_previous_expectation = last_expectation
        messages = build_messages(
            current_screenshot_path,
            system_prompt,
            task_prompt,
            history,
            history_n=history_n,
            feedback=feedback,
            collection_memory=build_collection_memory(output_jsonl_path),
            previous_expectation=turn_previous_expectation,
        )
        try:
            output_text, _, _ = vlm.invoke(messages)
        except Exception as exc:
            print(f"[ERROR] LLM invoke failed: {exc}")
            break
        print(f"[MODEL OUTPUT]\n{output_text}")

        try:
            response = parse_turn_response(output_text)
        except Exception as exc:
            print(f"[ERROR] Failed to parse model response: {exc}")
            history.append({"output": output_text or "Malformed model response.", "image": current_screenshot_path,
                            "previous_expectation": turn_previous_expectation})
            continue

        history_output = format_turn_response(response)
        last_expectation = response.get("expectation") or None
        action_parameter = copy.deepcopy(response["tool_call"]["arguments"])
        action_type = action_parameter["action"]

        if action_type == "extract":
            data = action_parameter.get("data")
            if isinstance(data, dict) and data:
                summary = response.get("summary") or "Extracted target page data"
                print(f"[EXTRACT] {summary}")
                append_extract_output(output_jsonl_path, step_id, action_parameter, summary)
                print(f"[EXTRACT SAVED] {output_jsonl_path}")
                pending_feedback = "[EXTRACT FEEDBACK] JSON data recorded successfully. Decide your next action."
            else:
                pending_feedback = "[EXTRACT FEEDBACK] Extract failed: 'data' must be a non-empty JSON object. Retry the extract with a properly structured data field."
                print(f"[EXTRACT ERROR] Invalid or empty data field.")
            history.append({"output": history_output, "image": current_screenshot_path,
                            "previous_expectation": turn_previous_expectation})
            continue

        if action_type == "terminate":
            status = action_parameter["status"]
            summary = response.get("summary") or (
                "Task completed" if status == "success" else "Task not completed; terminating"
            )
            print(f"[TERMINATE] {status}: {summary}")
            history.append({"output": history_output, "image": current_screenshot_path,
                            "previous_expectation": turn_previous_expectation})
            break

        if action_type == "interact":
            user_prompt = action_parameter.get("text", "the required action")
            input(f"[ACTION REQUIRED] Please complete: {user_prompt}\nPress Enter when done...")
            print("[INFO] User action completed. Resuming...")
            history.append({"output": history_output, "image": current_screenshot_path,
                            "previous_expectation": turn_previous_expectation})
            continue

        print(f"[ACTION RAW] {json.dumps(action_parameter, ensure_ascii=False)}")
        width, height = adb_tools.get_display_size()
        try:
            scaled_action_parameter = rescale_coordinates(action_parameter, width, height)
        except Exception as exc:
            print(f"[ERROR] Failed to rescale normalized action coordinates: {exc}")
            history.append({"output": history_output, "image": current_screenshot_path,
                            "previous_expectation": turn_previous_expectation})
            continue
        if scaled_action_parameter != action_parameter:
            print(
                "[ACTION SCALED] "
                f"{json.dumps(scaled_action_parameter, ensure_ascii=False)} "
                f"screen={width}x{height}"
            )

        execute_action(
            scaled_action_parameter,
            adb_tools,
        )

        history.append({"output": history_output, "image": current_screenshot_path,
                        "previous_expectation": turn_previous_expectation})
        annotate_screenshot(
            current_screenshot_path,
            scaled_action_parameter,
            os.path.join(anno_dir, f"screenshot_anno_{step_id}.png"),
        )
        time.sleep(2)


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
    task_prompt = load_task_prompt_arg(args.task_prompt, args.task_prompt_path)
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
