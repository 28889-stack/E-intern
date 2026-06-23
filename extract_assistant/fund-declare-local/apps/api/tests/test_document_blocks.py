import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PIL import Image


API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


class DocumentBlocksTest(unittest.TestCase):
    def test_builds_document_blocks_with_page_visual_evidence(self):
        from app.pipeline.document_blocks import build_document_blocks
        from app.services.local_store import read_json, save_json

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_image = root / "statement.png"
            output_dir = root / "processed" / "file_001"
            Image.new("RGB", (240, 160), "white").save(source_image)

            save_json(
                output_dir / "raw_text.json",
                {
                    "pages": [
                        {
                            "page": 1,
                            "text": "证券账号 A315570738\n证券名称 中国重汽",
                        }
                    ],
                    "full_text": "证券账号 A315570738\n证券名称 中国重汽",
                },
            )
            save_json(
                output_dir / "tables.json",
                {
                    "tables": [
                        {
                            "page": 1,
                            "table_index": 1,
                            "rows": [
                                ["业务日期", "证券代码", "证券名称"],
                                ["2025-04-14", "000951", "中国重汽"],
                            ],
                        }
                    ]
                },
            )
            save_json(
                output_dir / "ocr_result.json",
                {
                    "ocr_status": "success",
                    "pages": [
                        {
                            "page": 1,
                            "text": "OCR 识别文本",
                            "confidence_avg": 0.91,
                        }
                    ],
                },
            )

            result = build_document_blocks(
                file_path=source_image,
                output_dir=output_dir,
                route_type="image",
            )

            saved = read_json(output_dir / "document_blocks.json")
            page_image = output_dir / "visual_evidence" / "page_001.png"
            block_types = {block["block_type"] for block in result["blocks"]}
            self.assertTrue(page_image.exists())
            self.assertEqual(saved["document_block_status"], "success")
            self.assertIn("pdf_text", block_types)
            self.assertIn("pdf_table", block_types)
            self.assertIn("ocr_text", block_types)
            self.assertTrue(
                all(
                    block["image_refs"][0]["path"].endswith("page_001.png")
                    for block in result["blocks"]
                )
            )
        self.assertEqual(result["blocks"][0]["page_no"], 1)

    def test_detects_difficult_blocks_from_low_confidence_and_unstable_columns(self):
        from app.pipeline.difficult_block_detector import detect_difficult_blocks

        document_blocks = {
            "blocks": [
                {
                    "block_id": "page_001_table_001",
                    "page_no": 1,
                    "block_type": "pdf_table",
                    "text": "",
                    "table_rows": [
                        ["业务日期", "证券代码", "证券名称", "成交金额"],
                        ["2025-04-14", "000951", "中国重汽"],
                        ["2025-04-15", "600958", "东方证券", "116720.4800"],
                    ],
                    "image_refs": [],
                    "source": {},
                },
                {
                    "block_id": "page_002_ocr_001",
                    "page_no": 2,
                    "block_type": "ocr_text",
                    "text": "残缺 OCR 文本",
                    "table_rows": [],
                    "image_refs": [],
                    "source": {"confidence_avg": 0.72},
                },
            ]
        }

        result = detect_difficult_blocks(document_blocks)
        reasons_by_block = {
            item["block_id"]: set(item["difficulty_reasons"])
            for item in result["difficult_blocks"]
        }

        self.assertEqual(result["difficulty_status"], "has_difficult_blocks")
        self.assertIn("unstable_table_columns", reasons_by_block["page_001_table_001"])
        self.assertIn("ocr_low_confidence", reasons_by_block["page_002_ocr_001"])

    def test_sidecar_sends_difficult_block_page_images_to_llm(self):
        from app.pipeline.multimodal_review_sidecar import _extract_hints

        class _FakeClient:
            def __init__(self):
                self.image_paths = None

            def extract_json_with_images(self, prompt, input_text="", image_paths=None):
                self.image_paths = image_paths
                return {
                    "event_candidates": [],
                    "merge_suggestions": [],
                    "column_mapping_hints": [{"source_block_id": "page_001_table_001"}],
                    "uncertainty_reasons": [],
                }

        fake_client = _FakeClient()
        document_blocks = {
            "blocks": [
                {
                    "block_id": "page_001_table_001",
                    "page_no": 1,
                    "block_type": "pdf_table",
                    "text": "业务日期 | 证券代码",
                    "table_rows": [],
                    "image_refs": [
                        {
                            "type": "page",
                            "path": "/tmp/page_001.png",
                        }
                    ],
                    "source": {},
                }
            ]
        }
        difficult_blocks = {
            "difficult_blocks": [
                {
                    "block_id": "page_001_table_001",
                    "page_no": 1,
                    "block_type": "pdf_table",
                    "difficulty_reasons": ["unstable_table_columns"],
                    "image_refs": [
                        {
                            "type": "page",
                            "path": "/tmp/page_001.png",
                        }
                    ],
                }
            ]
        }

        result = _extract_hints(
            document_blocks=document_blocks,
            difficult_blocks=difficult_blocks,
            llm_client=fake_client,
        )

        self.assertEqual(result["multimodal_review_status"], "success")
        self.assertEqual(fake_client.image_paths, ["/tmp/page_001.png"])

    def test_sidecar_uses_multimodal_client_settings_by_default(self):
        from app.pipeline import multimodal_review_sidecar

        class _FakeClient:
            instances = []

            def __init__(
                self,
                provider,
                api_key,
                base_url,
                model,
                timeout_seconds,
                max_tokens,
                max_image_bytes,
            ):
                self.__class__.instances.append(
                    {
                        "provider": provider,
                        "api_key": api_key,
                        "base_url": base_url,
                        "model": model,
                        "timeout_seconds": timeout_seconds,
                        "max_tokens": max_tokens,
                        "max_image_bytes": max_image_bytes,
                    }
                )

        with patch.object(
            multimodal_review_sidecar,
            "LLMClient",
            _FakeClient,
        ), patch.object(
            multimodal_review_sidecar,
            "MULTIMODAL_API_KEY",
            "multi-key",
        ), patch.object(
            multimodal_review_sidecar,
            "MULTIMODAL_API_URL",
            "https://multi.example/v1/chat/completions",
        ), patch.object(
            multimodal_review_sidecar,
            "MULTIMODAL_MODEL",
            "multi-vision",
        ), patch.object(
            multimodal_review_sidecar,
            "MULTIMODAL_TIMEOUT_SECONDS",
            180,
        ), patch.object(
            multimodal_review_sidecar,
            "MULTIMODAL_MAX_TOKENS",
            2048,
        ), patch.object(
            multimodal_review_sidecar,
            "MULTIMODAL_MAX_IMG_BYTES",
            3500000,
        ):
            client = multimodal_review_sidecar._multimodal_llm_client()

        self.assertIsInstance(client, _FakeClient)
        self.assertEqual(
            _FakeClient.instances,
            [
                {
                    "provider": "openai_compatible",
                    "api_key": "multi-key",
                    "base_url": "https://multi.example/v1/chat/completions",
                    "model": "multi-vision",
                    "timeout_seconds": 180,
                    "max_tokens": 2048,
                    "max_image_bytes": 3500000,
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
