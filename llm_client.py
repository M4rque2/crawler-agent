"""LLM client and request/response helpers for OpenAI-compatible endpoints."""

from __future__ import annotations

import base64
import json
import time
import uuid
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import requests
from PIL import Image, ImageFile

ImageFile.LOAD_TRUNCATED_IMAGES = True
DEFAULT_MODEL_CONFIG_PATH = "model_config.json"


def _json_safe(value):
    try:
        json.dumps(value)
        return value
    except TypeError:
        if isinstance(value, dict):
            return {str(k): _json_safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [_json_safe(v) for v in value]
        if hasattr(value, "model_dump"):
            return _json_safe(value.model_dump())
        if hasattr(value, "dict"):
            return _json_safe(value.dict())
        return str(value)

class LlmTraceLogger:
    def __init__(self, trace_dir=None):
        self.trace_dir = Path(trace_dir) if trace_dir else Path.cwd() / "llm_traces"
        self.trace_dir.mkdir(parents=True, exist_ok=True)

    def log(self, request_payload, response_payload=None, metadata=None, error=None):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        log_path = self.trace_dir / f"llm_trace_{timestamp}_{uuid.uuid4().hex[:8]}.json"
        # Try to extract any model 'reasoning' text when present in the response
        reasoning = None
        try:
            if isinstance(response_payload, dict):
                # OpenAI-like schema: choices -> [ { message: { reasoning: ... } } ]
                choices = response_payload.get("choices") or []
                if choices and isinstance(choices, list):
                    msg = choices[0].get("message") if isinstance(choices[0], dict) else None
                    if isinstance(msg, dict):
                        reasoning = msg.get("reasoning") or msg.get("explanation")
                # Top-level reasoning key
                if reasoning is None:
                    reasoning = response_payload.get("reasoning")
        except Exception:
            reasoning = None

        record = {
            "timestamp": datetime.now().isoformat(),
            "metadata": _json_safe(metadata or {}),
            "request": _json_safe(request_payload),
            "response": _json_safe(response_payload),
            "reasoning": _json_safe(reasoning) if reasoning is not None else None,
            "error": str(error) if error else None,
        }
        with log_path.open("w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
        return str(log_path)


class LLMInvokeError(RuntimeError):
    """Raised when LLM invocation fails after all retries."""


def load_model_config(config_path: str) -> dict[str, Any]:
    path = Path(config_path)
    if not path.exists():
        raise SystemExit(f"Model config file not found: {path}")

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit(f"Failed to parse model config JSON at {path}: {exc}")

    if not isinstance(raw, dict):
        raise SystemExit(f"Model config must be a JSON object: {path}")

    config = {}
    for key in ("base_url", "api_key", "model_name"):
        if key not in raw:
            raise SystemExit(f"Missing '{key}' in model config: {path}")
        value = raw[key]
        if not isinstance(value, str):
            raise SystemExit(f"'{key}' must be a non-empty JSON string in model config: {path}")
        value = value.strip()
        if key == "base_url":
            value = value.rstrip("/")
        if not value:
            raise SystemExit(f"'{key}' must be a non-empty JSON string in model config: {path}")
        config[key] = value
    if "enable_thinking" in raw:
        if not isinstance(raw["enable_thinking"], bool):
            raise SystemExit("'enable_thinking' must be a JSON boolean (true or false), or omitted")
        config["enable_thinking"] = raw["enable_thinking"]
    return config


def pil_to_base64_png(image: Image.Image) -> str:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def image_to_data_url(image_path: str) -> str:
    if image_path.startswith("file://"):
        image_path = image_path[len("file://") :]
    with Image.open(image_path) as image:
        original_image = image.copy()
    return f"data:image/png;base64,{pil_to_base64_png(original_image)}"


def convert_messages_to_openai_image_url(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert Mobile-Agent message parts to OpenAI-compatible multimodal parts."""
    converted = []
    for message in messages:
        content = []
        for item in message["content"]:
            if "text" in item:
                content.append({"type": "text", "text": item["text"]})
            elif "image" in item:
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": image_to_data_url(item["image"])},
                    }
                )
        converted.append({"role": message["role"], "content": content})
    return converted


def parse_streaming_response(response: requests.Response) -> tuple[str, str]:
    """Assemble SSE data events, requiring the API's completion marker."""
    chunks = []
    reasoning_chunks = []
    data_lines = []
    response.encoding = "utf-8"
    for line in response.iter_lines(decode_unicode=True):
        if line:
            field, separator, value = line.partition(":")
            if field == "data":
                data_lines.append(value.removeprefix(" ") if separator else "")
            continue
        if not data_lines:
            continue
        data = "\n".join(data_lines)
        data_lines.clear()
        if data.strip() == "[DONE]":
            return "".join(chunks), "".join(reasoning_chunks)
        try:
            event = json.loads(data)
        except json.JSONDecodeError as exc:
            raise ValueError("Malformed JSON in LLM stream") from exc
        if not isinstance(event, dict):
            raise ValueError("Expected a JSON object in LLM stream")
        if event.get("error") is not None:
            raise ValueError(f"LLM stream error: {event['error']}")
        choices = event.get("choices") or []
        if not choices:
            continue
        choice = choices[0]
        delta = choice.get("delta") or {}
        message = choice.get("message") or {}
        for part in (delta, message):
            reasoning = part.get("reasoning_content") or part.get("reasoning")
            if reasoning:
                reasoning_chunks.append(reasoning)
            if part.get("content"):
                chunks.append(part["content"])
    raise ValueError("LLM stream ended before [DONE]; response may be incomplete")


class OpenAICompatibleMultimodalClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model_name: str,
        max_retry: int = 3,
        llm_trace_dir: str | None = None,
        enable_thinking: bool | None = None,
    ):
        self.base_url = base_url.strip().rstrip("/")
        self.api_key = api_key
        self.model_name = model_name
        self.max_retry = max_retry
        self.trace_logger = LlmTraceLogger(llm_trace_dir)
        self.enable_thinking = enable_thinking

    def invoke(self, messages: list[dict[str, Any]]) -> tuple[str, Any, Any]:
        request_url = f"{self.base_url}/chat/completions"
        payload_messages = convert_messages_to_openai_image_url(messages)
        payload = {
            "model": self.model_name,
            "messages": payload_messages,
            "stream": True,
        }
        if self.enable_thinking is not None:
            payload["chat_template_kwargs"] = {"enable_thinking": self.enable_thinking}
        headers = {
            "accept": "text/event-stream",
            "content-type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        metadata = {
            "provider": "http-openai-compatible",
            "model": self.model_name,
            "url": request_url,
            "wrapper": self.__class__.__name__,
            "stream": True,
        }

        wait_seconds = 5
        last_error: Exception | None = None
        for attempt in range(1, self.max_retry + 1):
            response = None
            try:
                response = requests.post(
                    request_url,
                    json=payload,
                    headers=headers,
                    stream=True,
                    timeout=300,
                )
                response.raise_for_status()
                content, reasoning = parse_streaming_response(response)
                self.trace_logger.log(payload, {"content": content, "reasoning": reasoning or None}, metadata=metadata)
                return content, payload_messages, response
            except Exception as exc:
                last_error = exc
                self.trace_logger.log(payload, None, metadata=metadata, error=exc)
                print(f"[WARN] Qwen3.5 call failed on attempt {attempt}: {exc}")
            finally:
                if response is not None:
                    response.close()
            if attempt < self.max_retry:
                time.sleep(wait_seconds)

        raise LLMInvokeError(
            f"LLM invoke failed after {self.max_retry} attempts for model '{self.model_name}' at '{request_url}': {last_error}"
        )


def create_llm_client(config_path: str = DEFAULT_MODEL_CONFIG_PATH, llm_trace_dir: str | None = None) -> OpenAICompatibleMultimodalClient:
    cfg = load_model_config(config_path)
    return OpenAICompatibleMultimodalClient(
        base_url=cfg["base_url"],
        api_key=cfg["api_key"],
        model_name=cfg["model_name"],
        llm_trace_dir=llm_trace_dir,
        enable_thinking=cfg.get("enable_thinking"),
    )
