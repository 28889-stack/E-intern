import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


class FileIssueSummaryTest(unittest.TestCase):
    def test_ocr_quality_checker_detects_large_scribble_occlusion(self):
        from PIL import Image, ImageDraw

        from app.pipeline.ocr_quality_checker import inspect_ocr_quality

        with TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "scribbled.png"
            image = Image.new("RGB", (900, 1200), "white")
            draw = ImageDraw.Draw(image)
            for row in range(120, 900, 40):
                draw.text((80, row), "2026-01-01 600000 100 10.00 1000.00", fill="black")
            for offset in range(0, 6):
                draw.line(
                    [(30, 360 + offset * 18), (820, 760 + offset * 28)],
                    fill="black",
                    width=26,
                )
            image.save(image_path)

            quality = inspect_ocr_quality(image_path, route_type="image")

        self.assertTrue(quality["manual_review_required"])
        self.assertIn("suspected_occlusion", quality["issue_types"])
        self.assertTrue(quality["quality_issues"])
        self.assertIn("遮挡或涂抹", quality["review_reasons"][0])

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
                        "quality_issues": [
                            {
                                "issue_type": "suspected_occlusion",
                                "severity": "warning",
                                "message": "材料存在大面积遮挡或涂抹。",
                            }
                        ],
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
            "suspected_occlusion",
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

    def test_material_validity_flags_account_material_missing_context(self):
        from app.pipeline.material_validity_checker import collect_material_validity_issues
        from app.services import local_store

        with TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "processed/file_001"
            local_store.save_json(
                output_dir / "ocr_result.json",
                {
                    "ocr_status": "success",
                    "page_results": [
                        {
                            "page": 1,
                            "text": "广发证券 金融终端 历史成交 查询 输出 共0条",
                        }
                    ],
                },
            )

            issues = collect_material_validity_issues(
                {
                    "file_id": "file_001",
                    "module": "account_info",
                    "content_type": "guangfa",
                },
                output_dir,
                {"extract_status": "success", "document_info": {}},
                transaction_rows=[],
                holding_rows=[],
            )

        issue_types = {issue["issue_type"] for issue in issues}
        self.assertIn("material_missing_securities_account", issue_types)
        self.assertIn("material_missing_period", issue_types)
        self.assertIn("material_missing_market", issue_types)

    def test_material_validity_accepts_empty_query_with_account_period_and_market(self):
        from app.pipeline.material_validity_checker import collect_material_validity_issues
        from app.services import local_store

        with TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "processed/file_001"
            local_store.save_json(
                output_dir / "ocr_result.json",
                {
                    "ocr_status": "success",
                    "page_results": [
                        {
                            "page": 1,
                            "text": (
                                "广发证券 历史成交 证券账号 A123456789 "
                                "起始日期：2024-01-01 终止日期：2024-12-31 沪A 共0条"
                            ),
                        }
                    ],
                },
            )

            issues = collect_material_validity_issues(
                {
                    "file_id": "file_001",
                    "module": "account_info",
                    "content_type": "guangfa",
                },
                output_dir,
                {"extract_status": "success", "document_info": {}},
                transaction_rows=[],
                holding_rows=[],
            )

        self.assertEqual(issues, [])

    def test_material_validity_does_not_require_securities_account_for_no_account_proof(self):
        from app.pipeline.material_validity_checker import collect_material_validity_issues
        from app.services import local_store

        with TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "processed/file_001"
            local_store.save_json(
                output_dir / "raw_text.json",
                {
                    "pages": [
                        {
                            "page": 1,
                            "text": "截至2024-12-31，张三未开立证券账户。",
                        }
                    ],
                },
            )

            issues = collect_material_validity_issues(
                {
                    "file_id": "file_001",
                    "module": "account_info",
                    "content_type": "chinaclear",
                },
                output_dir,
                {"extract_status": "success", "document_info": {}},
                transaction_rows=[],
                holding_rows=[],
            )

        self.assertEqual(issues, [])

    def test_build_final_result_adds_ocr_file_issues_to_review_issue_sheet(self):
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
                                "original_file_name": "涂抹材料.png",
                                "module": "account_info",
                                "content_type": "guangfa",
                                "route_type": "image",
                                "output_dir": (
                                    "data/cases/case_test/account_info/processed/file_001"
                                ),
                                "process_status": "ocr_done",
                                "ocr_status": "success",
                                "extract_status": "success",
                            }
                        ]
                    },
                )
                local_store.save_json(
                    output_dir / "ocr_result.json",
                    {
                        "ocr_status": "success",
                        "quality_issues": [
                            {
                                "issue_type": "suspected_occlusion",
                                "severity": "warning",
                                "message": "材料存在大面积遮挡或涂抹。",
                            }
                        ],
                        "page_results": [
                            {"page": 1, "confidence_avg": 0.92, "status": "success"}
                        ],
                    },
                )
                local_store.save_json(
                    output_dir / "extract_result.json",
                    {
                        "file_id": "file_001",
                        "case_id": case_id,
                        "content_type": "guangfa",
                        "source_type": "guangfa",
                        "extract_status": "success",
                        "document_info": {"file_name": "涂抹材料.png"},
                        "trade_group": {"columns": [], "trades": []},
                        "position_group": {"columns": [], "positions": []},
                        "transactions": [],
                        "events": [],
                        "other_events": [],
                        "cash_flows": [],
                        "holdings": [],
                    },
                )

                final_result = build_final_result(case_id)

        rows = final_result["sheets"]["待复核问题"]["rows"]
        ocr_rows = [row for row in rows if row["待复核原因"] == "申报材料问题"]
        self.assertEqual(len(ocr_rows), 1)
        self.assertIn("遮挡或涂抹", ocr_rows[0]["问题描述"])
        self.assertEqual(ocr_rows[0]["对应材料"], "001 涂抹材料.png")

    def test_build_final_result_adds_material_validity_issue_separately(self):
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
                                "original_file_name": "行情终端截图.png",
                                "module": "account_info",
                                "content_type": "guangfa",
                                "route_type": "image",
                                "output_dir": (
                                    "data/cases/case_test/account_info/processed/file_001"
                                ),
                                "process_status": "ocr_done",
                                "ocr_status": "success",
                                "extract_status": "success",
                            }
                        ]
                    },
                )
                local_store.save_json(
                    output_dir / "ocr_result.json",
                    {
                        "ocr_status": "success",
                        "page_results": [
                            {
                                "page": 1,
                                "confidence_avg": 0.93,
                                "status": "success",
                                "text": "广发证券 金融终端 历史成交 共0条 查询 输出",
                            }
                        ],
                    },
                )
                local_store.save_json(
                    output_dir / "extract_result.json",
                    {
                        "file_id": "file_001",
                        "case_id": case_id,
                        "content_type": "guangfa",
                        "source_type": "guangfa",
                        "extract_status": "success",
                        "document_info": {},
                        "trade_group": {"columns": [], "trades": []},
                        "position_group": {"columns": [], "positions": []},
                        "transactions": [],
                        "events": [],
                        "other_events": [],
                        "cash_flows": [],
                        "holdings": [],
                    },
                )

                final_result = build_final_result(case_id)

        file_issue = final_result["file_issues"][0]
        self.assertIn("material_missing_securities_account", file_issue["issue_types"])
        self.assertIn("material_missing_period", file_issue["issue_types"])
        self.assertIn("material_missing_market", file_issue["issue_types"])
        rows = final_result["sheets"]["待复核问题"]["rows"]
        material_rows = [row for row in rows if row["待复核原因"] == "申报材料问题"]
        self.assertEqual(len(material_rows), 1)
        self.assertIn("证券账号", material_rows[0]["问题描述"])
        self.assertEqual(material_rows[0]["对应材料"], "001 行情终端截图.png")

    def test_build_final_result_uses_processed_context_to_fill_market_accounts(self):
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
                        "name": "孙",
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
                                "original_file_name": "广发对账单.pdf",
                                "module": "account_info",
                                "content_type": "guangfa",
                                "route_type": "direct_pdf",
                                "output_dir": (
                                    "data/cases/case_test/account_info/processed/file_001"
                                ),
                                "process_status": "parsed",
                                "extract_status": "success",
                            }
                        ]
                    },
                )
                local_store.save_json(
                    output_dir / "raw_text.json",
                    {
                        "pages": [
                            {
                                "page": 1,
                                "text": (
                                    "基本信息\n"
                                    "账户姓名\n资金账号\n上海A股东卡号\n上海B股东卡号\n"
                                    "深圳A股东卡号\n深圳B股东卡号\n证件类型\n证件号码\n"
                                    "孙\n36914385\nA486746523\n/\n0022608195\n/\n身份证\n1521011965\n"
                                ),
                            }
                        ]
                    },
                )
                local_store.save_json(
                    output_dir / "extract_result.json",
                    {
                        "file_id": "file_001",
                        "case_id": case_id,
                        "content_type": "guangfa",
                        "source_type": "guangfa",
                        "extract_status": "success",
                        "document_info": {
                            "holder_name": "孙",
                            "capital_account": "36914385",
                            "period_start": "2025-01-01",
                            "period_end": "2025-09-24",
                        },
                        "trade_group": {
                            "trade_columns": [
                                "trade_id",
                                "account_type",
                                "securities_account",
                                "trade_date",
                                "trade_time",
                                "serial_no",
                                "capital_account",
                                "security_code",
                                "security_name",
                                "direction",
                                "quantity_raw",
                                "price_raw",
                                "amount_raw",
                                "transfer_type_raw",
                                "source_page",
                                "row_no",
                                "order_no",
                            ],
                            "trades": [
                                [
                                    "gf_sz",
                                    "",
                                    "",
                                    "2025-04-14",
                                    "191115",
                                    "805409415",
                                    "36914385",
                                    "000951",
                                    "中国重汽",
                                    "buy",
                                    "5000.0000",
                                    "18.7400",
                                    "-93716.4400",
                                    "证券买入",
                                    "1",
                                    "124",
                                    "",
                                ],
                                [
                                    "gf_sh",
                                    "",
                                    "",
                                    "2025-07-28",
                                    "192441",
                                    "805456215",
                                    "36914385",
                                    "600958",
                                    "东方证券",
                                    "buy",
                                    "10000.0000",
                                    "11.6700",
                                    "-116720.4800",
                                    "证券买入",
                                    "1",
                                    "234",
                                    "",
                                ],
                                [
                                    "gf_sh_name_only",
                                    "",
                                    "",
                                    "2025-07-29",
                                    "191936",
                                    "807399864",
                                    "36914385",
                                    "",
                                    "东方证券",
                                    "buy",
                                    "5000.00",
                                    "11.6700",
                                    "-113519.9100",
                                    "证券买入",
                                    "1",
                                    "251",
                                    "",
                                ],
                            ],
                        },
                        "position_group": {
                            "position_columns": [
                                "holding_id",
                                "holding_date",
                                "account_type",
                                "securities_account",
                                "security_code",
                                "security_name",
                                "quantity_raw",
                                "source_page",
                                "row_no",
                            ],
                            "positions": [
                                [
                                    "holding_blank",
                                    "2025-09-24",
                                    "",
                                    "",
                                    "",
                                    "",
                                    "",
                                    "1",
                                    "60-66",
                                ]
                            ],
                        },
                    },
                )

                final_result = build_final_result(case_id)

        complete_rows = final_result["sheets"]["完整表"]["rows"]
        china_truck = next(row for row in complete_rows if row["security_name"] == "中国重汽")
        east_securities = next(row for row in complete_rows if row["security_name"] == "东方证券")
        east_name_only = next(
            row for row in complete_rows if row["event_id"] == "807399864"
        )
        self.assertEqual(china_truck["securities_account"], "0022608195")
        self.assertEqual(east_securities["securities_account"], "A486746523")
        self.assertEqual(east_name_only["security_code"], "600958")
        self.assertEqual(east_name_only["securities_account"], "A486746523")

        review_text = "\n".join(
            row["问题描述"] for row in final_result["sheets"]["待复核问题"]["rows"]
        )
        self.assertNotIn("中国重汽", review_text)
        self.assertNotIn("东方证券", review_text)
        self.assertIn("持仓记录", review_text)
        self.assertIn("缺少证券账号", review_text)

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

    def test_multimodal_observation_is_display_context_not_review_issue(self):
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
                    },
                )
                local_store.save_json(
                    case_dir / "files_index.json",
                    {
                        "files": [
                            {
                                "file_id": "file_001",
                                "file_no": "001",
                                "original_file_name": "statement.pdf",
                                "module": "account_info",
                                "content_type": "guangfa",
                                "route_type": "scanned_pdf",
                                "output_dir": (
                                    "data/cases/case_test/account_info/processed/file_001"
                                ),
                                "process_status": "parsed",
                                "ocr_status": "success",
                                "extract_status": "success",
                            }
                        ]
                    },
                )
                local_store.save_json(
                    output_dir / "extract_result.json",
                    {
                        "file_id": "file_001",
                        "case_id": case_id,
                        "source_type": "guangfa",
                        "content_type": "guangfa",
                        "extract_status": "success",
                        "file_summary": {"document_type": "对账单"},
                        "trade_group": {"trades": []},
                        "holding_records": [
                            {
                                "holding_id": "holding_001",
                                "账户类型": "深A",
                                "证券账号": "0012345678",
                                "证券代码": "000001",
                                "证券名称": "平安银行",
                                "持有数量": "100",
                                "市值": "1000.00",
                                "查询结果所属日期": "2026-01-01",
                                "币种": "人民币",
                                "source_evidence": {
                                    "page": "1",
                                    "row_no": "8",
                                    "raw_text": "000001 平安银行 100 1000.00",
                                },
                            }
                        ],
                        "business_events": [],
                        "document_level_review_items": [
                            {
                                "severity": "warning",
                                "item_type": "extract_result",
                                "event_id": "document_level_review_1",
                                "field": "document_level_review_items",
                                "message": "page=2 row_no=/ OCR噪声：第2页存在多处低置信度OCR噪声，可能影响部分业务字段识别。",
                            }
                        ],
                        "multimodal_review": {
                            "multimodal_review_status": "success",
                            "visual_observations": [
                                "页面为资金流水查询结果，包含多条交易记录。"
                            ],
                        },
                    },
                )

                final_result = build_final_result(case_id)

        self.assertEqual(final_result["sheets"]["待复核问题"]["rows"], [])
        self.assertFalse(final_result["summary"]["manual_review_required"])
        self.assertEqual(final_result["file_issues"][0]["issue_types"], [])
        self.assertEqual(final_result["file_issues"][0]["severity"], "normal")
        self.assertIn(
            "页面为资金流水查询结果",
            final_result["file_issues"][0]["multimodal_observations"][0],
        )
        self.assertEqual(final_result["file_issue_summaries"][0]["status"], "通过")

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
