from pathlib import Path

import pdfplumber

try:
    import fitz
except ImportError:
    fitz = None


PDFPLUMBER_TEXT_TABLE_SETTINGS = {
    "vertical_strategy": "text",
    "horizontal_strategy": "text",
    "snap_tolerance": 3,
    "join_tolerance": 3,
    "intersection_tolerance": 5,
    "text_tolerance": 3,
}


def extract_pdf_tables(file_path: str | Path) -> dict:
    tried_strategies = []
    strategy_errors = []

    try:
        tables = _extract_with_pdfplumber(
            file_path,
            tried_strategies=tried_strategies,
            strategy_errors=strategy_errors,
        )
        if not tables:
            tables = _extract_with_pymupdf(
                file_path,
                tried_strategies=tried_strategies,
                strategy_errors=strategy_errors,
            )

        return {
            "table_extract_status": "success",
            "tables": tables,
            "table_count": len(tables),
            "tried_strategies": tried_strategies,
            "strategy_errors": strategy_errors,
            "manual_review_required": False,
            "review_reasons": [],
        }
    except Exception as exc:
        return {
            "table_extract_status": "partial_failed",
            "tables": [],
            "table_count": 0,
            "tried_strategies": tried_strategies,
            "strategy_errors": [*strategy_errors, str(exc)],
            "manual_review_required": True,
            "review_reasons": [f"PDF 表格提取失败：{exc}"],
        }


def _extract_with_pdfplumber(
    file_path: str | Path,
    *,
    tried_strategies: list[str],
    strategy_errors: list[str],
) -> list[dict]:
    strategies = [
        ("pdfplumber_default", None),
        ("pdfplumber_text", PDFPLUMBER_TEXT_TABLE_SETTINGS),
    ]

    for strategy_name, table_settings in strategies:
        tried_strategies.append(strategy_name)
        try:
            tables = []
            with pdfplumber.open(file_path) as pdf:
                for page_index, page in enumerate(pdf.pages, start=1):
                    page_tables = _extract_pdfplumber_page_tables(page, table_settings)
                    tables.extend(
                        _format_tables(
                            page_tables,
                            page=page_index,
                            extractor=strategy_name,
                        )
                    )
            if tables:
                return tables
        except Exception as exc:
            strategy_errors.append(f"{strategy_name}: {exc}")

    return []


def _extract_pdfplumber_page_tables(page, table_settings: dict | None) -> list:
    if table_settings:
        return page.extract_tables(table_settings=table_settings) or []
    return page.extract_tables() or []


def _extract_with_pymupdf(
    file_path: str | Path,
    *,
    tried_strategies: list[str],
    strategy_errors: list[str],
) -> list[dict]:
    strategy_name = "pymupdf_find_tables"
    tried_strategies.append(strategy_name)
    if fitz is None:
        strategy_errors.append(f"{strategy_name}: PyMuPDF 未安装")
        return []

    try:
        tables = []
        with fitz.open(file_path) as doc:
            for page_index, page in enumerate(doc, start=1):
                find_tables = getattr(page, "find_tables", None)
                if not callable(find_tables):
                    continue

                table_finder = find_tables()
                page_tables = []
                for table in getattr(table_finder, "tables", []) or []:
                    extract = getattr(table, "extract", None)
                    if callable(extract):
                        page_tables.append(extract())
                tables.extend(
                    _format_tables(
                        page_tables,
                        page=page_index,
                        extractor=strategy_name,
                    )
                )
        return tables
    except Exception as exc:
        strategy_errors.append(f"{strategy_name}: {exc}")
        return []


def _format_tables(page_tables: list, *, page: int, extractor: str) -> list[dict]:
    tables = []
    for table_index, rows in enumerate(page_tables, start=1):
        normalized_rows = _normalize_rows(rows)
        if not _has_useful_table_rows(normalized_rows):
            continue

        tables.append(
            {
                "page": page,
                "table_index": table_index,
                "extractor": extractor,
                "rows": normalized_rows,
            }
        )
    return tables


def _normalize_rows(rows) -> list[list[str]]:
    normalized_rows = []
    for row in rows or []:
        if isinstance(row, (list, tuple)):
            normalized_rows.append(["" if cell is None else str(cell) for cell in row])
        elif row is not None:
            normalized_rows.append([str(row)])
    return normalized_rows


def _has_useful_table_rows(rows: list[list[str]]) -> bool:
    non_empty_rows = [
        row for row in rows if any(str(cell).strip() for cell in row)
    ]
    return len(non_empty_rows) >= 2
