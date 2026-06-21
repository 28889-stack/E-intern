import sys
from tempfile import TemporaryDirectory
import unittest
from pathlib import Path


API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


class FinalProblemEventsTest(unittest.TestCase):
    def test_exact_duplicate_like_events_are_merged_with_trace(self):
        from app.pipeline.case_event_resolver import resolve_case_events

        base_row = {
            "file_id": "file_001",
            "file_no": "001",
            "original_file_name": "statement.pdf",
            "account_type": "A股",
            "securities_account": "A123",
            "event_type": "ordinary_trade",
            "event_date": "2026-01-01",
            "security_code": "600000",
            "security_name": "浦发银行",
            "direction": "buy",
            "quantity_raw": "100",
            "price_raw": "10",
            "amount_raw": "-1000",
            "balance_after_raw": "100",
        }
        resolved = resolve_case_events(
            [
                dict(
                    base_row,
                    event_id="event_001",
                    row_nos="1",
                    source_evidence=[
                        {
                            "file_id": "file_001",
                            "file_no": "001",
                            "file_name": "statement.pdf",
                            "source_row_id": "event_001",
                            "row_no": "1",
                        }
                    ],
                ),
                dict(
                    base_row,
                    event_id="event_002",
                    row_nos="2",
                    source_evidence=[
                        {
                            "file_id": "file_001",
                            "file_no": "001",
                            "file_name": "statement.pdf",
                            "source_row_id": "event_002",
                            "row_no": "2",
                        }
                    ],
                ),
            ]
        )

        self.assertEqual(len(resolved["full_transaction_rows"]), 1)
        self.assertEqual(len(resolved["final_declaration_rows"]), 1)
        self.assertEqual(len(resolved["merge_audit"]), 1)
        evidence = resolved["full_transaction_rows"][0]["source_evidence"]
        self.assertEqual(
            {item["source_row_id"] for item in evidence},
            {"event_001", "event_002"},
        )

    def test_unknown_event_creates_one_review_issue(self):
        from app.pipeline.case_event_resolver import resolve_case_events

        resolved = resolve_case_events(
            [
                {
                    "file_id": "file_001",
                    "file_no": "001",
                    "original_file_name": "statement.pdf",
                    "account_type": "A股",
                    "securities_account": "A123",
                    "event_id": "event_001",
                    "event_type": "unknown_event",
                    "event_date": "2026-01-01",
                    "security_code": "600000",
                    "security_name": "浦发银行",
                }
            ],
            review_items=[
                {
                    "severity": "warning",
                    "item_type": "event",
                    "file_id": "file_001",
                    "event_id": "event_001",
                    "field": "event_type",
                    "message": "无法判断该变动类型是否影响持仓，已保留在完整表并排除出最终申报表",
                }
            ],
        )

        self.assertEqual(len(resolved["review_issue_rows"]), 1)
        self.assertEqual(resolved["full_transaction_rows"], [])
        self.assertIn("无法判断事件类型", resolved["review_issue_rows"][0]["待复核原因"])
        self.assertIn("未知事件", resolved["review_issue_rows"][0]["问题描述"])
        self.assertIn("600000 浦发银行", resolved["review_issue_rows"][0]["问题描述"])
        self.assertNotIn("problem_list_rows", resolved)

    def test_reviewed_excel_payload_has_review_issues_and_scoped_source_columns(self):
        from app.pipeline.final_excel_exporter import _build_sheet_payloads

        payloads = _build_sheet_payloads(
            {
                "review_data": {
                    "最终申报表": [
                        {
                            "账户类型": "A股",
                            "证券账号": "001",
                            "证券代码": "600000",
                            "证券名称": "浦发银行",
                            "变动类型": "买入",
                            "起始日期": "2026-01-01",
                            "终止日期": "2026-01-31",
                            "日期": "2026-01-01",
                            "成交数量": "100",
                            "成交单价": "10",
                            "收付金额": "-1000",
                            "数据来源": "不应导出",
                            "_meta": {"file_id": "file_001"},
                        }
                    ],
                    "完整表": [
                        {
                            "账户类型": "A股",
                            "证券账号": "001",
                            "证券代码": "600000",
                            "证券名称": "浦发银行",
                            "变动类型": "买入",
                            "日期": "2026-01-01",
                            "成交数量": "100",
                            "成交单价": "10",
                            "收付金额": "-1000",
                            "数据来源": "file_001.pdf 第1页",
                            "_meta": {"file_id": "file_001"},
                        }
                    ],
                    "待复核问题": [
                        {
                            "序号": "1",
                            "待复核原因": "缺少证券账号",
                            "问题描述": "交易/事件记录 event_001 缺少证券账号。",
                            "对应材料": "file_001.pdf 第1页",
                            "_meta": {"file_id": "file_001"},
                        }
                    ],
                    "持仓": [],
                    "身份信息": {},
                    "checklist结果": [],
                }
            }
        )

        sheets = {payload["name"]: payload["matrix"] for payload in payloads}
        self.assertEqual(
            list(sheets),
            ["最终申报表", "完整表", "待复核问题", "持仓", "身份信息", "checklist结果"],
        )
        self.assertNotIn("数据来源", sheets["最终申报表"][0])
        self.assertIn("数据来源", sheets["完整表"][0])
        self.assertIn("起始日期", sheets["完整表"][0])
        self.assertIn("终止日期", sheets["完整表"][0])
        self.assertEqual(sheets["待复核问题"][0], ["序号", "待复核原因", "问题描述", "对应材料"])
        self.assertNotIn("问题ID", sheets["待复核问题"][0])
        self.assertNotIn("_meta", sheets["完整表"][0])

    def test_review_data_preserves_review_issues(self):
        from app.pipeline.final_review import build_review_data_from_final_result

        review_data = build_review_data_from_final_result(
            "case_test",
            {
                "source_extract_results": [
                    {"file_id": "file_001", "source_type": "chinaclear"}
                ],
                "sheets": {
                    "最终申报表": {"rows": []},
                    "完整表": {"rows": []},
                    "待复核问题": {
                        "rows": [
                            {
                                "序号": "1",
                                "待复核原因": "缺少证券账号",
                                "问题描述": "交易/事件记录 event_001 缺少证券账号。",
                                "对应材料": "file_001.pdf 第1页",
                                "_meta": {
                                    "file_id": "file_001",
                                    "source_type": "chinaclear",
                                    "source_row_id": "event_001",
                                    "original_row": {"event_id": "event_001"},
                                },
                            }
                        ]
                    },
                    "持仓": {"rows": []},
                    "身份信息": {"rows": []},
                    "checklist结果": {"rows": []},
                },
            },
        )

        self.assertIn("待复核问题", review_data)
        self.assertEqual(review_data["待复核问题"][0]["序号"], "1")
        self.assertEqual(review_data["待复核问题"][0]["对应材料"], "file_001.pdf 第1页")
        self.assertEqual(review_data["待复核问题"][0]["_meta"]["file_id"], "file_001")
        self.assertEqual(review_data["待复核问题"][0]["_meta"]["source_type"], "chinaclear")

    def test_column_selection_preserves_row_meta(self):
        from app.pipeline.final_result_builder import _select_columns

        selected = _select_columns(
            {
                "序号": "1",
                "对应材料": "file_001.pdf 第1页",
                "_meta": {
                    "file_id": "file_001",
                    "source_row_id": "event_001",
                },
            },
            ["序号", "对应材料"],
        )

        self.assertEqual(selected["_meta"]["file_id"], "file_001")

    def test_machine_final_excel_payload_uses_chinese_review_columns(self):
        from app.pipeline.final_excel_exporter import _build_sheet_payloads

        payloads = _build_sheet_payloads(
            {
                "case_id": "case_test",
                "source_extract_results": [
                    {"file_id": "file_001", "source_type": "chinaclear"}
                ],
                "sheet_order": ["最终申报表", "完整表", "待复核问题", "持仓", "身份信息", "checklist结果"],
                "sheets": {
                    "最终申报表": {
                        "columns": ["account_type", "data_source"],
                        "rows": [{"account_type": "A股", "data_source": "不应导出"}],
                    },
                    "完整表": {
                        "columns": ["account_type", "data_source"],
                        "rows": [{"account_type": "A股", "data_source": "source-a"}],
                    },
                    "待复核问题": {
                        "columns": ["序号", "对应材料"],
                        "rows": [{"序号": "1", "对应材料": "source-a"}],
                    },
                    "持仓": {"columns": [], "rows": []},
                    "身份信息": {"columns": [], "rows": []},
                    "checklist结果": {"columns": [], "rows": []},
                },
            }
        )

        sheets = {payload["name"]: payload["matrix"] for payload in payloads}
        self.assertIn("账户类型", sheets["最终申报表"][0])
        self.assertNotIn("account_type", sheets["最终申报表"][0])
        self.assertNotIn("数据来源", sheets["最终申报表"][0])
        self.assertIn("数据来源", sheets["完整表"][0])

    def test_review_reasons_include_review_issues(self):
        from app.pipeline.final_result_builder import _review_reasons_from_final_result

        reasons = _review_reasons_from_final_result(
            {
                "review_items": [
                    {
                        "message": "抽取状态为 failed，需人工复核",
                    }
                ],
                "sheets": {
                    "待复核问题": {
                        "rows": [
                            {
                                "序号": "1",
                                "待复核原因": "缺少证券账号",
                                "问题描述": "交易/事件记录 event_001 缺少证券账号。",
                                "对应材料": "source-a",
                            }
                        ]
                    }
                },
            }
        )

        self.assertIn("抽取状态为 failed，需人工复核", reasons)
        self.assertIn("交易/事件记录 event_001 缺少证券账号。", reasons)

    def test_checklist_is_exempt_when_trade_or_holding_data_is_absent(self):
        from app.pipeline.final_result_builder import _build_checklist_rows

        no_material = _build_checklist_rows([], [])
        no_holding = _build_checklist_rows(
            [
                {
                    "event_type": "ordinary_trade",
                    "securities_account": "001",
                    "event_date": "2026-01-01",
                }
            ],
            [],
        )

        self.assertEqual(no_material[0]["状态"], "无需校验")
        self.assertEqual(no_holding[0]["状态"], "无需校验")

    def test_review_issue_rows_include_related_file_id_and_metadata(self):
        from app.pipeline.case_event_resolver import resolve_case_events

        resolved = resolve_case_events(
            [],
            review_items=[
                {
                    "severity": "warning",
                    "item_type": "extract_result",
                    "file_id": "file_001",
                    "file_no": "001",
                    "original_file_name": "申报2.jpg",
                    "field": "guangfa",
                    "message": "广发抽取结果为空",
                }
            ],
        )

        row = resolved["review_issue_rows"][0]
        self.assertEqual(row["序号"], "1")
        self.assertIn("广发材料", row["待复核原因"])
        self.assertIn("广发抽取结果为空", row["问题描述"])
        self.assertEqual(row["对应材料"], "001 申报2.jpg")
        self.assertEqual(row["_meta"]["file_id"], "file_001")

    def test_guangfa_empty_trade_query_becomes_no_trade_record_event(self):
        from app.pipeline.case_event_resolver import resolve_case_events
        from app.pipeline.normalizers.guangfa_normalizer import normalize_guangfa
        from app.services import local_store

        with TemporaryDirectory() as temp_dir:
            ocr_path = Path(temp_dir) / "ocr_result.json"
            local_store.save_json(
                ocr_path,
                {
                    "page_results": [
                        {
                            "page": 1,
                            "text": "多帐号 15659218\n历史成交\n起始日期：2024-01-01\n终止日期：2024-12-20\n共0条\n没有相应的查询信息！",
                        }
                    ]
                },
            )
            normalized = normalize_guangfa(
                "case_test",
                {
                    "document_info": {"file_name": "申报2.jpg"},
                    "trade_group": {"columns": [], "trades": []},
                    "position_group": {"columns": [], "positions": []},
                    "transactions": [],
                    "events": [],
                    "other_events": [],
                    "cash_flows": [],
                    "holdings": [],
                    "input_sources": {"ocr_result_path": str(ocr_path)},
                },
                {
                    "file_id": "file_001",
                    "file_no": "001",
                    "original_file_name": "申报2.jpg",
                },
            )

        self.assertEqual(len(normalized["full_transaction_rows"]), 1)
        row = normalized["full_transaction_rows"][0]
        self.assertEqual(row["event_type"], "no_trade_record")
        self.assertEqual(row["securities_account"], "15659218")
        self.assertEqual(row["event_date"], "2024-12-20")
        self.assertEqual(row["security_code"], "0")
        self.assertEqual(row["quantity_raw"], "0")
        self.assertEqual(len(normalized["final_declaration_rows"]), 1)
        self.assertEqual(normalized["review_items"], [])

        resolved = resolve_case_events(
            normalized["full_transaction_rows"],
            review_items=normalized["review_items"],
        )
        self.assertEqual(len(resolved["full_transaction_rows"]), 1)
        self.assertEqual(len(resolved["final_declaration_rows"]), 1)
        self.assertEqual(resolved["review_issue_rows"], [])

    def test_chinaclear_empty_holding_semantics_becomes_no_holding_record_event(self):
        from app.pipeline.case_event_resolver import resolve_case_events
        from app.pipeline.normalizers.chinaclear_normalizer import normalize_chinaclear

        normalized = normalize_chinaclear(
            "case_test",
            {
                "document_info": {
                    "file_name": "chinaclear.pdf",
                    "document_type": "holding_snapshot",
                    "period_end": "2024-12-31",
                    "securities_account": "A123456789",
                },
                "trade_group": {"trade_columns": [], "trades": []},
                "other_events": [],
                "holdings": [],
                "input_text": "投资者证券持有信息\n证券账户 A123456789\n查询日期：2024-12-31\n无持仓",
            },
            {
                "file_id": "file_002",
                "file_no": "002",
                "original_file_name": "chinaclear.pdf",
            },
        )

        row = normalized["full_transaction_rows"][0]
        self.assertEqual(row["event_type"], "no_holding_record")
        self.assertEqual(row["securities_account"], "A123456789")
        self.assertEqual(row["event_date"], "2024-12-31")
        self.assertEqual(row["security_code"], "0")
        self.assertEqual(row["quantity_raw"], "0")
        self.assertEqual(len(normalized["final_declaration_rows"]), 1)

        resolved = resolve_case_events(normalized["full_transaction_rows"])
        self.assertEqual(len(resolved["final_declaration_rows"]), 1)
        self.assertEqual(resolved["review_issue_rows"], [])

    def test_no_account_semantics_becomes_final_result_event(self):
        from app.pipeline.case_event_resolver import resolve_case_events
        from app.pipeline.normalizers.chinaclear_normalizer import normalize_chinaclear

        normalized = normalize_chinaclear(
            "case_test",
            {
                "document_info": {
                    "file_name": "account_status.pdf",
                    "document_type": "account_status",
                    "period_end": "2024-12-31",
                },
                "trade_group": {"trade_columns": [], "trades": []},
                "other_events": [],
                "holdings": [],
                "input_text": "证券账户开户状态查询\n查询日期：2024-12-31\n未开立证券账户",
            },
            {
                "file_id": "file_004",
                "file_no": "004",
                "original_file_name": "account_status.pdf",
            },
        )

        self.assertEqual(len(normalized["full_transaction_rows"]), 1)
        row = normalized["full_transaction_rows"][0]
        self.assertEqual(row["event_type"], "no_account_record")
        self.assertEqual(row["securities_account"], "未开立")
        self.assertEqual(row["event_date"], "2024-12-31")
        self.assertEqual(row["transfer_type_raw"], "未开立账户")
        self.assertEqual(len(normalized["final_declaration_rows"]), 1)

        resolved = resolve_case_events(normalized["full_transaction_rows"])
        self.assertEqual(len(resolved["final_declaration_rows"]), 1)
        self.assertEqual(resolved["review_issue_rows"], [])

    def test_no_account_without_period_requires_review_but_not_account_review(self):
        from app.pipeline.case_event_resolver import resolve_case_events
        from app.pipeline.normalizers.chinaclear_normalizer import normalize_chinaclear

        normalized = normalize_chinaclear(
            "case_test",
            {
                "document_info": {"file_name": "account_status.pdf"},
                "trade_group": {"trade_columns": [], "trades": []},
                "other_events": [],
                "holdings": [],
                "input_text": "未开立证券账户",
            },
            {
                "file_id": "file_005",
                "file_no": "005",
                "original_file_name": "account_status.pdf",
            },
        )

        resolved = resolve_case_events(normalized["full_transaction_rows"])
        self.assertEqual(len(resolved["review_issue_rows"]), 1)
        issue = resolved["review_issue_rows"][0]
        self.assertIn("查询日期/期间", issue["待复核原因"])
        self.assertNotIn("证券账号", issue["待复核原因"])

    def test_empty_record_without_account_or_period_requires_review(self):
        from app.pipeline.case_event_resolver import resolve_case_events
        from app.pipeline.normalizers.chinaclear_normalizer import normalize_chinaclear

        normalized = normalize_chinaclear(
            "case_test",
            {
                "document_info": {"file_name": "chinaclear.pdf"},
                "trade_group": {"trade_columns": [], "trades": []},
                "other_events": [],
                "holdings": [],
                "input_text": "投资者证券持有信息\n无持仓",
            },
            {
                "file_id": "file_003",
                "file_no": "003",
                "original_file_name": "chinaclear.pdf",
            },
        )

        resolved = resolve_case_events(normalized["full_transaction_rows"])
        self.assertEqual(len(resolved["review_issue_rows"]), 1)
        issue = resolved["review_issue_rows"][0]
        self.assertEqual(issue["_meta"]["file_id"], "file_003")
        self.assertIn("证券账号", issue["待复核原因"])
        self.assertIn("查询日期/期间", issue["待复核原因"])
        self.assertNotIn("empty_record", issue["待复核原因"])

    def test_review_issue_rows_use_chinese_display_values(self):
        from app.pipeline.case_event_resolver import resolve_case_events

        resolved = resolve_case_events(
            [
                {
                    "file_id": "file_001",
                    "file_no": "001",
                    "original_file_name": "statement.pdf",
                    "event_id": "event_001",
                    "event_type": "unknown_event",
                    "event_date": "2026-01-01",
                    "security_code": "600000",
                    "security_name": "浦发银行",
                }
            ]
        )

        issue = resolved["review_issue_rows"][0]
        self.assertEqual(issue["序号"], "1")
        self.assertIn("缺少必填字段", issue["待复核原因"])
        self.assertIn("缺少证券账号", issue["待复核原因"])
        self.assertIn("缺少账户类型", issue["待复核原因"])
        self.assertIn("无法判断事件类型", issue["待复核原因"])
        self.assertIn("账户类型", issue["问题描述"])
        self.assertIn("证券账号", issue["问题描述"])
        self.assertIn("变动类型", issue["问题描述"])
        for key in ("待复核原因", "问题描述"):
            self.assertNotRegex(issue[key], r"[A-Za-z_]{2,}")

    def test_pending_review_events_are_not_duplicated_in_complete_table(self):
        from app.pipeline.case_event_resolver import resolve_case_events

        resolved = resolve_case_events(
            [
                {
                    "file_id": "file_001",
                    "file_no": "001",
                    "original_file_name": "statement.pdf",
                    "event_id": "event_001",
                    "event_type": "ordinary_trade",
                    "event_date": "2026-01-01",
                    "security_code": "600000",
                    "security_name": "浦发银行",
                    "direction": "buy",
                    "quantity_raw": "100",
                    "price_raw": "10",
                    "amount_raw": "-1000",
                    "source_evidence": [
                        {
                            "file_id": "file_001",
                            "file_no": "001",
                            "file_name": "statement.pdf",
                            "source_row_id": "event_001",
                            "source_page": "2",
                            "row_no": "5",
                        }
                    ],
                }
            ]
        )

        self.assertEqual(resolved["full_transaction_rows"], [])
        self.assertEqual(resolved["final_declaration_rows"], [])
        self.assertEqual(len(resolved["review_issue_rows"]), 1)
        issue = resolved["review_issue_rows"][0]
        self.assertEqual(issue["对应材料"], "001 statement.pdf 第2页 行5")
        self.assertIn("交易/事件记录", issue["问题描述"])
        self.assertIn("买入", issue["问题描述"])
        self.assertIn("浦发银行", issue["问题描述"])

    def test_pending_review_holdings_are_not_duplicated_in_holding_table(self):
        from app.pipeline.case_event_resolver import resolve_case_events

        resolved = resolve_case_events(
            [],
            holding_rows=[
                {
                    "file_id": "file_002",
                    "file_no": "002",
                    "original_file_name": "holding.pdf",
                    "holding_id": "holding_001",
                    "holding_date": "2026-01-01",
                    "security_code": "600000",
                    "security_name": "浦发银行",
                    "quantity_raw": "100",
                    "source_evidence": [
                        {
                            "file_id": "file_002",
                            "file_no": "002",
                            "file_name": "holding.pdf",
                            "source_row_id": "holding_001",
                            "source_page": "1",
                        }
                    ],
                }
            ],
        )

        self.assertEqual(resolved["holding_rows"], [])
        self.assertEqual(len(resolved["review_issue_rows"]), 1)
        self.assertIn("持仓记录", resolved["review_issue_rows"][0]["问题描述"])
        self.assertIn("浦发银行", resolved["review_issue_rows"][0]["问题描述"])


if __name__ == "__main__":
    unittest.main()
