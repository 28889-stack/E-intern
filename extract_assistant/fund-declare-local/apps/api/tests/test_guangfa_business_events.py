import sys
import tempfile
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

    def test_extractor_batches_long_guangfa_tables_and_saves_batch_results(self):
        from app.pipeline.guangfa_extractor import GuangfaExtractor
        from app.services import local_store

        class FakePromptLoader:
            def load(self, name):
                return "广发抽取 prompt"

        class FakeLLMClient:
            def __init__(self):
                self.prompts = []

            def extract_json(self, prompt):
                self.prompts.append(prompt)
                batch_id = "single"
                for line in prompt.splitlines():
                    if line.startswith("batch_id:"):
                        batch_id = line.split(":", 1)[1].strip()
                        break
                return {
                    "schema_version": "guangfa_business_event_understanding_v1",
                    "business_events": [
                        {
                            "raw_business_type": "证券买入",
                            "inferred_event_type": "买入",
                            "include_in_full_table": True,
                            "include_in_final_declaration": True,
                            "final_field_candidates": {
                                "证券账号": "36914385",
                                "证券代码": f"000{len(self.prompts):03d}",
                                "证券名称": f"测试证券{len(self.prompts)}",
                                "变动类型": "买入",
                                "日期": "2025-04-14",
                                "成交数量": "100",
                                "成交单价": "10.00",
                                "收付金额": "-1000.00",
                            },
                            "source_evidence": {
                                "page": 1,
                                "row_no": batch_id,
                                "raw_text": f"{batch_id} 证券买入 测试证券",
                            },
                        }
                    ],
                    "llm_response_metadata": {
                        "finish_reason": "stop",
                        "usage": {"total_tokens": 100},
                    },
                }

        tmp_root = local_store.ensure_dir(local_store.PROJECT_ROOT / "tmp")
        with tempfile.TemporaryDirectory(dir=tmp_root) as tmp_dir:
            output_dir = Path(tmp_dir)
            header = [
                "业务日期",
                "成交时间",
                "流水序号",
                "证券账号",
                "证券代码",
                "证券名称",
                "业务标志",
                "成交数量",
                "成交价格",
                "成交金额",
                "委托编号",
            ]
            rows = [header]
            for index in range(1, 126):
                rows.append(
                    [
                        "2025-04-14",
                        "09:30:00",
                        f"serial_{index:03d}",
                        "36914385",
                        f"000{index:03d}",
                        f"测试证券{index}",
                        "证券买入",
                        "100",
                        "10.00",
                        "-1000.00",
                        f"order_{index:03d}",
                    ]
                )
            local_store.save_json(
                output_dir / "tables.json",
                {"tables": [{"page": 1, "table_index": 1, "rows": rows}]},
            )

            fake_llm = FakeLLMClient()
            extractor = GuangfaExtractor(
                prompt_loader=FakePromptLoader(),
                llm_client=fake_llm,
            )
            result = extractor.extract(self.case_id, self.file_record, output_dir)

            self.assertGreater(len(fake_llm.prompts), 1)
            self.assertEqual(result["extract_status"], "success")
            self.assertTrue(result["llm_response_metadata"]["batch_mode"])
            self.assertIn("batch_result_path", result)
            self.assertGreaterEqual(len(result["business_events"]), len(fake_llm.prompts))
            batch_payload = local_store.read_json(output_dir / "extract_batches.json")
            self.assertEqual(len(batch_payload["batches"]), len(fake_llm.prompts))

    def test_extractor_carries_document_context_to_later_guangfa_batches(self):
        from app.pipeline.guangfa_extractor import GuangfaExtractor
        from app.pipeline.normalizers.guangfa_normalizer import normalize_guangfa
        from app.services import local_store

        class FakePromptLoader:
            def load(self, name):
                return "广发抽取 prompt"

        class FakeLLMClient:
            def __init__(self):
                self.prompts = []

            def extract_json(self, prompt):
                self.prompts.append(prompt)
                batch_id = "batch_001"
                for line in prompt.splitlines():
                    if line.startswith("batch_id:"):
                        batch_id = line.split(":", 1)[1].strip()
                        break
                return {
                    "schema_version": "guangfa_business_event_understanding_v1",
                    "business_events": [
                        {
                            "raw_business_type": "证券卖出",
                            "inferred_event_type": "卖出",
                            "include_in_full_table": True,
                            "include_in_final_declaration": True,
                            "final_field_candidates": {
                                "账户类型": "",
                                "证券账号": "",
                                "证券代码": "300129",
                                "证券名称": "泰胜风能",
                                "变动类型": "卖出",
                                "日期": "2025-06-09",
                                "成交数量": "-7700.0000",
                                "成交单价": "10.3860",
                                "收付金额": "79907.0946",
                            },
                            "source_evidence": {
                                "page": 2,
                                "row_no": batch_id,
                                "raw_text": (
                                    "2025-06-09 102558 88000046 36914385 "
                                    "300129 泰胜风能 证券卖出 -7700.0000 "
                                    "10.3860 79907.0946 23046"
                                ),
                            },
                        }
                    ],
                    "llm_response_metadata": {
                        "finish_reason": "stop",
                        "usage": {"total_tokens": 100},
                    },
                }

        tmp_root = local_store.ensure_dir(local_store.PROJECT_ROOT / "tmp")
        with tempfile.TemporaryDirectory(dir=tmp_root) as tmp_dir:
            output_dir = Path(tmp_dir)
            local_store.save_json(
                output_dir / "raw_text.json",
                {
                    "pages": [
                        {
                            "page": 1,
                            "text": (
                                "客户姓名：\n李\n资金账号：\n36914385\n"
                                "证券子账户：\n0268832573\n"
                                "深圳A股东卡号\n0268832573\n"
                                "统计区间：\n2025-01-01至2025-06-30"
                            ),
                        },
                        {
                            "page": 2,
                            "text": "2025-06-09 102558 88000046 36914385 300129 泰胜风能 证券卖出",
                        },
                    ]
                },
            )
            header = [
                "业务日期",
                "发生时间",
                "流水序号",
                "资金账号",
                "证券代码",
                "证券名称",
                "业务标志名称",
                "成交数量",
                "成交价格",
                "清算金额",
                "委托编号",
            ]
            rows = [header]
            for index in range(1, 46):
                rows.append(
                    [
                        "2025-02-05",
                        "093113",
                        f"880000{index:02d}",
                        "36914385",
                        "000837",
                        "秦川机床",
                        "证券买入",
                        "100",
                        "10.00",
                        "-1000.00",
                        f"230{index:02d}",
                    ]
                )
            second_page_rows = [header]
            second_page_rows.append(
                [
                    "2025-06-09",
                    "102558",
                    "88000046",
                    "36914385",
                    "300129",
                    "泰胜风能",
                    "证券卖出",
                    "-7700.0000",
                    "10.3860",
                    "79907.0946",
                    "23046",
                ]
            )
            local_store.save_json(
                output_dir / "tables.json",
                {
                    "tables": [
                        {"page": 1, "table_index": 1, "rows": rows},
                        {"page": 2, "table_index": 1, "rows": second_page_rows},
                    ]
                },
            )

            fake_llm = FakeLLMClient()
            result = GuangfaExtractor(
                prompt_loader=FakePromptLoader(),
                llm_client=fake_llm,
            ).extract(self.case_id, self.file_record, output_dir)

            self.assertGreater(len(fake_llm.prompts), 1)
            self.assertTrue(all("document_context:" in prompt for prompt in fake_llm.prompts))
            self.assertFalse(any("context_excerpt" in prompt for prompt in fake_llm.prompts))
            self.assertEqual(result["document_info"]["securities_account"], "0268832573")
            normalized = normalize_guangfa(self.case_id, result, self.file_record)
            self.assertTrue(normalized["full_transaction_rows"])
            for row in normalized["full_transaction_rows"]:
                self.assertEqual(row["securities_account"], "0268832573")

    def test_extractor_dedupes_overlap_trade_rows_during_batch_merge(self):
        from app.pipeline.guangfa_extractor import GUANGFA_TRADE_COLUMNS, GuangfaExtractor

        extractor = GuangfaExtractor(prompt_loader=object(), llm_client=object())
        base_row = [
            "gf_001",
            "深A",
            "",
            "2025-07-24",
            "095650",
            "807309015",
            "36914385",
            "002297",
            "博云新材",
            "sell",
            "-30000.0000",
            "10.3000",
            "308791.2800",
            "证券卖出",
            "2",
            "1",
            "",
        ]
        richer_overlap_row = [*base_row]
        richer_overlap_row[GUANGFA_TRADE_COLUMNS.index("securities_account")] = "002260819"
        richer_overlap_row[GUANGFA_TRADE_COLUMNS.index("order_no")] = "15132"

        merged = extractor._merge_batch_results(
            [
                {
                    "batch_id": "batch_001",
                    "trade_group": {
                        "trade_columns": GUANGFA_TRADE_COLUMNS,
                        "trades": [base_row],
                    },
                },
                {
                    "batch_id": "batch_002",
                    "trade_group": {
                        "trade_columns": GUANGFA_TRADE_COLUMNS,
                        "trades": [richer_overlap_row],
                    },
                },
            ]
        )

        trades = merged["trade_group"]["trades"]
        self.assertEqual(len(trades), 1)
        row = trades[0]
        self.assertEqual(row[GUANGFA_TRADE_COLUMNS.index("securities_account")], "002260819")
        self.assertEqual(row[GUANGFA_TRADE_COLUMNS.index("order_no")], "15132")

    def test_context_extracts_multiple_shareholder_cards_and_normalizer_applies_by_market(self):
        from app.pipeline.document_context import build_document_context
        from app.pipeline.normalizers.guangfa_normalizer import normalize_guangfa
        from app.services import local_store

        tmp_root = local_store.ensure_dir(local_store.PROJECT_ROOT / "tmp")
        with tempfile.TemporaryDirectory(dir=tmp_root) as tmp_dir:
            output_dir = Path(tmp_dir)
            local_store.save_json(
                output_dir / "raw_text.json",
                {
                    "pages": [
                        {
                            "page": 1,
                            "text": (
                                "基本信息\n"
                                "账户姓名\n资金账号\n上海A股东卡号\n上海B股东卡号\n"
                                "深圳A股东卡号\n深圳B股东卡号\n特转A股东卡号\n"
                                "证件类型\n证件号码\n"
                                "孙\n36914385\nA486746523\n/\n0022608195\n/\n/\n身份证\n1521011965\n"
                            ),
                        }
                    ]
                },
            )

            context = build_document_context(output_dir)

        self.assertEqual(
            context["securities_accounts"],
            {"沪A": "A486746523", "深A": "0022608195"},
        )

        normalized = normalize_guangfa(
            self.case_id,
            {
                "schema_version": "guangfa_business_event_understanding_v1",
                "source_type": "guangfa",
                "document_info": {
                    "holder_name": "孙",
                    "capital_account": "36914385",
                    "securities_accounts": context["securities_accounts"],
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
                    ],
                },
            },
            self.file_record,
        )

        rows = normalized["full_transaction_rows"]
        self.assertEqual(rows[0]["account_type"], "深A")
        self.assertEqual(rows[0]["securities_account"], "0022608195")
        self.assertEqual(rows[1]["account_type"], "沪A")
        self.assertEqual(rows[1]["securities_account"], "A486746523")
        self.assertEqual(normalized["review_items"], [])

    def test_context_extracts_shareholder_cards_when_ocr_placeholder_values_shift_table(self):
        from app.pipeline.document_context import build_document_context
        from app.services import local_store

        tmp_root = local_store.ensure_dir(local_store.PROJECT_ROOT / "tmp")
        with tempfile.TemporaryDirectory(dir=tmp_root) as tmp_dir:
            output_dir = Path(tmp_dir)
            local_store.save_json(
                output_dir / "ocr_result.json",
                {
                    "page_results": [
                        {
                            "page": 1,
                            "text": (
                                "基本信息\n"
                                "账户姓名\n资金账号\n上海A股东卡号\n上海B股东卡号\n"
                                "深圳A股东卡号\n深圳B股东卡号\n证件类型\n证件号码\n"
                                "张\n15685657\nA315570738\n1\n0002220266\n1\n身份证\n"
                                "资产信息\n"
                            ),
                        }
                    ]
                },
            )

            context = build_document_context(output_dir)

        self.assertEqual(
            context["securities_accounts"],
            {"沪A": "A315570738", "深A": "0002220266"},
        )

    def test_business_holding_keeps_top_level_chinese_fields_when_candidates_are_partial(self):
        from app.pipeline.case_event_resolver import resolve_case_events
        from app.pipeline.normalizers.guangfa_normalizer import normalize_guangfa

        normalized = normalize_guangfa(
            self.case_id,
            {
                "schema_version": "guangfa_business_event_understanding_v1",
                "source_type": "guangfa",
                "document_info": {
                    "document_title": "广发证券普通账户对账单",
                    "period_end": "2025-09-24",
                    "securities_accounts": {
                        "沪A": "A486746523",
                        "深A": "0022608195",
                    },
                },
                "holding_records": [
                    {
                        "holding_id": "asset_summary",
                        "账户类型": "",
                        "证券账号": "",
                        "证券代码": "",
                        "证券名称": "",
                        "持有数量": "",
                        "市值": "",
                        "币种": "人民币",
                        "source_evidence": {
                            "page": "1",
                            "row_no": "46-51",
                            "raw_text": "2025-09-24 人民币 0.0000 38862.9700 1306982.9700 0.0000",
                        },
                        "final_field_candidates": {"查询结果所属日期": "2025-09-24"},
                    },
                    {
                        "holding_id": "holding_001",
                        "账户类型": "深A",
                        "证券账号": "0022608195",
                        "证券代码": "000951",
                        "证券名称": "中国重汽",
                        "持有数量": "35000.0000",
                        "市值": "614250.0000",
                        "币种": "人民币",
                        "source_evidence": {
                            "page": "1",
                            "row_no": "61-68",
                            "raw_text": "2025-09-24 000951 中国重汽 35000.0000 614250.0000",
                        },
                        "final_field_candidates": {"查询结果所属日期": "2025-09-24"},
                    },
                    {
                        "holding_id": "holding_002",
                        "账户类型": "沪A",
                        "证券账号": "A486746523",
                        "证券代码": "600958",
                        "证券名称": "东方证券",
                        "持有数量": "60200.0000",
                        "市值": "638120.0000",
                        "币种": "人民币",
                        "source_evidence": {
                            "page": "1",
                            "row_no": "69-76",
                            "raw_text": "2025-09-24 600958 东方证券 60200.0000 638120.0000",
                        },
                        "final_field_candidates": {"查询结果所属日期": "2025-09-24"},
                    },
                ],
            },
            self.file_record,
        )

        self.assertEqual(len(normalized["holding_rows"]), 2)
        self.assertEqual(
            [
                (row["account_type"], row["securities_account"], row["security_code"], row["security_name"], row["quantity_raw"])
                for row in normalized["holding_rows"]
            ],
            [
                ("深A", "0022608195", "000951", "中国重汽", "35000.0000"),
                ("沪A", "A486746523", "600958", "东方证券", "60200.0000"),
            ],
        )
        resolved = resolve_case_events([], holding_rows=normalized["holding_rows"])
        self.assertEqual(len(resolved["holding_rows"]), 2)
        self.assertEqual(resolved["review_issue_rows"], [])

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

    def test_share_credit_for_convertible_bond_is_final_registration_without_price_review(self):
        from app.pipeline.case_event_resolver import resolve_case_events
        from app.pipeline.normalizers.guangfa_normalizer import normalize_guangfa

        normalized = normalize_guangfa(
            self.case_id,
            {
                "schema_version": "guangfa_business_event_understanding_v1",
                "source_type": "guangfa",
                "business_events": [
                    {
                        "raw_business_type": "股份入账",
                        "inferred_event_type": "股份入账",
                        "event_category": "证券登记入账",
                        "affects_holding": True,
                        "include_in_full_table": True,
                        "include_in_final_declaration": True,
                        "final_field_candidates": {
                            "账户类型": "深A",
                            "证券账号": "0268832573",
                            "证券代码": "123254",
                            "证券名称": "亿纬转债",
                            "变动类型": "股份入账",
                            "日期": "2025-03-31",
                            "成交数量": "1000.0000",
                            "成交单价": "",
                            "收付金额": "0.0000",
                        },
                        "source_evidence": {
                            "page": "1",
                            "row_no": "41",
                            "raw_text": "2025-03-31 101953 88000041 36914385 123254 亿纬转债 股份入账 1000.0000",
                        },
                    }
                ],
            },
            self.file_record,
        )

        self.assertEqual(normalized["review_items"], [])
        self.assertEqual(len(normalized["full_transaction_rows"]), 1)
        self.assertEqual(len(normalized["final_declaration_rows"]), 1)
        row = normalized["full_transaction_rows"][0]
        self.assertEqual(row["event_type"], "security_registration")
        self.assertEqual(row["direction"], "registration_in")
        self.assertEqual(row["transfer_type_raw"], "股份入账")
        self.assertEqual(row["price_raw"], "")
        self.assertEqual(row["amount_raw"], "0.0000")

        resolved = resolve_case_events(
            normalized["full_transaction_rows"],
            review_items=normalized["review_items"],
        )
        self.assertEqual(len(resolved["final_declaration_rows"]), 1)
        self.assertEqual(resolved["review_issue_rows"], [])

    def test_compact_trade_group_normalizes_ordinary_guangfa_trades(self):
        from app.pipeline.normalizers.guangfa_normalizer import normalize_guangfa

        normalized = normalize_guangfa(
            self.case_id,
            {
                "schema_version": "guangfa_business_event_understanding_v1",
                "source_type": "guangfa",
                "document_info": {
                    "holder_name": "李",
                    "account_type": "深A",
                    "securities_account": "0268832573",
                    "period_start": "2025-01-01",
                    "period_end": "2025-06-30",
                },
                "trade_group": {
                    "event_type": "ordinary_trade_group",
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
                            "gf_001",
                            "",
                            "",
                            "2025-06-09",
                            "102558",
                            "88000046",
                            "36914385",
                            "300129",
                            "泰胜风能",
                            "sell",
                            "-7700.0000",
                            "10.3860",
                            "79907.0946",
                            "证券卖出",
                            "2",
                            "46",
                            "23046",
                        ]
                    ],
                },
                "business_events": [],
                "holding_records": [],
                "negative_proofs": [],
            },
            self.file_record,
        )

        self.assertEqual(len(normalized["full_transaction_rows"]), 1)
        self.assertEqual(len(normalized["final_declaration_rows"]), 1)
        row = normalized["full_transaction_rows"][0]
        self.assertEqual(row["securities_account"], "0268832573")
        self.assertEqual(row["account_type"], "深A")
        self.assertEqual(row["security_code"], "300129")
        self.assertEqual(row["security_name"], "泰胜风能")
        self.assertEqual(row["direction"], "sell")
        self.assertEqual(row["event_date"], "2025-06-09")
        self.assertEqual(row["event_time"], "102558")
        self.assertEqual(row["serial_no"], "88000046")
        self.assertEqual(row["order_no"], "23046")
        self.assertEqual(row["amount_raw"], "79907.0946")
        self.assertEqual(normalized["review_items"], [])

    def test_batch_merge_preserves_compact_guangfa_trade_group(self):
        from app.pipeline.guangfa_extractor import GuangfaExtractor

        columns = [
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
        ]
        merged = GuangfaExtractor()._merge_batch_results(
            [
                {
                    "batch_id": "batch_001",
                    "trade_group": {
                        "trade_columns": columns,
                        "trades": [
                            [
                                "gf_001",
                                "深A",
                                "0268832573",
                                "2025-06-09",
                                "102558",
                                "88000046",
                                "36914385",
                                "300129",
                                "泰胜风能",
                                "sell",
                                "-7700.0000",
                                "10.3860",
                                "79907.0946",
                                "证券卖出",
                                "2",
                                "46",
                                "23046",
                            ]
                        ],
                    },
                    "llm_response_metadata": {"finish_reason": "stop"},
                },
                {
                    "batch_id": "batch_002",
                    "trade_group": {
                        "trade_columns": columns,
                        "trades": [
                            [
                                "gf_002",
                                "深A",
                                "0268832573",
                                "2025-06-10",
                                "102711",
                                "88000047",
                                "36914385",
                                "300129",
                                "泰胜风能",
                                "buy",
                                "7300.0000",
                                "9.9080",
                                "-72351.1184",
                                "证券买入",
                                "2",
                                "47",
                                "23047",
                            ]
                        ],
                    },
                    "llm_response_metadata": {"finish_reason": "stop"},
                },
            ]
        )

        self.assertEqual(merged["trade_group"]["trade_columns"], columns)
        self.assertEqual(len(merged["trade_group"]["trades"]), 2)
        self.assertEqual(merged["trade_group"]["trades"][0][7], "300129")
        self.assertEqual(merged["extract_status"], "success")

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

    def test_guangfa_pure_cash_flow_variants_are_ignored(self):
        from app.pipeline.normalizers.guangfa_normalizer import normalize_guangfa

        normalized = normalize_guangfa(
            self.case_id,
            {
                "schema_version": "guangfa_business_event_understanding_v1",
                "source_type": "guangfa",
                "business_events": [
                    {
                        "raw_business_type": "银行转存",
                        "inferred_event_type": "银行转存",
                        "include_in_full_table": True,
                        "include_in_final_declaration": False,
                        "final_field_candidates": {
                            "变动类型": "银行转存",
                            "日期": "2025-01-02",
                            "收付金额": "1000.00",
                        },
                    },
                    {
                        "raw_business_type": "转账冻结取消",
                        "inferred_event_type": "转账冻结取消",
                        "include_in_full_table": True,
                        "include_in_final_declaration": False,
                        "final_field_candidates": {
                            "变动类型": "转账冻结取消",
                            "日期": "2025-01-03",
                            "收付金额": "1000.00",
                        },
                    },
                    {
                        "raw_business_type": "账户利息入账",
                        "inferred_event_type": "账户利息入账",
                        "include_in_full_table": True,
                        "include_in_final_declaration": False,
                        "final_field_candidates": {
                            "变动类型": "账户利息入账",
                            "日期": "2025-01-04",
                            "收付金额": "1.23",
                        },
                    },
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

    def test_ordinary_trade_from_fund_flow_is_ignored(self):
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
                            "row_no": "37",
                            "raw_text": "2025-04-14 191115 805409415 证券买入 中国重汽",
                        },
                        "review_reasons": ["普通交易仅见于资金流水明细，需核对场内交割流水明细"],
                    }
                ],
            },
            self.file_record,
        )
        resolved = resolve_case_events(
            normalized["full_transaction_rows"],
            review_items=normalized["review_items"],
        )

        self.assertEqual(len(resolved["full_transaction_rows"]), 0)
        self.assertEqual(len(resolved["final_declaration_rows"]), 0)
        self.assertEqual(resolved["review_issue_rows"], [])

    def test_guangfa_floor_trade_inherits_account_from_same_file_holding(self):
        from app.pipeline.case_event_resolver import resolve_case_events
        from app.pipeline.normalizers.guangfa_normalizer import normalize_guangfa

        columns = [
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
        ]
        normalized = normalize_guangfa(
            self.case_id,
            {
                "schema_version": "guangfa_business_event_understanding_v1",
                "source_type": "guangfa",
                "trade_group": {
                    "trade_columns": columns,
                    "trades": [
                        [
                            "gf_floor_001",
                            "深A",
                            "",
                            "2025-04-14",
                            "142805",
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
                            "84",
                            "41398",
                        ]
                    ],
                },
                "holding_records": [
                    {
                        "账户类型": "深A",
                        "证券账号": "002260819",
                        "证券代码": "000951",
                        "证券名称": "中国重汽",
                        "持有数量": "35000.0000",
                        "市值": "614250.0000",
                        "查询结果所属日期": "2025-09-24",
                    }
                ],
            },
            self.file_record,
        )
        resolved = resolve_case_events(
            normalized["full_transaction_rows"],
            normalized["holding_rows"],
            normalized["review_items"],
        )

        self.assertEqual(len(resolved["review_issue_rows"]), 0)
        self.assertEqual(len(resolved["final_declaration_rows"]), 1)
        row = resolved["final_declaration_rows"][0]
        self.assertEqual(row["securities_account"], "002260819")
        self.assertEqual(row["security_code"], "000951")
        self.assertEqual(row["security_name"], "中国重汽")

    def test_same_file_partial_duplicate_trade_prefers_row_with_order_no(self):
        from app.pipeline.case_event_resolver import resolve_case_events

        base = {
            "case_id": self.case_id,
            "file_id": "file_001",
            "file_no": "001",
            "original_file_name": "广发证券对账单.pdf",
            "account_type": "深A",
            "securities_account": "002260819",
            "event_id": "805409415",
            "event_type": "ordinary_trade",
            "event_date": "2025-04-14",
            "serial_no": "805409415",
            "security_code": "000951",
            "security_name": "中国重汽",
            "direction": "buy",
            "quantity_raw": "5000.0000",
            "price_raw": "18.7400",
            "amount_raw": "-93716.4400",
            "transfer_type_raw": "证券买入",
        }
        incomplete = {
            **base,
            "event_time": "142805",
            "order_no": "",
            "row_nos": "84",
        }
        complete = {
            **base,
            "event_time": "142805",
            "order_no": "41398",
            "row_nos": "84",
        }

        resolved = resolve_case_events([incomplete, complete])

        self.assertEqual(len(resolved["full_transaction_rows"]), 1)
        row = resolved["full_transaction_rows"][0]
        self.assertEqual(row["order_no"], "41398")
        self.assertEqual(row["event_time"], "142805")
        self.assertEqual(len(resolved["final_declaration_rows"]), 1)

    def test_same_file_partial_duplicate_does_not_merge_when_trade_times_conflict(self):
        from app.pipeline.case_event_resolver import resolve_case_events

        base = {
            "case_id": self.case_id,
            "file_id": "file_001",
            "file_no": "001",
            "original_file_name": "广发证券对账单.pdf",
            "account_type": "深A",
            "securities_account": "002260819",
            "event_id": "805409415",
            "event_type": "ordinary_trade",
            "event_date": "2025-04-14",
            "serial_no": "805409415",
            "security_code": "000951",
            "security_name": "中国重汽",
            "direction": "buy",
            "quantity_raw": "5000.0000",
            "price_raw": "18.7400",
            "amount_raw": "-93716.4400",
            "transfer_type_raw": "证券买入",
        }
        fund_flow_like = {
            **base,
            "event_time": "191115",
            "order_no": "",
            "row_nos": "37",
        }
        floor_delivery = {
            **base,
            "event_time": "142805",
            "order_no": "41398",
            "row_nos": "84",
        }

        resolved = resolve_case_events([fund_flow_like, floor_delivery])

        self.assertEqual(len(resolved["full_transaction_rows"]), 2)

    def test_trade_account_reference_prefers_holding_over_cash_dividend_conflict(self):
        from app.pipeline.case_event_resolver import resolve_case_events

        trade = {
            "case_id": self.case_id,
            "file_id": "file_001",
            "file_no": "001",
            "account_type": "深A",
            "securities_account": "",
            "event_id": "805409415",
            "event_type": "ordinary_trade",
            "event_date": "2025-04-14",
            "event_time": "142805",
            "serial_no": "805409415",
            "order_no": "41398",
            "security_code": "000951",
            "security_name": "中国重汽",
            "direction": "buy",
            "quantity_raw": "5000.0000",
            "price_raw": "18.7400",
            "amount_raw": "-93716.4400",
        }
        cash_dividend = {
            "case_id": self.case_id,
            "file_id": "file_001",
            "file_no": "001",
            "account_type": "深A",
            "securities_account": "0022608195",
            "event_id": "803762914",
            "event_type": "cash_dividend",
            "event_date": "2025-06-26",
            "security_code": "000951",
            "security_name": "中国重汽",
            "direction": "cash_income",
            "amount_raw": "14175.0000",
        }
        holding = {
            "case_id": self.case_id,
            "file_id": "file_001",
            "file_no": "001",
            "account_type": "深A",
            "securities_account": "002260819",
            "holding_date": "2025-09-24",
            "security_code": "000951",
            "security_name": "中国重汽",
            "quantity_raw": "35000.0000",
            "market_value": "614250.0000",
        }

        resolved = resolve_case_events([trade, cash_dividend], [holding])

        self.assertEqual(len(resolved["review_issue_rows"]), 0)
        final_row = resolved["final_declaration_rows"][0]
        self.assertEqual(final_row["securities_account"], "002260819")

    def test_trade_inherits_unique_same_market_account_from_holding(self):
        from app.pipeline.case_event_resolver import resolve_case_events

        trade = {
            "case_id": self.case_id,
            "file_id": "file_001",
            "file_no": "001",
            "account_type": "深A",
            "securities_account": "",
            "event_id": "807309015",
            "event_type": "ordinary_trade",
            "event_date": "2025-07-24",
            "event_time": "095650",
            "serial_no": "807309015",
            "order_no": "15132",
            "security_code": "002297",
            "security_name": "博云新材",
            "direction": "sell",
            "quantity_raw": "-30000.0000",
            "price_raw": "10.3000",
            "amount_raw": "308791.2800",
        }
        holding = {
            "case_id": self.case_id,
            "file_id": "file_001",
            "file_no": "001",
            "account_type": "深A",
            "securities_account": "002260819",
            "holding_date": "2025-09-24",
            "security_code": "000951",
            "security_name": "中国重汽",
            "quantity_raw": "35000.0000",
            "market_value": "614250.0000",
        }

        resolved = resolve_case_events([trade], [holding])

        self.assertEqual(len(resolved["review_issue_rows"]), 0)
        final_row = resolved["final_declaration_rows"][0]
        self.assertEqual(final_row["security_code"], "002297")
        self.assertEqual(final_row["securities_account"], "002260819")

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
