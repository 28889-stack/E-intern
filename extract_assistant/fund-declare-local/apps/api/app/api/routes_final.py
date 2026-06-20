from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.pipeline.final_excel_exporter import export_excel_from_final_result
from app.pipeline.final_result_builder import build_and_save_final_result
from app.pipeline.final_review import (
    get_or_create_review_status,
    get_review_payload,
    reset_review_status,
    reviewed_final_result_path,
    save_review_payload,
    update_case_review_status,
)
from app.services import local_store


router = APIRouter(prefix="/api/cases", tags=["case-final"])


@router.post("/{case_id}/finalize")
def finalize_case(case_id: str) -> dict:
    _read_case_or_404(case_id)
    final_payload = build_and_save_final_result(case_id)
    final_result = final_payload["final_result"]
    final_result_path = final_payload["final_result_path"]
    review_status = reset_review_status(case_id)

    return {
        "case_id": case_id,
        "final_result_path": _relative_to_project(final_result_path),
        "excel_path": None,
        "review_status": review_status,
        "message": "final_result 已生成，请完成人工复核并保存后再导出 Excel",
        "summary": final_result.get("summary", {}),
        "review_items": final_result.get("review_items", []),
    }


@router.get("/{case_id}/review")
def get_case_review(case_id: str) -> dict:
    _read_case_or_404(case_id)
    try:
        return get_review_payload(case_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{case_id}/review")
def save_case_review(case_id: str, payload: dict) -> dict:
    _read_case_or_404(case_id)
    try:
        return save_review_payload(case_id, payload)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{case_id}/review/status")
def get_case_review_status(case_id: str) -> dict:
    _read_case_or_404(case_id)
    return get_or_create_review_status(case_id)


@router.get("/{case_id}/export/excel")
def export_case_excel(case_id: str) -> FileResponse:
    _read_case_or_404(case_id)
    review_status = get_or_create_review_status(case_id)
    reviewed_path = reviewed_final_result_path(case_id)

    if review_status.get("excel_export_allowed") is not True:
        raise HTTPException(
            status_code=409,
            detail="请先保存人工复核结果，再导出 Excel",
        )
    if not reviewed_path.exists():
        raise HTTPException(
            status_code=409,
            detail="请先保存人工复核结果，再导出 Excel",
        )

    excel_path = _export_excel(case_id, reviewed_path)
    update_case_review_status(case_id, excel_status="exported")
    return FileResponse(
        excel_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=f"{case_id}_final.xlsx",
    )


def _export_excel(case_id: str, final_result_path: Path) -> Path:
    final_dir = local_store.ensure_dir(local_store.get_case_dir(case_id) / "final")
    excel_path = final_dir / f"{case_id}_final.xlsx"
    export_excel_from_final_result(final_result_path, excel_path)
    _update_excel_status(case_id)
    return excel_path


def _read_case_or_404(case_id: str) -> dict:
    case = local_store.read_json(local_store.get_case_dir(case_id) / "case.json")
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    return case


def _update_excel_status(case_id: str) -> None:
    status_path = local_store.get_case_dir(case_id) / "status.json"
    status = local_store.read_json(status_path, {"case_id": case_id})
    status["excel_status"] = "exported"
    local_store.save_json(status_path, status)


def _relative_to_project(path: Path | str) -> str:
    return str(Path(path).resolve().relative_to(local_store.PROJECT_ROOT.resolve()))
