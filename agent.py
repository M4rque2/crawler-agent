"""GUI-agent message construction and prompt definitions."""

import copy
import json
import os
import time
from typing import Any

from agent_io import (
    annotate_screenshot,
    append_extract_output,
    execute_action,
    format_turn_response,
    parse_turn_response,
    rescale_coordinates,
)

def _extract_note_records(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    records = data.get("notes") if isinstance(data.get("notes"), list) else None
    if records is None:
        note_detail = data.get("note_detail")
        records = [note_detail] if isinstance(note_detail, dict) else [data]
    return [record for record in records if isinstance(record, dict)]


def build_collection_memory(output_jsonl_path: str, max_items: int = 12) -> str:
    """Summarize collected item identities for the next VLM turn."""
    if not os.path.exists(output_jsonl_path):
        return (
            "Collection memory:\n"
            "Collected items so far: 0.\n"
            "After returning to the source/list screen, choose an unseen visible item."
        )

    items: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    with open(output_jsonl_path, "r", encoding="utf-8") as output_file:
        for line in output_file:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            for record in _extract_note_records(payload.get("data")):
                title = str(record.get("note_title") or record.get("note_text") or "").strip()
                author = str(record.get("author_name") or "").strip()
                identity = (title, author)
                if identity in seen:
                    continue
                seen.add(identity)
                items.append(identity)

    if not items:
        return (
            "Collection memory:\n"
            "Collected items so far: 0.\n"
            "After returning to the source/list screen, choose an unseen visible item."
        )

    listed_items = items[-max_items:]
    lines = [
        "Collection memory:",
        f"Collected items so far: {len(items)}.",
        "Already collected; do not reopen or extract these items:",
    ]
    for index, (title, author) in enumerate(listed_items, start=1):
        label = title or "(missing title)"
        if author:
            label = f"{label} - {author}"
        lines.append(f"{index}. {label}")
    lines.append(
        "If the source/list screen's visible items are already collected or recently attempted, scroll to reveal more unseen items."
    )
    return "\n".join(lines)


def build_messages(
    image_path,
    system_prompt,
    task_prompt,
    history_output,
    history_n=6,
    reference_image_path=None,
    reference_text=None,
    feedback=None,
    collection_memory=None,
    previous_expectation=None,
):
    """Construct multi-turn messages for the VLM."""
    turn_instruction = (
        "Decide the next mobile action from the current screenshot.\n"
        "First compare the previous expectation with the current screenshot.\n"
        "Output exactly these 4 parts and nothing else:\n"
        "Expectation Check: <fulfilled | not_fulfilled | unknown> - <brief reason>\n"
        "Action: <one short imperative sentence>\n"
        "Expectation: <one short sentence describing the expected next screenshot/page after the action>\n"
        "<tool_call>\n"
        "{\"name\": \"mobile_use\", \"arguments\": { ... }}\n"
        "</tool_call>"
    )
    if reference_image_path:
        reference_prompt = reference_text or "Use the reference image to recognize the target UI region on the current screenshot."
        turn_instruction = (
            f"{turn_instruction}\n\n"
            f"Reference image guidance: {reference_prompt}\n"
            f"The first image is the reference image. The last image is the current screenshot."
        )

    turn_text_parts = [{"text": turn_instruction}]
    turn_text_parts.append({
        "text": (
            "Previous expectation:\n"
            f"{previous_expectation or 'None. Use Expectation Check: unknown.'}"
        )
    })
    if collection_memory:
        turn_text_parts.append({"text": collection_memory})

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
                first_turn_content = [{"text": task_prompt}, *turn_text_parts]
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
                    "content": [*turn_text_parts, {"image": "file://" + item["image"]}],
                })
            messages.append({
                "role": "assistant",
                "content": [{"text": item["output"]}],
            })
        messages.append({
            "role": "user",
            "content": (
                [*turn_text_parts, {"text": feedback}]
                if feedback is not None
                else [*turn_text_parts, {"image": "file://" + image_path}]
            ),
        })
    else:
        first_turn_content = [{"text": task_prompt}, *turn_text_parts]
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

        messages = build_messages(
            current_screenshot_path,
            system_prompt,
            task_prompt,
            history,
            history_n=history_n,
            feedback=feedback,
            collection_memory=build_collection_memory(output_jsonl_path),
            previous_expectation=last_expectation,
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

