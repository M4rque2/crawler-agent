"""Build per-turn LLM context for the GUI agent."""

import json
import os
from typing import Any


def _extract_item_records(data: Any) -> list[dict[str, Any]]:
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
            for record in _extract_item_records(payload.get("data")):
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
