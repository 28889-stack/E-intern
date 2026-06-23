import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest


API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


class DocumentStructureTest(unittest.TestCase):
    def test_builds_ocr_lines_and_layout_rows_from_bboxes(self):
        from app.pipeline.document_structure import build_document_structure
        from app.services.local_store import read_json, save_json

        with TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "processed" / "file_001"
            save_json(
                output_dir / "ocr_result.json",
                {
                    "ocr_status": "success",
                    "page_results": [
                        {
                            "page": 1,
                            "text": "证券代码 证券名称 成交数量\n000001 平安银行 100",
                            "blocks": [
                                {"text": "证券代码", "bbox": [10, 10, 70, 24], "confidence": 0.98},
                                {"text": "证券名称", "bbox": [110, 11, 170, 25], "confidence": 0.97},
                                {"text": "成交数量", "bbox": [210, 10, 270, 25], "confidence": 0.96},
                                {"text": "000001", "bbox": [10, 40, 70, 54], "confidence": 0.99},
                                {"text": "平安银行", "bbox": [110, 41, 170, 55], "confidence": 0.98},
                                {"text": "100", "bbox": [210, 40, 270, 54], "confidence": 0.97},
                            ],
                        }
                    ],
                },
            )

            result = build_document_structure(output_dir)
            saved = read_json(output_dir / "document_structure.json")

            self.assertEqual(result["document_structure_status"], "success")
            self.assertEqual(saved["page_count"], 1)
            self.assertEqual(len(saved["pages"][0]["lines"]), 6)
            self.assertEqual(saved["pages"][0]["lines"][0]["bbox"], [10.0, 10.0, 70.0, 24.0])
            table = saved["pages"][0]["tables"][0]
            self.assertEqual(table["table_type"], "ocr_layout_rows")
            self.assertEqual(table["structure_source"], "ocr_line_bbox")
            self.assertEqual(len(table["rows"]), 2)
            self.assertEqual(
                [cell["text"] for cell in table["rows"][1]["cells"]],
                ["000001", "平安银行", "100"],
            )

    def test_extraction_input_prefers_document_structure(self):
        from app.pipeline.document_structure import build_document_structure
        from app.pipeline.extraction_input_builder import build_extraction_input
        from app.services.local_store import save_json

        with TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "processed" / "file_001"
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
            build_document_structure(output_dir)

            payload = build_extraction_input(output_dir)

            self.assertIn("document_structure.json", payload["sources"]["document_structure_path"])
            self.assertIn("document_table", payload["input_text"])
            self.assertIn("row_id=p001_t001_r002", payload["input_text"])
            self.assertIn("2025-04-14", payload["input_text"])

    def test_extraction_input_includes_compact_graph_rag_context(self):
        from app.pipeline.extraction_input_builder import build_extraction_input
        from app.services.local_store import save_json

        with TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "processed" / "file_001"
            save_json(
                output_dir / "raw_text.json",
                {
                    "pages": [
                        {
                            "page": 1,
                            "text": "2022-01-05 688262 国芯科技 新股入账 500",
                        }
                    ]
                },
            )
            save_json(
                output_dir / "graph_rag/retrieval_result.json",
                {
                    "query": "抽取交易类事件",
                    "matched_entities": ["security:688262"],
                    "context_blocks": [
                        {
                            "page_no": 1,
                            "row_no": "18",
                            "source_text": "2022-01-05 688262 国芯科技 新股入账 500",
                            "related_entities": ["688262", "国芯科技"],
                            "reason": "same security",
                        }
                    ],
                },
            )

            payload = build_extraction_input(output_dir)

        self.assertIn("graph_rag_retrieval_path", payload["sources"])
        self.assertIn("graph_rag_context", payload)
        self.assertIn("security:688262", payload["graph_rag_context"])
        self.assertIn("国芯科技", payload["graph_rag_context"])

    def test_table_payload_preserves_row_and_cell_trace_metadata(self):
        from app.pipeline.document_structure import (
            build_document_structure,
            document_structure_to_tables_payload,
        )
        from app.services.local_store import save_json

        with TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "processed" / "file_001"
            save_json(
                output_dir / "ocr_result.json",
                {
                    "ocr_status": "success",
                    "page_results": [
                        {
                            "page": 1,
                            "blocks": [
                                {"text": "证券代码", "bbox": [10, 10, 70, 24], "confidence": 0.98},
                                {"text": "证券名称", "bbox": [110, 10, 170, 24], "confidence": 0.97},
                                {"text": "000001", "bbox": [10, 40, 70, 54], "confidence": 0.99},
                                {"text": "平安银行", "bbox": [110, 40, 170, 54], "confidence": 0.98},
                            ],
                        }
                    ],
                },
            )

            document_structure = build_document_structure(output_dir)
            payload = document_structure_to_tables_payload(document_structure)

        table = payload["tables"][0]
        self.assertEqual(table["rows"][1], ["000001", "平安银行"])
        self.assertEqual(table["row_metadata"][1]["row_id"], "p001_ocr_row_002")
        self.assertEqual(table["row_metadata"][1]["bbox"], [10.0, 40.0, 170.0, 54.0])
        self.assertEqual(
            table["cell_metadata"][1][0]["source_line_id"],
            "p001_ocr_l003",
        )

    def test_guangfa_table_batch_keeps_document_structure_trace_metadata(self):
        from app.pipeline.guangfa_extractor import GuangfaExtractor

        extractor = GuangfaExtractor.__new__(GuangfaExtractor)
        rows = extractor._flatten_table_rows(
            {
                "tables": [
                    {
                        "page": 1,
                        "table_index": 1,
                        "rows": [
                            ["业务日期", "证券代码", "证券名称", "业务标志"],
                            ["2025-01-02", "000001", "平安银行", "证券买入"],
                        ],
                        "row_metadata": [
                            {"row_id": "p001_ocr_table_001_r001", "bbox": [10, 10, 300, 24]},
                            {"row_id": "p001_ocr_table_001_r002", "bbox": [10, 40, 300, 54]},
                        ],
                        "cell_metadata": [
                            [
                                {"cell_id": "h1", "source_line_id": "l1"},
                                {"cell_id": "h2", "source_line_id": "l2"},
                                {"cell_id": "h3", "source_line_id": "l3"},
                                {"cell_id": "h4", "source_line_id": "l4"},
                            ],
                            [
                                {"cell_id": "c1", "source_line_id": "p001_ocr_l005"},
                                {"cell_id": "c2", "source_line_id": "p001_ocr_l006"},
                                {"cell_id": "c3", "source_line_id": "p001_ocr_l007"},
                                {"cell_id": "c4", "source_line_id": "p001_ocr_l008"},
                            ],
                        ],
                    }
                ]
            }
        )
        text = extractor._batch_rows_to_text(rows)

        self.assertIn("row_id=p001_ocr_table_001_r002", text)
        self.assertIn("bbox=[10, 40, 300, 54]", text)
        self.assertIn("source_line_ids=p001_ocr_l005,p001_ocr_l006,p001_ocr_l007,p001_ocr_l008", text)


if __name__ == "__main__":
    unittest.main()
