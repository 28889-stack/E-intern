from __future__ import annotations

from pathlib import Path
from typing import Any

from app.pipeline.visual_evidence import build_visual_evidence
from app.services.local_store import read_json, save_json


def build_document_blocks(
    *,
    output_dir: str | Path,
    file_path: str | Path | None = None,
    route_type: str | None = None,
) -> dict[str, Any]:
    output_path = Path(output_dir)
    visual_evidence = (
        build_visual_evidence(file_path, output_path, route_type=route_type)
        if file_path
        else {"visual_evidence_status": "not_available", "pages": []}
    )
    page_image_refs = _page_image_refs(visual_evidence.get("pages", []))

    blocks: list[dict[str, Any]] = []
    blocks.extend(_raw_text_blocks(output_path, page_image_refs))
    blocks.extend(_table_blocks(output_path, page_image_refs))
    blocks.extend(_ocr_text_blocks(output_path, page_image_refs))

    result = {
        "document_block_status": "success",
        "block_count": len(blocks),
        "blocks": blocks,
        "visual_evidence": visual_evidence,
        "review_reasons": visual_evidence.get("review_reasons", []),
    }
    save_json(output_path / "document_blocks.json", result)
    return result


def _raw_text_blocks(
    output_path: Path,
    page_image_refs: dict[int, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    raw_text = read_json(output_path / "raw_text.json", {}) or {}
    blocks = []
    for index, page in enumerate(raw_text.get("pages", []) or [], start=1):
        text = str(page.get("text") or "").strip()
        if not text:
            continue
        page_no = _page_no(page)
        blocks.append(
            _block(
                block_id=f"page_{page_no:03d}_text_{index:03d}",
                page_no=page_no,
                block_type="pdf_text",
                text=text,
                table_rows=[],
                image_refs=page_image_refs.get(page_no, []),
                source={"file": "raw_text.json", "page_index": index},
            )
        )
    return blocks


def _table_blocks(
    output_path: Path,
    page_image_refs: dict[int, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    tables = read_json(output_path / "tables.json", {}) or {}
    blocks = []
    for index, table in enumerate(tables.get("tables", []) or [], start=1):
        rows = table.get("rows") or []
        if not rows:
            continue
        page_no = _page_no(table)
        table_index = table.get("table_index") or index
        blocks.append(
            _block(
                block_id=f"page_{page_no:03d}_table_{int(table_index):03d}",
                page_no=page_no,
                block_type="pdf_table",
                text=_table_text(rows),
                table_rows=rows,
                image_refs=page_image_refs.get(page_no, []),
                source={
                    "file": "tables.json",
                    "table_index": table_index,
                    "extractor": table.get("extractor", ""),
                },
            )
        )
    return blocks


def _ocr_text_blocks(
    output_path: Path,
    page_image_refs: dict[int, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    ocr_result = read_json(output_path / "ocr_result.json", {}) or {}
    pages = _ocr_pages(ocr_result)
    blocks = []
    for index, page in enumerate(pages, start=1):
        text = str(page.get("text") or page.get("page_text") or "").strip()
        if not text:
            continue
        page_no = _page_no(page)
        blocks.append(
            _block(
                block_id=f"page_{page_no:03d}_ocr_{index:03d}",
                page_no=page_no,
                block_type="ocr_text",
                text=text,
                table_rows=[],
                image_refs=page_image_refs.get(page_no, []),
                source={
                    "file": "ocr_result.json",
                    "page_index": index,
                    "confidence_avg": page.get("confidence_avg"),
                },
            )
        )
    return blocks


def _ocr_pages(ocr_result: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("pages", "page_results", "ocr_pages"):
        pages = ocr_result.get(key)
        if isinstance(pages, list):
            return [page for page in pages if isinstance(page, dict)]

    text = str(
        ocr_result.get("text")
        or ocr_result.get("full_text")
        or ocr_result.get("ocr_text")
        or ""
    ).strip()
    if not text:
        return []
    return [{"page": 1, "text": text}]


def _page_image_refs(pages: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    refs: dict[int, list[dict[str, Any]]] = {}
    for page in pages:
        page_no = int(page.get("page_no") or page.get("page") or 1)
        refs.setdefault(page_no, []).append(
            {
                "type": page.get("type", "page"),
                "path": page.get("path", ""),
                "width": page.get("width"),
                "height": page.get("height"),
            }
        )
    return refs


def _block(
    *,
    block_id: str,
    page_no: int,
    block_type: str,
    text: str,
    table_rows: list,
    image_refs: list[dict[str, Any]],
    source: dict[str, Any],
) -> dict[str, Any]:
    return {
        "block_id": block_id,
        "page_no": page_no,
        "block_type": block_type,
        "text": text,
        "table_rows": table_rows,
        "image_refs": image_refs,
        "source": source,
    }


def _page_no(item: dict[str, Any]) -> int:
    value = item.get("page_no") or item.get("page") or 1
    try:
        return max(int(value), 1)
    except (TypeError, ValueError):
        return 1


def _table_text(rows: list) -> str:
    return "\n".join(
        " | ".join(str(cell or "").strip() for cell in row)
        for row in rows
        if isinstance(row, list)
    )
