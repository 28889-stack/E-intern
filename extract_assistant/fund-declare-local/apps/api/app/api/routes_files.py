import shutil
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.pipeline import content_classifier
from app.pipeline.document_processor import process_document
from app.services import local_store


router = APIRouter(prefix="/api/cases", tags=["case-files"])


@router.post("/{case_id}/files")
def upload_case_file(case_id: str, file: UploadFile = File(...)) -> dict:
    case = _read_case_or_404(case_id)
    local_store.ensure_case_structure(case_id)

    file_id = local_store.generate_file_id(case_id)
    file_no = local_store.generate_file_no(case_id)
    original_file_name = local_store.safe_filename(file.filename or "uploaded_file")
    stored_file_name = f"{file_no}_{original_file_name}"
    raw_dir = local_store.get_uploads_raw_dir(case_id)
    processed_dir = local_store.get_uploads_processed_dir(case_id)
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
        "process_status": "uploaded",
        "ocr_status": None,
        "extract_status": None,
        "content_classify_status": "not_started",
        "manual_review_required": False,
        "review_reasons": [],
        "created_at": now,
        "updated_at": now,
    }
    local_store.append_file_index(case_id, file_record)

    try:
        process_result = process_document(stored_path, output_dir)
        classification = content_classifier.classify_content(
            stored_path,
            output_dir,
            original_file_name=original_file_name,
        )
        classification_path = output_dir / "content_classification.json"
        local_store.save_json(classification_path, classification)

        review_reasons = [
            *process_result.get("review_reasons", []),
            *classification.get("review_reasons", []),
        ]
        updated_record = local_store.update_file_index(
            case_id,
            file_id,
            {
                "route_type": process_result.get("route_type"),
                "content_type": classification.get("content_type"),
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

        return {
            "case_id": case_id,
            "case": case,
            "file": updated_record,
            "process_result": _relativize_process_result(process_result),
            "content_classification": classification,
            "content_classification_path": _relative_to_project(classification_path),
        }
    except Exception as exc:
        failure_reason = f"文件处理失败：{exc}"
        updated_record = local_store.update_file_index(
            case_id,
            file_id,
            {
                "process_status": "failed",
                "content_classify_status": "failed",
                "manual_review_required": True,
                "review_reasons": [failure_reason],
                "updated_at": _now(),
            },
        )
        return {
            "case_id": case_id,
            "case": case,
            "file": updated_record,
            "process_result": {
                "process_status": "failed",
                "manual_review_required": True,
                "review_reasons": [failure_reason],
            },
            "content_classification": None,
        }


@router.get("/{case_id}/files")
def list_case_files(case_id: str) -> dict:
    _read_case_or_404(case_id)
    return {
        "case_id": case_id,
        "files": local_store.read_files_index(case_id).get("files", []),
    }


@router.get("/{case_id}/files/{file_id}/result")
def get_case_file_result(case_id: str, file_id: str) -> dict:
    _read_case_or_404(case_id)
    file_record = _get_file_record_or_404(case_id, file_id)
    output_dir = local_store.PROJECT_ROOT / file_record["output_dir"]

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
    }


def _read_case_or_404(case_id: str) -> dict:
    case = local_store.read_json(local_store.get_case_dir(case_id) / "case.json")
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    return case


def _get_file_record_or_404(case_id: str, file_id: str) -> dict:
    for file_record in local_store.read_files_index(case_id).get("files", []):
        if file_record.get("file_id") == file_id:
            return file_record
    raise HTTPException(status_code=404, detail="file not found")


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
