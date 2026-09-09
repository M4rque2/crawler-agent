import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import requests

from llm_client import LLMInvokeError, create_llm_client, load_model_config, parse_streaming_response


def response_with(body):
    response = requests.Response()
    response.status_code = 200
    response._content = body.encode("utf-8")
    response._content_consumed = True
    response.close = Mock()
    return response


def content_event(text):
    return "data: " + json.dumps({"choices": [{"delta": {"content": text}}]}) + "\n\n"


class StreamingResponseTests(unittest.TestCase):
    def test_multiline_events_metadata_reasoning_and_utf8(self):
        response = response_with(
            ': heartbeat\r\n\r\nevent: message\r\nid: 1\r\n'
            'data: {"choices":\r\ndata: [{"delta": {"reasoning_content": "thinking"}}]}\r\n\r\n'
            'data: {"choices": [{"delta": {"content": "地球"}}]}\n\n'
            'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}\n\n'
            'data: {"choices": [], "usage": {"completion_tokens": 10}}\n\n'
            'data: [DONE]\n\n'
        )
        self.assertEqual(parse_streaming_response(response), ("地球", "thinking"))

    def test_missing_completion_marker_rejects_partial_answer(self):
        response = response_with(content_event("partial"))
        with self.assertRaisesRegex(ValueError, "before.*DONE"):
            parse_streaming_response(response)

    def test_unterminated_completion_event_is_not_accepted(self):
        response = response_with(content_event("partial") + "data: [DONE]\n")
        with self.assertRaisesRegex(ValueError, "before.*DONE"):
            parse_streaming_response(response)

    def test_malformed_event_is_not_silently_skipped(self):
        for data in ("{broken", "[]"):
            with self.subTest(data=data), self.assertRaises(ValueError):
                parse_streaming_response(response_with(f"data: {data}\n\ndata: [DONE]\n\n"))

    def test_server_error_after_http_success_is_rejected(self):
        response = response_with('data: {"error": {"message": "generation failed"}}\n\n')
        with self.assertRaisesRegex(ValueError, "generation failed"):
            parse_streaming_response(response)


class StreamingClientTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config_path = Path(self.temp.name) / "model.json"
        # A legacy config must not turn streaming off.
        self.config_path.write_text(json.dumps({
            "base_url": "https://example.invalid/v1",
            "api_key": "test-key",
            "model_name": "test-model",
            "stream": False,
        }))
        self.client = create_llm_client(str(self.config_path), llm_trace_dir=self.temp.name)
        self.messages = [{"role": "user", "content": [{"text": "hello"}]}]

    def test_fixed_streaming_and_retry_discard_partial_response(self):
        partial = response_with(content_event("discard this"))
        complete = response_with(content_event("complete answer") + "data: [DONE]\n\n")
        self.assertNotIn("stream", load_model_config(str(self.config_path)))
        with patch("llm_client.requests.post", side_effect=[partial, complete]) as post, \
                patch("llm_client.time.sleep"), patch("builtins.print"):
            content, _, _ = self.client.invoke(self.messages)
        self.assertEqual(content, "complete answer")
        self.assertEqual(post.call_count, 2)
        for call in post.call_args_list:
            self.assertEqual(call.args[0], "https://example.invalid/v1/chat/completions")
            self.assertEqual(set(call.kwargs["json"]), {"model", "messages", "stream"})
            self.assertIs(call.kwargs["json"]["stream"], True)
            self.assertIs(call.kwargs["stream"], True)
            self.assertEqual(call.kwargs["headers"]["accept"], "text/event-stream")
        partial.close.assert_called_once()
        complete.close.assert_called_once()
        traces = [json.loads(p.read_text()) for p in Path(self.temp.name).glob("llm_trace_*.json")]
        self.assertEqual(sum(trace["error"] is not None for trace in traces), 1)

    def test_failed_stream_exhausts_retries_and_closes_response(self):
        response = response_with(content_event("partial"))
        self.client.max_retry = 1
        with patch("llm_client.requests.post", return_value=response), patch("builtins.print"):
            with self.assertRaises(LLMInvokeError):
                self.client.invoke(self.messages)
        response.close.assert_called_once()

    def test_base_url_preserves_gateway_path_and_handles_trailing_slash(self):
        expected = "https://example.invalid/inference/qwen/model/v1/chat/completions"
        for suffix in ("", "/"):
            with self.subTest(suffix=suffix):
                config = json.loads(self.config_path.read_text())
                config["base_url"] = "https://example.invalid/inference/qwen/model/v1" + suffix
                self.config_path.write_text(json.dumps(config))
                client = create_llm_client(str(self.config_path), llm_trace_dir=self.temp.name)
                response = response_with(content_event("answer") + "data: [DONE]\n\n")
                with patch("llm_client.requests.post", return_value=response) as post:
                    client.invoke(self.messages)
                self.assertEqual(post.call_args.args[0], expected)
                trace = json.loads(max(Path(self.temp.name).glob("llm_trace_*.json")).read_text())
                self.assertEqual(trace["metadata"]["url"], expected)

    def test_explicit_thinking_switch_is_forwarded_and_traced(self):
        for enabled in (True, False):
            with self.subTest(enabled=enabled):
                config = json.loads(self.config_path.read_text())
                config["enable_thinking"] = enabled
                self.config_path.write_text(json.dumps(config))
                client = create_llm_client(str(self.config_path), llm_trace_dir=self.temp.name)
                response = response_with(content_event("answer") + "data: [DONE]\n\n")
                with patch("llm_client.requests.post", return_value=response) as post:
                    client.invoke(self.messages)
                self.assertEqual(post.call_args.kwargs["json"]["chat_template_kwargs"],
                                 {"enable_thinking": enabled})
                trace_path = max(Path(self.temp.name).glob("llm_trace_*.json"))
                trace = json.loads(trace_path.read_text())
                self.assertIs(trace["request"]["chat_template_kwargs"]["enable_thinking"], enabled)

    def test_invalid_thinking_switch_is_rejected(self):
        for value in ("false", "true", 0, 1, None, [], {}):
            with self.subTest(value=value):
                config = json.loads(self.config_path.read_text())
                config["enable_thinking"] = value
                self.config_path.write_text(json.dumps(config))
                with self.assertRaisesRegex(SystemExit, "must be a JSON boolean"):
                    load_model_config(str(self.config_path))
