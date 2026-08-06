import json
import unittest
from pathlib import Path

from app_name_to_package import resolve_package_ids
from smoke_runner import default_scenario_paths, load_scenario, run_scenario


ROOT = Path(__file__).resolve().parents[1]
SYSTEM_PROMPT = (ROOT / "system_prompt.md").read_text(encoding="utf-8").strip()


def _response(arguments: dict, *, expectation: str = "The expected screen will be visible.") -> str:
    return (
        "Expectation Check: unknown - This is the first turn.\n"
        "Action: Perform the requested action.\n"
        f"Expectation: {expectation}\n"
        "<tool_call>\n"
        + json.dumps({"name": "mobile_use", "arguments": arguments}, ensure_ascii=False)
        + "\n</tool_call>"
    )


class FakeVlm:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.messages = []

    def invoke(self, messages):
        self.messages.append(messages)
        return self.outputs.pop(0), None, None


class SmokeRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.paths = default_scenario_paths(ROOT / "tasks" / "smoke")

    def test_fixtures_validate(self):
        for path in self.paths.values():
            scenario = load_scenario(path)
            self.assertEqual((scenario.width, scenario.height), (1080, 2424))

    def test_package_id_and_alias_resolve(self):
        self.assertEqual(resolve_package_ids("com.sina.weibo"), ["com.sina.weibo"])
        self.assertEqual(resolve_package_ids("Weibo"), ["com.sina.weibo"])

    def test_open_accepts_normalized_launcher_click(self):
        scenario = load_scenario(self.paths["open_weibo"])
        fake = FakeVlm([_response({"action": "click", "coordinate": [386, 154]})])
        result = run_scenario(scenario, SYSTEM_PROMPT, fake)
        self.assertTrue(result["passed"])
        self.assertEqual(result["turns"], 1)
        first_user = fake.messages[0][1]
        self.assertEqual(first_user["content"][0]["text"], "Open Weibo app.")
        self.assertFalse(
            any("Collection memory" in item.get("text", "") for item in first_user["content"])
        )

    def test_open_rejects_physical_pixel_coordinates(self):
        scenario = load_scenario(self.paths["open_weibo"])
        fake = FakeVlm([_response({"action": "click", "coordinate": [416, 374]})])
        result = run_scenario(scenario, SYSTEM_PROMPT, fake)
        self.assertFalse(result["passed"])
        self.assertEqual(result["failure_category"], "action_match")

    def test_open_accepts_package_id(self):
        scenario = load_scenario(self.paths["open_weibo"])
        fake = FakeVlm([_response({"action": "open", "text": "com.sina.weibo"})])
        result = run_scenario(scenario, SYSTEM_PROMPT, fake)
        self.assertTrue(result["passed"])

    def test_extract_requires_expected_subset(self):
        scenario = load_scenario(self.paths["extract_wikipedia"])
        fake = FakeVlm([
            _response({
                "action": "extract",
                "data": {
                    "title": "Earth",
                    "description": "Third planet from the Sun",
                    "extra": "allowed",
                },
            })
        ])
        result = run_scenario(scenario, SYSTEM_PROMPT, fake)
        self.assertTrue(result["passed"])

    def test_lag_requires_retry_then_alternative_then_escalation(self):
        scenario = load_scenario(self.paths["dead_phone_back"])
        fake = FakeVlm([
            _response({"action": "system_button", "button": "Back"}),
            _response({"action": "system_button", "button": "Back"}),
            _response({"action": "click", "coordinate": [40, 80]}),
            _response({"action": "interact", "text": "Please check the phone."}),
        ])
        result = run_scenario(scenario, SYSTEM_PROMPT, fake)
        self.assertTrue(result["passed"])
        self.assertEqual(result["turns"], 4)
        image_paths = []
        for messages in fake.messages:
            for message in messages:
                for item in message.get("content", []):
                    if "image" in item:
                        image_paths.append(item["image"])
        self.assertTrue(image_paths)
        self.assertEqual(len(set(image_paths)), 1)

    def test_lag_rejects_early_interact(self):
        scenario = load_scenario(self.paths["dead_phone_back"])
        fake = FakeVlm([_response({"action": "interact", "text": "Help."})])
        result = run_scenario(scenario, SYSTEM_PROMPT, fake)
        self.assertFalse(result["passed"])
        self.assertEqual(result["failure_category"], "action_match")

    def test_lag_rejects_same_mechanism_on_third_attempt(self):
        scenario = load_scenario(self.paths["dead_phone_back"])
        fake = FakeVlm([
            _response({"action": "system_button", "button": "Back"}),
            _response({"action": "system_button", "button": "Back"}),
            _response({"action": "system_button", "button": "Back"}),
        ])
        result = run_scenario(scenario, SYSTEM_PROMPT, fake)
        self.assertFalse(result["passed"])
        self.assertEqual(result["turns"], 3)


if __name__ == "__main__":
    unittest.main()
