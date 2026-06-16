from pathlib import Path

import pdfplumber


def extract_pdf_tables(file_path: str | Path) -> dict:
    try:
        tables = []
        with pdfplumber.open(file_path) as pdf:
            for page_index, page in enumerate(pdf.pages, start=1):
                page_tables = page.extract_tables() or []
                for table_index, rows in enumerate(page_tables, start=1):
                    tables.append(
                        {
                            "page": page_index,
                            "table_index": table_index,
                            "rows": rows,
                        }
                    )

        return {
            "table_extract_status": "success",
            "tables": tables,
            "table_count": len(tables),
            "manual_review_required": False,
            "review_reasons": [],
        }
    except Exception as exc:
        return {
            "table_extract_status": "partial_failed",
            "tables": [],
            "table_count": 0,
            "manual_review_required": True,
            "review_reasons": [f"PDF 表格提取失败：{exc}"],
        }
