from pathlib import Path

from app.pipeline import file_router, pdf_table_extractor, pdf_text_extractor
from app.services.local_store import ensure_dir, save_json
from app.services.ocr_client import OcrClient


def process_document(file_path: str | Path, output_dir: str | Path) -> dict:
    output_path = ensure_dir(output_dir)
    route_result = file_router.route_file(file_path)
    route_result_path = output_path / "route_result.json"
    save_json(route_result_path, route_result)

    result = {
        "process_status": "failed",
        "route_result_path": str(route_result_path),
        "raw_text_path": None,
        "tables_path": None,
        "ocr_result_path": None,
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
            *route_result["review_reasons"],
            *raw_text["review_reasons"],
            *tables["review_reasons"],
        ]

        return {
            **result,
            "process_status": "parsed",
            "raw_text_path": str(raw_text_path),
            "tables_path": str(tables_path),
            "manual_review_required": (
                route_result["manual_review_required"]
                or raw_text["manual_review_required"]
                or tables["manual_review_required"]
            ),
            "review_reasons": review_reasons,
        }

    if route_type in {"scanned_pdf", "image"}:
        file_type = 0 if route_type == "scanned_pdf" else 1
        ocr_result = OcrClient().infer(file_path, file_type=file_type)
        ocr_result_path = output_path / "ocr_result.json"
        save_json(ocr_result_path, ocr_result)

        return {
            **result,
            "process_status": (
                "ocr_done" if ocr_result["ocr_status"] == "success" else "ocr_failed"
            ),
            "ocr_result_path": str(ocr_result_path),
            "manual_review_required": (
                route_result["manual_review_required"]
                or ocr_result["manual_review_required"]
            ),
            "review_reasons": [
                *route_result["review_reasons"],
                *ocr_result["review_reasons"],
            ],
        }

    return result
