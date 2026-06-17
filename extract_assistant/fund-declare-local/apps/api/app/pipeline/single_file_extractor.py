from pathlib import Path

from app.pipeline.chinaclear_extractor import ChinaclearExtractor
from app.services import local_store


def extract_single_file(case_id: str, file_record: dict) -> dict:
    output_dir = _get_output_dir(file_record)
    extract_result_path = output_dir / "extract_result.json"
    content_type = file_record.get("content_type") or "unknown"

    if content_type == "chinaclear":
        extract_result = ChinaclearExtractor().extract(case_id, file_record, output_dir)
    elif content_type == "identity":
        extract_result = _skipped_result(
            case_id,
            file_record,
            reason="identity prompt placeholder only",
            manual_review_required=False,
        )
    elif content_type == "guangfa":
        extract_result = _skipped_result(
            case_id,
            file_record,
            reason="guangfa prompt placeholder only",
            manual_review_required=False,
        )
    else:
        extract_result = _skipped_result(
            case_id,
            file_record,
            reason="unknown content_type, manual review required",
            manual_review_required=True,
        )

    local_store.save_json(extract_result_path, extract_result)
    _update_file_index(case_id, file_record, extract_result, extract_result_path)
    return extract_result


def _get_output_dir(file_record: dict) -> Path:
    output_dir = file_record.get("output_dir")
    if output_dir:
        return local_store.ensure_dir(local_store.PROJECT_ROOT / output_dir)

    case_id = file_record.get("case_id", "")
    file_id = file_record.get("file_id", "")
    return local_store.ensure_dir(
        local_store.get_uploads_processed_dir(case_id) / file_id
    )


def _skipped_result(
    case_id: str,
    file_record: dict,
    reason: str,
    manual_review_required: bool,
) -> dict:
    review_reasons = [reason] if manual_review_required else []
    return {
        "schema_version": "placeholder_extract_v1",
        "file_id": file_record.get("file_id"),
        "case_id": case_id,
        "content_type": file_record.get("content_type") or "unknown",
        "extract_status": "skipped",
        "reason": reason,
        "source_file": {
            "original_file_name": file_record.get("original_file_name", ""),
            "route_type": file_record.get("route_type", ""),
            "content_type": file_record.get("content_type") or "unknown",
        },
        "accounts": [],
        "holdings": [],
        "transactions": [],
        "events": [],
        "raw_llm_output": None,
        "manual_review_required": manual_review_required,
        "review_reasons": review_reasons,
    }


def _update_file_index(
    case_id: str,
    file_record: dict,
    extract_result: dict,
    extract_result_path: Path,
) -> None:
    extract_review_reasons = extract_result.get("review_reasons", [])

    local_store.update_file_index(
        case_id,
        file_record["file_id"],
        {
            "extract_status": extract_result.get("extract_status", "failed"),
            "extract_result_path": _relative_to_project(extract_result_path),
            "manual_review_required": extract_result.get(
                "manual_review_required", False
            ),
            "review_reasons": _dedupe_reasons(extract_review_reasons),
            "updated_at": _now(),
        },
    )


def _dedupe_reasons(review_reasons: list) -> list[str]:
    deduped = []
    for reason in review_reasons:
        if reason and reason not in deduped:
            deduped.append(str(reason))
    return deduped


def _relative_to_project(path: Path | str) -> str:
    return str(Path(path).resolve().relative_to(local_store.PROJECT_ROOT.resolve()))


def _now() -> str:
    from datetime import datetime

    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
