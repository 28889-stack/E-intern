from pathlib import Path

from app.pipeline import file_router, pdf_table_extractor, pdf_text_extractor
from app.pipeline.ocr_quality_checker import inspect_ocr_quality
from app.services.local_store import ensure_dir, save_json
from app.services.ocr_client import OcrClient


def process_document(file_path: str | Path, output_dir: str | Path) -> dict:
    output_path = ensure_dir(output_dir)
    route_result = file_router.route_file(file_path)
    route_result_path = output_path / "route_result.json"
    process_result_path = output_path / "process_result.json"
    save_json(route_result_path, route_result)

    result = {
        "process_status": "failed",
        "route_type": route_result["route_type"],
        "ocr_status": "not_required",
        "extract_status": "not_required",
        "table_extract_status": "not_required",
        "route_result_path": str(route_result_path),
        "raw_text_path": None,
        "tables_path": None,
        "ocr_result_path": None,
        "process_result_path": str(process_result_path),
        "manual_review_required": route_result["manual_review_required"],
        "review_reasons": list(route_result["review_reasons"]),
    }

    route_type = route_result["route_type"]

    if route_type == "direct_pdf":
        raw_text = pdf_text_extractor.extract_pdf_text(file_path)
        tables = pdf_table_extractor.extract_pdf_tables(file_path)
        raw_text_path = output_path / "raw_text.json"
        tables_path = output_path / "tables.json"
        save_json(raw_text_path, raw_text)
        save_json(tables_path, tables)

        review_reasons = [
            *route_result.get("review_reasons", []),
            *raw_text.get("review_reasons", []),
            *tables.get("review_reasons", []),
        ]

        process_result = {
            **result,
            "process_status": "parsed",
            "extract_status": raw_text.get("extract_status", "failed"),
            "table_extract_status": tables.get("table_extract_status", "partial_failed"),
            "raw_text_path": str(raw_text_path),
            "tables_path": str(tables_path),
            "manual_review_required": (
                route_result.get("manual_review_required", False)
                or raw_text.get("manual_review_required", False)
                or tables.get("manual_review_required", False)
            ),
            "review_reasons": review_reasons,
        }
        save_json(process_result_path, process_result)
        return process_result

    if route_type in {"scanned_pdf", "image"}:
        file_type = 0 if route_type == "scanned_pdf" else 1
        quality_result = inspect_ocr_quality(file_path, route_type)
        ocr_result = OcrClient().infer(file_path, file_type=file_type)
        ocr_result = {
            **ocr_result,
            "quality_status": quality_result.get("quality_status", "normal"),
            "quality_issues": quality_result.get("quality_issues", []),
            "quality_metrics": quality_result.get("metrics", {}),
            "manual_review_required": (
                ocr_result.get("manual_review_required", False)
                or quality_result.get("manual_review_required", False)
            ),
            "review_reasons": _unique(
                [
                    *ocr_result.get("review_reasons", []),
                    *quality_result.get("review_reasons", []),
                ]
            ),
        }
        ocr_result_path = output_path / "ocr_result.json"
        save_json(ocr_result_path, ocr_result)

        process_result = {
            **result,
            "process_status": (
                "ocr_done" if ocr_result.get("ocr_status") == "success" else "ocr_failed"
            ),
            "ocr_status": ocr_result.get("ocr_status", "failed"),
            "ocr_quality_status": quality_result.get("quality_status", "normal"),
            "ocr_result_path": str(ocr_result_path),
            "manual_review_required": (
                route_result.get("manual_review_required", False)
                or ocr_result.get("manual_review_required", False)
            ),
            "review_reasons": [
                *route_result.get("review_reasons", []),
                *ocr_result.get("review_reasons", []),
            ],
        }
        save_json(process_result_path, process_result)
        return process_result

    save_json(process_result_path, result)
    return result


def _unique(values: list) -> list:
    result = []
    seen = set()
    for value in values:
        if value in (None, "") or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
