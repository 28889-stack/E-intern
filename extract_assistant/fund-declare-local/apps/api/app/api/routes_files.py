import shutil
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from app.pipeline import content_classifier
from app.pipeline.document_processor import process_document
from app.pipeline.extraction_input_builder import build_extraction_input
from app.pipeline.single_file_extractor import extract_single_file
from app.services import local_store


router = APIRouter(prefix="/api/cases", tags=["case-files"])
MODULE_IDENTITY_INFO = "identity_info"
MODULE_ACCOUNT_INFO = "account_info"
VALID_MODULES = {MODULE_IDENTITY_INFO, MODULE_ACCOUNT_INFO}
LEGACY_MODULE_MAP = {
    "identity": MODULE_IDENTITY_INFO,
    "account_material": MODULE_ACCOUNT_INFO,
}


@router.post("/{case_id}/identity-info/files")
def upload_identity_info_file(case_id: str, file: UploadFile = File(...)) -> dict:
    return _upload_case_file(case_id, MODULE_IDENTITY_INFO, file)


@router.post("/{case_id}/account-info/files")
def upload_account_info_file(case_id: str, file: UploadFile = File(...)) -> dict:
    return _upload_case_file(case_id, MODULE_ACCOUNT_INFO, file)


def _upload_case_file(case_id: str, module: str, file: UploadFile) -> dict:
    case = _read_case_or_404(case_id)
    local_store.ensure_case_structure(case_id)

    file_id = local_store.generate_file_id(case_id)
    file_no = local_store.generate_file_no(case_id)
    original_file_name = local_store.safe_filename(file.filename or "uploaded_file")
    stored_file_name = f"{file_no}_{original_file_name}"
    raw_dir = local_store.get_module_raw_dir(case_id, module)
    processed_dir = local_store.get_module_processed_dir(case_id, module)
    stored_path = raw_dir / stored_file_name
    output_dir = local_store.ensure_dir(processed_dir / file_id)
    now = _now()

    with stored_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    file_record = {
        "file_id": file_id,
        "file_no": file_no,
        "case_id": case_id,
        "original_file_name": original_file_name,
        "stored_file_name": stored_file_name,
        "storage_path": _relative_to_project(stored_path),
        "output_dir": _relative_to_project(output_dir),
        "route_type": None,
        "content_type": None,
        "module": module,
        "process_status": "uploaded",
        "ocr_status": None,
        "extract_status": None,
        "extract_result_path": None,
        "content_classify_status": "not_started",
        "manual_review_required": False,
        "review_reasons": [],
        "created_at": now,
        "updated_at": now,
    }
    local_store.append_file_index(case_id, file_record)

    return {
        "case_id": case_id,
        "case": case,
        "file": file_record,
        "process_result": None,
        "content_classification": None,
        "extract_result": None,
        "message": "材料已上传，等待系统分析",
    }


@router.post("/{case_id}/files/analyze")
def analyze_case_files(case_id: str) -> dict:
    _read_case_or_404(case_id)
    files = _read_files_with_modules(case_id)
    results = []

    for file_record in files:
        if _is_file_already_analyzed(file_record):
            results.append(
                {
                    "file_id": file_record.get("file_id"),
                    "file_no": file_record.get("file_no"),
                    "status": "skipped",
                    "file": file_record,
                }
            )
            continue
        results.append(_analyze_case_file(case_id, file_record))

    return {
        "case_id": case_id,
        "results": results,
        "files": _read_files_with_modules(case_id),
        "summary": _build_analyze_summary(results),
    }


def _is_file_already_analyzed(file_record: dict) -> bool:
    return (
        file_record.get("process_status") not in {None, "uploaded"}
        and file_record.get("content_classify_status") == "success"
        and file_record.get("extract_status") is not None
    )


def _analyze_case_file(case_id: str, file_record: dict) -> dict:
    file_id = file_record.get("file_id")
    storage_path = file_record.get("storage_path")
    output_dir_path = file_record.get("output_dir")
    if not file_id or not storage_path or not output_dir_path:
        raise HTTPException(status_code=400, detail="invalid file record")

    stored_path = local_store.PROJECT_ROOT / storage_path
    output_dir = local_store.ensure_dir(local_store.PROJECT_ROOT / output_dir_path)
    original_file_name = file_record.get("original_file_name") or stored_path.name
    module = _normalize_module(file_record.get("module"), file_record.get("content_type"))

    try:
        process_result = process_document(stored_path, output_dir)
        classification = content_classifier.classify_content(
            stored_path,
            output_dir,
            original_file_name=original_file_name,
        )
        classification_path = output_dir / "content_classification.json"
        local_store.save_json(classification_path, classification)
        content_type = classification.get("content_type") or "unknown"

        review_reasons = [
            *process_result.get("review_reasons", []),
            *classification.get("review_reasons", []),
        ]
        updated_record = local_store.update_file_index(
            case_id,
            file_id,
            {
                "route_type": process_result.get("route_type"),
                "content_type": content_type,
                "module": module,
                "process_status": process_result.get("process_status", "failed"),
                "ocr_status": process_result.get("ocr_status"),
                "extract_status": process_result.get("extract_status"),
                "content_classify_status": "success",
                "manual_review_required": (
                    process_result.get("manual_review_required", False)
                    or classification.get("manual_review_required", False)
                ),
                "review_reasons": review_reasons,
                "updated_at": _now(),
            },
        )
        extract_result = extract_single_file(case_id, updated_record)
        updated_record = _get_file_record_or_404(case_id, file_id)

        return {
            "file_id": file_id,
            "file_no": file_record.get("file_no"),
            "status": "success",
            "file": updated_record,
            "process_result": _relativize_process_result(process_result),
            "content_classification": classification,
            "content_classification_path": _relative_to_project(classification_path),
            "extract_result": extract_result,
        }
    except Exception as exc:
        failure_reason = f"文件处理失败：{exc}"
        updated_record = local_store.update_file_index(
            case_id,
            file_id,
            {
                "process_status": "failed",
                "content_classify_status": "failed",
                "module": module,
                "manual_review_required": True,
                "review_reasons": [failure_reason],
                "updated_at": _now(),
            },
        )
        return {
            "file_id": file_id,
            "file_no": file_record.get("file_no"),
            "status": "failed",
            "file": updated_record,
            "process_result": {
                "process_status": "failed",
                "manual_review_required": True,
                "review_reasons": [failure_reason],
            },
            "content_classification": None,
            "extract_result": None,
        }


@router.get("/{case_id}/files")
def list_case_files(
    case_id: str,
    module: str | None = Query(default=None),
) -> dict:
    _read_case_or_404(case_id)
    module = module or None
    if module is not None and module not in VALID_MODULES:
        raise HTTPException(status_code=400, detail="invalid module")

    files = _read_files_with_modules(case_id)
    filtered_files = (
        [file_record for file_record in files if file_record.get("module") == module]
        if module
        else files
    )

    return {
        "case_id": case_id,
        "module": module,
        "summary": _build_module_summary(files),
        "files": filtered_files,
    }


@router.post("/{case_id}/files/{file_id}/extract")
def rerun_case_file_extract(case_id: str, file_id: str) -> dict:
    _read_case_or_404(case_id)
    file_record = _get_file_record_or_404(case_id, file_id)
    extract_result = extract_single_file(case_id, file_record)
    updated_record = _get_file_record_or_404(case_id, file_id)

    return {
        "case_id": case_id,
        "file_id": file_id,
        "file": updated_record,
        "extract_result": extract_result,
    }


@router.get("/{case_id}/files/{file_id}/extract-input")
def get_case_file_extract_input(case_id: str, file_id: str) -> dict:
    _read_case_or_404(case_id)
    file_record = _get_file_record_or_404(case_id, file_id)
    output_dir = local_store.PROJECT_ROOT / file_record["output_dir"]
    input_payload = build_extraction_input(output_dir)
    input_text = input_payload["input_text"]

    return {
        "case_id": case_id,
        "file_id": file_id,
        "content_type": file_record.get("content_type"),
        "input_text_preview": input_text[:3000],
        "input_text_length": len(input_text),
        "sources": input_payload["sources"],
    }


@router.get("/{case_id}/files/{file_id}/result")
def get_case_file_result(case_id: str, file_id: str) -> dict:
    _read_case_or_404(case_id)
    file_record = _get_file_record_or_404(case_id, file_id)
    output_dir = local_store.PROJECT_ROOT / file_record["output_dir"]
    extract_result_path = output_dir / "extract_result.json"

    return {
        "case_id": case_id,
        "file_id": file_id,
        "file_index": file_record,
        "route_result": local_store.read_json(output_dir / "route_result.json", {}),
        "process_result": local_store.read_json(output_dir / "process_result.json", {}),
        "content_classification": local_store.read_json(
            output_dir / "content_classification.json", {}
        ),
        "raw_text": local_store.read_json(output_dir / "raw_text.json", None),
        "tables": local_store.read_json(output_dir / "tables.json", None),
        "ocr_result": local_store.read_json(output_dir / "ocr_result.json", None),
        "extract_result_path": (
            _relative_to_project(extract_result_path)
            if extract_result_path.exists()
            else None
        ),
        "extract_result": local_store.read_json(extract_result_path, None),
    }


def _read_case_or_404(case_id: str) -> dict:
    case = local_store.read_json(local_store.get_case_dir(case_id) / "case.json")
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    return case


def _get_file_record_or_404(case_id: str, file_id: str) -> dict:
    for file_record in _read_files_with_modules(case_id):
        if file_record.get("file_id") == file_id:
            return file_record
    raise HTTPException(status_code=404, detail="file not found")


def _read_files_with_modules(case_id: str) -> list[dict]:
    files_index = local_store.read_files_index(case_id)
    files = files_index.get("files", [])
    changed = False

    for file_record in files:
        module = _normalize_module(
            file_record.get("module"),
            file_record.get("content_type"),
        )
        if file_record.get("module") != module:
            file_record["module"] = module
            changed = True

    if changed:
        local_store.save_json(
            local_store.get_case_dir(case_id) / "files_index.json",
            files_index,
        )

    return files


def _normalize_module(module: str | None, content_type: str | None = None) -> str:
    if module in VALID_MODULES:
        return module
    if module in LEGACY_MODULE_MAP:
        return LEGACY_MODULE_MAP[module]

    inferred_module = content_classifier.module_for_content_type(content_type)
    if module is None and inferred_module in VALID_MODULES:
        return inferred_module

    return module or "unknown"


def _build_module_summary(files: list[dict]) -> dict:
    return {
        "identity_info_file_count": sum(
            1
            for file_record in files
            if file_record.get("module") == MODULE_IDENTITY_INFO
        ),
        "account_info_file_count": sum(
            1
            for file_record in files
            if file_record.get("module") == MODULE_ACCOUNT_INFO
        ),
    }


def _build_analyze_summary(results: list[dict]) -> dict:
    return {
        "total_file_count": len(results),
        "analyzed_file_count": sum(1 for item in results if item.get("status") == "success"),
        "skipped_file_count": sum(1 for item in results if item.get("status") == "skipped"),
        "failed_file_count": sum(1 for item in results if item.get("status") == "failed"),
    }


def _relative_to_project(path: Path | str) -> str:
    return str(Path(path).resolve().relative_to(local_store.PROJECT_ROOT.resolve()))


def _relativize_process_result(process_result: dict) -> dict:
    relativized = dict(process_result)
    for key in (
        "route_result_path",
        "raw_text_path",
        "tables_path",
        "ocr_result_path",
        "process_result_path",
    ):
        if relativized.get(key):
            relativized[key] = _relative_to_project(relativized[key])
    return relativized


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
