from pathlib import Path
from typing import Any

from app.pipeline.graph_rag_sidecar import format_graph_rag_context
from app.services.local_store import read_json


MAX_MULTIMODAL_OBSERVATIONS = 3
MAX_MULTIMODAL_NOISE_ZONES = 5
MAX_MULTIMODAL_CONTEXT_CHARS = 800


def build_extraction_input(process_output_dir: str | Path) -> dict:
    output_dir = Path(process_output_dir)
    input_sections = []
    sources = {
        "document_structure_path": None,
        "raw_text_path": None,
        "tables_path": None,
        "ocr_result_path": None,
        "graph_rag_retrieval_path": None,
        "multimodal_review_hints_path": None,
    }

    document_structure_path = output_dir / "document_structure.json"
    document_structure = read_json(document_structure_path, None)
    if isinstance(document_structure, dict):
        sources["document_structure_path"] = str(document_structure_path)
        structure_sources = document_structure.get("sources")
        if isinstance(structure_sources, dict):
            for key in ("raw_text_path", "tables_path", "ocr_result_path"):
                sources[key] = structure_sources.get(key)
        input_sections.extend(_sections_from_document_structure(document_structure))

    if input_sections:
        input_text = _sections_to_text(input_sections)
        graph_rag_context = _load_graph_rag_context(output_dir, sources)
        multimodal_context = _load_multimodal_context(output_dir, sources)
        return {
            "input_text": input_text,
            "sources": sources,
            "input_sections": input_sections,
            "graph_rag_context": graph_rag_context,
            "multimodal_context": multimodal_context,
            "manual_review_required": False,
            "review_reasons": [],
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
    graph_rag_context = _load_graph_rag_context(output_dir, sources)
    multimodal_context = _load_multimodal_context(output_dir, sources)

    return {
        "input_text": input_text,
        "sources": sources,
        "input_sections": input_sections,
        "graph_rag_context": graph_rag_context,
        "multimodal_context": multimodal_context,
        "manual_review_required": bool(review_reasons),
        "review_reasons": review_reasons,
    }


def _load_graph_rag_context(output_dir: Path, sources: dict) -> str:
    retrieval_path = output_dir / "graph_rag" / "retrieval_result.json"
    if retrieval_path.exists():
        sources["graph_rag_retrieval_path"] = str(retrieval_path)
    return format_graph_rag_context(output_dir)


def _load_multimodal_context(output_dir: Path, sources: dict) -> str:
    hints_path = output_dir / "multimodal_review_hints.json"
    hints = read_json(hints_path, None)
    if not isinstance(hints, dict):
        return ""
    sources["multimodal_review_hints_path"] = str(hints_path)
    return _format_multimodal_context(hints)


def _format_multimodal_context(hints: dict[str, Any]) -> str:
    parts = []
    page_type = str(hints.get("page_type") or "").strip()
    if page_type:
        parts.append(f"page_type: {page_type}")
    for key in (
        "query_condition_zone_visible",
        "result_table_zone_visible",
        "empty_result_visible",
        "key_field_occlusion_visible",
    ):
        if key in hints:
            parts.append(f"{key}: {_json_bool(hints.get(key))}")
    noise_zones = [
        str(item).strip()
        for item in _as_list(hints.get("noise_zones"))[:MAX_MULTIMODAL_NOISE_ZONES]
        if str(item).strip()
    ]
    if noise_zones:
        parts.append("noise_zones: " + ", ".join(noise_zones))
    observations = [
        str(item).strip()
        for item in _as_list(hints.get("visual_observations"))[:MAX_MULTIMODAL_OBSERVATIONS]
        if str(item).strip()
    ]
    if observations:
        parts.append("visual_observations:")
        parts.extend(f"- {item[:80]}" for item in observations)
    return _compact_text("\n".join(parts), MAX_MULTIMODAL_CONTEXT_CHARS)


def _sections_from_document_structure(document_structure: dict[str, Any]) -> list[dict]:
    sections = []
    for page in _as_list(document_structure.get("pages")):
        if not isinstance(page, dict):
            continue
        page_no = page.get("page_no") or page.get("page")
        for table in _as_list(page.get("tables")):
            if not isinstance(table, dict):
                continue
            text = _structured_rows_to_text(table.get("rows"))
            if not text.strip():
                continue
            sections.append(
                {
                    "section_type": "document_table",
                    "page": page_no,
                    "table_index": table.get("table_index"),
                    "table_id": table.get("table_id"),
                    "table_type": table.get("table_type"),
                    "structure_source": table.get("structure_source"),
                    "text": text,
                }
            )

        lines_text = _structured_lines_to_text(page.get("lines"))
        if lines_text.strip():
            sections.append(
                {
                    "section_type": "document_lines",
                    "page": page_no,
                    "text": lines_text,
                }
            )
    return sections


def _sections_to_text(input_sections: list[dict]) -> str:
    text_parts = []
    for section in input_sections:
        text = str(section.get("text", "")).strip()
        if not text:
            continue

        page = section.get("page")
        table_index = section.get("table_index")
        table_id = section.get("table_id")
        table_type = section.get("table_type")
        structure_source = section.get("structure_source")
        label_parts = [str(section.get("section_type", "section"))]
        if page is not None:
            label_parts.append(f"page={page}")
        if table_index is not None:
            label_parts.append(f"table_index={table_index}")
        if table_id:
            label_parts.append(f"table_id={table_id}")
        if table_type:
            label_parts.append(f"table_type={table_type}")
        if structure_source:
            label_parts.append(f"source={structure_source}")
        text_parts.append(f"[{' '.join(label_parts)}]\n{text}")

    return "\n\n".join(text_parts)


def _structured_rows_to_text(rows: Any) -> str:
    row_texts = []
    for row in _as_list(rows):
        if not isinstance(row, dict):
            continue
        row_id = row.get("row_id", "")
        bbox = row.get("bbox")
        cells = []
        for cell in _as_list(row.get("cells")):
            if not isinstance(cell, dict):
                continue
            cell_text = str(cell.get("text", ""))
            if cell.get("bbox"):
                cell_text = f"{cell_text}{{bbox={cell.get('bbox')}}}"
            cells.append(cell_text)
        if cells:
            row_texts.append(f"[row_id={row_id} bbox={bbox}] " + "\t".join(cells))
    return "\n".join(row_texts)


def _structured_lines_to_text(lines: Any) -> str:
    line_texts = []
    for line in _as_list(lines):
        if not isinstance(line, dict):
            continue
        text = str(line.get("text", "")).strip()
        if not text:
            continue
        line_texts.append(
            (
                f"[line_id={line.get('line_id', '')} bbox={line.get('bbox')} "
                f"confidence={line.get('confidence')}] {text}"
            )
        )
    return "\n".join(line_texts)


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


def _json_bool(value: Any) -> str:
    return "true" if value is True else "false" if value is False else str(value)


def _compact_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"
