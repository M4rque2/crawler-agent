"""Screenshot-only smoke tests for the mobile GUI action space.

The smoke runner deliberately shares the production prompt construction and
response parser, but never creates an ADB client or executes a device action.
Each scenario supplies an immutable screenshot and a small action oracle.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from PIL import Image

from agent_io import format_turn_response, parse_turn_response
from context_manager import build_messages, load_task_prompt_arg


class SmokeScenarioError(RuntimeError):
    """Raised when a smoke scenario or its fixture is invalid."""


@dataclass(frozen=True)
class SmokeScenario:
    scenario_path: Path
    task_id: str
    task_prompt: list[dict[str, str]]
    image_path: Path
    width: int
    height: int
    max_turns: int
    oracle: dict[str, Any]


def _normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value))
    return " ".join(text.split()).casefold()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SmokeScenarioError(f"Cannot read scenario JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SmokeScenarioError(f"Scenario must be a JSON object: {path}")
    return value


def _inside_rect(x: float, y: float, rect: list[Any]) -> bool:
    if len(rect) != 4:
        return False
    left, top, right, bottom = (float(item) for item in rect)
    return left <= x <= right and top <= y <= bottom


def _normalized_click_in_rect(
    coordinate: Any,
    rect_px: list[Any],
    width: int,
    height: int,
) -> bool:
    if not isinstance(coordinate, (list, tuple)) or len(coordinate) != 2:
        return False
    try:
        x_norm, y_norm = float(coordinate[0]), float(coordinate[1])
    except (TypeError, ValueError):
        return False
    if not (0 <= x_norm <= 1000 and 0 <= y_norm <= 1000):
        return False
    return _inside_rect(x_norm * width / 1000, y_norm * height / 1000, rect_px)


def _action_arguments(parsed: dict[str, Any]) -> dict[str, Any]:
    tool_call = parsed.get("tool_call")
    if not isinstance(tool_call, dict):
        return {}
    arguments = tool_call.get("arguments")
    return arguments if isinstance(arguments, dict) else {}


def _subset_matches(actual: Any, expected: Any) -> bool:
    """Match the required extraction subset while allowing extra fields."""
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False
        return all(key in actual and _subset_matches(actual[key], value) for key, value in expected.items())
    if isinstance(expected, str):
        return _normalize_text(actual) == _normalize_text(expected)
    return actual == expected


def _back_mechanism(arguments: dict[str, Any], scenario: SmokeScenario) -> str | None:
    action = arguments.get("action")
    if action == "system_button" and _normalize_text(arguments.get("button")) == "back":
        return "system_button"
    if action == "click" and _normalized_click_in_rect(
        arguments.get("coordinate"),
        scenario.oracle["back_click_region_px"],
        scenario.width,
        scenario.height,
    ):
        return "click"
    return None


def _result(
    scenario: SmokeScenario,
    *,
    passed: bool,
    turns: int,
    actions: list[dict[str, Any]],
    failure_category: str | None = None,
    message: str = "",
) -> dict[str, Any]:
    return {
        "task": scenario.task_id,
        "passed": passed,
        "verdict": "passed" if passed else "failed",
        "turns": turns,
        "actions": actions,
        "failure_category": failure_category,
        "message": message,
    }


def load_scenario(scenario_path: str | Path) -> SmokeScenario:
    path = Path(scenario_path).resolve()
    payload = _read_json(path)
    if payload.get("version") != 1:
        raise SmokeScenarioError(f"Unsupported scenario version in {path}")

    task_id = payload.get("id")
    task_prompt_name = payload.get("task_prompt")
    fixture = payload.get("fixture")
    oracle = payload.get("oracle")
    max_turns = payload.get("max_turns")
    if not isinstance(task_id, str) or not task_id:
        raise SmokeScenarioError(f"Scenario id is missing: {path}")
    if not isinstance(task_prompt_name, str):
        raise SmokeScenarioError(f"Scenario task_prompt is missing: {path}")
    if not isinstance(fixture, dict) or not isinstance(oracle, dict):
        raise SmokeScenarioError(f"Scenario fixture/oracle must be objects: {path}")
    if not isinstance(max_turns, int) or max_turns < 1:
        raise SmokeScenarioError(f"Scenario max_turns must be positive: {path}")

    image_path = (path.parent / str(fixture.get("image", ""))).resolve()
    prompt_path = (path.parent / task_prompt_name).resolve()
    if not image_path.is_file():
        raise SmokeScenarioError(f"Fixture image not found: {image_path}")
    if not prompt_path.is_file():
        raise SmokeScenarioError(f"Task prompt not found: {prompt_path}")

    try:
        with Image.open(image_path) as image:
            actual_width, actual_height = image.size
            image.verify()
    except Exception as exc:
        raise SmokeScenarioError(f"Invalid fixture image {image_path}: {exc}") from exc

    try:
        width = int(fixture["width"])
        height = int(fixture["height"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SmokeScenarioError(f"Fixture width/height are invalid: {path}") from exc
    if (actual_width, actual_height) != (width, height):
        raise SmokeScenarioError(
            f"Fixture dimensions changed for {image_path}: "
            f"manifest={width}x{height}, actual={actual_width}x{actual_height}"
        )

    expected_hash = str(fixture.get("sha256", "")).lower()
    actual_hash = hashlib.sha256(image_path.read_bytes()).hexdigest()
    if not expected_hash or actual_hash != expected_hash:
        raise SmokeScenarioError(
            f"Fixture checksum mismatch for {image_path}: "
            f"manifest={expected_hash}, actual={actual_hash}"
        )

    task_prompt = load_task_prompt_arg("", str(prompt_path))
    kind = oracle.get("kind")
    if kind not in {"open_or_click", "extract", "lag_back"}:
        raise SmokeScenarioError(f"Unsupported smoke oracle kind {kind!r}: {path}")
    if kind == "open_or_click":
        if not isinstance(oracle.get("package_id"), str) or not isinstance(oracle.get("accepted_names"), list):
            raise SmokeScenarioError(f"Open oracle is incomplete: {path}")
        if not isinstance(oracle.get("click_region_px"), list):
            raise SmokeScenarioError(f"Open click region is missing: {path}")
    elif kind == "extract" and not isinstance(oracle.get("expected"), dict):
        raise SmokeScenarioError(f"Extract oracle expected object is missing: {path}")
    elif kind == "lag_back" and not isinstance(oracle.get("back_click_region_px"), list):
        raise SmokeScenarioError(f"Lag back click region is missing: {path}")

    return SmokeScenario(
        scenario_path=path,
        task_id=task_id,
        task_prompt=task_prompt,
        image_path=image_path,
        width=width,
        height=height,
        max_turns=max_turns,
        oracle=oracle,
    )


def _build_turn_messages(
    scenario: SmokeScenario,
    system_prompt: str,
    history: list[dict[str, Any]],
    previous_expectation: str | None,
) -> list[dict[str, Any]]:
    return build_messages(
        str(scenario.image_path),
        system_prompt,
        scenario.task_prompt,
        history,
        history_n=6,
        feedback=None,
        collection_memory=None,
        previous_expectation=previous_expectation,
    )


def _check_single_turn(scenario: SmokeScenario, arguments: dict[str, Any]) -> tuple[bool, str]:
    kind = scenario.oracle["kind"]
    if kind == "open_or_click":
        action = arguments.get("action")
        if action == "open":
            accepted = {_normalize_text(item) for item in scenario.oracle["accepted_names"]}
            if _normalize_text(arguments.get("text")) in accepted:
                return True, "open action matched accepted app name"
            return False, "open action used an unrecognized app name"
        if action == "click" and _normalized_click_in_rect(
            arguments.get("coordinate"),
            scenario.oracle["click_region_px"],
            scenario.width,
            scenario.height,
        ):
            return True, "click coordinate landed inside the Weibo launcher bounds"
        return False, "expected open(com.sina.weibo) or a click inside the Weibo icon bounds"

    if kind == "extract":
        if arguments.get("action") != "extract":
            return False, "expected action=extract"
        if not _subset_matches(arguments.get("data"), scenario.oracle["expected"]):
            return False, "extracted data did not match the required subset"
        return True, "required extraction fields matched"

    return False, f"unsupported single-turn oracle: {kind}"


def _check_lag_turn(
    scenario: SmokeScenario,
    turn: int,
    arguments: dict[str, Any],
    previous_mechanism: str | None,
) -> tuple[bool, str, str | None, bool]:
    mechanism = _back_mechanism(arguments, scenario)
    if turn <= 3:
        if mechanism is None:
            return False, "expected a Back system button or a click on the visible Back button", mechanism, False
        if turn == 1:
            return True, f"first Back attempt used {mechanism}", mechanism, False
        if turn == 2 and mechanism != previous_mechanism:
            return False, "second attempt must retry the same Back mechanism once", mechanism, False
        if turn == 3 and mechanism == previous_mechanism:
            return False, "third attempt must switch to the alternative Back mechanism", mechanism, False
        return True, f"Back attempt {turn} used {mechanism}", mechanism, False

    action = arguments.get("action")
    if action == "interact" and str(arguments.get("text", "")).strip():
        return True, "escalated to human interaction after three failed Back attempts", mechanism, True
    if action == "terminate" and _normalize_text(arguments.get("status")) == "failure":
        return True, "terminated with failure after three failed Back attempts", mechanism, True
    return False, "after three failed Back attempts, expected interact or terminate(failure)", mechanism, False


def run_scenario(
    scenario: SmokeScenario,
    system_prompt: str,
    vlm: Any,
    *,
    on_turn: Callable[[int, str], None] | None = None,
) -> dict[str, Any]:
    """Run one screenshot-only scenario against a supplied model client."""
    history: list[dict[str, Any]] = []
    previous_expectation: str | None = None
    actions: list[dict[str, Any]] = []
    previous_mechanism: str | None = None

    for turn in range(1, scenario.max_turns + 1):
        messages = _build_turn_messages(scenario, system_prompt, history, previous_expectation)
        try:
            output_text, _, _ = vlm.invoke(messages)
        except Exception as exc:
            return _result(
                scenario,
                passed=False,
                turns=turn,
                actions=actions,
                failure_category="infrastructure",
                message=f"LLM invocation failed: {exc}",
            )
        if on_turn:
            on_turn(turn, output_text)

        try:
            response = parse_turn_response(output_text)
        except Exception as exc:
            return _result(
                scenario,
                passed=False,
                turns=turn,
                actions=actions,
                failure_category="model_protocol",
                message=f"Could not parse model tool call: {exc}",
            )

        arguments = _action_arguments(response)
        action_record = {
            "turn": turn,
            "action": arguments.get("action"),
            "arguments": arguments,
        }
        actions.append(action_record)
        history.append({
            "output": format_turn_response(response),
            "image": str(scenario.image_path),
            "previous_expectation": previous_expectation,
        })
        previous_expectation = response.get("expectation") or None

        if scenario.oracle["kind"] != "lag_back":
            passed, message = _check_single_turn(scenario, arguments)
            return _result(
                scenario,
                passed=passed,
                turns=turn,
                actions=actions,
                failure_category=None if passed else "action_match",
                message=message,
            )

        passed, message, mechanism, terminal = _check_lag_turn(
            scenario, turn, arguments, previous_mechanism
        )
        if not passed:
            return _result(
                scenario,
                passed=False,
                turns=turn,
                actions=actions,
                failure_category="action_match",
                message=message,
            )
        if mechanism is not None:
            previous_mechanism = mechanism
        if terminal:
            return _result(
                scenario,
                passed=True,
                turns=turn,
                actions=actions,
                message=message,
            )

    return _result(
        scenario,
        passed=False,
        turns=scenario.max_turns,
        actions=actions,
        failure_category="task_outcome",
        message="Scenario ended before the required terminal action",
    )


SCENARIO_IDS = ("open_weibo", "extract_wikipedia", "dead_phone_back")


def default_scenario_paths(root: str | Path = "tasks/smoke") -> dict[str, Path]:
    root_path = Path(root).resolve()
    return {
        task_id: root_path / task_id / "scenario.json"
        for task_id in SCENARIO_IDS
    }
