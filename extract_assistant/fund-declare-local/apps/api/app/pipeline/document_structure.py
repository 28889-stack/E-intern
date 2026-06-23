from __future__ import annotations

from pathlib import Path
from statistics import median
from typing import Any

from app.services.local_store import read_json, save_json


DOCUMENT_STRUCTURE_VERSION = "document_structure_v1"


def build_document_structure(output_dir: str | Path) -> dict[str, Any]:
    output_path = Path(output_dir)
    pages_by_no: dict[int, dict[str, Any]] = {}
    sources = {
        "raw_text_path": None,
        "tables_path": None,
        "ocr_result_path": None,
    }

    raw_text_path = output_path / "raw_text.json"
    raw_text = read_json(raw_text_path, None)
    if isinstance(raw_text, dict):
        sources["raw_text_path"] = str(raw_text_path)
        _add_raw_text_pages(pages_by_no, raw_text)

    tables_path = output_path / "tables.json"
    tables = read_json(tables_path, None)
    if isinstance(tables, dict):
        sources["tables_path"] = str(tables_path)
        _add_pdf_tables(pages_by_no, tables)

    ocr_result_path = output_path / "ocr_result.json"
    ocr_result = read_json(ocr_result_path, None)
    if isinstance(ocr_result, dict):
        sources["ocr_result_path"] = str(ocr_result_path)
        _add_ocr_pages(pages_by_no, ocr_result)

    pages = [pages_by_no[page_no] for page_no in sorted(pages_by_no)]
    result = {
        "document_structure_status": "success",
        "schema_version": DOCUMENT_STRUCTURE_VERSION,
        "page_count": len(pages),
        "pages": pages,
        "sources": sources,
        "review_reasons": [] if pages else ["未能生成结构化文档信息"],
    }
    save_json(output_path / "document_structure.json", result)
    return result


def document_structure_to_tables_payload(
    document_structure: dict[str, Any],
) -> dict[str, Any]:
    tables = []
    for page in _as_list(document_structure.get("pages")):
        if not isinstance(page, dict):
            continue
        page_no = _page_no(page)
        for table_index, table in enumerate(_as_list(page.get("tables")), start=1):
            if not isinstance(table, dict):
                continue
            rows = []
            row_metadata = []
            cell_metadata = []
            for row in _as_list(table.get("rows")):
                if not isinstance(row, dict):
                    continue
                cells = [
                    str(cell.get("text", ""))
                    for cell in _as_list(row.get("cells"))
                    if isinstance(cell, dict)
                ]
                if any(cell.strip() for cell in cells):
                    rows.append(cells)
                    row_metadata.append(_table_row_metadata(row))
                    cell_metadata.append(
                        [
                            _table_cell_metadata(cell)
                            for cell in _as_list(row.get("cells"))
                            if isinstance(cell, dict)
                        ]
                    )
            if not rows:
                continue
            tables.append(
                {
                    "page": page_no,
                    "table_index": table.get("table_index") or table_index,
                    "table_id": table.get("table_id", ""),
                    "extractor": table.get("structure_source", "document_structure"),
                    "table_type": table.get("table_type", ""),
                    "rows": rows,
                    "row_metadata": row_metadata,
                    "cell_metadata": cell_metadata,
                }
            )
    return {"tables": tables}


def _table_row_metadata(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "row_id": row.get("row_id", ""),
        "row_index": row.get("row_index"),
        "bbox": row.get("bbox"),
    }


def _table_cell_metadata(cell: dict[str, Any]) -> dict[str, Any]:
    return {
        "cell_id": cell.get("cell_id", ""),
        "column_index": cell.get("column_index"),
        "column_name": cell.get("column_name", ""),
        "bbox": cell.get("bbox"),
        "source_line_id": cell.get("source_line_id", ""),
    }


def _add_raw_text_pages(
    pages_by_no: dict[int, dict[str, Any]],
    raw_text: dict[str, Any],
) -> None:
    for page in _as_list(raw_text.get("pages")):
        if not isinstance(page, dict):
            continue
        page_no = _page_no(page)
        text = str(page.get("text", "")).strip()
        if not text:
            continue
        target_page = _ensure_page(pages_by_no, page_no)
        target_page["raw_text"] = text
        if target_page["lines"]:
            continue
        for line_index, line_text in enumerate(_non_empty_lines(text), start=1):
            target_page["lines"].append(
                {
                    "line_id": f"p{page_no:03d}_pdf_l{line_index:03d}",
                    "line_index": line_index,
                    "text": line_text,
                    "bbox": None,
                    "confidence": None,
                    "source": "raw_text",
                }
            )


def _add_pdf_tables(
    pages_by_no: dict[int, dict[str, Any]],
    tables_payload: dict[str, Any],
) -> None:
    for table_index, table in enumerate(_as_list(tables_payload.get("tables")), start=1):
        if not isinstance(table, dict):
            continue
        rows = _as_list(table.get("rows"))
        if not rows:
            continue
        page_no = _page_no(table)
        normalized_rows = _normalize_pdf_table_rows(page_no, table_index, rows)
        if not normalized_rows:
            continue
        _ensure_page(pages_by_no, page_no)["tables"].append(
            {
                "table_id": f"p{page_no:03d}_pdf_table_{table_index:03d}",
                "table_index": table.get("table_index") or table_index,
                "table_type": "pdf_table",
                "structure_source": table.get("extractor") or "tables_json",
                "rows": normalized_rows,
            }
        )


def _add_ocr_pages(
    pages_by_no: dict[int, dict[str, Any]],
    ocr_result: dict[str, Any],
) -> None:
    for page in _ocr_pages(ocr_result):
        if not isinstance(page, dict):
            continue
        page_no = _page_no(page)
        target_page = _ensure_page(pages_by_no, page_no)
        lines = _ocr_lines(page_no, page)
        if lines:
            target_page["lines"] = lines
        elif not target_page["lines"]:
            for line_index, line_text in enumerate(
                _non_empty_lines(str(page.get("text") or "")),
                start=1,
            ):
                target_page["lines"].append(
                    {
                        "line_id": f"p{page_no:03d}_ocr_l{line_index:03d}",
                        "line_index": line_index,
                        "text": line_text,
                        "bbox": None,
                        "confidence": page.get("confidence_avg"),
                        "source": "ocr_text",
                    }
                )
        ocr_table = _build_ocr_layout_table(page_no, target_page["lines"])
        if ocr_table:
            target_page["tables"].append(ocr_table)


def _normalize_pdf_table_rows(
    page_no: int,
    table_index: int,
    rows: list[Any],
) -> list[dict[str, Any]]:
    header = rows[0] if rows and isinstance(rows[0], list) else []
    normalized_rows = []
    for row_index, row in enumerate(rows, start=1):
        if not isinstance(row, list):
            continue
        cells = []
        for column_index, cell in enumerate(row, start=1):
            cells.append(
                {
                    "cell_id": (
                        f"p{page_no:03d}_t{table_index:03d}_"
                        f"r{row_index:03d}_c{column_index:03d}"
                    ),
                    "column_index": column_index,
                    "column_name": (
                        str(header[column_index - 1])
                        if row_index > 1 and column_index <= len(header)
                        else ""
                    ),
                    "text": "" if cell is None else str(cell),
                    "bbox": None,
                }
            )
        if any(str(cell.get("text", "")).strip() for cell in cells):
            normalized_rows.append(
                {
                    "row_id": f"p{page_no:03d}_t{table_index:03d}_r{row_index:03d}",
                    "row_index": row_index,
                    "text": "\t".join(cell["text"] for cell in cells),
                    "bbox": None,
                    "cells": cells,
                }
            )
    return normalized_rows


def _ocr_lines(page_no: int, page: dict[str, Any]) -> list[dict[str, Any]]:
    lines = []
    for line_index, block in enumerate(_as_list(page.get("blocks")), start=1):
        if not isinstance(block, dict):
            continue
        text = str(block.get("text") or "").strip()
        if not text:
            continue
        lines.append(
            {
                "line_id": f"p{page_no:03d}_ocr_l{line_index:03d}",
                "line_index": line_index,
                "text": text,
                "bbox": _normalize_bbox(block.get("bbox")),
                "confidence": block.get("confidence"),
                "source": "ocr_block",
            }
        )
    return lines


def _build_ocr_layout_table(
    page_no: int,
    lines: list[dict[str, Any]],
) -> dict[str, Any] | None:
    positioned_lines = [line for line in lines if line.get("bbox")]
    if len(positioned_lines) < 4:
        return None

    heights = [
        max(float(line["bbox"][3]) - float(line["bbox"][1]), 1)
        for line in positioned_lines
    ]
    y_threshold = max(8.0, median(heights) * 0.85)
    grouped_rows: list[dict[str, Any]] = []

    for line in sorted(
        positioned_lines,
        key=lambda item: (_bbox_center_y(item["bbox"]), float(item["bbox"][0])),
    ):
        center_y = _bbox_center_y(line["bbox"])
        if not grouped_rows or abs(center_y - grouped_rows[-1]["center_y"]) > y_threshold:
            grouped_rows.append({"center_y": center_y, "lines": [line]})
            continue
        grouped_rows[-1]["lines"].append(line)
        grouped_rows[-1]["center_y"] = (
            grouped_rows[-1]["center_y"] * (len(grouped_rows[-1]["lines"]) - 1)
            + center_y
        ) / len(grouped_rows[-1]["lines"])

    rows = []
    for row_index, row in enumerate(grouped_rows, start=1):
        row_lines = sorted(row["lines"], key=lambda item: float(item["bbox"][0]))
        if len(row_lines) < 2:
            continue
        cells = []
        for column_index, line in enumerate(row_lines, start=1):
            cells.append(
                {
                    "cell_id": f"p{page_no:03d}_ocr_r{row_index:03d}_c{column_index:03d}",
                    "column_index": column_index,
                    "column_name": "",
                    "text": line["text"],
                    "bbox": line["bbox"],
                    "source_line_id": line["line_id"],
                }
            )
        row_bbox = _union_bboxes([cell["bbox"] for cell in cells])
        rows.append(
            {
                "row_id": f"p{page_no:03d}_ocr_row_{row_index:03d}",
                "row_index": row_index,
                "text": "\t".join(cell["text"] for cell in cells),
                "bbox": row_bbox,
                "cells": cells,
            }
        )

    if len(rows) < 2:
        return None
    return {
        "table_id": f"p{page_no:03d}_ocr_table_001",
        "table_index": 1,
        "table_type": "ocr_layout_rows",
        "structure_source": "ocr_line_bbox",
        "rows": rows,
    }


def _ensure_page(pages_by_no: dict[int, dict[str, Any]], page_no: int) -> dict[str, Any]:
    if page_no not in pages_by_no:
        pages_by_no[page_no] = {
            "page_no": page_no,
            "raw_text": "",
            "lines": [],
            "tables": [],
        }
    return pages_by_no[page_no]


def _ocr_pages(ocr_result: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("page_results", "pages", "ocr_pages"):
        pages = ocr_result.get(key)
        if isinstance(pages, list):
            return [page for page in pages if isinstance(page, dict)]
    text = str(
        ocr_result.get("text")
        or ocr_result.get("full_text")
        or ocr_result.get("ocr_text")
        or ""
    ).strip()
    return [{"page": 1, "text": text}] if text else []


def _page_no(item: dict[str, Any]) -> int:
    value = item.get("page_no") or item.get("page") or 1
    try:
        return max(int(value), 1)
    except (TypeError, ValueError):
        return 1


def _normalize_bbox(value: Any) -> list[float] | None:
    if not isinstance(value, list):
        return None
    if len(value) == 4 and all(isinstance(item, (int, float)) for item in value):
        x1, y1, x2, y2 = [float(item) for item in value]
        return [min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)]

    points = []
    for point in value:
        if (
            isinstance(point, list)
            and len(point) >= 2
            and isinstance(point[0], (int, float))
            and isinstance(point[1], (int, float))
        ):
            points.append((float(point[0]), float(point[1])))
    if not points:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return [min(xs), min(ys), max(xs), max(ys)]


def _bbox_center_y(bbox: list[float]) -> float:
    return (float(bbox[1]) + float(bbox[3])) / 2


def _union_bboxes(bboxes: list[Any]) -> list[float] | None:
    normalized = [bbox for bbox in bboxes if isinstance(bbox, list) and len(bbox) == 4]
    if not normalized:
        return None
    return [
        min(float(bbox[0]) for bbox in normalized),
        min(float(bbox[1]) for bbox in normalized),
        max(float(bbox[2]) for bbox in normalized),
        max(float(bbox[3]) for bbox in normalized),
    ]


def _non_empty_lines(text: str) -> list[str]:
    return [line.strip() for line in str(text or "").splitlines() if line.strip()]


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]
