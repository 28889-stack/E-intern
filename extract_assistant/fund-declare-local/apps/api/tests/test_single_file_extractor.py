import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


class SingleFileExtractorTest(unittest.TestCase):
    def test_rerun_extract_restores_successful_process_status_from_disk(self):
        from app.pipeline.single_file_extractor import extract_single_file
        from app.services import local_store

        with TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            case_id = "case_test"
            output_dir = project_root / "data/cases/case_test/account_info/processed/file_001"
            file_record = {
                "file_id": "file_001",
                "file_no": "001",
                "case_id": case_id,
                "original_file_name": "statement.pdf",
                "output_dir": "data/cases/case_test/account_info/processed/file_001",
                "content_type": "chinaclear",
                "route_type": "direct_pdf",
                "process_status": "failed",
                "extract_status": "failed",
                "manual_review_required": True,
                "review_reasons": ["文件处理失败：旧的抽取异常"],
            }

            with patch.object(local_store, "PROJECT_ROOT", project_root):
                local_store.save_json(
                    project_root / "data/cases/case_test/files_index.json",
                    {"files": [dict(file_record)]},
                )
                local_store.save_json(
                    output_dir / "process_result.json",
                    {
                        "process_status": "parsed",
                        "route_type": "direct_pdf",
                        "ocr_status": "not_required",
                        "extract_status": "success",
                        "manual_review_required": False,
                        "review_reasons": [],
                    },
                )
                local_store.save_json(
                    output_dir / "content_classification.json",
                    {
                        "content_type": "chinaclear",
                        "content_classify_status": "success",
                        "manual_review_required": False,
                        "review_reasons": [],
                    },
                )

                with patch(
                    "app.pipeline.single_file_extractor.ChinaclearExtractor.extract",
                    return_value={
                        "extract_status": "success",
                        "manual_review_required": False,
                        "review_reasons": [],
                    },
                ):
                    extract_single_file(case_id, file_record)

                updated = local_store.read_files_index(case_id)["files"][0]

        self.assertEqual(updated["process_status"], "parsed")
        self.assertEqual(updated["ocr_status"], "not_required")
        self.assertEqual(updated["content_classify_status"], "success")
        self.assertEqual(updated["extract_status"], "success")
        self.assertFalse(updated["manual_review_required"])
        self.assertEqual(updated["review_reasons"], [])

    def test_multimodal_review_sidecar_runs_only_when_enabled(self):
        from app.pipeline.single_file_extractor import extract_single_file
        from app.services import local_store

        with TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            case_id = "case_test"
            output_dir = project_root / "data/cases/case_test/account_info/processed/file_001"
            raw_dir = project_root / "data/cases/case_test/account_info/raw"
            raw_dir.mkdir(parents=True)
            stored_path = raw_dir / "001_statement.pdf"
            stored_path.write_bytes(b"%PDF-1.4")
            file_record = {
                "file_id": "file_001",
                "file_no": "001",
                "case_id": case_id,
                "original_file_name": "statement.pdf",
                "storage_path": "data/cases/case_test/account_info/raw/001_statement.pdf",
                "output_dir": "data/cases/case_test/account_info/processed/file_001",
                "content_type": "identity",
                "route_type": "direct_pdf",
            }

            with patch.object(local_store, "PROJECT_ROOT", project_root):
                local_store.save_json(
                    project_root / "data/cases/case_test/files_index.json",
                    {"files": [dict(file_record)]},
                )
                with patch(
                    "app.pipeline.single_file_extractor.run_multimodal_review_sidecar"
                ) as sidecar:
                    sidecar.return_value = {"multimodal_review_status": "skipped"}
                    with patch(
                        "app.pipeline.single_file_extractor.ENABLE_MULTIMODAL_REVIEW",
                        False,
                    ):
                        result = extract_single_file(case_id, file_record)
                    sidecar.assert_not_called()
                    self.assertNotIn("multimodal_review", result)

                with patch(
                    "app.pipeline.single_file_extractor.run_multimodal_review_sidecar"
                ) as sidecar:
                    sidecar.return_value = {
                        "multimodal_review_status": "no_difficult_blocks",
                        "multimodal_review_hints_path": "hint.json",
                    }
                    with patch(
                        "app.pipeline.single_file_extractor.ENABLE_MULTIMODAL_REVIEW",
                        True,
                    ):
                        result = extract_single_file(case_id, file_record)
                    sidecar.assert_called_once()
                    self.assertEqual(
                        result["multimodal_review"]["multimodal_review_status"],
                        "no_difficult_blocks",
                    )

    def test_graph_rag_sidecar_runs_for_account_material_and_trace_is_saved(self):
        from app.pipeline.single_file_extractor import extract_single_file
        from app.services import local_store

        with TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            case_id = "case_test"
            output_dir = project_root / "data/cases/case_test/account_info/processed/file_001"
            file_record = {
                "file_id": "file_001",
                "file_no": "001",
                "case_id": case_id,
                "original_file_name": "statement.pdf",
                "output_dir": "data/cases/case_test/account_info/processed/file_001",
                "content_type": "guangfa",
                "route_type": "direct_pdf",
            }

            with patch.object(local_store, "PROJECT_ROOT", project_root):
                local_store.save_json(
                    project_root / "data/cases/case_test/files_index.json",
                    {"files": [dict(file_record)]},
                )
                with patch(
                    "app.pipeline.single_file_extractor.run_graph_rag_sidecar",
                    return_value={
                        "graph_rag_status": "success",
                        "graph_path": "data/cases/case_test/account_info/processed/file_001/graph_rag/graph.json",
                        "retrieval_result_path": "data/cases/case_test/account_info/processed/file_001/graph_rag/retrieval_result.json",
                    },
                ) as sidecar:
                    with patch(
                        "app.pipeline.single_file_extractor.GuangfaExtractor.extract",
                        return_value={
                            "extract_status": "success",
                            "manual_review_required": False,
                            "review_reasons": [],
                        },
                    ):
                        result = extract_single_file(case_id, file_record)

                sidecar.assert_called_once()
                saved = local_store.read_json(output_dir / "extract_result.json")

        self.assertEqual(result["graph_rag_trace"]["graph_rag_status"], "success")
        self.assertEqual(saved["graph_rag_trace"]["graph_rag_status"], "success")
