from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import local_store

router = APIRouter(prefix="/api/cases", tags=["cases"])

RELATION_TYPE_LABELS = {
    "employee_self": "员工本人",
}


class CaseCreateRequest(BaseModel):
    name: str
    phone: str
    relation_type: str = "employee_self"
    relation_type_label: str | None = None


@router.post("")
def create_case(request: CaseCreateRequest) -> dict:
    name = request.name.strip()
    phone = request.phone.strip()
    relation_type = request.relation_type.strip() or "employee_self"
    custom_relation_type_label = (request.relation_type_label or "").strip()

    if not name:
        raise HTTPException(status_code=400, detail="name is required")

    if not phone:
        raise HTTPException(status_code=400, detail="phone is required")

    if custom_relation_type_label:
        relation_type = "custom" if relation_type == "employee_self" else relation_type
        relation_type_label = custom_relation_type_label
    else:
        relation_type_label = RELATION_TYPE_LABELS.get(relation_type)

    if not relation_type_label:
        raise HTTPException(status_code=400, detail="unsupported relation_type")

    case = local_store.create_case(
        {
            "name": name,
            "phone": phone,
            "relation_type": relation_type,
            "relation_type_label": relation_type_label,
        }
    )

    return {
        "case_id": case["case_id"],
        "status": case["status"],
        "case": {
            "case_id": case["case_id"],
            "name": case["name"],
            "phone": case["phone"],
            "relation_type": case["relation_type"],
            "relation_type_label": case["relation_type_label"],
            "status": case["status"],
        },
    }


@router.get("/{case_id}")
def get_case(case_id: str) -> dict:
    case_dir = local_store.get_case_dir(case_id)
    case = local_store.read_json(case_dir / "case.json")

    if case is None:
        raise HTTPException(status_code=404, detail="case not found")

    return {
        "case": case,
        "files_index": local_store.read_json(case_dir / "files_index.json", {"files": []}),
        "status": local_store.read_json(case_dir / "status.json", {}),
    }
