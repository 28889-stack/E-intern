import json
import re
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


def get_uploads_raw_dir(case_id: str) -> Path:
    return ensure_dir(get_case_dir(case_id) / "uploads" / "raw")


def get_uploads_processed_dir(case_id: str) -> Path:
    return ensure_dir(get_case_dir(case_id) / "uploads" / "processed")


def ensure_case_structure(case_id: str) -> None:
    case_dir = ensure_dir(get_case_dir(case_id))
    ensure_dir(case_dir / "uploads" / "raw")
    ensure_dir(case_dir / "uploads" / "processed")
    ensure_dir(case_dir / "identity" / "extract")
    ensure_dir(case_dir / "final")


def read_files_index(case_id: str) -> dict:
    files_index = read_json(get_case_dir(case_id) / "files_index.json", {"files": []})
    if not isinstance(files_index, dict):
        return {"files": []}

    files = files_index.get("files")
    if not isinstance(files, list):
        files_index["files"] = []

    return files_index


def generate_file_id(case_id: str) -> str:
    file_numbers = []
    for file_record in read_files_index(case_id).get("files", []):
        file_id = str(file_record.get("file_id", ""))
        file_number = file_id.removeprefix("file_")
        if file_id.startswith("file_") and file_number.isdigit():
            file_numbers.append(int(file_number))

    return f"file_{max(file_numbers, default=0) + 1:03d}"


def generate_file_no(case_id: str) -> str:
    file_numbers = []
    for file_record in read_files_index(case_id).get("files", []):
        file_no = str(file_record.get("file_no", ""))
        if file_no.isdigit():
            file_numbers.append(int(file_no))

    return f"{max(file_numbers, default=0) + 1:03d}"


def append_file_index(case_id: str, file_record: dict) -> dict:
    files_index = read_files_index(case_id)
    files_index["files"].append(file_record)
    save_json(get_case_dir(case_id) / "files_index.json", files_index)
    return file_record


def update_file_index(case_id: str, file_id: str, patch: dict) -> dict | None:
    files_index = read_files_index(case_id)
    updated_record = None

    for file_record in files_index["files"]:
        if file_record.get("file_id") == file_id:
            file_record.update(patch)
            updated_record = file_record
            break

    if updated_record is None:
        return None

    save_json(get_case_dir(case_id) / "files_index.json", files_index)
    return updated_record


def safe_filename(original_file_name: str) -> str:
    file_name = Path(original_file_name or "uploaded_file").name.strip()
    file_name = re.sub(r'[\\/:\*\?"<>\|\x00-\x1f]+', "_", file_name)
    file_name = re.sub(r"\s+", " ", file_name).strip().lstrip(".")
    return file_name or "uploaded_file"


def create_case(case_data: dict) -> dict:
    case_id = generate_case_id()
    case_dir = ensure_dir(get_case_dir(case_id))
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    ensure_case_structure(case_id)
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
