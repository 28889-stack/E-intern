from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from app.pipeline.case_event_resolver import (
    PROBLEM_COLUMNS,
    resolve_case_events,
)
from app.pipeline.normalizers import normalize_chinaclear, normalize_guangfa
from app.pipeline.normalizers.common import (
    empty_normalized_result,
    is_final_declaration_row as normalizer_is_final_declaration_row,
    movement_type as normalizer_movement_type,
    review_item as normalizer_review_item,
)
from app.services import local_store


PROMPT_SCHEMA_PATH = local_store.PROJECT_ROOT / "prompts" / "chinaclear_extract_prompt.md"
FINAL_RESULT_SCHEMA_VERSION = "final_result_v1"

SHEET_FINAL = "最终申报表"
SHEET_COMPLETE = "完整表"
SHEET_HOLDINGS = "持仓"
SHEET_IDENTITY = "身份信息"
SHEET_CHECKLIST = "checklist结果"
SHEET_PROBLEMS = "问题清单"

DOCUMENT_COLUMNS = [
    "document_type",
    "market",
    "document_title",
    "period_start",
    "period_end",
    "holder_name",
    "one_code_account",
    "fund_account",
    "securities_account",
    "account_type",
]

EVENT_COLUMNS = [
    "case_id",
    "file_id",
    "file_no",
    "original_file_name",
    "document_type",
    "document_title",
    "holder_name",
    "one_code_account",
    "fund_account",
    "securities_account",
    "account_type",
    "event_id",
    "event_type",
    "event_type_raw",
    "market",
    "event_date",
    "event_time",
    "security_code",
    "security_name",
    "direction",
    "quantity_raw",
    "price_raw",
    "amount_raw",
    "balance_after_raw",
    "transfer_type_raw",
    "rights_category_raw",
    "security_category_raw",
    "source_pages",
    "row_nos",
    "manual_review_required",
    "problem_types",
    "missing_fields",
    "conflict_fields",
    "review_reason",
]

CHECKLIST_COLUMNS = [
    "checklist条件",
    "状态",
    "说明",
]

HOLDING_COLUMNS = [
    "case_id",
    "file_id",
    "file_no",
    "original_file_name",
    "document_type",
    "holder_name",
    "one_code_account",
    "fund_account",
    "securities_account",
    "market",
    "account_type",
    "holding_date",
    "security_code",
    "security_name",
    "quantity_raw",
    "market_value_raw",
    "currency",
    "security_category_raw",
    "source_pages",
    "row_nos",
    "manual_review_required",
    "problem_types",
    "missing_fields",
    "conflict_fields",
    "review_reason",
]

IDENTITY_COLUMNS = [
    "case_id",
    "name",
    "phone",
    "relation_type",
    "relation_type_label",
    "source",
    "review_reason",
]

REVIEW_COLUMNS = [
    "severity",
    "item_type",
    "file_id",
    "event_id",
    "field",
    "message",
]

CRITICAL_EVENT_FIELDS = [
    "event_type",
    "market",
    "event_date",
    "security_code",
    "security_name",
    "direction",
    "quantity_raw",
    "balance_after_raw",
    "transfer_type_raw",
]


def build_and_save_final_result(case_id: str) -> dict:
    case = local_store.read_json(local_store.get_case_dir(case_id) / "case.json")
    if case is None:
        raise FileNotFoundError(f"case not found: {case_id}")

    local_store.ensure_case_structure(case_id)
    final_dir = local_store.ensure_dir(local_store.get_case_dir(case_id) / "final")
    final_result = build_final_result(case_id)
    final_result_path = final_dir / "final_result.json"
    local_store.save_json(final_result_path, final_result)
    _update_status(case_id, final_result)
    return {
        "final_result": final_result,
        "final_result_path": final_result_path,
    }


def build_final_result(case_id: str) -> dict:
    case = local_store.read_json(local_store.get_case_dir(case_id) / "case.json", {})
    files_index = local_store.read_files_index(case_id)
    file_records_by_id = {
        file_record.get("file_id"): file_record
        for file_record in files_index.get("files", [])
        if file_record.get("file_id")
    }
    prompt_schema = _load_prompt_schema()
    extract_items = _collect_extract_results(case_id, file_records_by_id)
    review_items: list[dict] = []
    normalized_transaction_rows: list[dict] = []
    normalized_holding_rows: list[dict] = []
    source_extract_results = []
    review_items.extend(_file_record_review_items(files_index.get("files", [])))

    for item in extract_items:
        extract_result = item["extract_result"]
        file_record = item["file_record"]
        extract_path = item["extract_path"]
        file_id = file_record.get("file_id") or extract_result.get("file_id") or ""

        source_extract_results.append(
            {
                "file_id": file_id,
                "content_type": extract_result.get("content_type", ""),
                "source_type": extract_result.get("source_type", ""),
                "schema_version": extract_result.get("schema_version", ""),
                "extract_status": extract_result.get("extract_status", ""),
                "extract_result_path": _relative_to_project(extract_path),
            }
        )

        if extract_result.get("extract_status") not in {"success", "skipped"}:
            review_items.append(
                _review_item(
                    "warning",
                    "extract_result",
                    file_id,
                    "",
                    "extract_status",
                    f"抽取状态为 {extract_result.get('extract_status') or 'unknown'}，需人工复核",
                )
            )

        for reason in _as_list(extract_result.get("review_reasons")):
            if reason:
                review_items.append(
                    _review_item(
                        "warning",
                        "extract_result",
                        file_id,
                        "",
                        "review_reasons",
                        str(reason),
                    )
                )

        normalized = _normalize_source_extract_result(
            case_id,
            extract_result,
            file_record,
        )
        normalized_transaction_rows.extend(normalized["full_transaction_rows"])
        normalized_holding_rows.extend(normalized["holding_rows"])
        review_items.extend(normalized["review_items"])

    if not extract_items:
        review_items.append(
            _review_item(
                "warning",
                "case",
                "",
                "",
                "extract_result",
                "未找到任何 extract_result.json，需人工复核",
            )
        )

    checklist_rows = _build_checklist_rows(normalized_transaction_rows, normalized_holding_rows)
    if any(row.get("状态") == "需人工复核" for row in checklist_rows):
        review_items.append(
            _review_item(
                "warning",
                "checklist",
                "",
                "",
                "上次持仓 + 交易 = 本次持仓",
                "材料不足，暂无法校验‘上次持仓 + 交易 = 本次持仓’。",
            )
        )

    resolved = resolve_case_events(
        normalized_transaction_rows,
        normalized_holding_rows,
        review_items=review_items,
        checklist_rows=checklist_rows,
    )
    complete_rows = resolved["full_transaction_rows"]
    final_rows = resolved["final_declaration_rows"]
    holding_rows = resolved["holding_rows"]
    problem_events = resolved["problem_events"]
    problem_rows = resolved["problem_list_rows"]
    export_audit = _build_export_audit(complete_rows, final_rows)

    sheets = {
        SHEET_FINAL: {
            "columns": EVENT_COLUMNS,
            "rows": [_select_columns(row, EVENT_COLUMNS) for row in final_rows],
        },
        SHEET_COMPLETE: {
            "columns": EVENT_COLUMNS,
            "rows": [_select_columns(row, EVENT_COLUMNS) for row in complete_rows],
        },
        SHEET_HOLDINGS: {
            "columns": HOLDING_COLUMNS,
            "rows": [_select_columns(row, HOLDING_COLUMNS) for row in holding_rows],
        },
        SHEET_IDENTITY: {
            "columns": IDENTITY_COLUMNS,
            "rows": [_select_columns(row, IDENTITY_COLUMNS) for row in _build_identity_rows(case)],
        },
        SHEET_CHECKLIST: {
            "columns": CHECKLIST_COLUMNS,
            "rows": [_select_columns(row, CHECKLIST_COLUMNS) for row in checklist_rows],
        },
        SHEET_PROBLEMS: {
            "columns": PROBLEM_COLUMNS,
            "rows": [_select_columns(row, PROBLEM_COLUMNS) for row in problem_rows],
        },
    }
    identity_rows = _build_identity_rows(case)

    return {
        "schema_version": FINAL_RESULT_SCHEMA_VERSION,
        "case_id": case_id,
        "generated_at": _now(),
        "mapping_source": _relative_to_project(PROMPT_SCHEMA_PATH),
        "prompt_schema": prompt_schema,
        "case": {
            "case_id": case_id,
            "name": case.get("name", ""),
            "phone": case.get("phone", ""),
            "relation_type": case.get("relation_type", ""),
            "relation_type_label": case.get("relation_type_label", ""),
        },
        "source_extract_results": source_extract_results,
        "summary": {
            "source_extract_result_count": len(source_extract_results),
            "complete_row_count": len(complete_rows),
            "final_declaration_row_count": len(final_rows),
            "holding_row_count": len(holding_rows),
            "identity_row_count": 1,
            "review_item_count": len(review_items),
            "problem_event_count": len(problem_events),
            "manual_review_required": bool(review_items or problem_events),
        },
        "export_audit": export_audit,
        "sheet_order": [
            SHEET_FINAL,
            SHEET_COMPLETE,
            SHEET_HOLDINGS,
            SHEET_IDENTITY,
            SHEET_CHECKLIST,
            SHEET_PROBLEMS,
        ],
        "sheets": sheets,
        SHEET_FINAL: sheets[SHEET_FINAL]["rows"],
        SHEET_COMPLETE: sheets[SHEET_COMPLETE]["rows"],
        SHEET_HOLDINGS: sheets[SHEET_HOLDINGS]["rows"],
        SHEET_IDENTITY: identity_rows[0] if identity_rows else {},
        SHEET_CHECKLIST: sheets[SHEET_CHECKLIST]["rows"],
        SHEET_PROBLEMS: sheets[SHEET_PROBLEMS]["rows"],
        "verified_events": resolved["verified_events"],
        "pending_review_events": resolved["pending_review_events"],
        "verified_holdings": resolved["verified_holdings"],
        "pending_review_holdings": resolved["pending_review_holdings"],
        "problem_events": problem_events,
        "merge_audit": resolved["merge_audit"],
        "review_items": review_items,
    }


def _collect_extract_results(case_id: str, file_records_by_id: dict[str, dict]) -> list[dict]:
    extract_paths = []
    for processed_dir in local_store.iter_existing_processed_dirs(case_id):
        extract_paths.extend(processed_dir.glob("*/extract_result.json"))
    extract_paths = sorted(extract_paths)
    items = []

    for extract_path in extract_paths:
        extract_result = local_store.read_json(extract_path, {})
        if not isinstance(extract_result, dict):
            continue

        file_id = extract_result.get("file_id") or extract_path.parent.name
        file_record = file_records_by_id.get(file_id, {})
        if not file_record:
            for candidate in file_records_by_id.values():
                if candidate.get("output_dir") == _relative_to_project(extract_path.parent):
                    file_record = candidate
                    break

        items.append(
            {
                "extract_path": extract_path,
                "extract_result": extract_result,
                "file_record": file_record,
            }
        )

    return items


def _normalize_source_extract_result(
    case_id: str,
    extract_result: dict,
    file_record: dict,
) -> dict:
    source_type = str(
        extract_result.get("source_type") or extract_result.get("content_type") or ""
    )
    if source_type == "chinaclear":
        return normalize_chinaclear(case_id, extract_result, file_record)
    if source_type == "guangfa":
        return normalize_guangfa(case_id, extract_result, file_record)

    file_id = file_record.get("file_id") or extract_result.get("file_id") or ""
    return empty_normalized_result(
        [
            normalizer_review_item(
                "warning",
                "extract_result",
                file_id,
                "",
                "content_type",
                f"暂不支持的归一化来源：{source_type or 'unknown'}",
            )
        ]
    )


def _file_record_review_items(file_records: list[dict]) -> list[dict]:
    items = []
    failed_process_statuses = {"failed", "ocr_failed"}
    failed_extract_statuses = {
        "failed",
        "llm_request_failed",
        "json_parse_failed",
        "partial_failed",
    }

    for file_record in file_records:
        if not isinstance(file_record, dict):
            continue
        file_id = str(file_record.get("file_id") or "")
        process_status = str(file_record.get("process_status") or "")
        extract_status = str(file_record.get("extract_status") or "")
        common = {
            "file_no": file_record.get("file_no", ""),
            "original_file_name": file_record.get("original_file_name", ""),
        }

        if process_status in failed_process_statuses:
            problem_type = "ocr_failed" if process_status == "ocr_failed" else "process_failed"
            item = _review_item(
                "warning",
                "file",
                file_id,
                "",
                problem_type,
                f"文件处理状态为 {process_status}，需人工复核",
            )
            item.update(common)
            items.append(item)

        if extract_status in failed_extract_statuses:
            item = _review_item(
                "warning",
                "extract_result",
                file_id,
                "",
                "extract_status",
                f"抽取状态为 {extract_status}，需人工复核",
            )
            item.update(common)
            items.append(item)

    return items


def _build_identity_rows(case: dict) -> list[dict]:
    return [
        {
            "case_id": case.get("case_id", ""),
            "name": case.get("name", ""),
            "phone": case.get("phone", ""),
            "relation_type": case.get("relation_type", ""),
            "relation_type_label": case.get("relation_type_label", ""),
            "source": "case.json",
            "review_reason": "",
        }
    ]


def _is_final_declaration_row(row: dict) -> bool:
    return normalizer_is_final_declaration_row(row)


def _build_checklist_rows(rows: list[dict], holding_rows: list[dict]) -> list[dict]:
    status = "需人工复核"
    details = "材料不足，暂无法校验‘上次持仓 + 交易 = 本次持仓’。"
    if rows and holding_rows:
        details = "当前已收集交易和持仓数据，但尚未实现跨材料自动勾稽，需人工复核。"
    return [
        {
            "checklist条件": "上次持仓 + 交易 = 本次持仓",
            "状态": status,
            "说明": details,
        }
    ]


def _build_export_audit(complete_rows: list[dict], final_rows: list[dict]) -> dict:
    final_keys = {_row_compare_key(row) for row in final_rows}
    excluded_rows = [
        row for row in complete_rows if _row_compare_key(row) not in final_keys
    ]
    warnings = []
    if complete_rows and len(complete_rows) == len(final_rows):
        warnings.append(
            "完整表和最终申报表行数相同，请确认是否不存在股息、派息、分红、利息、资金流水等非持仓影响事件。"
        )

    return {
        "full_transaction_count": len(complete_rows),
        "final_declaration_count": len(final_rows),
        "excluded_transaction_count": len(excluded_rows),
        "transaction_type_summary": _type_summary(complete_rows),
        "excluded_type_summary": _type_summary(excluded_rows),
        "warnings": warnings,
    }


def _type_summary(rows: list[dict]) -> list[dict]:
    counts: dict[str, int] = {}
    for row in rows:
        transaction_type = _movement_type(row)
        counts[transaction_type] = counts.get(transaction_type, 0) + 1
    return [
        {"transaction_type": transaction_type, "count": count}
        for transaction_type, count in sorted(
            counts.items(),
            key=lambda item: (-item[1], item[0]),
        )
    ]


def _movement_type(row: dict) -> str:
    return normalizer_movement_type(row)


def _row_compare_key(row: dict) -> tuple:
    return (
        row.get("file_id", ""),
        row.get("event_id", ""),
        row.get("securities_account", ""),
        row.get("event_type", ""),
        row.get("event_date", ""),
        row.get("security_code", ""),
        row.get("quantity_raw", ""),
        row.get("price_raw", ""),
        row.get("amount_raw", ""),
    )


def _missing_field_reviews(row: dict) -> list[dict]:
    reviews = []
    for field in CRITICAL_EVENT_FIELDS:
        if row.get(field) in (None, ""):
            reviews.append(
                _review_item(
                    "warning",
                    "event",
                    str(row.get("file_id") or ""),
                    str(row.get("event_id") or ""),
                    field,
                    f"字段 {field} 缺失，已在最终表中留空",
                )
            )
    return reviews


def _load_prompt_schema() -> dict:
    if not PROMPT_SCHEMA_PATH.exists():
        return {
            "source_exists": False,
            "document_columns": DOCUMENT_COLUMNS,
            "event_columns": EVENT_COLUMNS,
            "holding_columns": HOLDING_COLUMNS,
            "problem_columns": PROBLEM_COLUMNS,
        }

    prompt_text = PROMPT_SCHEMA_PATH.read_text(encoding="utf-8")
    return {
        "source_exists": True,
        "document_info_fields": _extract_object_keys(prompt_text, "document_info"),
        "trade_columns": _extract_trade_columns(prompt_text) or [],
        "position_columns": _extract_position_columns(prompt_text) or [],
        "other_event_fields": _extract_object_keys(prompt_text, "other_events"),
        "excel_sheets": [
            SHEET_FINAL,
            SHEET_COMPLETE,
            SHEET_HOLDINGS,
            SHEET_IDENTITY,
            SHEET_CHECKLIST,
            SHEET_PROBLEMS,
        ],
        "normalized_event_columns": EVENT_COLUMNS,
        "normalized_holding_columns": HOLDING_COLUMNS,
        "problem_columns": PROBLEM_COLUMNS,
    }


def _extract_object_keys(prompt_text: str, object_name: str) -> list[str]:
    if object_name == "other_events":
        match = re.search(r'"other_events"\s*:\s*\[\s*\{(?P<body>.*?)\}\s*\]', prompt_text, re.S)
    else:
        match = re.search(rf'"{re.escape(object_name)}"\s*:\s*\{{(?P<body>.*?)\}}', prompt_text, re.S)
    if not match:
        return []
    return re.findall(r'"([^"]+)"\s*:', match.group("body"))


def _extract_trade_columns(prompt_text: str) -> list[str]:
    match = re.search(r'"trade_columns"\s*:\s*\[(?P<body>.*?)\]', prompt_text, re.S)
    if not match:
        return []
    return re.findall(r'"([^"]+)"', match.group("body"))


def _extract_position_columns(prompt_text: str) -> list[str]:
    match = re.search(r'"position_columns"\s*:\s*\[(?P<body>.*?)\]', prompt_text, re.S)
    if not match:
        return []
    return re.findall(r'"([^"]+)"', match.group("body"))


def _select_columns(row: dict, columns: list[str]) -> dict:
    return {column: _display_value(row.get(column, "")) for column in columns}


def _display_value(value: Any) -> Any:
    if isinstance(value, list):
        return ",".join(str(item) for item in value if item not in (None, ""))
    if isinstance(value, dict):
        return ""
    return value


def _review_item(
    severity: str,
    item_type: str,
    file_id: str,
    event_id: str,
    field: str,
    message: str,
) -> dict:
    return {
        "severity": severity,
        "item_type": item_type,
        "file_id": file_id,
        "event_id": event_id,
        "field": field,
        "message": message,
    }


def _update_status(case_id: str, final_result: dict) -> None:
    status_path = local_store.get_case_dir(case_id) / "status.json"
    status = local_store.read_json(status_path, {"case_id": case_id})
    status.update(
        {
            "current_stage": "finalized",
            "final_status": "success",
            "checklist_status": "success",
            "manual_review_required": final_result["summary"]["manual_review_required"],
            "review_reasons": [
                item.get("message", "")
                for item in final_result.get("review_items", [])
                if item.get("message")
            ],
            "updated_at": _now(),
        }
    )
    local_store.save_json(status_path, status)


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _relative_to_project(path: Path | str) -> str:
    return str(Path(path).resolve().relative_to(local_store.PROJECT_ROOT.resolve()))


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
