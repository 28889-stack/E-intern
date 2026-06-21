import sys
import unittest
from pathlib import Path


API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


class GuangfaBusinessEventsTest(unittest.TestCase):
    def setUp(self):
        self.case_id = "case_test"
        self.file_record = {
            "file_id": "file_001",
            "file_no": "001",
            "original_file_name": "广发证券对账单.pdf",
            "content_type": "guangfa",
        }

    def test_business_event_uses_final_field_candidates_and_infers_shenzhen_credit_account(self):
        from app.pipeline.normalizers.guangfa_normalizer import normalize_guangfa

        normalized = normalize_guangfa(
            self.case_id,
            {
                "schema_version": "guangfa_business_event_understanding_v1",
                "source_type": "guangfa",
                "business_events": [
                    {
                        "raw_business_type": "证券买入",
                        "inferred_event_type": "买入",
                        "affects_holding": True,
                        "include_in_full_table": True,
                        "include_in_final_declaration": True,
                        "classification_reason": "业务标志名称为证券买入。",
                        "final_field_candidates": {
                            "账户类型": "",
                            "证券账号": "0612345678",
                            "证券代码": "000951",
                            "证券名称": "中国重汽",
                            "变动类型": "买入",
                            "日期": "2025-09-24",
                            "成交数量": "100",
                            "成交单价": "18.74",
                            "收付金额": "-1874.00",
                        },
                        "source_evidence": {
                            "page": "3",
                            "row_no": "12",
                            "raw_text": "证券买入 中国重汽 100 18.74",
                        },
                    }
                ],
            },
            self.file_record,
        )

        self.assertEqual(len(normalized["full_transaction_rows"]), 1)
        self.assertEqual(len(normalized["final_declaration_rows"]), 1)
        row = normalized["full_transaction_rows"][0]
        self.assertEqual(row["account_type"], "深圳信用账户")
        self.assertEqual(row["securities_account"], "0612345678")
        self.assertEqual(row["security_code"], "000951")
        self.assertEqual(row["security_name"], "中国重汽")
        self.assertEqual(row["event_type"], "ordinary_trade")
        self.assertEqual(row["direction"], "buy")
        self.assertEqual(row["event_date"], "2025-09-24")
        self.assertEqual(row["quantity_raw"], "100")
        self.assertEqual(row["price_raw"], "18.74")
        self.assertEqual(row["amount_raw"], "-1874.00")
        self.assertEqual(row["source_pages"], "3")
        self.assertEqual(row["row_nos"], "12")
        self.assertEqual(normalized["review_items"], [])

    def test_business_event_preserves_time_and_serial_from_source_text(self):
        from app.pipeline.normalizers.guangfa_normalizer import normalize_guangfa

        normalized = normalize_guangfa(
            self.case_id,
            {
                "schema_version": "guangfa_business_event_understanding_v1",
                "source_type": "guangfa",
                "business_events": [
                    {
                        "raw_business_type": "证券买入",
                        "inferred_event_type": "买入",
                        "include_in_full_table": True,
                        "include_in_final_declaration": True,
                        "final_field_candidates": {
                            "账户类型": "深A",
                            "证券账号": "0022608195",
                            "证券代码": "000951",
                            "证券名称": "中国重汽",
                            "变动类型": "买入",
                            "日期": "2025-04-14",
                            "成交数量": "5000.0000",
                            "成交单价": "18.7400",
                            "收付金额": "-93716.4400",
                        },
                        "source_evidence": {
                            "page": 1,
                            "row_no": "场内交割流水明细",
                            "raw_text": "2025-04-14 191115 805409415 36914385 000951 中国重汽 证券买入 5000.0000 18.7400 -93716.4400 人民币 41398",
                        },
                    }
                ],
            },
            self.file_record,
        )

        row = normalized["full_transaction_rows"][0]
        self.assertEqual(row["event_time"], "19:11:15")
        self.assertEqual(row["serial_no"], "805409415")
        self.assertEqual(row["order_no"], "41398")
        self.assertEqual(row["event_id"], "805409415")

    def test_business_event_infers_shanghai_credit_account_from_securities_account(self):
        from app.pipeline.normalizers.guangfa_normalizer import normalize_guangfa

        normalized = normalize_guangfa(
            self.case_id,
            {
                "schema_version": "guangfa_business_event_understanding_v1",
                "source_type": "guangfa",
                "business_events": [
                    {
                        "inferred_event_type": "卖出",
                        "include_in_full_table": True,
                        "include_in_final_declaration": True,
                        "final_field_candidates": {
                            "证券账号": "E123456789",
                            "证券代码": "600000",
                            "证券名称": "浦发银行",
                            "变动类型": "卖出",
                            "日期": "2025-09-24",
                            "成交数量": "200",
                            "成交单价": "9.50",
                            "收付金额": "1900.00",
                        },
                    }
                ],
            },
            self.file_record,
        )

        self.assertEqual(normalized["full_transaction_rows"][0]["account_type"], "上海信用账户")
        self.assertEqual(len(normalized["final_declaration_rows"]), 1)

    def test_fund_account_starting_with_06_is_not_treated_as_securities_account(self):
        from app.pipeline.case_event_resolver import resolve_case_events
        from app.pipeline.normalizers.guangfa_normalizer import normalize_guangfa

        normalized = normalize_guangfa(
            self.case_id,
            {
                "schema_version": "guangfa_business_event_understanding_v1",
                "source_type": "guangfa",
                "business_events": [
                    {
                        "raw_business_type": "证券买入",
                        "inferred_event_type": "买入",
                        "include_in_full_table": True,
                        "include_in_final_declaration": True,
                        "final_field_candidates": {
                            "账户类型": "",
                            "资金账号": "0612345678",
                            "证券账号": "",
                            "证券代码": "000951",
                            "证券名称": "中国重汽",
                            "变动类型": "买入",
                            "日期": "2025-09-24",
                            "成交数量": "100",
                            "成交单价": "18.74",
                            "收付金额": "-1874.00",
                        },
                    }
                ],
            },
            self.file_record,
        )

        row = normalized["full_transaction_rows"][0]
        self.assertEqual(row["securities_account"], "")
        self.assertEqual(row["account_type"], "深A")

        resolved = resolve_case_events(
            normalized["full_transaction_rows"],
            review_items=normalized["review_items"],
        )
        self.assertEqual(len(resolved["full_transaction_rows"]), 1)
        self.assertEqual(len(resolved["final_declaration_rows"]), 0)
        self.assertIn("缺少证券账号", resolved["review_issue_rows"][0]["待复核原因"])

    def test_cash_dividend_is_full_table_only_without_quantity_or_price_review(self):
        from app.pipeline.normalizers.guangfa_normalizer import normalize_guangfa

        normalized = normalize_guangfa(
            self.case_id,
            {
                "schema_version": "guangfa_business_event_understanding_v1",
                "source_type": "guangfa",
                "business_events": [
                    {
                        "raw_business_type": "红利入账",
                        "inferred_event_type": "现金分红",
                        "affects_holding": False,
                        "include_in_full_table": True,
                        "include_in_final_declaration": False,
                        "final_field_candidates": {
                            "账户类型": "沪A",
                            "证券账号": "A123456789",
                            "证券代码": "600000",
                            "证券名称": "浦发银行",
                            "变动类型": "红利入账",
                            "日期": "2025-06-30",
                            "成交数量": "",
                            "成交单价": "",
                            "收付金额": "88.00",
                        },
                    }
                ],
            },
            self.file_record,
        )

        self.assertEqual(len(normalized["full_transaction_rows"]), 1)
        self.assertEqual(len(normalized["final_declaration_rows"]), 0)
        row = normalized["full_transaction_rows"][0]
        self.assertEqual(row["event_type"], "cash_dividend")
        self.assertEqual(row["quantity_raw"], "")
        self.assertEqual(row["price_raw"], "")
        self.assertEqual(normalized["review_items"], [])

    def test_bank_to_securities_transfer_is_ignored(self):
        from app.pipeline.normalizers.guangfa_normalizer import normalize_guangfa

        normalized = normalize_guangfa(
            self.case_id,
            {
                "schema_version": "guangfa_business_event_understanding_v1",
                "source_type": "guangfa",
                "business_events": [
                    {
                        "raw_business_type": "银行转证券",
                        "inferred_event_type": "银行转证券",
                        "affects_holding": False,
                        "include_in_full_table": True,
                        "include_in_final_declaration": False,
                        "final_field_candidates": {
                            "变动类型": "银行转证券",
                            "日期": "2025-01-02",
                            "收付金额": "10000.00",
                        },
                    }
                ],
            },
            self.file_record,
        )

        self.assertEqual(normalized["full_transaction_rows"], [])
        self.assertEqual(normalized["final_declaration_rows"], [])
        self.assertEqual(normalized["review_items"], [])

    def test_interest_capitalization_is_ignored(self):
        from app.pipeline.normalizers.guangfa_normalizer import normalize_guangfa

        normalized = normalize_guangfa(
            self.case_id,
            {
                "schema_version": "guangfa_business_event_understanding_v1",
                "source_type": "guangfa",
                "business_events": [
                    {
                        "raw_business_type": "利息归本",
                        "inferred_event_type": "利息归本",
                        "affects_holding": False,
                        "include_in_full_table": True,
                        "include_in_final_declaration": False,
                        "final_field_candidates": {
                            "变动类型": "利息归本",
                            "日期": "2025-01-02",
                            "收付金额": "1.23",
                        },
                    }
                ],
            },
            self.file_record,
        )

        self.assertEqual(normalized["full_transaction_rows"], [])
        self.assertEqual(normalized["final_declaration_rows"], [])
        self.assertEqual(normalized["review_items"], [])

    def test_legacy_cash_flow_is_ignored(self):
        from app.pipeline.normalizers.guangfa_normalizer import normalize_guangfa

        normalized = normalize_guangfa(
            self.case_id,
            {
                "schema_version": "gf_statement_extract_v1",
                "cash_flows": [
                    {
                        "cash_flow_id": "cash_001",
                        "event_type_raw": "银行转证券",
                        "event_date": "2025-01-02",
                        "amount": "10000.00",
                    }
                ],
            },
            self.file_record,
        )

        self.assertEqual(normalized["full_transaction_rows"], [])
        self.assertEqual(normalized["final_declaration_rows"], [])
        self.assertEqual(normalized["review_items"], [])

    def test_script_exclusion_overrides_llm_final_flag_for_cash_events(self):
        from app.pipeline.normalizers.common import is_final_declaration_row

        self.assertFalse(
            is_final_declaration_row(
                {
                    "event_type": "cash_dividend",
                    "transfer_type_raw": "红利入账",
                    "include_in_final_declaration": True,
                }
            )
        )

    def test_securities_account_and_security_code_market_conflict_creates_review_item(self):
        from app.pipeline.normalizers.guangfa_normalizer import normalize_guangfa

        normalized = normalize_guangfa(
            self.case_id,
            {
                "schema_version": "guangfa_business_event_understanding_v1",
                "source_type": "guangfa",
                "business_events": [
                    {
                        "inferred_event_type": "买入",
                        "include_in_full_table": True,
                        "include_in_final_declaration": True,
                        "final_field_candidates": {
                            "证券账号": "0612345678",
                            "证券代码": "600000",
                            "证券名称": "浦发银行",
                            "变动类型": "买入",
                            "日期": "2025-09-24",
                            "成交数量": "100",
                            "成交单价": "9.50",
                            "收付金额": "-950.00",
                        },
                    }
                ],
            },
            self.file_record,
        )

        self.assertEqual(normalized["full_transaction_rows"][0]["account_type"], "深圳信用账户")
        messages = [item["message"] for item in normalized["review_items"]]
        self.assertIn("证券账号推断账户类型与证券代码市场推断结果不一致", messages)

    def test_ordinary_trade_from_fund_flow_is_full_table_review_not_final(self):
        from app.pipeline.case_event_resolver import resolve_case_events
        from app.pipeline.normalizers.guangfa_normalizer import normalize_guangfa

        normalized = normalize_guangfa(
            self.case_id,
            {
                "schema_version": "guangfa_business_event_understanding_v1",
                "source_type": "guangfa",
                "business_events": [
                    {
                        "raw_business_type": "证券买入",
                        "inferred_event_type": "买入",
                        "include_in_full_table": True,
                        "include_in_final_declaration": True,
                        "final_field_candidates": {
                            "账户类型": "深A",
                            "证券账号": "0022608195",
                            "证券代码": "000951",
                            "证券名称": "中国重汽",
                            "变动类型": "买入",
                            "日期": "2025-04-14",
                            "成交数量": "5000.0000",
                            "成交单价": "18.7400",
                            "收付金额": "-93716.4400",
                        },
                        "source_evidence": {
                            "page": 1,
                            "row_no": "资金流水明细",
                            "raw_text": "资金流水明细 2025-04-14 191115 805409415 证券买入 中国重汽",
                        },
                    }
                ],
            },
            self.file_record,
        )
        resolved = resolve_case_events(
            normalized["full_transaction_rows"],
            review_items=normalized["review_items"],
        )

        self.assertEqual(len(resolved["full_transaction_rows"]), 1)
        self.assertEqual(len(resolved["final_declaration_rows"]), 0)
        self.assertEqual(len(resolved["review_issue_rows"]), 1)
        self.assertIn("资金流水明细", resolved["review_issue_rows"][0]["问题描述"])

    def test_unknown_business_event_stays_in_full_table_and_review_issue_only(self):
        from app.pipeline.case_event_resolver import resolve_case_events
        from app.pipeline.normalizers.guangfa_normalizer import normalize_guangfa

        normalized = normalize_guangfa(
            self.case_id,
            {
                "schema_version": "guangfa_business_event_understanding_v1",
                "source_type": "guangfa",
                "business_events": [
                    {
                        "raw_business_type": "特殊业务",
                        "inferred_event_type": "无法判断",
                        "include_in_full_table": True,
                        "include_in_final_declaration": False,
                        "final_field_candidates": {
                            "账户类型": "深A",
                            "证券账号": "A123456789",
                            "证券代码": "000001",
                            "证券名称": "平安银行",
                            "变动类型": "特殊业务",
                            "日期": "2025-09-24",
                            "成交数量": "",
                            "成交单价": "",
                            "收付金额": "",
                        },
                    }
                ],
            },
            self.file_record,
        )
        resolved = resolve_case_events(
            normalized["full_transaction_rows"],
            review_items=normalized["review_items"],
        )

        self.assertEqual(len(resolved["full_transaction_rows"]), 1)
        self.assertEqual(len(resolved["final_declaration_rows"]), 0)
        self.assertEqual(len(resolved["review_issue_rows"]), 1)
        self.assertIn("无法判断", resolved["review_issue_rows"][0]["待复核原因"])

    def test_old_guangfa_trade_group_still_normalizes(self):
        from app.pipeline.normalizers.guangfa_normalizer import normalize_guangfa

        normalized = normalize_guangfa(
            self.case_id,
            {
                "schema_version": "gf_statement_extract_v1",
                "document_info": {"account_type": "深A", "securities_account": "A123"},
                "trade_group": {
                    "columns": [
                        "event_date",
                        "security_code",
                        "security_name",
                        "direction",
                        "quantity",
                        "price",
                        "amount",
                        "event_type_raw",
                    ],
                    "trades": [
                        [
                            "2025-09-24",
                            "000951",
                            "中国重汽",
                            "buy",
                            "100",
                            "18.74",
                            "-1874.00",
                            "证券买入",
                        ]
                    ],
                },
            },
            self.file_record,
        )

        self.assertEqual(len(normalized["full_transaction_rows"]), 1)
        self.assertEqual(normalized["full_transaction_rows"][0]["security_name"], "中国重汽")

    def test_no_account_info_negative_proof_becomes_final_declaration_row(self):
        from app.pipeline.case_event_resolver import resolve_case_events
        from app.pipeline.normalizers.guangfa_normalizer import normalize_guangfa

        normalized = normalize_guangfa(
            self.case_id,
            {
                "schema_version": "guangfa_business_event_understanding_v1",
                "source_type": "guangfa",
                "negative_proofs": [
                    {
                        "proof_type": "无账户信息",
                        "person_name": "张三",
                        "as_of_date": "2024-12-31",
                        "description": "截至2024-12-31，张三无账户信息。",
                        "source_evidence": {
                            "page": 1,
                            "row_no": "1",
                            "raw_text": "截至2024-12-31，张三无账户信息。",
                        },
                    }
                ],
            },
            self.file_record,
        )
        resolved = resolve_case_events(
            normalized["full_transaction_rows"],
            review_items=normalized["review_items"],
        )

        self.assertEqual(len(resolved["final_declaration_rows"]), 1)
        row = resolved["final_declaration_rows"][0]
        self.assertEqual(row["event_type"], "no_account_info")
        self.assertEqual(row["transfer_type_raw"], "无账户信息")
        self.assertEqual(row["event_date"], "2024-12-31")
        self.assertEqual(row["person_name"], "张三")
        self.assertEqual(row["security_code"], "")
        self.assertEqual(row["quantity_raw"], "")
        self.assertEqual(resolved["review_issue_rows"], [])

    def test_no_account_info_negative_proof_uses_raw_summary_as_evidence(self):
        from app.pipeline.case_event_resolver import resolve_case_events
        from app.pipeline.normalizers.guangfa_normalizer import normalize_guangfa

        normalized = normalize_guangfa(
            self.case_id,
            {
                "schema_version": "guangfa_business_event_understanding_v1",
                "source_type": "guangfa",
                "negative_proofs": [
                    {
                        "proof_type": "无账户信息",
                        "person_name": "张三",
                        "as_of_date": "2024-12-31",
                        "raw_summary": "截至2024-12-31，张三无账户信息。",
                        "source_evidence": {
                            "page": 1,
                            "row_no": "1",
                        },
                    }
                ],
            },
            self.file_record,
        )
        resolved = resolve_case_events(normalized["full_transaction_rows"])

        self.assertEqual(len(resolved["final_declaration_rows"]), 1)
        self.assertEqual(resolved["review_issue_rows"], [])

    def test_no_account_info_negative_proof_missing_name_or_date_needs_review(self):
        from app.pipeline.case_event_resolver import resolve_case_events
        from app.pipeline.normalizers.guangfa_normalizer import normalize_guangfa

        normalized = normalize_guangfa(
            self.case_id,
            {
                "schema_version": "guangfa_business_event_understanding_v1",
                "source_type": "guangfa",
                "negative_proofs": [
                    {
                        "proof_type": "无账户信息",
                        "description": "材料显示无账户信息。",
                        "source_evidence": {
                            "page": 1,
                            "row_no": "1",
                            "raw_text": "材料显示无账户信息。",
                        },
                    }
                ],
            },
            self.file_record,
        )
        resolved = resolve_case_events(
            normalized["full_transaction_rows"],
            review_items=normalized["review_items"],
        )

        self.assertEqual(len(resolved["final_declaration_rows"]), 0)
        self.assertEqual(len(resolved["review_issue_rows"]), 1)
        issue = resolved["review_issue_rows"][0]
        self.assertIn("姓名", issue["待复核原因"])
        self.assertIn("查询日期/期间", issue["待复核原因"])
        self.assertNotIn("证券代码", issue["待复核原因"])

    def test_no_account_info_business_event_is_supported(self):
        from app.pipeline.case_event_resolver import resolve_case_events
        from app.pipeline.normalizers.guangfa_normalizer import normalize_guangfa

        normalized = normalize_guangfa(
            self.case_id,
            {
                "schema_version": "guangfa_business_event_understanding_v1",
                "source_type": "guangfa",
                "business_events": [
                    {
                        "raw_business_type": "无账户信息",
                        "inferred_event_type": "无账户信息",
                        "event_category": "negative_proof",
                        "affects_holding": False,
                        "include_in_full_table": False,
                        "include_in_final_declaration": True,
                        "person_name": "张三",
                        "final_field_candidates": {
                            "变动类型": "无账户信息",
                            "日期": "2024-12-31",
                        },
                        "source_evidence": {
                            "page": 1,
                            "row_no": "1",
                            "raw_text": "截至2024-12-31，张三无账户信息。",
                        },
                    }
                ],
            },
            self.file_record,
        )
        resolved = resolve_case_events(
            normalized["full_transaction_rows"],
            review_items=normalized["review_items"],
        )

        self.assertEqual(len(resolved["final_declaration_rows"]), 1)
        row = resolved["final_declaration_rows"][0]
        self.assertEqual(row["event_type"], "no_account_info")
        self.assertEqual(row["person_name"], "张三")
        self.assertEqual(row["transfer_type_raw"], "无账户信息")

    def test_extractor_marks_business_event_schema_when_llm_returns_business_events(self):
        from app.pipeline.guangfa_extractor import GuangfaExtractor

        result = GuangfaExtractor()._normalize_result(
            self.case_id,
            self.file_record,
            {"business_events": [{"inferred_event_type": "买入"}]},
        )

        self.assertEqual(
            result["schema_version"],
            "guangfa_business_event_understanding_v1",
        )
        self.assertEqual(result["source_type"], "guangfa")
        self.assertEqual(result["content_type"], "guangfa")
        self.assertEqual(result["file_summary"], {})
        self.assertEqual(result["account_candidates"], [])
        self.assertEqual(result["holding_records"], [])
        self.assertEqual(result["negative_proofs"], [])
        self.assertEqual(result["document_level_review_items"], [])

    def test_extractor_keeps_old_schema_when_no_business_events_exist(self):
        from app.pipeline.guangfa_extractor import GuangfaExtractor

        result = GuangfaExtractor()._normalize_result(
            self.case_id,
            self.file_record,
            {"trade_group": {"columns": [], "trades": []}},
        )

        self.assertEqual(result["schema_version"], "guangfa_extract_v1")
        self.assertEqual(result["trade_group"], {"columns": [], "trades": []})


if __name__ == "__main__":
    unittest.main()
