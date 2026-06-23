from pathlib import Path

from app.core.config import ENABLE_MULTIMODAL_REVIEW
from app.pipeline.chinaclear_extractor import ChinaclearExtractor
from app.pipeline.guangfa_extractor import GuangfaExtractor
from app.pipeline.graph_rag_sidecar import run_graph_rag_sidecar
from app.pipeline.multimodal_review_sidecar import run_multimodal_review_sidecar
from app.services import local_store


def extract_single_file(case_id: str, file_record: dict) -> dict:
    output_dir = _get_output_dir(file_record)
    extract_result_path = output_dir / "extract_result.json"
    content_type = file_record.get("content_type") or "unknown"
    multimodal_review = _run_optional_multimodal_review(file_record, output_dir)
    graph_rag_trace = _run_graph_rag_for_account_material(
        content_type,
        file_record,
        output_dir,
    )

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
        extract_result = GuangfaExtractor().extract(case_id, file_record, output_dir)
    else:
        extract_result = _skipped_result(
            case_id,
            file_record,
            reason="unknown content_type, manual review required",
            manual_review_required=True,
        )

    if multimodal_review:
        extract_result["multimodal_review"] = multimodal_review
    if graph_rag_trace:
        extract_result["graph_rag_trace"] = graph_rag_trace

    local_store.save_json(extract_result_path, extract_result)
    _update_file_index(case_id, file_record, extract_result, extract_result_path)
    return extract_result


def _get_output_dir(file_record: dict) -> Path:
    output_dir = file_record.get("output_dir")
    if output_dir:
        return local_store.ensure_dir(local_store.PROJECT_ROOT / output_dir)

    case_id = file_record.get("case_id", "")
    file_id = file_record.get("file_id", "")
    module = file_record.get("module") or "account_info"
    return local_store.ensure_dir(
        local_store.get_module_processed_dir(case_id, module) / file_id
    )


def _run_optional_multimodal_review(file_record: dict, output_dir: Path) -> dict | None:
    if not ENABLE_MULTIMODAL_REVIEW:
        return None
    return run_multimodal_review_sidecar(file_record, output_dir)


def _run_graph_rag_for_account_material(
    content_type: str,
    file_record: dict,
    output_dir: Path,
) -> dict | None:
    if content_type not in {"chinaclear", "guangfa"}:
        return None
    return run_graph_rag_sidecar(file_record, output_dir)


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
    output_dir = extract_result_path.parent
    process_result = local_store.read_json(output_dir / "process_result.json", {})
    classification = local_store.read_json(
        output_dir / "content_classification.json",
        {},
    )
    extract_review_reasons = extract_result.get("review_reasons", [])
    process_reasons = (
        process_result.get("review_reasons") if isinstance(process_result, dict) else []
    )
    classification_reasons = (
        classification.get("review_reasons") if isinstance(classification, dict) else []
    )
    review_reasons = [
        *_as_list(process_reasons),
        *_as_list(classification_reasons),
        *_as_list(extract_review_reasons),
    ]

    patch = {
        "extract_status": extract_result.get("extract_status", "failed"),
        "extract_result_path": _relative_to_project(extract_result_path),
        "manual_review_required": (
            bool(process_result.get("manual_review_required"))
            if isinstance(process_result, dict)
            else False
        )
        or (
            bool(classification.get("manual_review_required"))
            if isinstance(classification, dict)
            else False
        )
        or extract_result.get("manual_review_required", False),
        "review_reasons": _dedupe_reasons(review_reasons),
        "updated_at": _now(),
    }

    if isinstance(process_result, dict) and process_result:
        patch.update(
            {
                "route_type": process_result.get(
                    "route_type",
                    file_record.get("route_type"),
                ),
                "process_status": process_result.get(
                    "process_status",
                    file_record.get("process_status"),
                ),
                "ocr_status": process_result.get(
                    "ocr_status",
                    file_record.get("ocr_status"),
                ),
            }
        )
        if process_result.get("table_extract_status") is not None:
            patch["table_extract_status"] = process_result.get("table_extract_status")

    if isinstance(classification, dict) and classification:
        if classification.get("content_type"):
            patch["content_type"] = classification.get("content_type")
        patch["content_classify_status"] = "success"

    local_store.update_file_index(
        case_id,
        file_record["file_id"],
        patch,
    )


def _dedupe_reasons(review_reasons: list) -> list[str]:
    deduped = []
    for reason in review_reasons:
        if reason and reason not in deduped:
            deduped.append(str(reason))
    return deduped


def _as_list(value: object) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _relative_to_project(path: Path | str) -> str:
    return str(Path(path).resolve().relative_to(local_store.PROJECT_ROOT.resolve()))


def _now() -> str:
    from datetime import datetime

    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
