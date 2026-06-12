"""GUI-agent message construction and prompt definitions."""

import copy
import json
import os
import time
from datetime import datetime
from typing import Any

from agent_io import (
    annotate_screenshot,
    append_extract_output,
    execute_action,
    format_turn_response,
    parse_turn_response,
    rescale_coordinates,
    summarize_history_output,
)

def build_today_str():
    today = datetime.today()
    weekday_names = [
        "Monday", "Tuesday", "Wednesday", "Thursday",
        "Friday", "Saturday", "Sunday",
    ]
    formatted_date = today.strftime("%Y-%m-%d") + " " + weekday_names[today.weekday()]
    return f"Today's date is: {formatted_date}."

def build_messages(
    image_path,
    system_prompt,
    task_prompt,
    history_output,
    history_n=6,
    reference_image_path=None,
    reference_text=None,
    feedback=None,
):
    """Construct multi-turn messages for the VLM."""
    current_step = len(history_output)
    history_start_idx = max(0, current_step - history_n)

    previous_actions = []
    for i in range(history_start_idx):
        if i < len(history_output):
            text = summarize_history_output(history_output[i]["output"])
            previous_actions.append(f"Step {i + 1}: {text}")

    previous_actions_str = "\n".join(previous_actions) if previous_actions else "None"

    date_info = build_today_str()

    task_prompt_message = (
        f"Please generate the next action according to the UI screenshot, "
        f"task prompt and previous actions.\n\n"
        f"Task prompt: {task_prompt}\n\n"
        f"Previous actions:\n{previous_actions_str}"
    )
    if reference_image_path:
        reference_prompt = reference_text or "Use the reference image to recognize the target UI region on the current screenshot."
        task_prompt_message = (
            f"{task_prompt_message}\n\n"
            f"Reference image guidance: {reference_prompt}\n"
            f"The first image is the reference image. The last image is the current screenshot."
        )

    messages = [
        {
            "role": "system",
            "content": [{"text": system_prompt}],
        }
    ]

    history_len = min(history_n, len(history_output))
    if history_len > 0:
        for idx, item in enumerate(history_output[-history_n:]):
            if idx == 0:
                first_turn_content = [{"text": task_prompt_message}]
                if reference_image_path:
                    first_turn_content.append({"image": "file://" + reference_image_path})
                first_turn_content.append({"image": "file://" + item["image"]})
                messages.append({
                    "role": "user",
                    "content": first_turn_content,
                })
            else:
                messages.append({
                    "role": "user",
                    "content": [{"image": "file://" + item["image"]}],
                })
            messages.append({
                "role": "assistant",
                "content": [{"text": item["output"]}],
            })
        messages.append({
            "role": "user",
            "content": [{"text": feedback}] if feedback is not None else [{"image": "file://" + image_path}],
        })
    else:
        first_turn_content = [{"text": task_prompt_message}]
        if reference_image_path:
            first_turn_content.append({"image": "file://" + reference_image_path})
        first_turn_content.append({"image": "file://" + image_path})
        messages.append({
            "role": "user",
            "content": first_turn_content,
        })

    return messages


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
    task_prompt: str,
    history_n: int,
    adb_tools: Any,
    vlm: Any,
) -> None:
    prepare_device_for_task(adb_tools)

    history = []
    output_jsonl_path = os.path.join(task_root, "output.jsonl")
    last_screenshot_path: str | None = None
    pending_feedback: str | None = None

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

        messages = build_messages(
            current_screenshot_path,
            system_prompt,
            task_prompt,
            history,
            history_n=history_n,
            feedback=feedback,
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
            history.append({"output": output_text or "Malformed model response.", "image": current_screenshot_path})
            continue

        history_output = format_turn_response(response)
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
            history.append({"output": history_output, "image": current_screenshot_path})
            continue

        if action_type == "terminate":
            status = action_parameter["status"]
            summary = response.get("summary") or (
                "Task completed" if status == "success" else "Task not completed; terminating"
            )
            print(f"[TERMINATE] {status}: {summary}")
            history.append({"output": history_output, "image": current_screenshot_path})
            break

        if action_type == "interact":
            user_prompt = action_parameter.get("text", "the required action")
            input(f"[ACTION REQUIRED] Please complete: {user_prompt}\nPress Enter when done...")
            print("[INFO] User action completed. Resuming...")
            history.append({"output": history_output, "image": current_screenshot_path})
            continue

        print(f"[ACTION RAW] {json.dumps(action_parameter, ensure_ascii=False)}")
        width, height = adb_tools.get_display_size()
        try:
            scaled_action_parameter = rescale_coordinates(action_parameter, width, height)
        except Exception as exc:
            print(f"[ERROR] Failed to rescale normalized action coordinates: {exc}")
            history.append({"output": history_output, "image": current_screenshot_path})
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

        history.append({"output": history_output, "image": current_screenshot_path})
        annotate_screenshot(
            current_screenshot_path,
            scaled_action_parameter,
            os.path.join(anno_dir, f"screenshot_anno_{step_id}.png"),
        )
        time.sleep(2)

