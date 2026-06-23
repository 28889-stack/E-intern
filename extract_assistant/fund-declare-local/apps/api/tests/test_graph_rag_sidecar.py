import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


class GraphRagSidecarTest(unittest.TestCase):
    def test_builds_business_graph_from_document_structure(self):
        from app.pipeline.graph_rag_sidecar import run_graph_rag_sidecar
        from app.services import local_store

        with TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            output_dir = project_root / "data/cases/case_test/account_info/processed/file_001"
            with patch.object(local_store, "PROJECT_ROOT", project_root):
                local_store.save_json(
                    output_dir / "document_structure.json",
                    _document_structure(),
                )

                with patch(
                    "app.pipeline.graph_rag_sidecar.GRAPH_RAG_EMBEDDING_ENABLED",
                    False,
                ):
                    result = run_graph_rag_sidecar(
                        {
                            "file_id": "file_001",
                            "file_no": "001",
                            "case_id": "case_test",
                            "original_file_name": "statement.pdf",
                        },
                        output_dir,
                    )

                graph_dir = output_dir / "graph_rag"
                graph = json.loads((graph_dir / "graph.json").read_text())
                entities = json.loads((graph_dir / "entities.json").read_text())
                relationships = json.loads((graph_dir / "relationships.json").read_text())
                retrieval = json.loads((graph_dir / "retrieval_result.json").read_text())
                debug = json.loads((graph_dir / "build_debug.json").read_text())

        entity_ids = {item["id"] for item in entities["entities"]}
        security = next(item for item in entities["entities"] if item["id"] == "security:688262")

        self.assertEqual(result["graph_rag_status"], "success")
        self.assertEqual(debug["source_priority"], "document_structure")
        self.assertIn("document:file_001", entity_ids)
        self.assertIn("account:A315570738", entity_ids)
        self.assertIn("security:688262", entity_ids)
        self.assertNotIn("security:802777", entity_ids)
        self.assertIn("国芯科技", security["aliases"])
        self.assertTrue(
            any(edge["type"] == "AFFECTS_SECURITY" and edge["target"] == "security:688262" for edge in relationships["relationships"])
        )
        self.assertTrue(retrieval["context_blocks"])
        self.assertLessEqual(len(retrieval["context_blocks"]), 20)
        self.assertIn("688262", retrieval["context_blocks"][0]["source_text"])
        self.assertEqual(graph["schema_version"], "graph_rag_v1")

    def test_formats_compact_graph_context_for_prompt(self):
        from app.pipeline.graph_rag_sidecar import format_graph_rag_context
        from app.services import local_store

        with TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            output_dir = project_root / "processed"
            graph_dir = output_dir / "graph_rag"
            with patch.object(local_store, "PROJECT_ROOT", project_root):
                local_store.save_json(
                    graph_dir / "retrieval_result.json",
                    {
                        "query": "抽取交易类事件",
                        "matched_entities": ["account:A315570738", "security:688262"],
                        "context_blocks": [
                            {
                                "page_no": 1,
                                "row_no": "18",
                                "source_text": "2022-01-05 A315570738 688262 国芯科技 新股入账 500.0000 41.9800 0.0000",
                                "related_entities": ["A315570738", "688262", "国芯科技"],
                                "reason": "same account and same security",
                            }
                        ],
                    },
                )

                text = format_graph_rag_context(output_dir)

        self.assertIn("query: 抽取交易类事件", text)
        self.assertIn("matched_entities: account:A315570738, security:688262", text)
        self.assertIn("[page=1 row_no=18]", text)
        self.assertIn("国芯科技", text)

    def test_extractors_include_graph_rag_context_in_prompts(self):
        from app.pipeline.chinaclear_extractor import ChinaclearExtractor
        from app.pipeline.guangfa_extractor import GuangfaExtractor

        context = (
            "graph_rag_query: 抽取交易类事件\n"
            "matched_entities: security:688262\n"
            "[page=1 row_no=18]\n"
            "source_text: 2022-01-05 688262 国芯科技 新股入账 500"
        )
        file_record = {
            "file_id": "file_001",
            "file_no": "001",
            "original_file_name": "statement.pdf",
            "route_type": "direct_pdf",
            "content_type": "guangfa",
        }

        guangfa_prompt = GuangfaExtractor()._build_final_prompt(
            "base prompt",
            file_record,
            "input body",
            {},
            context,
        )
        chinaclear_prompt = ChinaclearExtractor()._build_batch_prompt(
            "base prompt",
            file_record,
            {
                "batch_id": "batch_001",
                "row_start": "1",
                "row_end": "20",
                "input_text": "batch body",
            },
            {},
            context,
        )

        self.assertIn("graph_rag_context:", guangfa_prompt)
        self.assertIn("security:688262", guangfa_prompt)
        self.assertIn("辅助证据上下文", guangfa_prompt)
        self.assertIn("graph_rag_context:", chinaclear_prompt)
        self.assertIn("国芯科技", chinaclear_prompt)

    def test_retrieves_chinaclear_rights_and_transfer_rows(self):
        from app.pipeline.graph_rag_sidecar import run_graph_rag_sidecar
        from app.services import local_store

        with TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            output_dir = project_root / "data/cases/case_test/account_info/processed/file_001"
            with patch.object(local_store, "PROJECT_ROOT", project_root):
                local_store.save_json(
                    output_dir / "document_structure.json",
                    _chinaclear_rights_document_structure(),
                )

                with patch(
                    "app.pipeline.graph_rag_sidecar.GRAPH_RAG_EMBEDDING_ENABLED",
                    False,
                ):
                    run_graph_rag_sidecar(
                        {
                            "file_id": "file_001",
                            "file_no": "001",
                            "case_id": "case_test",
                            "original_file_name": "rights.pdf",
                        },
                        output_dir,
                    )

                retrieval = json.loads(
                    (output_dir / "graph_rag/retrieval_result.json").read_text()
                )

        source_texts = [block["source_text"] for block in retrieval["context_blocks"]]
        joined = "\n".join(source_texts)

        self.assertIn("113641 华友转债", joined)
        self.assertIn("兑息", joined)
        self.assertIn("权益挂牌", joined)
        self.assertIn("交易过户", joined)
        self.assertIn("600794 保税科技", joined)

    def test_retrieval_reason_does_not_claim_missing_account_relation(self):
        from app.pipeline.graph_rag_sidecar import run_graph_rag_sidecar
        from app.services import local_store

        with TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            output_dir = project_root / "data/cases/case_test/account_info/processed/file_001"
            with patch.object(local_store, "PROJECT_ROOT", project_root):
                local_store.save_json(
                    output_dir / "document_structure.json",
                    _chinaclear_rights_document_structure(),
                )

                with patch(
                    "app.pipeline.graph_rag_sidecar.GRAPH_RAG_EMBEDDING_ENABLED",
                    False,
                ):
                    run_graph_rag_sidecar(
                        {
                            "file_id": "file_001",
                            "file_no": "001",
                            "case_id": "case_test",
                            "original_file_name": "rights.pdf",
                        },
                        output_dir,
                    )

                retrieval = json.loads(
                    (output_dir / "graph_rag/retrieval_result.json").read_text()
                )

        reasons = {block["reason"] for block in retrieval["context_blocks"]}

        self.assertIn("same security", reasons)
        self.assertNotIn("same account and same security", reasons)

    def test_embedding_retrieval_writes_chunks_embeddings_and_vector_context(self):
        from app.pipeline.graph_rag_sidecar import run_graph_rag_sidecar
        from app.services import local_store

        class FakeEmbeddingClient:
            model_name = "fake-bge-small-zh"

            def encode(self, texts):
                vectors = []
                for text in texts:
                    if "股息" in text or "红利" in text or "兑息" in text:
                        vectors.append([1.0, 0.0, 0.0])
                    elif "证券账号" in text:
                        vectors.append([0.0, 1.0, 0.0])
                    else:
                        vectors.append([0.0, 0.0, 1.0])
                return vectors

        with TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            output_dir = project_root / "data/cases/case_test/account_info/processed/file_001"
            with patch.object(local_store, "PROJECT_ROOT", project_root):
                local_store.save_json(
                    output_dir / "document_structure.json",
                    _chinaclear_rights_document_structure(),
                )

                with patch(
                    "app.pipeline.graph_rag_sidecar.GRAPH_RAG_EMBEDDING_ENABLED",
                    True,
                ):
                    result = run_graph_rag_sidecar(
                        {
                            "file_id": "file_001",
                            "file_no": "001",
                            "case_id": "case_test",
                            "original_file_name": "rights.pdf",
                        },
                        output_dir,
                        embedding_client=FakeEmbeddingClient(),
                    )

                graph_dir = output_dir / "graph_rag"
                embeddings_exists = (graph_dir / "embeddings.npy").exists()
                chunks = json.loads((graph_dir / "chunks.json").read_text())
                retrieval = json.loads((graph_dir / "retrieval_result.json").read_text())
                debug = json.loads((graph_dir / "build_debug.json").read_text())

        self.assertTrue(embeddings_exists)
        self.assertEqual(result["embedding_status"], "success")
        self.assertEqual(debug["embedding_model"], "fake-bge-small-zh")
        self.assertGreaterEqual(len(chunks["chunks"]), 3)
        self.assertTrue(retrieval["vector_context_blocks"])
        self.assertIn("股息", "\n".join(block["query"] for block in retrieval["vector_context_blocks"]))
        self.assertTrue(
            any(
                block.get("retrieval_method") == "vector"
                for block in retrieval["context_blocks"]
            )
        )

    def test_embedding_disabled_still_writes_chunks_without_loading_model(self):
        from app.pipeline.graph_rag_sidecar import run_graph_rag_sidecar
        from app.services import local_store

        with TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            output_dir = project_root / "data/cases/case_test/account_info/processed/file_001"
            with patch.object(local_store, "PROJECT_ROOT", project_root):
                local_store.save_json(
                    output_dir / "document_structure.json",
                    _document_structure(),
                )

                with patch(
                    "app.pipeline.graph_rag_sidecar.GRAPH_RAG_EMBEDDING_ENABLED",
                    False,
                ):
                    result = run_graph_rag_sidecar(
                        {
                            "file_id": "file_001",
                            "file_no": "001",
                            "case_id": "case_test",
                            "original_file_name": "statement.pdf",
                        },
                        output_dir,
                    )

                graph_dir = output_dir / "graph_rag"
                embeddings_exists = (graph_dir / "embeddings.npy").exists()
                chunks = json.loads((graph_dir / "chunks.json").read_text())

        self.assertEqual(result["embedding_status"], "disabled")
        self.assertTrue(chunks["chunks"])
        self.assertFalse(embeddings_exists)


def _document_structure():
    return {
        "pages": [
            {
                "page_no": 1,
                "tables": [
                    {
                        "table_index": 1,
                        "rows": [
                            {
                                "row_id": "p001_t001_r001",
                                "cells": [
                                    {"text": "业务日期"},
                                    {"text": "证券账号"},
                                    {"text": "证券代码"},
                                    {"text": "证券名称"},
                                    {"text": "业务标志名称"},
                                    {"text": "成交数量"},
                                    {"text": "成交价格"},
                                    {"text": "清算金额"},
                                    {"text": "流水号"},
                                ],
                            },
                            {
                                "row_id": "p001_t001_r018",
                                "bbox": [10, 80, 500, 100],
                                "cells": [
                                    {"text": "2022-01-05"},
                                    {"text": "A315570738"},
                                    {"text": "688262"},
                                    {"text": "国芯科技"},
                                    {"text": "新股入账"},
                                    {"text": "500.0000"},
                                    {"text": "41.9800"},
                                    {"text": "0.0000"},
                                    {"text": "802777974"},
                                ],
                            },
                        ],
                    }
                ],
            }
        ],
        "sources": {"document_structure_path": "document_structure.json"},
    }


def _chinaclear_rights_document_structure():
    header = [
        "序号",
        "证券代码",
        "证券简称",
        "证券类别",
        "权益类别",
        "过户日期",
        "过户类型",
        "过户数量",
        "期末余额",
        "成交价格",
        "交易单元号",
        "结算参与人简称",
    ]
    rows = [
        header,
        [
            "1",
            "113641",
            "华友转债",
            "固定收益类",
            "2025 第一次 兑息",
            "2025-02-21",
            "权益登记",
            "2,000",
            "2,000",
            "0",
            "23206",
            "广发证券公司客户",
        ],
        [
            "2",
            "113641",
            "华友转债",
            "固定收益类",
            "2025 第一次 兑息",
            "2025-02-21",
            "权益挂牌",
            "-2,000",
            "0",
            "0.6",
            "23206",
            "广发证券公司客户",
        ],
        [
            "3",
            "600794",
            "保税科技",
            "无限售流通股",
            "",
            "2025-04-24",
            "交易过户",
            "-8,000",
            "16,400",
            "5.86",
            "23206",
            "广发证券公司客户",
        ],
    ]
    return {
        "pages": [
            {
                "page_no": 1,
                "tables": [
                    {
                        "table_index": 1,
                        "rows": [
                            {
                                "row_id": f"p001_t001_r{index:03d}",
                                "cells": [{"text": cell} for cell in row],
                            }
                            for index, row in enumerate(rows, start=1)
                        ],
                    }
                ],
            }
        ],
        "sources": {"document_structure_path": "document_structure.json"},
    }


if __name__ == "__main__":
    unittest.main()
