import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PIL import Image


API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


class _FakeResponse:
    ok = True
    status_code = 200
    reason = "OK"
    text = "{}"

    def json(self):
        return {
            "id": "chatcmpl-test",
            "model": "vision-test",
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": '{"event_candidates":[{"event_type":"test"}],"merge_suggestions":[],"column_mapping_hints":[],"uncertainty_reasons":[]}'
                    },
                }
            ],
            "usage": {"total_tokens": 12},
        }


class LLMClientMultimodalTest(unittest.TestCase):
    def test_openai_compatible_multimodal_request_includes_text_and_image_url(self):
        from app.services.llm_client import LLMClient

        with TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "page_001.png"
            Image.new("RGB", (16, 16), "white").save(image_path)
            captured = {}

            client = LLMClient(
                provider="openai_compatible",
                api_key="test-key",
                base_url="https://example.test/v1",
                model="vision-model",
                timeout_seconds=7,
                max_tokens=256,
            )

            def fake_post(url, json, headers, timeout):
                captured["url"] = url
                captured["json"] = json
                captured["headers"] = headers
                captured["timeout"] = timeout
                return _FakeResponse()

            client.session.post = fake_post
            result = client.extract_json_with_images(
                "只输出 JSON",
                input_text="block_id: page_001_table_001",
                image_paths=[image_path],
            )

        user_content = captured["json"]["messages"][1]["content"]
        self.assertEqual(result["event_candidates"][0]["event_type"], "test")
        self.assertEqual(captured["url"], "https://example.test/v1/chat/completions")
        self.assertEqual(user_content[0]["type"], "text")
        self.assertIn("block_id: page_001_table_001", user_content[0]["text"])
        self.assertEqual(user_content[1]["type"], "image_url")
        self.assertTrue(
            user_content[1]["image_url"]["url"].startswith("data:image/png;base64,")
        )
        self.assertEqual(captured["json"]["thinking"], {"type": "disabled"})
        self.assertEqual(captured["json"]["response_format"], {"type": "json_object"})

    def test_openai_compatible_accepts_full_chat_completions_url(self):
        from app.services.llm_client import LLMClient

        captured = {}
        client = LLMClient(
            provider="openai_compatible",
            api_key="test-key",
            base_url="https://example.test/v1/chat/completions",
            model="vision-model",
            timeout_seconds=7,
            max_tokens=256,
        )

        def fake_post(url, json, headers, timeout):
            captured["url"] = url
            return _FakeResponse()

        client.session.post = fake_post
        result = client.extract_json("只输出 JSON")

        self.assertEqual(result["event_candidates"][0]["event_type"], "test")
        self.assertEqual(captured["url"], "https://example.test/v1/chat/completions")


if __name__ == "__main__":
    unittest.main()
