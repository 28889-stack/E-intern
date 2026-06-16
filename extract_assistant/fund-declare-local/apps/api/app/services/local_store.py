import json
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[4]


def get_data_root() -> Path:
    return PROJECT_ROOT / "data" / "cases"


def ensure_dir(path: Path | str) -> Path:
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def save_json(path: Path | str, data: dict) -> None:
    json_path = Path(path)
    ensure_dir(json_path.parent)
    json_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def read_json(path: Path | str, default: Any = None) -> Any:
    json_path = Path(path)
    if not json_path.exists():
        return default

    return json.loads(json_path.read_text(encoding="utf-8"))


def generate_case_id() -> str:
    data_root = ensure_dir(get_data_root())
    case_numbers = []

    for path in data_root.iterdir():
        if not path.is_dir() or not path.name.startswith("case_"):
            continue

        case_number = path.name.removeprefix("case_")
        if case_number.isdigit():
            case_numbers.append(int(case_number))

    next_number = max(case_numbers, default=0) + 1
    return f"case_{next_number:03d}"


def get_case_dir(case_id: str) -> Path:
    return get_data_root() / case_id


def create_case(case_data: dict) -> dict:
    case_id = generate_case_id()
    case_dir = ensure_dir(get_case_dir(case_id))
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    ensure_dir(case_dir / "identity" / "raw")
    ensure_dir(case_dir / "identity" / "ocr")
    ensure_dir(case_dir / "identity" / "extract")
    ensure_dir(case_dir / "accounts")
    ensure_dir(case_dir / "final")

    case = {
        "case_id": case_id,
        "name": case_data["name"],
        "phone": case_data["phone"],
        "relation_type": case_data["relation_type"],
        "relation_type_label": case_data["relation_type_label"],
        "created_at": now,
        "updated_at": now,
        "status": "created",
    }

    files_index = {
        "files": [],
    }

    status = {
        "case_id": case_id,
        "current_stage": "created",
        "identity_status": "not_started",
        "account_status": {},
        "final_status": "not_started",
        "checklist_status": "not_started",
        "excel_status": "not_started",
        "manual_review_required": False,
        "review_reasons": [],
    }

    save_json(case_dir / "case.json", case)
    save_json(case_dir / "files_index.json", files_index)
    save_json(case_dir / "status.json", status)

    return case
