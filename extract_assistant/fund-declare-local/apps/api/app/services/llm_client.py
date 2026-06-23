import json
import re
import base64
import mimetypes
from pathlib import Path
from typing import Any

import requests

from app.core.config import (
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_MAX_TOKENS,
    LLM_MODEL,
    LLM_PROVIDER,
    LLM_TIMEOUT_SECONDS,
)


class LLMClient:
    def __init__(
        self,
        provider: str = LLM_PROVIDER,
        api_key: str = LLM_API_KEY,
        base_url: str = LLM_BASE_URL,
        model: str = LLM_MODEL,
        timeout_seconds: int = LLM_TIMEOUT_SECONDS,
        max_tokens: int = LLM_MAX_TOKENS,
        max_image_bytes: int | None = None,
    ) -> None:
        self.provider = provider or "mock"
        self.api_key = api_key or ""
        self.base_url = (base_url or "").rstrip("/")
        self.model = model or ""
        self.timeout_seconds = timeout_seconds
        self.max_tokens = max_tokens
        self.max_image_bytes = max_image_bytes
        self.session = requests.Session()
        self.session.trust_env = False

    def extract_json(self, final_prompt: str, input_text: str = "") -> dict:
        if self.provider == "mock":
            return self._mock_response()

        if self.provider == "openai_compatible":
            user_content = (
                f"{final_prompt}\n\n{input_text}" if input_text else final_prompt
            )
            return self._call_openai_compatible(user_content)

        return {
            "extract_status": "failed",
            "raw_llm_output": None,
            "manual_review_required": True,
            "review_reasons": [f"不支持的 LLM_PROVIDER：{self.provider}"],
        }

    def extract_json_with_images(
        self,
        final_prompt: str,
        input_text: str = "",
        image_paths: list[str | Path] | None = None,
    ) -> dict:
        if self.provider == "mock":
            return self._mock_response()

        if self.provider == "openai_compatible":
            user_content = self._build_multimodal_user_content(
                final_prompt,
                input_text,
                image_paths or [],
            )
            return self._call_openai_compatible(user_content)

        return {
            "extract_status": "failed",
            "raw_llm_output": None,
            "manual_review_required": True,
            "review_reasons": [f"不支持的 LLM_PROVIDER：{self.provider}"],
        }

    def _mock_response(self) -> dict:
        return {
            "schema_version": "chinaclear_extract_v1",
            "extract_status": "mock_success",
            "content_type": "chinaclear",
            "accounts": [],
            "holdings": [],
            "transactions": [],
            "events": [],
            "manual_review_required": True,
            "review_reasons": ["当前为 mock 模式，未调用真实 LLM"],
        }

    def _call_openai_compatible(self, user_content: str | list[dict[str, Any]]) -> dict:
        missing_configs = []
        if not self.base_url:
            missing_configs.append("LLM_BASE_URL")
        if not self.model:
            missing_configs.append("LLM_MODEL")
        if not self.api_key:
            missing_configs.append("LLM_API_KEY")
        if self._is_placeholder_api_key():
            missing_configs.append("LLM_API_KEY 未配置真实值")

        if missing_configs:
            return {
                "extract_status": "llm_request_failed",
                "raw_llm_output": None,
                "manual_review_required": True,
                "review_reasons": [f"LLM 配置缺失：{', '.join(missing_configs)}"],
            }

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": "你是一个严格的金融材料结构化抽取助手。你只能输出 JSON，不要输出解释文字、Markdown、代码块或多余文本。",
                },
                {
                    "role": "user",
                    "content": user_content,
                },
            ],
            "thinking": {"type": "disabled"},
            "response_format": {"type": "json_object"},
            "max_tokens": self.max_tokens,
            "temperature": 0,
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = self.session.post(
                self._chat_completions_url(),
                json=payload,
                headers=headers,
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            return {
                "extract_status": "llm_request_failed",
                "raw_llm_output": None,
                "manual_review_required": True,
                "review_reasons": [f"LLM 请求失败：{self._sanitize_error(exc)}"],
            }

        if not response.ok:
            return {
                "extract_status": "llm_request_failed",
                "raw_llm_output": self._sanitize_text(response.text),
                "manual_review_required": True,
                "review_reasons": [
                    f"LLM 请求失败：HTTP {response.status_code} {response.reason}"
                ],
            }

        try:
            response_json = response.json()
            choice = self._extract_choice(response_json)
            raw_output = self._strip_json_code_fence(
                self._extract_message_content(choice)
            )
            response_metadata = self._build_response_metadata(response_json, choice)
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            return {
                "extract_status": "llm_request_failed",
                "raw_llm_output": self._sanitize_text(response.text),
                "manual_review_required": True,
                "review_reasons": [f"LLM 响应格式异常：{exc}"],
            }

        try:
            parsed_output = json.loads(raw_output)
        except ValueError:
            review_reason = "LLM 输出不是合法 JSON"
            if response_metadata.get("finish_reason") == "length":
                review_reason = "LLM 输出被截断：finish_reason=length"

            return {
                "extract_status": "json_parse_failed",
                "raw_llm_output": raw_output,
                "llm_response_metadata": response_metadata,
                "manual_review_required": True,
                "review_reasons": [review_reason],
            }

        if not isinstance(parsed_output, dict):
            return {
                "extract_status": "json_parse_failed",
                "raw_llm_output": raw_output,
                "llm_response_metadata": response_metadata,
                "manual_review_required": True,
                "review_reasons": ["LLM 输出 JSON 不是对象"],
            }

        parsed_output.setdefault("llm_response_metadata", response_metadata)
        return parsed_output

    def _build_multimodal_user_content(
        self,
        final_prompt: str,
        input_text: str,
        image_paths: list[str | Path],
    ) -> list[dict[str, Any]]:
        text = f"{final_prompt}\n\n{input_text}" if input_text else final_prompt
        content: list[dict[str, Any]] = [{"type": "text", "text": text}]

        for image_path in image_paths:
            data_url = self._image_data_url(Path(image_path))
            if data_url:
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": data_url},
                    }
                )

        return content

    def _image_data_url(self, image_path: Path) -> str:
        if not image_path.exists() or not image_path.is_file():
            return ""
        if self.max_image_bytes and image_path.stat().st_size > self.max_image_bytes:
            return ""
        mime_type = mimetypes.guess_type(str(image_path))[0] or "image/png"
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"

    def _chat_completions_url(self) -> str:
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        return f"{self.base_url}/chat/completions"

    def _extract_choice(self, response_json: dict[str, Any]) -> dict[str, Any]:
        return response_json["choices"][0]

    def _extract_message_content(self, choice: dict[str, Any]) -> str:
        return choice["message"]["content"]

    def _build_response_metadata(
        self,
        response_json: dict[str, Any],
        choice: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "id": response_json.get("id"),
            "model": response_json.get("model"),
            "finish_reason": choice.get("finish_reason"),
            "usage": response_json.get("usage"),
            "request_options": {
                "thinking": {"type": "disabled"},
                "response_format": {"type": "json_object"},
                "max_tokens": self.max_tokens,
                "temperature": 0,
                "stream": False,
            },
        }

    def _strip_json_code_fence(self, raw_output: str) -> str:
        text = raw_output.strip()
        fenced_match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.S)
        if fenced_match:
            return fenced_match.group(1).strip()
        return text

    def _sanitize_error(self, exc: Exception) -> str:
        return self._sanitize_text(str(exc))

    def _sanitize_text(self, message: str) -> str:
        if self.api_key:
            message = message.replace(self.api_key, "[REDACTED]")
        return message

    def _is_placeholder_api_key(self) -> bool:
        return "这里填" in self.api_key or "你的 DeepSeek" in self.api_key
