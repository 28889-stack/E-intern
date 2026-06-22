import sys
from pathlib import Path
import unittest
from unittest.mock import patch


API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


class _FakePdf:
    def __init__(self, pages):
        self.pages = pages

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _PdfplumberTextPage:
    def extract_tables(self, table_settings=None):
        if table_settings and table_settings.get("vertical_strategy") == "text":
            return [
                [
                    ["业务日期", "证券代码", "证券名称", "成交金额"],
                    ["2025-04-14", "000951", "中国重汽", "-93716.4400"],
                ]
            ]
        return []


class _EmptyPdfplumberPage:
    def extract_tables(self, table_settings=None):
        return []


class _FakeFitzDoc:
    def __init__(self, pages):
        self._pages = pages

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def __iter__(self):
        return iter(self._pages)


class _FakeFitzPage:
    def find_tables(self):
        return _FakeTableFinder(
            [
                _FakeFitzTable(
                    [
                        ["业务日期", "证券代码", "证券名称", "成交金额"],
                        ["2025-04-14", "000951", "中国重汽", "-93716.4400"],
                    ]
                )
            ]
        )


class _FakeTableFinder:
    def __init__(self, tables):
        self.tables = tables


class _FakeFitzTable:
    def __init__(self, rows):
        self._rows = rows

    def extract(self):
        return self._rows


class _FakeFitzModule:
    def open(self, file_path):
        return _FakeFitzDoc([_FakeFitzPage()])


class PdfTableExtractorTest(unittest.TestCase):
    def test_uses_pdfplumber_text_strategy_when_default_finds_no_tables(self):
        from app.pipeline.pdf_table_extractor import extract_pdf_tables

        with patch(
            "app.pipeline.pdf_table_extractor.pdfplumber.open",
            return_value=_FakePdf([_PdfplumberTextPage()]),
        ):
            result = extract_pdf_tables("statement.pdf")

        self.assertEqual(result["table_extract_status"], "success")
        self.assertEqual(result["table_count"], 1)
        self.assertEqual(result["tables"][0]["extractor"], "pdfplumber_text")
        self.assertEqual(result["tables"][0]["rows"][1][2], "中国重汽")
        self.assertIn("pdfplumber_default", result["tried_strategies"])
        self.assertIn("pdfplumber_text", result["tried_strategies"])

    def test_uses_pymupdf_find_tables_when_pdfplumber_finds_no_tables(self):
        from app.pipeline import pdf_table_extractor

        with patch(
            "app.pipeline.pdf_table_extractor.pdfplumber.open",
            return_value=_FakePdf([_EmptyPdfplumberPage()]),
        ), patch.object(
            pdf_table_extractor,
            "fitz",
            _FakeFitzModule(),
            create=True,
        ):
            result = pdf_table_extractor.extract_pdf_tables("statement.pdf")

        self.assertEqual(result["table_extract_status"], "success")
        self.assertEqual(result["table_count"], 1)
        self.assertEqual(result["tables"][0]["extractor"], "pymupdf_find_tables")
        self.assertEqual(result["tables"][0]["rows"][1][3], "-93716.4400")
        self.assertIn("pymupdf_find_tables", result["tried_strategies"])

    def test_guangfa_table_batch_keeps_first_row_when_table_has_no_header(self):
        from app.pipeline.guangfa_extractor import GuangfaExtractor

        extractor = GuangfaExtractor.__new__(GuangfaExtractor)
        rows = extractor._flatten_table_rows(
            {
                "tables": [
                    {
                        "page": 1,
                        "table_index": 1,
                        "rows": [
                            ["2025-04-14", "000951", "中国重汽", "-93716.4400"],
                            ["2025-04-15", "600958", "东方证券", "116720.4800"],
                        ],
                    }
                ]
            }
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["cells"][0], "2025-04-14")
        self.assertEqual(rows[0]["header"], [])

    def test_guangfa_table_batch_skips_fund_flow_section(self):
        from app.pipeline.guangfa_extractor import GuangfaExtractor

        extractor = GuangfaExtractor.__new__(GuangfaExtractor)
        rows = extractor._flatten_table_rows(
            {
                "tables": [
                    {
                        "page": 1,
                        "table_index": 1,
                        "rows": [
                            ["持仓信息"],
                            ["业务日期", "证券代码", "证券名称", "当前数量"],
                            ["2025-09-24", "000951", "中国重汽", "35000.0000"],
                            ["资金流水明细"],
                            ["业务日期", "发生时间", "流水序号", "业务标志", "发生金额"],
                            ["2025-04-14", "191115", "805409415", "证券买入", "-93716.4400"],
                            ["场内交割流水明细"],
                            ["业务日期", "成交时间", "流水序号", "证券代码", "证券名称", "业务标志", "成交数量", "成交价格", "成交金额"],
                            ["2025-04-14", "142805", "805409415", "000951", "中国重汽", "证券买入", "5000.0000", "18.7400", "-93716.4400"],
                        ],
                    }
                ]
            }
        )

        flattened_text = "\n".join(" ".join(row["cells"]) for row in rows)
        self.assertIn("持仓信息", {row["table_title"] for row in rows})
        self.assertIn("场内交割流水明细", {row["table_title"] for row in rows})
        self.assertIn("35000.0000", flattened_text)
        self.assertIn("142805", flattened_text)
        self.assertNotIn("191115", flattened_text)

    def test_chinaclear_table_batch_keeps_first_row_when_table_has_no_header(self):
        from app.pipeline.chinaclear_extractor import ChinaclearExtractor

        extractor = ChinaclearExtractor.__new__(ChinaclearExtractor)
        rows = extractor._flatten_table_rows(
            {
                "tables": [
                    {
                        "page": 1,
                        "table_index": 1,
                        "rows": [
                            ["2025-04-14", "000951", "中国重汽", "买入"],
                            ["2025-04-15", "600958", "东方证券", "卖出"],
                        ],
                    }
                ]
            }
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["cells"][0], "2025-04-14")
        self.assertEqual(rows[0]["header"], [])


if __name__ == "__main__":
    unittest.main()
