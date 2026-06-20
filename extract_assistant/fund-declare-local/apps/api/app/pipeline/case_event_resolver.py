from __future__ import annotations

from typing import Any

from app.pipeline.normalizers.common import (
    as_list,
    is_final_declaration_row,
    movement_type,
    unique_list,
)


EVENT_REQUIRED_FIELDS = [
    "account_type",
    "securities_account",
    "event_type",
    "event_date",
    "security_code",
    "security_name",
]
HOLDING_REQUIRED_FIELDS = [
    "account_type",
    "securities_account",
    "holding_date",
    "security_code",
    "security_name",
    "quantity_raw",
]
EVENT_CONFLICT_FIELDS = [
    "direction",
    "quantity_raw",
    "price_raw",
    "amount_raw",
    "balance_after_raw",
]

PROBLEM_COLUMNS = [
    "问题ID",
    "问题对象类型",
    "问题类型",
    "严重程度",
    "状态",
    "关联文件编号",
    "关联文件名",
    "关联记录ID",
    "缺失字段",
    "冲突字段",
    "问题说明",
    "处理建议",
]


def resolve_case_events(
    transaction_rows: list[dict],
    holding_rows: list[dict] | None = None,
    review_items: list[dict] | None = None,
    checklist_rows: list[dict] | None = None,
) -> dict:
    """Resolve normalized source rows into verified, pending, and problem pools.

    This layer intentionally treats market as candidate information only. A row
    without securities_account cannot receive a verified account_type from market.
    """

    merge_audit: list[dict] = []
    events = _merge_exact_event_duplicates(transaction_rows, merge_audit)
    _mark_event_conflicts(events, merge_audit)

    verified_events: list[dict] = []
    pending_review_events: list[dict] = []
    problem_events: list[dict] = []

    for row in events:
        event_row = dict(row)
        _validate_event_row(event_row)
        if event_row.get("manual_review_required"):
            pending_review_events.append(event_row)
            problem_events.append(_problem_from_row(event_row, "transaction"))
            continue

        verified_events.append(event_row)

    resolved_holding_rows = [dict(row) for row in holding_rows or []]
    verified_holdings: list[dict] = []
    pending_review_holdings: list[dict] = []
    for row in resolved_holding_rows:
        _validate_holding_row(row)
        if row.get("manual_review_required"):
            pending_review_holdings.append(row)
            problem_events.append(_problem_from_row(row, "holding"))
        else:
            verified_holdings.append(row)

    problem_events.extend(_problems_from_review_items(review_items or []))
    problem_events.extend(_problems_from_checklist(checklist_rows or []))
    problem_events = _assign_problem_ids(problem_events)

    full_transaction_rows = verified_events + pending_review_events
    final_declaration_rows = [
        row for row in verified_events if is_final_declaration_row(row)
    ]

    return {
        "full_transaction_rows": full_transaction_rows,
        "final_declaration_rows": final_declaration_rows,
        "holding_rows": verified_holdings + pending_review_holdings,
        "verified_events": verified_events,
        "pending_review_events": pending_review_events,
        "verified_holdings": verified_holdings,
        "pending_review_holdings": pending_review_holdings,
        "problem_events": problem_events,
        "problem_list_rows": problem_list_rows(problem_events),
        "merge_audit": merge_audit,
    }


def problem_list_rows(problem_events: list[dict]) -> list[dict]:
    return [
        {
            "问题ID": problem.get("problem_id", ""),
            "问题对象类型": problem.get("record_category", ""),
            "问题类型": _join(problem.get("problem_types")),
            "严重程度": problem.get("severity", ""),
            "状态": problem.get("status", ""),
            "关联文件编号": _join(problem.get("related_file_nos")),
            "关联文件名": _join(problem.get("related_file_names")),
            "关联记录ID": problem.get("related_record_id", ""),
            "缺失字段": _join(problem.get("missing_fields")),
            "冲突字段": _join(problem.get("conflict_fields")),
            "问题说明": problem.get("message", ""),
            "处理建议": problem.get("suggestion", ""),
        }
        for problem in problem_events
    ]


def _merge_exact_event_duplicates(rows: list[dict], merge_audit: list[dict]) -> list[dict]:
    merged: list[dict] = []
    seen: dict[tuple, dict] = {}

    for row in rows:
        candidate = dict(row)
        key = _exact_event_key(candidate)
        if key and key in seen:
            target = seen[key]
            target["source_evidence"] = _merge_evidence(
                target.get("source_evidence"),
                candidate.get("source_evidence"),
            )
            merge_audit.append(
                {
                    "action": "merged_exact_duplicate",
                    "kept_record_id": target.get("event_id", ""),
                    "merged_record_id": candidate.get("event_id", ""),
                    "reason": "交易关键字段完全一致，已合并来源证据",
                }
            )
            continue

        if key:
            seen[key] = candidate
        merged.append(candidate)

    return merged


def _mark_event_conflicts(rows: list[dict], merge_audit: list[dict]) -> None:
    groups: dict[tuple, list[dict]] = {}
    for row in rows:
        key = _conflict_event_key(row)
        if not key:
            continue
        groups.setdefault(key, []).append(row)

    for key, group in groups.items():
        if len(group) <= 1:
            continue

        conflict_fields = []
        for field in EVENT_CONFLICT_FIELDS:
            values = {str(row.get(field) or "").strip() for row in group if row.get(field) not in (None, "")}
            if len(values) > 1:
                conflict_fields.append(field)

        if not conflict_fields:
            continue

        for row in group:
            _mark_problem(
                row,
                ["conflict_between_sources"],
                conflict_fields=conflict_fields,
            )
        merge_audit.append(
            {
                "action": "possible_same_event_conflict",
                "event_key": "|".join(str(part) for part in key),
                "conflict_fields": conflict_fields,
                "record_ids": [row.get("event_id", "") for row in group],
                "reason": "疑似同一交易在多个来源字段不一致，需人工复核",
            }
        )


def _validate_event_row(row: dict) -> None:
    missing_fields = _missing_fields(row, EVENT_REQUIRED_FIELDS)
    problem_types = []
    if missing_fields:
        problem_types.append("missing_required_fields")
    if not row.get("securities_account"):
        problem_types.append("securities_account_missing")
        problem_types.append("account_type_missing")
        if "securities_account" not in missing_fields:
            missing_fields.append("securities_account")
        if "account_type" not in missing_fields:
            missing_fields.append("account_type")
    elif not row.get("account_type"):
        problem_types.append("account_type_missing")
        if "account_type" not in missing_fields:
            missing_fields.append("account_type")
    if row.get("event_type") in (None, "", "unknown_event"):
        problem_types.append("unknown_event_type")
        if "event_type" not in missing_fields:
            missing_fields.append("event_type")

    if problem_types:
        _mark_problem(row, problem_types, missing_fields=missing_fields)


def _validate_holding_row(row: dict) -> None:
    missing_fields = _missing_fields(row, HOLDING_REQUIRED_FIELDS)
    problem_types = []
    if missing_fields:
        problem_types.append("missing_required_fields")
    if not row.get("securities_account"):
        problem_types.append("securities_account_missing")
        problem_types.append("account_type_missing")
        if "securities_account" not in missing_fields:
            missing_fields.append("securities_account")
        if "account_type" not in missing_fields:
            missing_fields.append("account_type")
    elif not row.get("account_type"):
        problem_types.append("account_type_missing")
        if "account_type" not in missing_fields:
            missing_fields.append("account_type")

    if problem_types:
        _mark_problem(row, problem_types, missing_fields=missing_fields)


def _problem_from_row(row: dict, record_category: str) -> dict:
    evidence = as_list(row.get("source_evidence"))
    return {
        "record_category": record_category,
        "problem_types": unique_list(row.get("problem_types")),
        "severity": "warning",
        "status": "待复核",
        "related_file_ids": _values_from_evidence(evidence, "file_id", row.get("file_id")),
        "related_file_nos": _values_from_evidence(evidence, "file_no", row.get("file_no")),
        "related_file_names": _values_from_evidence(
            evidence,
            "file_name",
            row.get("original_file_name"),
        ),
        "related_record_id": str(row.get("event_id") or row.get("holding_id") or ""),
        "missing_fields": unique_list(row.get("missing_fields")),
        "conflict_fields": unique_list(row.get("conflict_fields")),
        "message": _problem_message(row, record_category),
        "suggestion": _problem_suggestion(row, record_category),
        "source_evidence": evidence,
    }


def _problems_from_review_items(review_items: list[dict]) -> list[dict]:
    problems = []
    for item in review_items:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("item_type") or "")
        if item_type == "checklist":
            continue
        field = str(item.get("field") or "")
        message = str(item.get("message") or "")
        problem_type = _review_item_problem_type(item_type, field, message)
        problems.append(
            {
                "record_category": _review_item_record_category(item_type),
                "problem_types": [problem_type],
                "severity": item.get("severity") or "warning",
                "status": "待复核",
                "related_file_ids": unique_list([item.get("file_id")]),
                "related_file_nos": unique_list([item.get("file_no")]),
                "related_file_names": unique_list([item.get("original_file_name")]),
                "related_record_id": str(item.get("event_id") or ""),
                "missing_fields": unique_list([field]) if field else [],
                "conflict_fields": [],
                "message": message or "存在需要人工复核的问题",
                "suggestion": "请回到原始材料或抽取结果确认该问题。",
                "source_evidence": [],
            }
        )
    return problems


def _review_item_record_category(item_type: str) -> str:
    if item_type == "event":
        return "transaction"
    if item_type == "holding":
        return "holding"
    if item_type == "checklist":
        return "checklist"
    return "file"


def _problems_from_checklist(checklist_rows: list[dict]) -> list[dict]:
    problems = []
    for row in checklist_rows:
        if not isinstance(row, dict):
            continue
        status = str(row.get("状态") or "")
        details = str(row.get("说明") or "")
        if status != "需人工复核" and "暂无法校验" not in details:
            continue
        problems.append(
            {
                "record_category": "checklist",
                "problem_types": ["checklist_pending_review"],
                "severity": "warning",
                "status": "待复核",
                "related_file_ids": [],
                "related_file_nos": [],
                "related_file_names": [],
                "related_record_id": str(row.get("checklist条件") or ""),
                "missing_fields": [],
                "conflict_fields": [],
                "message": details or "checklist 条件暂无法自动校验",
                "suggestion": "请结合完整表、持仓和原始材料人工核查。",
                "source_evidence": [],
            }
        )
    return problems


def _assign_problem_ids(problem_events: list[dict]) -> list[dict]:
    assigned = []
    for index, problem in enumerate(problem_events, start=1):
        item = dict(problem)
        item["problem_id"] = item.get("problem_id") or f"problem_{index:03d}"
        assigned.append(item)
    return assigned


def _mark_problem(
    row: dict,
    problem_types: list[str],
    missing_fields: list[str] | None = None,
    conflict_fields: list[str] | None = None,
) -> None:
    row["manual_review_required"] = True
    row["problem_types"] = unique_list(as_list(row.get("problem_types")) + problem_types)
    row["missing_fields"] = unique_list(as_list(row.get("missing_fields")) + (missing_fields or []))
    row["conflict_fields"] = unique_list(as_list(row.get("conflict_fields")) + (conflict_fields or []))


def _missing_fields(row: dict, fields: list[str]) -> list[str]:
    return [field for field in fields if row.get(field) in (None, "")]


def _problem_message(row: dict, record_category: str) -> str:
    problem_types = set(unique_list(row.get("problem_types")))
    if "conflict_between_sources" in problem_types:
        return "疑似同一记录在多个来源中的字段不一致，需人工复核。"
    if "securities_account_missing" in problem_types:
        return "缺少证券账号，无法确认账户类型和最终申报归属。"
    if "unknown_event_type" in problem_types:
        return "无法判断该交易/事件类型是否影响持仓。"
    if "missing_required_fields" in problem_types:
        return "缺少关键字段，无法通过自动核验。"
    if record_category == "holding":
        return "持仓记录需要人工复核。"
    return "交易/事件记录需要人工复核。"


def _problem_suggestion(row: dict, record_category: str) -> str:
    if not row.get("securities_account"):
        return "请补充证券账号；如只有资金账号，请在人工复核后确认其对应证券账号。"
    if record_category == "holding":
        return "请核对持仓日期、证券账号、证券代码、证券名称和持有数量。"
    return "请核对交易日期、证券账号、证券代码、变动类型、数量、价格和收付金额。"


def _review_item_problem_type(item_type: str, field: str, message: str) -> str:
    lowered = f"{item_type} {field} {message}".lower()
    if "ocr_failed" in lowered or "ocr failed" in lowered:
        return "ocr_failed"
    if "schema" in lowered:
        return "schema_invalid"
    if "extract" in lowered or "抽取" in message:
        return "extract_failed"
    if "checklist" in lowered:
        return "checklist_pending_review"
    return "manual_review_required"


def _values_from_evidence(evidence: list, key: str, fallback: Any = None) -> list[str]:
    values = []
    for item in evidence:
        if isinstance(item, dict):
            values.append(item.get(key))
    if fallback not in (None, ""):
        values.append(fallback)
    return unique_list(values)


def _merge_evidence(*sources: Any) -> list[dict]:
    evidence = []
    seen = set()
    for source in sources:
        for item in as_list(source):
            if not isinstance(item, dict):
                continue
            key = (
                item.get("file_id", ""),
                item.get("source_row_id", ""),
                item.get("source_page", ""),
                item.get("row_no", ""),
            )
            if key in seen:
                continue
            seen.add(key)
            evidence.append(item)
    return evidence


def _exact_event_key(row: dict) -> tuple:
    parts = [
        row.get("securities_account"),
        row.get("account_type"),
        row.get("event_type"),
        row.get("event_date"),
        row.get("security_code"),
        row.get("security_name"),
        row.get("direction"),
        row.get("quantity_raw"),
        row.get("price_raw"),
        row.get("amount_raw"),
        row.get("balance_after_raw"),
    ]
    if not any(part not in (None, "") for part in parts):
        return ()
    return tuple(str(part or "").strip() for part in parts)


def _conflict_event_key(row: dict) -> tuple:
    parts = [
        row.get("securities_account"),
        row.get("event_type"),
        row.get("event_date"),
        row.get("security_code"),
        row.get("security_name"),
    ]
    if any(part in (None, "") for part in parts):
        return ()
    return tuple(str(part).strip() for part in parts)


def _join(value: Any) -> str:
    return ",".join(unique_list(value))
