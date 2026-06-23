import sys
from tempfile import TemporaryDirectory
import unittest
from pathlib import Path
from unittest.mock import patch


API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


class FinalProblemEventsTest(unittest.TestCase):
    def test_document_context_extracts_chinaclear_split_holding_header(self):
        from app.pipeline.document_context import build_document_context
        from app.services import local_store

        with TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            output_dir = project_root / "processed"
            with patch.object(local_store, "PROJECT_ROOT", project_root):
                local_store.save_json(
                    output_dir / "raw_text.json",
                    {
                        "text": "\n".join(
                            [
                                "中国证券登记结算有限责任公司投资者证券持有信息（深市B股）",
                                "一码通账户号码：",
                                "陈",
                                "180112022881",
                                "持有人名称：",
                                "证券子账户号码：",
                                "证件号码：",
                                "4401111966",
                                "2091310595（非定向资管账户）",
                                "2001-05-30",
                                "持有日期：",
                                "2026-02-02",
                            ]
                        )
                    },
                )

                context = build_document_context(output_dir)

        self.assertEqual(context["holder_name"], "陈")
        self.assertEqual(context["securities_account"], "2091310595")
        self.assertEqual(context["account_type"], "深B")
        self.assertEqual(context["period_end"], "2026-02-02")

    def test_common_event_type_normalizes_registration_synonyms(self):
        from app.pipeline.normalizers.common import normalize_direction, normalize_event_type

        for raw_type in ["股份入账", "股份登记", "证券登记入账", "转债入账", "申购中签"]:
            event = {"transfer_type_raw": raw_type}
            self.assertEqual(normalize_event_type(event), "security_registration")
            self.assertEqual(normalize_direction(event), "registration_in")

    def test_guangfa_allotment_is_full_table_only_without_review(self):
        from app.pipeline.normalizers.guangfa_normalizer import normalize_guangfa

        file_record = {
            "file_id": "file_001",
            "file_no": "001",
            "original_file_name": "guangfa.pdf",
            "content_type": "guangfa",
        }
        extract_result = {
            "document_info": {
                "holder_name": "张",
                "securities_accounts": {"沪A": "A315570738"},
            },
            "business_events": [
                {
                    "raw_business_type": "申购配号",
                    "inferred_event_type": "新股申购配号",
                    "event_category": "打新",
                    "include_in_full_table": True,
                    "include_in_final_declaration": False,
                    "affects_holding": False,
                    "final_field_candidates": {
                        "证券名称": "希获配号",
                        "变动类型": "申购配号",
                        "日期": "2022-01-11",
                        "成交数量": "11.0000",
                        "成交单价": "0.0000",
                        "收付金额": "0.0000",
                    },
                    "source_evidence": {
                        "raw_text": "2022-01-11 195954 100450901 15685657 789173 希获配号 申购配号 11.0000"
                    },
                }
            ],
        }

        normalized = normalize_guangfa("case_001", extract_result, file_record)

        self.assertEqual(len(normalized["full_transaction_rows"]), 1)
        self.assertEqual(normalized["full_transaction_rows"][0]["event_type"], "subscription_allotment")
        self.assertEqual(normalized["full_transaction_rows"][0]["account_type"], "沪A")
        self.assertEqual(normalized["full_transaction_rows"][0]["security_code"], "789173")
        self.assertEqual(normalized["full_transaction_rows"][0]["securities_account"], "A315570738")
        self.assertEqual(normalized["final_declaration_rows"], [])
        self.assertEqual(normalized["review_items"], [])

    def test_subscription_allotment_missing_security_code_does_not_require_review(self):
        from app.pipeline.case_event_resolver import resolve_case_events

        resolved = resolve_case_events(
            [
                {
                    "file_id": "file_001",
                    "file_no": "001",
                    "original_file_name": "guangfa.pdf",
                    "account_type": "深A",
                    "securities_account": "0002220266",
                    "event_id": "allot_001",
                    "event_type": "subscription_allotment",
                    "event_date": "2022-01-14",
                    "security_code": "",
                    "security_name": "百合配号",
                    "direction": "subscribe",
                    "quantity_raw": "5.0000",
                    "include_in_final_declaration": False,
                }
            ]
        )

        self.assertEqual(len(resolved["full_transaction_rows"]), 1)
        self.assertEqual(resolved["final_declaration_rows"], [])
        self.assertEqual(resolved["pending_review_events"], [])
        self.assertEqual(resolved["review_issue_rows"], [])

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

    def test_cross_file_trade_rows_are_merged_when_one_to_one_and_complementary(self):
        from app.pipeline.case_event_resolver import resolve_case_events

        chinaclear_row = {
            "file_id": "file_001",
            "file_no": "001",
            "original_file_name": "chinaclear.pdf",
            "account_type": "深A",
            "securities_account": "0268832573",
            "event_id": "zc_001",
            "event_type": "ordinary_trade",
            "event_date": "2025-02-05",
            "security_code": "000837",
            "security_name": "秦川机床",
            "direction": "buy",
            "quantity_raw": "9,800.00",
            "price_raw": "",
            "amount_raw": "",
            "balance_after_raw": "9,800.00",
            "transfer_type_raw": "买入",
            "source_evidence": [
                {
                    "file_id": "file_001",
                    "file_no": "001",
                    "file_name": "chinaclear.pdf",
                    "source_row_id": "zc_001",
                    "source_page": "1",
                    "row_no": "1",
                }
            ],
        }
        guangfa_row = {
            "file_id": "file_002",
            "file_no": "002",
            "original_file_name": "guangfa.pdf",
            "account_type": "深A",
            "securities_account": "0268832573",
            "event_id": "gf_001",
            "event_type": "ordinary_trade",
            "event_date": "2025-02-05",
            "event_time": "09:31:13",
            "security_code": "000837",
            "security_name": "秦川机床",
            "direction": "buy",
            "quantity_raw": "9800.0000",
            "price_raw": "13.3920",
            "amount_raw": "-131282.8230",
            "serial_no": "88000001",
            "order_no": "23001",
            "transfer_type_raw": "证券买入",
            "source_evidence": [
                {
                    "file_id": "file_002",
                    "file_no": "002",
                    "file_name": "guangfa.pdf",
                    "source_row_id": "gf_001",
                    "source_page": "1",
                    "row_no": "1",
                }
            ],
        }

        resolved = resolve_case_events([chinaclear_row, guangfa_row])

        self.assertEqual(len(resolved["full_transaction_rows"]), 1)
        row = resolved["full_transaction_rows"][0]
        self.assertEqual(row["price_raw"], "13.3920")
        self.assertEqual(row["amount_raw"], "-131282.8230")
        self.assertEqual(row["balance_after_raw"], "9,800.00")
        self.assertEqual(row["event_time"], "09:31:13")
        self.assertEqual(row["serial_no"], "88000001")
        self.assertEqual(
            {item["file_id"] for item in row["source_evidence"]},
            {"file_001", "file_002"},
        )
        self.assertEqual(len(resolved["final_declaration_rows"]), 1)
        self.assertEqual(resolved["review_issue_rows"], [])
        self.assertEqual(
            resolved["merge_audit"][0]["action"],
            "merged_cross_file_complementary_trade",
        )

    def test_cross_file_registration_rows_are_merged_when_one_to_one(self):
        from app.pipeline.case_event_resolver import resolve_case_events

        base_row = {
            "account_type": "深A",
            "securities_account": "0268832573",
            "event_type": "security_registration",
            "event_date": "2025-03-31",
            "security_code": "123254",
            "security_name": "亿纬转债",
            "direction": "registration_in",
            "quantity_raw": "1000.0000",
            "price_raw": "",
        }
        resolved = resolve_case_events(
            [
                dict(
                    base_row,
                    file_id="file_001",
                    file_no="001",
                    original_file_name="chinaclear.pdf",
                    event_id="zc_reg_001",
                    transfer_type_raw="股份登记",
                    source_evidence=[
                        {
                            "file_id": "file_001",
                            "file_no": "001",
                            "file_name": "chinaclear.pdf",
                            "source_row_id": "zc_reg_001",
                            "source_page": "1",
                            "row_no": "61",
                        }
                    ],
                ),
                dict(
                    base_row,
                    file_id="file_002",
                    file_no="002",
                    original_file_name="guangfa.pdf",
                    event_id="gf_reg_001",
                    amount_raw="0.0000",
                    transfer_type_raw="证券登记入账",
                    source_evidence=[
                        {
                            "file_id": "file_002",
                            "file_no": "002",
                            "file_name": "guangfa.pdf",
                            "source_row_id": "gf_reg_001",
                            "source_page": "1",
                            "row_no": "41",
                        }
                    ],
                ),
            ]
        )

        self.assertEqual(len(resolved["full_transaction_rows"]), 1)
        row = resolved["full_transaction_rows"][0]
        self.assertEqual(row["event_type"], "security_registration")
        self.assertEqual(row["amount_raw"], "0.0000")
        self.assertEqual(
            {item["file_id"] for item in row["source_evidence"]},
            {"file_001", "file_002"},
        )
        self.assertEqual(len(resolved["final_declaration_rows"]), 1)
        self.assertEqual(resolved["review_issue_rows"], [])

    def test_ambiguous_cross_file_trade_matches_are_not_merged(self):
        from app.pipeline.case_event_resolver import resolve_case_events

        base_row = {
            "account_type": "深A",
            "securities_account": "0268832573",
            "event_type": "ordinary_trade",
            "event_date": "2025-02-05",
            "security_code": "000837",
            "security_name": "秦川机床",
            "direction": "buy",
            "quantity_raw": "9800.0000",
        }
        resolved = resolve_case_events(
            [
                dict(
                    base_row,
                    file_id="file_001",
                    file_no="001",
                    original_file_name="chinaclear.pdf",
                    event_id="zc_001",
                    balance_after_raw="9,800.00",
                ),
                dict(
                    base_row,
                    file_id="file_002",
                    file_no="002",
                    original_file_name="guangfa.pdf",
                    event_id="gf_001",
                    price_raw="13.3920",
                    amount_raw="-131282.8230",
                ),
                dict(
                    base_row,
                    file_id="file_002",
                    file_no="002",
                    original_file_name="guangfa.pdf",
                    event_id="gf_002",
                    price_raw="13.5000",
                    amount_raw="-132300.0000",
                ),
            ]
        )

        self.assertEqual(len(resolved["full_transaction_rows"]), 3)
        self.assertEqual(resolved["review_issue_rows"], [])
        self.assertEqual(resolved["merge_audit"], [])

    def test_distinct_trades_with_different_prices_are_not_source_conflicts(self):
        from app.pipeline.case_event_resolver import resolve_case_events

        base_row = {
            "file_id": "file_001",
            "file_no": "001",
            "original_file_name": "statement.pdf",
            "account_type": "普通账户",
            "securities_account": "36914385",
            "event_type": "ordinary_trade",
            "event_date": "2025-09-24",
            "security_code": "000951",
            "security_name": "中国重汽",
            "direction": "sell",
            "quantity_raw": "100",
            "balance_after_raw": "0",
        }
        resolved = resolve_case_events(
            [
                dict(
                    base_row,
                    event_id="trade_001",
                    price_raw="18.75",
                    amount_raw="1875.00",
                    source_evidence=[
                        {
                            "file_id": "file_001",
                            "file_no": "001",
                            "file_name": "statement.pdf",
                            "source_row_id": "trade_001",
                            "source_page": "3",
                            "row_no": "12",
                        }
                    ],
                ),
                dict(
                    base_row,
                    event_id="trade_002",
                    price_raw="18.92",
                    amount_raw="1892.00",
                    source_evidence=[
                        {
                            "file_id": "file_001",
                            "file_no": "001",
                            "file_name": "statement.pdf",
                            "source_row_id": "trade_002",
                            "source_page": "3",
                            "row_no": "13",
                        }
                    ],
                ),
            ]
        )

        self.assertEqual(len(resolved["full_transaction_rows"]), 2)
        self.assertEqual(len(resolved["final_declaration_rows"]), 2)
        self.assertEqual(resolved["review_issue_rows"], [])

    def test_same_record_id_with_different_price_or_amount_is_not_source_conflict(self):
        from app.pipeline.case_event_resolver import resolve_case_events

        base_row = {
            "file_id": "file_001",
            "file_no": "001",
            "original_file_name": "statement.pdf",
            "account_type": "普通账户",
            "securities_account": "36914385",
            "event_id": "805409415",
            "event_type": "ordinary_trade",
            "event_date": "2025-09-24",
            "event_time": "10:15:30",
            "security_code": "000951",
            "security_name": "中国重汽",
            "direction": "sell",
            "quantity_raw": "100",
            "balance_after_raw": "0",
            "serial_no": "805409415",
        }
        resolved = resolve_case_events(
            [
                dict(
                    base_row,
                    price_raw="18.75",
                    amount_raw="1875.00",
                    source_evidence=[
                        {
                            "file_id": "file_001",
                            "file_no": "001",
                            "file_name": "statement.pdf",
                            "source_row_id": "805409415",
                            "source_page": "3",
                            "row_no": "12",
                        }
                    ],
                ),
                dict(
                    base_row,
                    price_raw="18.92",
                    amount_raw="1892.00",
                    source_evidence=[
                        {
                            "file_id": "file_001",
                            "file_no": "001",
                            "file_name": "statement.pdf",
                            "source_row_id": "805409415",
                            "source_page": "3",
                            "row_no": "13",
                        }
                    ],
                ),
            ]
        )

        self.assertEqual(len(resolved["full_transaction_rows"]), 2)
        self.assertEqual(len(resolved["final_declaration_rows"]), 2)
        self.assertEqual(resolved["review_issue_rows"], [])
        self.assertFalse(
            [
                item
                for item in resolved["merge_audit"]
                if item.get("action") == "possible_same_event_conflict"
            ]
        )

    def test_common_account_type_infers_b_share_markets(self):
        from app.pipeline.normalizers.common import build_holding_row

        sh_b = build_holding_row(
            "case_test",
            {"file_id": "file_001", "file_no": "001", "original_file_name": "holding.pdf"},
            {"securities_accounts": {"沪B": "C123456789"}},
            {"security_code": "900901", "security_name": "云赛B股", "quantity_raw": "100"},
        )
        sz_b = build_holding_row(
            "case_test",
            {"file_id": "file_001", "file_no": "001", "original_file_name": "holding.pdf"},
            {"securities_accounts": {"深B": "2001234567"}},
            {"security_code": "200869", "security_name": "张裕B", "quantity_raw": "100"},
        )

        self.assertEqual(sh_b["account_type"], "沪B")
        self.assertEqual(sh_b["securities_account"], "C123456789")
        self.assertEqual(sz_b["account_type"], "深B")
        self.assertEqual(sz_b["securities_account"], "2001234567")

    def test_holding_preserves_market_value_and_defaults_currency(self):
        from app.pipeline.normalizers.common import build_holding_row

        row = build_holding_row(
            "case_test",
            {"file_id": "file_001", "file_no": "001", "original_file_name": "holding.pdf"},
            {},
            {
                "account_type": "深A",
                "securities_account": "0012345678",
                "holding_id": "holding_001",
                "holding_date": "2026-01-01",
                "security_code": "000001",
                "security_name": "平安银行",
                "quantity_raw": "100",
                "market_value": "1000.00",
            },
        )

        self.assertEqual(row["market_value"], "1000.00")
        self.assertEqual(row["currency"], "人民币")

    def test_holding_missing_market_value_enters_review_not_holding_table(self):
        from app.pipeline.case_event_resolver import resolve_case_events

        resolved = resolve_case_events(
            [],
            holding_rows=[
                {
                    "file_id": "file_001",
                    "file_no": "001",
                    "original_file_name": "holding.pdf",
                    "account_type": "深A",
                    "securities_account": "0012345678",
                    "holding_id": "holding_001",
                    "holding_date": "2026-01-01",
                    "security_code": "000001",
                    "security_name": "平安银行",
                    "quantity_raw": "100",
                    "currency": "人民币",
                }
            ],
        )

        self.assertEqual(resolved["holding_rows"], [])
        self.assertEqual(len(resolved["review_issue_rows"]), 1)
        issue = resolved["review_issues"][0]
        self.assertIn("market_value", issue["missing_fields"])
        self.assertIn("市值", resolved["review_issue_rows"][0]["待复核原因"])

    def test_distinct_trades_with_generic_table_record_id_are_not_source_conflicts(self):
        from app.pipeline.case_event_resolver import resolve_case_events

        base_row = {
            "file_id": "file_001",
            "file_no": "001",
            "original_file_name": "statement.pdf",
            "account_type": "深A",
            "securities_account": "0022608195",
            "event_id": "资金流水明细",
            "event_type": "ordinary_trade",
            "event_date": "2025-04-14",
            "security_code": "000951",
            "security_name": "中国重汽",
            "direction": "buy",
            "quantity_raw": "5000.0000",
            "source_evidence": [
                {
                    "file_id": "file_001",
                    "file_no": "001",
                    "file_name": "statement.pdf",
                    "source_row_id": "资金流水明细",
                    "source_page": "1",
                    "row_no": "资金流水明细",
                }
            ],
        }
        resolved = resolve_case_events(
            [
                dict(
                    base_row,
                    price_raw="18.7400",
                    amount_raw="-93716.4400",
                    raw_text="2025-04-14 191115 805409415 证券买入 中国重汽 5000 18.7400 -93716.4400",
                ),
                dict(
                    base_row,
                    price_raw="18.7800",
                    amount_raw="-93916.4800",
                    raw_text="2025-04-14 191115 805409416 证券买入 中国重汽 5000 18.7800 -93916.4800",
                ),
            ]
        )

        self.assertEqual(len(resolved["full_transaction_rows"]), 2)
        self.assertEqual(len(resolved["final_declaration_rows"]), 2)
        self.assertEqual(resolved["review_issue_rows"], [])

    def test_same_economic_fields_with_different_trade_times_are_not_merged(self):
        from app.pipeline.case_event_resolver import resolve_case_events

        base_row = {
            "file_id": "file_001",
            "file_no": "001",
            "original_file_name": "statement.pdf",
            "account_type": "深A",
            "securities_account": "0022608195",
            "event_type": "ordinary_trade",
            "event_date": "2025-04-14",
            "security_code": "000951",
            "security_name": "中国重汽",
            "direction": "buy",
            "quantity_raw": "5000.0000",
            "price_raw": "18.7400",
            "amount_raw": "-93716.4400",
        }
        resolved = resolve_case_events(
            [
                dict(base_row, event_id="trade_001", event_time="09:30:01"),
                dict(base_row, event_id="trade_002", event_time="10:30:01"),
            ]
        )

        self.assertEqual(len(resolved["full_transaction_rows"]), 2)
        self.assertEqual(len(resolved["final_declaration_rows"]), 2)
        self.assertEqual(resolved["merge_audit"], [])

    def test_reused_serial_with_different_trade_facts_is_not_source_conflict(self):
        from app.pipeline.case_event_resolver import resolve_case_events

        base_row = {
            "file_id": "file_001",
            "file_no": "001",
            "original_file_name": "statement.pdf",
            "account_type": "深A",
            "securities_account": "0022608195",
            "event_id": "805409415",
            "event_type": "ordinary_trade",
            "event_date": "2025-04-14",
            "security_code": "000951",
            "security_name": "中国重汽",
            "quantity_raw": "5000.0000",
            "price_raw": "18.7400",
            "amount_raw": "-93716.4400",
            "serial_no": "805409415",
        }
        resolved = resolve_case_events(
            [
                dict(
                    base_row,
                    event_time="191115",
                    direction="buy",
                    transfer_type_raw="证券买入",
                    row_nos="124",
                    source_evidence=[
                        {
                            "file_id": "file_001",
                            "file_no": "001",
                            "file_name": "statement.pdf",
                            "source_row_id": "805409415",
                            "source_page": "1",
                            "row_no": "124",
                        }
                    ],
                ),
                dict(
                    base_row,
                    event_time="142805",
                    direction="sell",
                    transfer_type_raw="证券卖出",
                    order_no="41398",
                    row_nos="339",
                    source_evidence=[
                        {
                            "file_id": "file_001",
                            "file_no": "001",
                            "file_name": "statement.pdf",
                            "source_row_id": "805409415",
                            "source_page": "1",
                            "row_no": "339",
                        }
                    ],
                ),
            ]
        )

        self.assertEqual(len(resolved["full_transaction_rows"]), 2)
        self.assertEqual(len(resolved["final_declaration_rows"]), 2)
        self.assertEqual(resolved["review_issue_rows"], [])
        self.assertEqual(
            [
                item
                for item in resolved["merge_audit"]
                if item.get("action") == "possible_same_event_conflict"
            ],
            [],
        )

    def test_zero_quantity_ordinary_trade_artifacts_do_not_require_review(self):
        from app.pipeline.case_event_resolver import resolve_case_events

        base_row = {
            "file_id": "file_001",
            "file_no": "001",
            "original_file_name": "statement.pdf",
            "account_type": "深A",
            "securities_account": "0022608195",
            "event_id": "803762914",
            "event_type": "ordinary_trade",
            "event_date": "2025-06-26",
            "event_time": "170001",
            "security_code": "000951",
            "security_name": "中国重汽",
            "direction": "buy",
            "quantity_raw": "0.0000",
            "price_raw": "17.7100",
            "transfer_type_raw": "证券买入",
            "serial_no": "803762914",
            "source_evidence": [
                {
                    "file_id": "file_001",
                    "file_no": "001",
                    "file_name": "statement.pdf",
                    "source_row_id": "803762914",
                    "source_page": "1",
                    "row_no": "393",
                }
            ],
        }
        resolved = resolve_case_events(
            [
                dict(base_row, amount_raw="14175.0000", order_no="0"),
                dict(base_row, amount_raw="0.0000"),
                {
                    "file_id": "file_001",
                    "file_no": "001",
                    "original_file_name": "statement.pdf",
                    "account_type": "深A",
                    "securities_account": "0022608195",
                    "event_id": "7100",
                    "event_type": "cash_dividend",
                    "event_date": "2025-06-26",
                    "security_code": "000951",
                    "security_name": "中国重汽",
                    "direction": "cash_income",
                    "quantity_raw": "",
                    "price_raw": "",
                    "amount_raw": "14175.0000",
                },
            ]
        )

        self.assertEqual(resolved["review_issue_rows"], [])
        self.assertEqual(len(resolved["full_transaction_rows"]), 1)
        self.assertEqual(resolved["full_transaction_rows"][0]["event_type"], "cash_dividend")
        self.assertEqual(resolved["final_declaration_rows"], [])

    def test_review_item_reasons_do_not_expose_internal_field_names(self):
        from app.pipeline.case_event_resolver import resolve_case_events

        resolved = resolve_case_events(
            [],
            review_items=[
                {
                    "severity": "warning",
                    "item_type": "event",
                    "file_id": "file_001",
                    "file_no": "001",
                    "original_file_name": "statement.pdf",
                    "event_id": "event_001",
                    "field": "final_field_candidates",
                    "message": "最终申报关键字段缺失：成交单价",
                },
                {
                    "severity": "warning",
                    "item_type": "event",
                    "file_id": "file_001",
                    "file_no": "001",
                    "original_file_name": "statement.pdf",
                    "event_id": "event_002",
                    "field": "include_in_final_declaration",
                    "message": "LLM 判断进入最终申报表但脚本规则判断为完整表记录",
                },
            ],
        )

        reason_text = " ".join(row["待复核原因"] for row in resolved["review_issue_rows"])
        self.assertIn("抽取结果字段不完整", reason_text)
        self.assertIn("最终申报归类待确认", reason_text)
        self.assertNotIn("final_field_candidates", reason_text)
        self.assertNotIn("include_in_final_declaration", reason_text)

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

    def test_chinaclear_pure_cash_flow_events_are_excluded_from_full_table(self):
        from app.pipeline.normalizers.chinaclear_normalizer import normalize_chinaclear

        normalized = normalize_chinaclear(
            "case_test",
            {
                "document_info": {
                    "file_name": "chinaclear.pdf",
                    "securities_account": "A123456789",
                    "account_type": "沪A",
                },
                "trade_group": {"trade_columns": [], "trades": []},
                "other_events": [
                    {
                        "event_id": "cash_001",
                        "event_type": "interest",
                        "event_date": "2025-06-30",
                        "transfer_type_raw": "账户利息入账",
                        "amount_raw": "12.34",
                    },
                    {
                        "event_id": "cash_002",
                        "event_type": "bank_transfer",
                        "event_date": "2025-07-01",
                        "transfer_type_raw": "银行转存",
                        "amount_raw": "1000.00",
                    },
                ],
            },
            {
                "file_id": "file_002",
                "file_no": "002",
                "original_file_name": "chinaclear.pdf",
            },
        )

        self.assertEqual(normalized["full_transaction_rows"], [])
        self.assertEqual(normalized["final_declaration_rows"], [])

    def test_chinaclear_security_income_events_remain_in_full_table_only(self):
        from app.pipeline.case_event_resolver import resolve_case_events
        from app.pipeline.normalizers.chinaclear_normalizer import normalize_chinaclear

        normalized = normalize_chinaclear(
            "case_test",
            {
                "document_info": {
                    "file_name": "chinaclear.pdf",
                    "securities_account": "A123456789",
                    "account_type": "沪A",
                },
                "trade_group": {"trade_columns": [], "trades": []},
                "other_events": [
                    {
                        "event_id": "dividend_001",
                        "event_type": "cash_dividend",
                        "event_date": "2025-06-30",
                        "security_code": "600000",
                        "security_name": "浦发银行",
                        "transfer_type_raw": "红利入账",
                        "amount_raw": "88.00",
                    },
                    {
                        "event_id": "interest_001",
                        "event_type": "bond_interest",
                        "event_date": "2025-07-01",
                        "security_code": "113000",
                        "security_name": "测试转债",
                        "transfer_type_raw": "兑息派息",
                        "amount_raw": "66.00",
                    },
                ],
            },
            {
                "file_id": "file_002",
                "file_no": "002",
                "original_file_name": "chinaclear.pdf",
            },
        )
        resolved = resolve_case_events(normalized["full_transaction_rows"])

        self.assertEqual(len(resolved["full_transaction_rows"]), 2)
        self.assertEqual(len(resolved["final_declaration_rows"]), 0)
        self.assertEqual(resolved["review_issue_rows"], [])

    def test_chinaclear_event_schema_normalizes_holdings_negative_proofs_and_review_items(self):
        from app.pipeline.case_event_resolver import resolve_case_events
        from app.pipeline.normalizers.chinaclear_normalizer import normalize_chinaclear

        normalized = normalize_chinaclear(
            "case_test",
            {
                "schema_version": "chinaclear_event_understanding_v2",
                "source_type": "chinaclear",
                "document_info": {
                    "file_name": "chinaclear.pdf",
                    "document_type": "holding_snapshot",
                    "market": "SZ",
                    "period_start": "2024-01-01",
                    "period_end": "2024-12-31",
                    "securities_account": "A123456789",
                },
                "trade_group": {"trade_columns": [], "trades": []},
                "other_events": [],
                "holding_records": [
                    {
                        "holding_id": "holding_001",
                        "账户类型": "深A",
                        "证券账号": "A123456789",
                        "证券代码": "000001",
                        "证券名称": "平安银行",
                        "持有数量": "100",
                        "市值": "1000",
                        "查询结果所属日期": "2024-12-31",
                        "source_evidence": {
                            "page": 2,
                            "row_no": "8",
                            "raw_text": "000001 平安银行 100",
                        },
                    }
                ],
                "negative_proofs": [
                    {
                        "proof_type": "no_trade_record",
                        "account_type": "深A",
                        "securities_account": "A123456789",
                        "period_start": "2024-01-01",
                        "period_end": "2024-12-31",
                        "source_evidence": {
                            "page": 1,
                            "row_no": "1",
                            "raw_text": "2024年度无交易记录。",
                        },
                    }
                ],
                "document_level_review_items": [
                    {
                        "severity": "warning",
                        "item_type": "event",
                        "event_id": "event_uncertain_001",
                        "field": "event_type",
                        "message": "存在疑似跨页权益事件，需人工复核。",
                    }
                ],
            },
            {
                "file_id": "file_006",
                "file_no": "006",
                "original_file_name": "chinaclear.pdf",
            },
        )

        self.assertEqual(len(normalized["holding_rows"]), 1)
        holding = normalized["holding_rows"][0]
        self.assertEqual(holding["account_type"], "深A")
        self.assertEqual(holding["securities_account"], "A123456789")
        self.assertEqual(holding["security_code"], "000001")
        self.assertEqual(holding["quantity_raw"], "100")
        self.assertEqual(holding["market_value"], "1000")

        resolved = resolve_case_events(
            normalized["full_transaction_rows"],
            holding_rows=normalized["holding_rows"],
            review_items=normalized["review_items"],
        )
        self.assertEqual(len(resolved["final_declaration_rows"]), 1)
        self.assertEqual(resolved["final_declaration_rows"][0]["event_type"], "no_trade_record")
        self.assertEqual(resolved["review_issue_rows"][0]["对应材料"], "006 chinaclear.pdf")
        self.assertIn("跨页权益事件", resolved["review_issue_rows"][0]["问题描述"])

    def test_chinaclear_holding_reads_final_field_candidates_when_top_level_is_sparse(self):
        from app.pipeline.case_event_resolver import resolve_case_events
        from app.pipeline.normalizers.chinaclear_normalizer import normalize_chinaclear

        normalized = normalize_chinaclear(
            "case_test",
            {
                "schema_version": "chinaclear_event_understanding_v2",
                "source_type": "chinaclear",
                "document_info": {"period_end": "2025-12-31"},
                "holding_records": [
                    {
                        "holding_id": "holding_001",
                        "final_field_candidates": {
                            "账户类型": "深A",
                            "证券账号": "0012345678",
                            "证券代码": "000001",
                            "证券名称": "平安银行",
                            "持有数量": "100",
                            "市值": "1000",
                            "查询结果所属日期": "2025-12-31",
                            "币种": "人民币",
                        },
                        "source_evidence": {
                            "page": 1,
                            "row_no": "8",
                            "raw_text": "000001 平安银行 100",
                        },
                    }
                ],
            },
            {
                "file_id": "file_006",
                "file_no": "006",
                "original_file_name": "chinaclear.pdf",
            },
        )

        self.assertEqual(len(normalized["holding_rows"]), 1)
        holding = normalized["holding_rows"][0]
        self.assertEqual(holding["account_type"], "深A")
        self.assertEqual(holding["securities_account"], "0012345678")
        self.assertEqual(holding["security_code"], "000001")
        self.assertEqual(holding["security_name"], "平安银行")
        self.assertEqual(holding["quantity_raw"], "100")
        resolved = resolve_case_events([], holding_rows=normalized["holding_rows"])
        self.assertEqual(len(resolved["holding_rows"]), 1)
        self.assertEqual(resolved["review_issue_rows"], [])

    def test_chinaclear_batch_merge_preserves_event_understanding_sections(self):
        from app.pipeline.chinaclear_extractor import ChinaclearExtractor

        merged = ChinaclearExtractor()._merge_batch_results(
            [
                {
                    "batch_id": "batch_001",
                    "document_info": {"document_type": "holding_snapshot"},
                    "holding_records": [
                        {
                            "holding_id": "holding_001",
                            "证券账号": "A123456789",
                            "证券代码": "000001",
                            "证券名称": "平安银行",
                            "持有数量": "100",
                            "查询结果所属日期": "2024-12-31",
                        }
                    ],
                    "negative_proofs": [
                        {
                            "proof_type": "no_trade_record",
                            "securities_account": "A123456789",
                            "period_end": "2024-12-31",
                            "source_evidence": {"raw_text": "无交易记录"},
                        }
                    ],
                },
                {
                    "batch_id": "batch_002",
                    "document_level_review_items": [
                        {
                            "severity": "warning",
                            "item_type": "event",
                            "field": "event_type",
                            "message": "疑似跨批次事件",
                        }
                    ],
                },
            ]
        )

        self.assertEqual(merged["schema_version"], "chinaclear_event_understanding_v2")
        self.assertEqual(len(merged["holding_records"]), 1)
        self.assertEqual(len(merged["negative_proofs"]), 1)
        self.assertEqual(len(merged["document_level_review_items"]), 1)

    def test_chinaclear_normalize_result_applies_document_context(self):
        from app.pipeline.chinaclear_extractor import ChinaclearExtractor

        result = ChinaclearExtractor()._normalize_result(
            "case_test",
            {
                "file_id": "file_001",
                "original_file_name": "chinaclear.pdf",
                "route_type": "direct_pdf",
            },
            {
                "schema_version": "chinaclear_event_understanding_v2",
                "document_info": {},
                "holding_records": [
                    {
                        "holding_id": "holding_001",
                        "证券代码": "200001",
                        "证券名称": "深物业B",
                        "持有数量": "100",
                    }
                ],
                "negative_proofs": [
                    {
                        "proof_type": "no_trade_record",
                        "source_evidence": {"raw_text": "本期间无交易记录"},
                    }
                ],
            },
            {
                "holder_name": "孙",
                "securities_account": "2001234567",
                "account_type": "深B",
                "period_start": "2025-01-01",
                "period_end": "2025-12-31",
            },
        )

        self.assertEqual(result["holding_records"][0]["证券账号"], "2001234567")
        self.assertEqual(result["holding_records"][0]["账户类型"], "深B")
        self.assertEqual(result["holding_records"][0]["查询结果所属日期"], "2025-12-31")
        self.assertEqual(result["negative_proofs"][0]["person_name"], "孙")
        self.assertEqual(result["negative_proofs"][0]["securities_account"], "2001234567")

    def test_chinaclear_extractor_carries_document_context_to_later_batches(self):
        from app.pipeline.chinaclear_extractor import ChinaclearExtractor
        from app.pipeline.normalizers.chinaclear_normalizer import normalize_chinaclear
        from app.services import local_store

        class FakePromptLoader:
            def load(self, name):
                return "中证登抽取 prompt"

        class FakeLLMClient:
            def __init__(self):
                self.prompts = []

            def extract_json(self, prompt):
                self.prompts.append(prompt)
                return {
                    "schema_version": "chinaclear_event_understanding_v2",
                    "document_info": {},
                    "trade_group": {
                        "trade_columns": [
                            "trade_id",
                            "market",
                            "trade_date",
                            "security_code",
                            "security_name",
                            "direction",
                            "quantity_raw",
                            "price_raw",
                            "balance_after_raw",
                            "transfer_type_raw",
                            "source_page",
                            "row_no",
                        ],
                        "trades": [
                            [
                                "t001",
                                "SZ",
                                "2025-06-09",
                                "300129",
                                "泰胜风能",
                                "sell",
                                "-7700.00",
                                "",
                                "0.00",
                                "卖出",
                                "2",
                                "46",
                            ]
                        ],
                    },
                    "llm_response_metadata": {
                        "finish_reason": "stop",
                        "usage": {"total_tokens": 100},
                    },
                }

        tmp_root = local_store.ensure_dir(local_store.PROJECT_ROOT / "tmp")
        with TemporaryDirectory(dir=tmp_root) as tmp_dir:
            output_dir = Path(tmp_dir)
            local_store.save_json(
                output_dir / "raw_text.json",
                {
                    "pages": [
                        {
                            "page": 1,
                            "text": (
                                "中国证券登记结算有限责任公司投资者证券持有变更信息（深市）\n"
                                "李\n一码通账户号码：\n180187180877\n"
                                "持有人名称：\n证件号码：\n证券子账户号码：\n"
                                "44138119950824\n0268832573（非定向资管账户）\n"
                                "2025-01-01 到 2025-06-30"
                            ),
                        },
                        {
                            "page": 2,
                            "text": "46 300129 泰胜风能 2025-06-09 卖出 -7700.00 0.00",
                        },
                    ]
                },
            )
            header = [
                "序号",
                "证券代码",
                "证券简称",
                "过户日期",
                "过户类型",
                "过户数量",
                "期末余额",
            ]
            rows = [header]
            for index in range(1, 56):
                rows.append(
                    [
                        str(index),
                        "300129",
                        "泰胜风能",
                        "2025-06-09",
                        "卖出",
                        "-7700.00",
                        "0.00",
                    ]
                )
            local_store.save_json(
                output_dir / "tables.json",
                {"tables": [{"page": 2, "table_index": 1, "rows": rows}]},
            )

            fake_llm = FakeLLMClient()
            result = ChinaclearExtractor(
                prompt_loader=FakePromptLoader(),
                llm_client=fake_llm,
            ).extract(
                "case_test",
                {
                    "file_id": "file_006",
                    "file_no": "006",
                    "original_file_name": "chinaclear.pdf",
                },
                output_dir,
            )

            self.assertGreater(len(fake_llm.prompts), 1)
            self.assertTrue(all("document_context:" in prompt for prompt in fake_llm.prompts))
            self.assertFalse(any("context_excerpt" in prompt for prompt in fake_llm.prompts))
            self.assertEqual(result["document_info"]["holder_name"], "李")
            self.assertEqual(result["document_info"]["securities_account"], "0268832573")
            normalized = normalize_chinaclear(
                "case_test",
                result,
                {
                    "file_id": "file_006",
                    "file_no": "006",
                    "original_file_name": "chinaclear.pdf",
                },
            )
            self.assertTrue(normalized["full_transaction_rows"])
            self.assertEqual(
                normalized["full_transaction_rows"][0]["securities_account"],
                "0268832573",
            )
            self.assertEqual(normalized["full_transaction_rows"][0]["account_type"], "深A")

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
                "input_text": "证券账户开户状态查询\n查询日期：2024-12-31\n截至2024-12-31，张三无账户信息",
            },
            {
                "file_id": "file_004",
                "file_no": "004",
                "original_file_name": "account_status.pdf",
            },
        )

        self.assertEqual(len(normalized["full_transaction_rows"]), 1)
        row = normalized["full_transaction_rows"][0]
        self.assertEqual(row["event_type"], "no_account_info")
        self.assertEqual(row["transfer_type_raw"], "无账户信息")
        self.assertEqual(row["event_date"], "2024-12-31")
        self.assertEqual(row["person_name"], "张三")
        self.assertEqual(row["security_code"], "")
        self.assertEqual(row["quantity_raw"], "")
        self.assertEqual(len(normalized["final_declaration_rows"]), 1)

        resolved = resolve_case_events(normalized["full_transaction_rows"])
        self.assertEqual(len(resolved["final_declaration_rows"]), 1)
        self.assertEqual(resolved["review_issue_rows"], [])

    def test_chinaclear_negative_proof_no_account_info_is_supported(self):
        from app.pipeline.case_event_resolver import resolve_case_events
        from app.pipeline.normalizers.chinaclear_normalizer import normalize_chinaclear

        normalized = normalize_chinaclear(
            "case_test",
            {
                "document_info": {"file_name": "account_status.pdf"},
                "trade_group": {"trade_columns": [], "trades": []},
                "negative_proofs": [
                    {
                        "proof_type": "无账户信息",
                        "person_name": "李四",
                        "as_of_date": "2024-12-31",
                        "source_evidence": {
                            "page": 1,
                            "row_no": "1",
                            "raw_text": "截至2024-12-31，李四无账户信息。",
                        },
                    }
                ],
            },
            {
                "file_id": "file_004",
                "file_no": "004",
                "original_file_name": "account_status.pdf",
            },
        )
        resolved = resolve_case_events(normalized["full_transaction_rows"])

        self.assertEqual(len(resolved["final_declaration_rows"]), 1)
        row = resolved["final_declaration_rows"][0]
        self.assertEqual(row["event_type"], "no_account_info")
        self.assertEqual(row["person_name"], "李四")
        self.assertEqual(row["event_date"], "2024-12-31")

    def test_chinaclear_negative_proof_uses_raw_summary_as_evidence(self):
        from app.pipeline.case_event_resolver import resolve_case_events
        from app.pipeline.normalizers.chinaclear_normalizer import normalize_chinaclear

        normalized = normalize_chinaclear(
            "case_test",
            {
                "document_info": {"file_name": "account_status.pdf"},
                "trade_group": {"trade_columns": [], "trades": []},
                "negative_proofs": [
                    {
                        "proof_type": "无账户信息",
                        "person_name": "李四",
                        "as_of_date": "2024-12-31",
                        "raw_summary": "截至2024-12-31，李四无账户信息。",
                        "source_evidence": {
                            "page": 1,
                            "row_no": "1",
                        },
                    }
                ],
            },
            {
                "file_id": "file_004",
                "file_no": "004",
                "original_file_name": "account_status.pdf",
            },
        )
        resolved = resolve_case_events(normalized["full_transaction_rows"])

        self.assertEqual(len(resolved["final_declaration_rows"]), 1)
        self.assertEqual(resolved["review_issue_rows"], [])

    def test_chinaclear_no_account_other_event_uses_raw_text_input_source_as_evidence(self):
        from app.pipeline.case_event_resolver import resolve_case_events
        from app.pipeline.normalizers.chinaclear_normalizer import normalize_chinaclear
        from app.services.local_store import save_json

        with TemporaryDirectory() as tmp_dir:
            raw_text_path = Path(tmp_dir) / "raw_text.json"
            save_json(
                raw_text_path,
                {
                    "pages": [
                        {
                            "page": 1,
                            "text": "未曾开立证券账户证明\n截至2026年03月06日，申请人张，未曾开立证券账户。",
                        }
                    ]
                },
            )

            normalized = normalize_chinaclear(
                "case_test",
                {
                    "document_info": {
                        "file_name": "account_status.pdf",
                        "document_title": "未曾开立证券账户证明",
                        "period_end": "2026-03-06",
                        "holder_name": "张",
                    },
                    "trade_group": {"trade_columns": [], "trades": []},
                    "other_events": [
                        {
                            "event_id": "e1",
                            "event_type": "no_account_info",
                            "event_date": "2026-03-06",
                            "transfer_type_raw": "无账户信息",
                            "source_pages": [1],
                        }
                    ],
                    "input_sources": {
                        "raw_text_path": str(raw_text_path),
                    },
                },
                {
                    "file_id": "file_004",
                    "file_no": "004",
                    "original_file_name": "account_status.pdf",
                },
            )

        resolved = resolve_case_events(normalized["full_transaction_rows"])

        self.assertEqual(len(resolved["final_declaration_rows"]), 1)
        self.assertEqual(resolved["review_issue_rows"], [])
        row = resolved["final_declaration_rows"][0]
        self.assertEqual(row["event_type"], "no_account_info")
        self.assertEqual(row["person_name"], "张")
        self.assertIn("未曾开立证券账户证明", row["source_evidence"][0]["raw_text"])

    def test_no_account_without_period_or_name_requires_review_but_not_trade_field_review(self):
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
        self.assertIn("姓名", issue["待复核原因"])
        self.assertNotIn("证券账号", issue["待复核原因"])
        self.assertNotIn("证券代码", issue["待复核原因"])

    def test_no_account_info_checklist_passes_when_name_and_date_exist(self):
        from app.pipeline.final_result_builder import _build_checklist_rows

        rows = _build_checklist_rows(
            [],
            [],
            account_info_rows=[
                {
                    "event_type": "no_account_info",
                    "event_date": "2024-12-31",
                    "person_name": "张三",
                    "transfer_type_raw": "无账户信息",
                }
            ],
        )

        account_check = [row for row in rows if row["checklist条件"] == "账户信息检查"][0]
        self.assertEqual(account_check["状态"], "通过")
        self.assertEqual(account_check["说明"], "截至2024-12-31，张三无账户信息。")

    def test_no_account_info_checklist_requires_review_when_name_or_date_missing(self):
        from app.pipeline.final_result_builder import _build_checklist_rows

        rows = _build_checklist_rows(
            [],
            [],
            pending_review_events=[
                {
                    "event_type": "no_account_info",
                    "transfer_type_raw": "无账户信息",
                    "missing_fields": ["person_name", "event_date"],
                }
            ],
        )

        account_check = [row for row in rows if row["checklist条件"] == "账户信息检查"][0]
        self.assertEqual(account_check["状态"], "需人工复核")
        self.assertIn("缺少姓名或截止日期", account_check["说明"])

    def test_no_account_info_is_not_exported_to_complete_transaction_sheet(self):
        from app.pipeline.final_result_builder import _complete_sheet_rows

        rows = _complete_sheet_rows(
            [
                {"event_type": "no_account_info", "transfer_type_raw": "无账户信息"},
                {"event_type": "ordinary_trade", "transfer_type_raw": "买入"},
            ]
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["event_type"], "ordinary_trade")

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

    def test_missing_securities_account_does_not_report_account_type_missing(self):
        from app.pipeline.case_event_resolver import resolve_case_events

        resolved = resolve_case_events(
            [
                {
                    "file_id": "file_001",
                    "file_no": "001",
                    "original_file_name": "statement.pdf",
                    "account_type": "普通账户",
                    "event_id": "event_001",
                    "event_type": "ordinary_trade",
                    "event_date": "2026-01-01",
                    "security_code": "600000",
                    "security_name": "浦发银行",
                    "direction": "buy",
                    "quantity_raw": "100",
                    "price_raw": "10",
                    "amount_raw": "-1000",
                }
            ]
        )

        issue = resolved["review_issues"][0]
        self.assertIn("securities_account_missing", issue["issue_types"])
        self.assertNotIn("account_type_missing", issue["issue_types"])
        self.assertEqual(issue["missing_fields"], ["securities_account"])
        self.assertIn("证券账号", resolved["review_issue_rows"][0]["待复核原因"])
        self.assertNotIn("账户类型", resolved["review_issue_rows"][0]["待复核原因"])

    def test_checklist_mentions_pending_review_data_before_reconciliation(self):
        from app.pipeline.final_result_builder import _build_checklist_rows

        rows = _build_checklist_rows(
            [],
            [],
            pending_review_event_count=2,
            pending_review_holding_count=1,
        )

        self.assertEqual(rows[0]["checklist条件"], "上次持仓 + 交易 = 本次持仓")
        self.assertEqual(rows[0]["状态"], "需人工复核")
        self.assertIn("2条待复核交易", rows[0]["说明"])
        self.assertIn("1条待复核持仓", rows[0]["说明"])
        self.assertIn("暂无法自动校验", rows[0]["说明"])


if __name__ == "__main__":
    unittest.main()
