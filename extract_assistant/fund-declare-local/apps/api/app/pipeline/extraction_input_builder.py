from pathlib import Path
from typing import Any

from app.services.local_store import read_json


def build_extraction_input(process_output_dir: str | Path) -> dict:
    output_dir = Path(process_output_dir)
    input_sections = []
    sources = {
        "raw_text_path": None,
        "tables_path": None,
        "ocr_result_path": None,
    }

    raw_text_path = output_dir / "raw_text.json"
    raw_text = read_json(raw_text_path, None)
    if isinstance(raw_text, dict):
        sources["raw_text_path"] = str(raw_text_path)
        for page in _as_list(raw_text.get("pages")):
            if isinstance(page, dict):
                input_sections.append(
                    {
                        "section_type": "pdf_text",
                        "page": page.get("page"),
                        "text": str(page.get("text", "")),
                    }
                )

    tables_path = output_dir / "tables.json"
    tables = read_json(tables_path, None)
    if isinstance(tables, dict):
        sources["tables_path"] = str(tables_path)
        for table in _as_list(tables.get("tables")):
            if not isinstance(table, dict):
                continue

            input_sections.append(
                {
                    "section_type": "pdf_table",
                    "page": table.get("page"),
                    "table_index": table.get("table_index"),
                    "text": _rows_to_text(table.get("rows")),
                }
            )

    ocr_result_path = output_dir / "ocr_result.json"
    ocr_result = read_json(ocr_result_path, None)
    if isinstance(ocr_result, dict):
        sources["ocr_result_path"] = str(ocr_result_path)
        for page_result in _as_list(ocr_result.get("page_results")):
            if isinstance(page_result, dict):
                input_sections.append(
                    {
                        "section_type": "ocr_text",
                        "page": page_result.get("page"),
                        "text": str(page_result.get("text", "")),
                    }
                )

    input_text = _sections_to_text(input_sections)
    review_reasons = [] if input_text else ["抽取输入文本为空"]

    return {
        "input_text": input_text,
        "sources": sources,
        "input_sections": input_sections,
        "manual_review_required": bool(review_reasons),
        "review_reasons": review_reasons,
    }


def _sections_to_text(input_sections: list[dict]) -> str:
    text_parts = []
    for section in input_sections:
        text = str(section.get("text", "")).strip()
        if not text:
            continue

        page = section.get("page")
        table_index = section.get("table_index")
        label_parts = [str(section.get("section_type", "section"))]
        if page is not None:
            label_parts.append(f"page={page}")
        if table_index is not None:
            label_parts.append(f"table_index={table_index}")
        text_parts.append(f"[{' '.join(label_parts)}]\n{text}")

    return "\n\n".join(text_parts)


def _rows_to_text(rows: Any) -> str:
    row_texts = []
    for row in _as_list(rows):
        if isinstance(row, list):
            row_texts.append("\t".join("" if cell is None else str(cell) for cell in row))
        elif row is not None:
            row_texts.append(str(row))
    return "\n".join(row_texts)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]
