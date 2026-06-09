"""Action parsing and execution for Mobile-Agent.

This module converts model text output into predefined actions and executes
those actions via ADB tools.
"""

import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
import unicodedata
import copy
from typing import Any

from PIL import Image, ImageDraw

from app_name_to_package import resolve_package_ids


# ---------------------------------------------------------------------------
# ADB Tools
# ---------------------------------------------------------------------------


class AdbTools:
    """Wrapper around ADB commands for device interaction."""

    def __init__(self, device=None):
        resolved_adb_path = shutil.which("adb")
        if not resolved_adb_path:
            raise SystemExit("Missing adb executable in system PATH.")
        if not os.path.exists(resolved_adb_path):
            raise SystemExit(f"Resolved adb path does not exist: {resolved_adb_path}")

        self.adb_path = resolved_adb_path
        self.device = device
        self._device_flag = f" -s {device} " if device is not None else " "
        self.image_info = None

    def _run(self, args):
        """Run an ADB command string."""
        cmd = self.adb_path + self._device_flag + args
        return subprocess.run(cmd, capture_output=True, text=True, shell=True)

    def _run_args(self, args):
        """Run an ADB command with argv args to avoid shell quoting issues."""
        cmd = [self.adb_path]
        if self.device:
            cmd.extend(["-s", self.device])
        cmd.extend(args)
        return subprocess.run(cmd, capture_output=True, text=True, check=False)

    def _load_image_info(self, path):
        """Cache the width and height of the screenshot."""
        width, height = Image.open(path).size
        self.image_info = (width, height)

    def get_screenshot(self, image_path, retry_times=3, timeout_seconds=8):
        """Capture screenshot and save to image_path."""
        # self._run("shell input keyevent KEYCODE_WAKEUP")
        # time.sleep(0.3)

        cmd = [self.adb_path]
        if self.device:
            cmd.extend(["-s", self.device])
        cmd.extend(["exec-out", "screencap", "-p"])

        for attempt in range(1, retry_times + 1):
            if os.path.exists(image_path):
                os.remove(image_path)
            try:
                res = subprocess.run(
                    cmd,
                    capture_output=True,
                    check=False,
                    timeout=timeout_seconds,
                )
            except subprocess.TimeoutExpired:
                print(
                    "[WARN] Screenshot capture timed out "
                    f"after {timeout_seconds}s on attempt {attempt}/{retry_times}."
                )
                time.sleep(0.3)
                continue

            if res.returncode == 0 and res.stdout:
                with open(image_path, "wb") as f:
                    f.write(res.stdout)
            if os.path.exists(image_path) and os.path.getsize(image_path) > 0:
                self._load_image_info(image_path)
                return True
            stderr = (res.stderr or b"").decode("utf-8", errors="replace").strip()
            if stderr:
                print(
                    "[WARN] Screenshot capture failed "
                    f"on attempt {attempt}/{retry_times}: {stderr}"
                )
            time.sleep(0.1)
        return False

    def dump_ui_hierarchy(
        self,
        output_path,
        retry_times=3,
        retry_delay_seconds=1,
        compressed=False,
    ):
        output_path = os.fspath(output_path)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        remote_name = f"window_dump_{int(time.time() * 1000)}.xml"
        remote_path = f"/sdcard/{remote_name}"
        dump_args = ["shell", "uiautomator", "dump"]
        if compressed:
            dump_args.append("--compressed")
        dump_args.append(remote_path)

        dump_succeeded = False
        for attempt in range(1, retry_times + 1):
            self._run_args(["shell", "input", "keyevent", "KEYCODE_WAKEUP"])
            time.sleep(0.3)
            dump_result = self._run_args(dump_args)
            dump_output = f"{dump_result.stdout}\n{dump_result.stderr}".strip()
            if dump_output:
                print(f"[UI XML] dump attempt {attempt}/{retry_times}: {dump_output}")
            ls_result = self._run_args(["shell", "ls", remote_path])
            remote_exists = ls_result.returncode == 0 and "No such file or directory" not in (
                f"{ls_result.stdout}\n{ls_result.stderr}"
            )
            if dump_result.returncode == 0 and remote_exists:
                dump_succeeded = True
                break
            if attempt < retry_times:
                time.sleep(retry_delay_seconds)

        if not dump_succeeded:
            print(f"[WARN] uiautomator dump failed after {retry_times} attempts: {remote_path}")
            return False

        temp_dir = tempfile.mkdtemp(prefix="ui_dump_")
        try:
            pull_result = self._run_args(["pull", remote_path, temp_dir])
            if pull_result.returncode != 0:
                print(f"[WARN] adb pull failed: {pull_result.stderr.strip()}")
                return False
            pulled_path = os.path.join(temp_dir, remote_name)
            if not os.path.exists(pulled_path):
                print(f"[WARN] Pulled XML file missing: {pulled_path}")
                return False
            shutil.move(pulled_path, output_path)
            return True
        finally:
            self._run_args(["shell", "rm", remote_path])
            shutil.rmtree(temp_dir, ignore_errors=True)

    def click(self, x, y):
        self._run(f"shell input tap {x} {y}")

    def long_press(self, x, y, duration=800):
        self._run(f"shell input swipe {x} {y} {x} {y} {duration}")

    def slide(self, x1, y1, x2, y2, slide_time=800):
        self._run(f"shell input swipe {x1} {y1} {x2} {y2} {slide_time}")

    def back(self):
        self._run("shell input keyevent 4")

    def home(self):
        self._run(
            "shell am start -a android.intent.action.MAIN "
            "-c android.intent.category.HOME"
        )

    def type(self, text):
        if self._type_with_adb_keyboard(text):
            return

        print("[WARN] ADB Keyboard input failed; falling back to clipboard paste.")
        if self._type_with_clipboard(text):
            return

        print("[WARN] Clipboard paste failed; falling back to adb shell input text.")
        safe_text = self._adb_input_text_safe(text)
        self._run_args(["shell", "input", "text", safe_text])

    def _adb_input_text_safe(self, text):
        ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
        if ascii_text:
            return ascii_text.replace(" ", "%s")
        return text.replace(" ", "%s")

    def _type_with_adb_keyboard(self, text):
        adb_ime = "com.android.adbkeyboard/.AdbIME"
        ime_list = self._run_args(["shell", "ime", "list", "-a"])
        if adb_ime not in ime_list.stdout:
            return False

        current_ime = self._run_args(["shell", "settings", "get", "secure", "default_input_method"]).stdout.strip()

        self._run_args(["shell", "ime", "enable", adb_ime])
        set_result = self._run_args(["shell", "ime", "set", adb_ime])
        if set_result.returncode != 0:
            print(f"[WARN] Failed to switch to ADB Keyboard: {set_result.stderr.strip()}")
            return False

        time.sleep(0.5)
        self._run_args(["shell", "am", "broadcast", "-a", "ADB_CLEAR_TEXT"])
        time.sleep(0.2)
        broadcast = self._run_args(
            ["shell", "am", "broadcast", "-a", "ADB_INPUT_TEXT", "--es", "msg", text]
        )
        time.sleep(0.8)

        if current_ime and current_ime != adb_ime:
            self._run_args(["shell", "ime", "set", current_ime])

        if broadcast.returncode != 0:
            print(f"[WARN] ADB Keyboard broadcast failed: {broadcast.stderr.strip()}")
            return False
        return True

    def _type_with_clipboard(self, text):
        set_clipboard = self._run_args(["shell", "cmd", "clipboard", "set", "text", text])
        clipboard_output = f"{set_clipboard.stdout}\n{set_clipboard.stderr}".strip()
        if set_clipboard.returncode != 0 or "No shell command implementation" in clipboard_output:
            print(f"[WARN] Clipboard set failed: {clipboard_output}")
            return False
        time.sleep(0.2)
        paste = self._run_args(["shell", "input", "keyevent", "KEYCODE_PASTE"])
        time.sleep(0.5)
        return paste.returncode == 0

    def get_package_name(self, all_packages=False):
        try:
            flag = "" if all_packages else " -3"
            cmd = f"{self.adb_path}{self._device_flag}shell pm list packages{flag}"
            res = subprocess.run(cmd, capture_output=True, text=True, shell=True)
            pkgs = []
            for line in res.stdout.splitlines():
                s = line.strip()
                if not s:
                    continue
                if s.startswith("package:"):
                    s = s[len("package:"):]
                if "=" in s:
                    _, s = s.split("=", 1)
                if s:
                    pkgs.append(s)
            return sorted(set(pkgs))
        except Exception as e:
            print(f"[ERROR] Failed to list packages: {e}")
            return []

    def open_app(self, package_name):
        self._run(
            f"shell monkey -p {package_name} "
            "-c android.intent.category.LAUNCHER 1"
        )

    def get_display_size(self) -> tuple[int, int]:
        result = self._run_args(["shell", "wm", "size"])
        if result.returncode != 0:
            raise RuntimeError(
                "Failed to query display size with `adb shell wm size`: "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )
        output = f"{result.stdout}\n{result.stderr}"
        match = re.search(r"Override size:\s*(\d+)x(\d+)", output)
        if not match:
            match = re.search(r"Physical size:\s*(\d+)x(\d+)", output)
        if not match:
            raise RuntimeError(
                "Could not parse display size from `adb shell wm size` output: "
                f"{output.strip()}"
            )
        return int(match.group(1)), int(match.group(2))

    def get_device_state(self) -> dict[str, bool]:
        power_result = self._run_args(["shell", "dumpsys", "power"])
        power_output = f"{power_result.stdout}\n{power_result.stderr}"
        power_output_lower = power_output.lower()

        window_result = self._run_args(["shell", "dumpsys", "window"])
        window_output = f"{window_result.stdout}\n{window_result.stderr}"
        window_output_lower = window_output.lower()

        policy_result = self._run_args(["shell", "dumpsys", "window", "policy"])
        policy_output = f"{policy_result.stdout}\n{policy_result.stderr}"
        policy_output_lower = policy_output.lower()

        screen_on = (
            "mwakefulness=awake" in power_output_lower
            or "display power: state=on" in power_output_lower
            or "display power state=on" in power_output_lower
        )

        lock_markers = [
            "mdreaminglockscreen=true",
            "isstatusbarkeyguard=true",
            "mshowinglockscreen=true",
            "mkeyguardshowing=true",
            "keyguardshowing=true",
        ]
        locked = any(marker in window_output_lower for marker in lock_markers) or any(
            marker in policy_output_lower for marker in lock_markers
        )

        return {
            "screen_on": screen_on,
            "locked": locked,
        }

    def wake_if_needed(self) -> None:
        state = self.get_device_state()
        if state["screen_on"]:
            return
        self._run_args(["shell", "input", "keyevent", "KEYCODE_WAKEUP"])
        time.sleep(0.6)

    def unlock_if_needed(self, max_attempts: int = 3) -> bool:
        width, height = self.get_display_size()
        x = width // 2
        start_y = int(height * 0.86)
        end_y = int(height * 0.25)

        for _ in range(max_attempts):
            state = self.get_device_state()
            if not state["locked"]:
                return True
            self._run_args(
                [
                    "shell",
                    "input",
                    "swipe",
                    str(x),
                    str(start_y),
                    str(x),
                    str(end_y),
                    "450",
                ]
            )
            time.sleep(0.8)

        return not self.get_device_state()["locked"]

    def go_home_default_page(self) -> None:
        self.home()
        time.sleep(0.4)
        self.home()
        time.sleep(0.6)


def annotate_screenshot(image_path, action_parameter, save_path="screenshot_anno.png"):
    """Render action visualization on a screenshot for debugging artifacts.

    Supported actions:
    - click: draw a red dot centered at `coordinate`
    - scroll/swipe: draw a red arrow from `coordinate` to `coordinate2`

    Coordinates are expected to be absolute device pixel coordinates.
    Returns the saved annotation path on success, or None for unsupported actions.
    """
    image = Image.open(image_path)
    draw = ImageDraw.Draw(image)

    action_type = action_parameter.get("action", "")

    if action_type == "click":
        radius = 15
        cx, cy = action_parameter["coordinate"]
        draw.ellipse(
            (cx - radius, cy - radius, cx + radius, cy + radius),
            fill="red",
            outline="red",
        )
    elif action_type in ("scroll", "swipe"):
        x1, y1 = action_parameter["coordinate"]
        x2, y2 = action_parameter["coordinate2"]
        color = "red"
        arrow_size = 10

        draw.line((x1, y1, x2, y2), fill=color, width=2)

        angle = math.atan2(y2 - y1, x2 - x1)
        ax1 = x2 - arrow_size * math.cos(angle - math.pi / 6)
        ay1 = y2 - arrow_size * math.sin(angle - math.pi / 6)
        ax2 = x2 - arrow_size * math.cos(angle + math.pi / 6)
        ay2 = y2 - arrow_size * math.sin(angle + math.pi / 6)
        draw.polygon([(x2, y2), (ax1, ay1), (ax2, ay2)], fill=color)
    else:
        return None

    image.save(save_path)
    return save_path


def _validate_normalized_coordinate(value: Any, key: str) -> tuple[float, float]:
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 2
        or not all(isinstance(item, (int, float)) for item in value)
    ):
        raise ValueError(f"{key} must be a two-number normalized coordinate: {value}")

    x, y = float(value[0]), float(value[1])
    if not (0 <= x <= 1000 and 0 <= y <= 1000):
        raise ValueError(
            f"{key} is outside normalized 0-1000 coordinate space: {value}"
        )
    return x, y


def rescale_coordinates(
    action_parameter: dict[str, Any],
    width: int,
    height: int,
) -> dict[str, Any]:
    """Scale normalized 0-1000 action coordinates to screen pixels.

    This follows the Qwen/GUI-Owl convention: model outputs are normalized
    relative coordinates, while ADB actions require absolute device pixels.
    """
    scaled_action = copy.deepcopy(action_parameter)
    action_type = scaled_action.get("action")

    if action_type in {"click", "long_press", "swipe"}:
        x, y = _validate_normalized_coordinate(
            scaled_action.get("coordinate"),
            "coordinate",
        )
        scaled_action["coordinate"] = [
            int(round(x / 1000 * width)),
            int(round(y / 1000 * height)),
        ]

    if action_type == "swipe":
        x2, y2 = _validate_normalized_coordinate(
            scaled_action.get("coordinate2"),
            "coordinate2",
        )
        scaled_action["coordinate2"] = [
            int(round(x2 / 1000 * width)),
            int(round(y2 / 1000 * height)),
        ]

    return scaled_action


def try_parse_json(text: str):
    if not text:
        return None
    try:
        return json.loads(text.strip())
    except Exception:
        return None


def _append_missing_json_closers(text: str) -> str | None:
    """Repair model JSON that stops before closing all objects/arrays."""
    stack: list[str] = []
    in_string = False
    escaped = False

    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char in "{[":
            stack.append("}" if char == "{" else "]")
        elif char in "}]":
            if not stack or stack[-1] != char:
                return None
            stack.pop()

    if in_string or not stack:
        return None
    return text.rstrip() + "".join(reversed(stack))


def extract_json_payload(text: str):
    """Extract the current prompt's <tool_call> JSON payload."""
    if not text or "<tool_call>" not in text:
        return None

    block = text.split("<tool_call>", 1)[1]
    block = block.split("</tool_call>", 1)[0].strip()
    parsed = try_parse_json(block)
    if parsed is not None:
        return parsed

    repaired = _append_missing_json_closers(block)
    return try_parse_json(repaired) if repaired else None


def _extract_note_summaries(data: Any) -> list[dict[str, Any]]:
    records = data.get("notes") if isinstance(data, dict) and isinstance(data.get("notes"), list) else None
    if records is None:
        # Support the wrapper format: {"note_detail": {...}} or {"notes_collected": N, "note_detail": {...}}
        note_detail = data.get("note_detail") if isinstance(data, dict) else None
        records = [note_detail] if isinstance(note_detail, dict) else [data]

    summaries = []
    for record in records:
        if not isinstance(record, dict):
            continue
        summaries.append({
            "note_title": record.get("note_title"),
            "author_name": record.get("author_name"),
            "is_video": record.get("is_video"),
        })
    return summaries


def _note_identity(record: Any) -> str | None:
    if not isinstance(record, dict):
        return None
    title = str(record.get("note_title") or "").strip()
    author = str(record.get("author_name") or "").strip()
    if not title:
        text = str(record.get("note_text") or "").strip()
        title = text.splitlines()[0].strip() if text else ""
    author_key = re.sub(r"[（(].*?[）)]", "", author)
    author_key = re.sub(r"[^\w\u4e00-\u9fff]+", "", author_key.lower())
    title_key = re.sub(r"[^\w\u4e00-\u9fff]+", "", title.lower())
    identity = f"{author_key}\n{title_key}".strip()
    return identity or None


def _is_duplicate_note_identity(identity: str | None, existing_identities: set[str]) -> bool:
    if not identity:
        return False
    if identity in existing_identities:
        return True

    try:
        author, title = identity.split("\n", 1)
    except ValueError:
        return False
    if len(title) < 8:
        return False

    for existing_identity in existing_identities:
        try:
            existing_author, existing_title = existing_identity.split("\n", 1)
        except ValueError:
            continue
        if author != existing_author or len(existing_title) < 8:
            continue
        if title in existing_title or existing_title in title:
            return True
    return False


def _load_existing_note_identities(output_path: str) -> set[str]:
    identities: set[str] = set()
    if not os.path.exists(output_path):
        return identities

    with open(output_path, "r", encoding="utf-8") as output_file:
        for line in output_file:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            record = payload.get("data") if isinstance(payload, dict) else payload
            identity = _note_identity(record)
            if identity:
                identities.add(identity)
    return identities


def append_extract_output(
    output_path: str,
    step_id: int,
    action_parameter: dict[str, Any],
    summary: str | None = None,
) -> None:
    """Append extracted note records as JSONL.

    If the model returns a crawler-style payload containing `notes`, each new
    note is written as its own line. Repeated notes are skipped because some
    models return a cumulative notes list on each extract turn.
    """
    data = action_parameter.get("data")
    records = data.get("notes") if isinstance(data, dict) and isinstance(data.get("notes"), list) else None
    if not records:
        records = [data]

    existing_identities = _load_existing_note_identities(output_path)
    seen_this_turn: set[str] = set()

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "a", encoding="utf-8") as output_file:
        for index, record in enumerate(records):
            identity = _note_identity(record)
            if (
                identity
                and (
                    _is_duplicate_note_identity(identity, existing_identities)
                    or _is_duplicate_note_identity(identity, seen_this_turn)
                )
            ):
                print(f"[EXTRACT SKIPPED] duplicate note at record_index={index}")
                continue
            if identity:
                seen_this_turn.add(identity)
            line_payload = {
                "step": step_id,
                "summary": summary or action_parameter.get("summary"),
                "record_index": index,
                "data": record,
            }
            output_file.write(json.dumps(line_payload, ensure_ascii=False) + "\n")


def parse_action(tool_call: dict[str, Any]) -> dict[str, Any]:
    """Validate a current-prompt mobile_use tool-call payload."""
    if not isinstance(tool_call, dict):
        raise ValueError(f"tool_call must be an object: {tool_call}")

    if tool_call.get("name") != "mobile_use":
        raise ValueError(f"Unexpected tool name: {tool_call}")
    if "arguments" not in tool_call:
        raise ValueError(f"tool_call has no arguments: {tool_call}")
    if not isinstance(tool_call["arguments"], dict):
        raise ValueError(f"tool_call arguments must be an object: {tool_call}")
    return {
        "name": "mobile_use",
        "arguments": tool_call["arguments"],
    }


def _summary_from_output_text(output_text: str) -> str:
    if not output_text:
        return ""
    before_tool_call = output_text.split("<tool_call>", 1)[0].strip()
    if before_tool_call.lower().startswith("action:"):
        before_tool_call = before_tool_call.split(":", 1)[1].strip()
    return before_tool_call


def format_turn_response(response: dict[str, Any]) -> str:
    """Render a parsed response in the current system-prompt response schema."""
    tool_call = parse_action(response.get("tool_call"))
    arguments = tool_call["arguments"]
    if arguments.get("action") == "extract" and isinstance(arguments.get("data"), dict):
        arguments = copy.deepcopy(arguments)
        arguments["data"] = {
            "notes": _extract_note_summaries(arguments["data"]),
        }
        tool_call = {
            "name": "mobile_use",
            "arguments": arguments,
        }
    summary = response.get("summary") or arguments.get("summary") or f"Run mobile action: {arguments.get('action')}"
    return (
        f"Action: {summary}\n"
        "<tool_call>\n"
        f"{json.dumps(tool_call, ensure_ascii=False)}\n"
        "</tool_call>"
    )


def parse_turn_response(output_text: str) -> dict[str, Any]:
    payload = extract_json_payload(output_text)
    if not isinstance(payload, dict):
        raise ValueError(f"No <tool_call> JSON object found in model output: {output_text}")

    tool_call = parse_action(payload)
    arguments = tool_call["arguments"]

    action = arguments.get("action")
    if not isinstance(action, str) or not action:
        raise ValueError(f"tool_call arguments missing action: {tool_call}")
    summary = arguments.get("summary") or _summary_from_output_text(output_text)

    if action == "extract" and not isinstance(arguments.get("data"), dict):
        raise ValueError(f"Extract action missing data object: {tool_call}")

    if action == "terminate":
        status = arguments.get("status")
        if status not in {"success", "failure"}:
            raise ValueError(f"Terminate action missing valid status: {tool_call}")

    return {
        "summary": summary or f"Run mobile action: {action}",
        "tool_call": tool_call,
    }


def summarize_history_output(text: str) -> str:
    """Summarize prior assistant output using the shared response parser."""
    try:
        response = parse_turn_response(text)
    except Exception:
        if text and "<tool_call>" in text:
            return text.split("<tool_call>", 1)[0].strip()
        return (text or "").strip()

    tool_call = parse_action(response.get("tool_call"))
    arguments = tool_call["arguments"]
    action = arguments.get("action", "unknown")
    if action == "extract":
        return response.get("summary") or arguments.get("summary") or "Extracted target page data"
    if action == "terminate":
        status = arguments.get("status", "unknown")
        summary = response.get("summary") or arguments.get("summary") or "Terminated"
        return f"Terminate ({status}): {summary}"
    return response.get("summary") or f"Action {action}: {json.dumps(arguments, ensure_ascii=False)}"


def handle_open_action(
    action_parameter: dict[str, Any],
    adb_tools: AdbTools,
):
    app_name = action_parameter.get("text", "")
    package_candidates = resolve_package_ids(app_name)
    if not package_candidates:
        print(f"[WARN] No package mapping found for app: {app_name}")
        return False

    installed_packages = adb_tools.get_package_name()

    for pkg in package_candidates:
        if pkg in installed_packages:
            adb_tools.open_app(pkg)
            return True

    print(f"[WARN] App mapped but not installed on device: {app_name} -> {package_candidates}")
    return False

def execute_action(
    action_parameter: dict[str, Any],
    adb_tools: AdbTools,
) -> None:
    """Execute one device action."""
    action_type = action_parameter["action"]

    if action_type == "click":
        adb_tools.click(*action_parameter["coordinate"])
    elif action_type == "long_press":
        duration = int(float(action_parameter.get("time", 1)) * 1000)
        adb_tools.long_press(*action_parameter["coordinate"], duration=duration)
    elif action_type == "type":
        adb_tools.type(action_parameter["text"])
        if action_parameter["text"]:
            time.sleep(0.5)
            adb_tools._run("shell input keyevent 66")
    elif action_type in ("scroll", "swipe"):
        adb_tools.slide(
            action_parameter["coordinate"][0],
            action_parameter["coordinate"][1],
            action_parameter["coordinate2"][0],
            action_parameter["coordinate2"][1],
        )
    elif action_type == "system_button":
        button = action_parameter["button"]
        if button == "Back":
            adb_tools.back()
        elif button == "Home":
            adb_tools.home()
        elif button == "Enter":
            adb_tools._run("shell input keyevent 66")
        elif button == "Menu":
            adb_tools._run("shell input keyevent KEYCODE_APP_SWITCH")
    elif action_type == "key":
        adb_tools._run(f"shell input keyevent {action_parameter['text']}")
    elif action_type == "wait":
        time.sleep(float(action_parameter.get("time", 2)))
    elif action_type == "open":
        opened = handle_open_action(
            action_parameter,
            adb_tools,
        )
        if not opened:
            print("[WARN] Open action was not executed successfully.")
    else:
        print(f"[WARN] Unsupported action type: {action_type}")
