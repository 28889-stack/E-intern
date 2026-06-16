import shutil
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, File, UploadFile

from app.pipeline.document_processor import process_document
from app.services import local_store

router = APIRouter(prefix="/api/debug", tags=["debug"])


@router.post("/process-file")
def process_file(file: UploadFile = File(...)) -> dict:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    original_file_name = Path(file.filename or "uploaded_file").name
    saved_name = f"{timestamp}_{original_file_name}"
    upload_dir = local_store.ensure_dir(local_store.PROJECT_ROOT / "data" / "debug_uploads")
    output_dir = local_store.ensure_dir(
        local_store.PROJECT_ROOT / "data" / "debug_outputs" / timestamp
    )
    saved_path = upload_dir / saved_name

    with saved_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    result = process_document(saved_path, output_dir)

    return {
        "original_file_name": original_file_name,
        "saved_path": _relative_to_project(saved_path),
        "output_dir": _relative_to_project(output_dir),
        "result": _relativize_result_paths(result),
    }


def _relative_to_project(path: Path | str) -> str:
    return str(Path(path).resolve().relative_to(local_store.PROJECT_ROOT))


def _relativize_result_paths(result: dict) -> dict:
    relativized = dict(result)
    for key in ("route_result_path", "raw_text_path", "tables_path", "ocr_result_path"):
        if relativized.get(key):
            relativized[key] = _relative_to_project(relativized[key])
    return relativized
