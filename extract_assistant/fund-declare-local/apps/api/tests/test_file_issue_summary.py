import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


class FileIssueSummaryTest(unittest.TestCase):
    def test_collect_file_issues_from_status_ocr_and_review_issues(self):
        from app.pipeline.file_issue_collector import collect_file_issues
        from app.services import local_store

        with TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            with patch.object(local_store, "PROJECT_ROOT", project_root):
                case_id = "case_test"
                output_dir = (
                    project_root
                    / "data/cases/case_test/account_info/processed/file_001"
                )
                local_store.save_json(
                    output_dir / "process_result.json",
                    {
                        "process_status": "ocr_done",
                        "ocr_status": "success",
                        "extract_status": "success",
                    },
                )
                local_store.save_json(
                    output_dir / "ocr_result.json",
                    {
                        "ocr_status": "success",
                        "page_results": [
                            {"page": 1, "confidence_avg": 0.72, "status": "success"}
                        ],
                    },
                )
                local_store.save_json(
                    output_dir / "extract_result.json",
                    {
                        "extract_status": "json_parse_failed",
                        "review_reasons": ["LLM 输出被截断：finish_reason=length"],
                        "llm_response_metadata": {"finish_reason": "length"},
                    },
                )

                files_index = {
                    "files": [
                        {
                            "file_id": "file_001",
                            "file_no": "001",
                            "original_file_name": "statement.pdf",
                            "module": "account_info",
                            "content_type": "unknown",
                            "route_type": "ocr_image",
                            "output_dir": (
                                "data/cases/case_test/account_info/processed/file_001"
                            ),
                            "process_status": "ocr_done",
                            "ocr_status": "success",
                            "extract_status": "json_parse_failed",
                        }
                    ]
                }
                review_issues = [
                    {
                        "review_issue_id": "复核问题_001",
                        "related_file_ids": ["file_001"],
                        "related_record_id": "event_001",
                        "issue_types": ["missing_required_fields"],
                        "missing_fields": [
                            "event_date",
                            "securities_account",
                            "account_type",
                        ],
                        "message": "缺少关键字段，无法通过自动核验。",
                    }
                ]

                file_issues = collect_file_issues(
                    case_id,
                    files_index,
                    review_issues=review_issues,
                    pending_review_events=[{"file_id": "file_001"} for _ in range(5)],
                )

        self.assertEqual(len(file_issues), 1)
        issue = file_issues[0]
        self.assertEqual(issue["file_id"], "file_001")
        self.assertEqual(issue["severity"], "error")
        for issue_type in [
            "content_type_unknown",
            "ocr_low_confidence",
            "json_parse_failed",
            "llm_output_truncated",
            "missing_date",
            "missing_securities_account",
            "missing_account_type",
            "many_pending_review_items",
        ]:
            self.assertIn(issue_type, issue["issue_types"])
        self.assertIn("复核问题_001", issue["related_problem_ids"])
        self.assertTrue(issue["evidence"])

    def test_file_issue_summarizer_fallback_without_issues_passes(self):
        from app.pipeline.file_issue_summarizer import summarize_file_issues

        result = summarize_file_issues([], [], {"files": []}, llm_client=None)

        self.assertEqual(result["file_issue_summaries"], [])
        self.assertEqual(result["checklist_rows"][0]["checklist条件"], "文件级问题归纳")
        self.assertEqual(result["checklist_rows"][0]["状态"], "通过")
        self.assertIn("未发现文件级 OCR", result["checklist_rows"][0]["说明"])

    def test_file_issue_summarizer_fallback_groups_issues_by_file(self):
        from app.pipeline.file_issue_summarizer import summarize_file_issues

        result = summarize_file_issues(
            [
                {
                    "file_id": "file_001",
                    "file_no": "001",
                    "file_name": "statement.pdf",
                    "severity": "warning",
                    "issue_types": ["ocr_low_confidence", "missing_date"],
                    "evidence": ["OCR 平均置信度 0.72 低于 0.85", "缺失：日期"],
                    "suggested_action": "请核对原文件日期和 OCR 结果。",
                }
            ],
            [],
            {"files": []},
            llm_client=None,
        )

        self.assertEqual(result["checklist_rows"][0]["状态"], "需人工复核")
        summary = result["file_issue_summaries"][0]
        self.assertEqual(summary["file_id"], "file_001")
        self.assertEqual(summary["status"], "需人工复核")
        self.assertIn("OCR", summary["summary"])
        self.assertIn("日期", summary["summary"])

    def test_build_final_result_keeps_file_issues_out_of_legal_checklist(self):
        from app.pipeline.final_result_builder import build_final_result
        from app.services import local_store

        with TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            with patch.object(local_store, "PROJECT_ROOT", project_root):
                case_id = "case_test"
                case_dir = project_root / "data/cases/case_test"
                output_dir = case_dir / "account_info/processed/file_001"
                local_store.save_json(
                    case_dir / "case.json",
                    {
                        "case_id": case_id,
                        "name": "张三",
                        "phone": "13800000000",
                        "relation_type": "custom",
                        "relation_type_label": "员工本人",
                    },
                )
                local_store.save_json(
                    case_dir / "files_index.json",
                    {
                        "files": [
                            {
                                "file_id": "file_001",
                                "file_no": "001",
                                "original_file_name": "unknown.pdf",
                                "module": "account_info",
                                "content_type": "unknown",
                                "route_type": "direct_pdf",
                                "output_dir": (
                                    "data/cases/case_test/account_info/processed/file_001"
                                ),
                                "process_status": "parsed",
                                "ocr_status": "not_required",
                                "extract_status": "skipped",
                            }
                        ]
                    },
                )
                local_store.save_json(
                    output_dir / "extract_result.json",
                    {
                        "file_id": "file_001",
                        "case_id": case_id,
                        "content_type": "unknown",
                        "extract_status": "skipped",
                        "review_reasons": [],
                    },
                )

                final_result = build_final_result(case_id)

        self.assertIn("file_issues", final_result)
        self.assertIn("file_issue_summaries", final_result)
        self.assertTrue(final_result["file_issues"])
        checklist_rows = final_result["sheets"]["checklist结果"]["rows"]
        file_issue_rows = [
            row for row in checklist_rows if row["checklist条件"] == "文件级问题归纳"
        ]
        self.assertEqual(file_issue_rows, [])
        self.assertEqual(checklist_rows[0]["checklist条件"], "上次持仓 + 交易 = 本次持仓")

    def test_reviewed_result_preserves_file_issue_trace(self):
        from app.pipeline.final_review import get_review_payload, save_review_payload
        from app.services import local_store

        with TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            with patch.object(local_store, "PROJECT_ROOT", project_root):
                case_id = "case_test"
                final_dir = project_root / "data/cases/case_test/final"
                local_store.save_json(
                    project_root / "data/cases/case_test/case.json",
                    {
                        "case_id": case_id,
                        "name": "张三",
                        "phone": "13800000000",
                        "relation_type": "custom",
                        "relation_type_label": "员工本人",
                    },
                )
                local_store.save_json(
                    final_dir / "final_result.json",
                    {
                        "case_id": case_id,
                        "source_extract_results": [],
                        "file_issues": [{"file_id": "file_001"}],
                        "file_issue_summaries": [{"file_id": "file_001"}],
                        "sheets": {
                            "最终申报表": {"rows": []},
                            "完整表": {"rows": []},
                            "待复核问题": {"rows": []},
                            "持仓": {"rows": []},
                            "身份信息": {"rows": []},
                            "checklist结果": {
                                "rows": [
                                    {
                                        "checklist条件": "文件级问题归纳",
                                        "状态": "需人工复核",
                                        "说明": "存在文件级问题。",
                                    }
                                ]
                            },
                        },
                    },
                )

                review_payload = get_review_payload(case_id)
                self.assertEqual(review_payload["file_issues"], [{"file_id": "file_001"}])
                self.assertEqual(
                    review_payload["file_issue_summaries"],
                    [{"file_id": "file_001"}],
                )
                self.assertEqual(review_payload["data"]["checklist结果"], [])

                save_review_payload(case_id, {"review_data": {}})
                reviewed = local_store.read_json(
                    final_dir / "reviewed_final_result.json",
                    {},
                )
                reviewed_payload = get_review_payload(case_id)

        self.assertEqual(reviewed["file_issues"], [{"file_id": "file_001"}])
        self.assertEqual(reviewed["file_issue_summaries"], [{"file_id": "file_001"}])
        self.assertEqual(reviewed_payload["file_issues"], [{"file_id": "file_001"}])
        self.assertEqual(
            reviewed_payload["file_issue_summaries"],
            [{"file_id": "file_001"}],
        )
        self.assertEqual(reviewed["review_data"]["checklist结果"], [])


if __name__ == "__main__":
    unittest.main()
