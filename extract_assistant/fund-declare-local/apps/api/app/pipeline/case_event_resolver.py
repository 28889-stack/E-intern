from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re
from typing import Any

from app.pipeline.normalizers.common import (
    as_list,
    is_final_declaration_row,
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
    "market_value",
]
EVENT_CONFLICT_FIELDS = [
    "direction",
    "quantity_raw",
    "price_raw",
    "amount_raw",
    "balance_after_raw",
]
CROSS_FILE_MERGE_EVENT_TYPES = {
    "ordinary_trade",
    "security_registration",
    "bonus_share",
    "new_share_subscription",
    "new_bond_subscription",
}
WEAK_RECORD_IDS = {
    "资金流水明细",
    "场内交割流水明细",
    "持仓信息",
    "资金流水",
    "场内交割流水",
    "历史成交",
    "交易流水",
}
FULL_ONLY_EVENT_TYPES = {
    "subscription_allotment",
    "cash_dividend",
    "bond_interest",
    "cash_flow",
    "bank_transfer",
    "fund_transfer",
    "interest",
}
FULL_ONLY_TRANSFER_KEYWORDS = (
    "申购配号",
    "中购配号",
    "配号",
    "股息",
    "派息",
    "现金分红",
    "分红",
    "红利",
    "兑息",
    "利息",
    "银证转账",
    "银行转账",
    "资金流水",
    "资金存取",
)

REVIEW_ISSUE_COLUMNS = [
    "序号",
    "待复核原因",
    "问题描述",
    "对应材料",
]

RECORD_CATEGORY_LABELS = {
    "transaction": "交易/事件",
    "holding": "持仓",
    "file": "材料",
}

ISSUE_TYPE_LABELS = {
    "missing_required_fields": "缺少必填字段",
    "securities_account_missing": "缺少证券账号",
    "account_type_missing": "缺少账户类型",
    "person_name_missing": "缺少姓名",
    "source_evidence_missing": "缺少原文证据",
    "unknown_event_type": "无法判断事件类型",
    "conflict_between_sources": "来源字段冲突",
    "empty_record_account_missing": "空记录缺少账户",
    "empty_record_period_missing": "空记录缺少查询时间",
    "ocr_failed": "文字识别失败",
    "schema_invalid": "抽取结构不符合要求",
    "extract_failed": "抽取失败",
    "manual_review_required": "需要人工复核",
    "extraction_field_incomplete": "抽取结果字段不完整",
    "final_declaration_classification_uncertain": "最终申报归类待确认",
    "holding_effect_classification_uncertain": "是否影响持仓待确认",
}

SEVERITY_LABELS = {
    "warning": "提醒",
    "error": "错误",
    "info": "提示",
}

FIELD_LABELS = {
    "account_type": "账户类型",
    "securities_account": "证券账号",
    "event_type": "变动类型",
    "event_date": "查询日期/期间",
    "holding_date": "查询结果所属日期",
    "security_code": "证券代码",
    "security_name": "证券名称",
    "quantity_raw": "数量",
    "market_value": "市值",
    "direction": "方向",
    "price_raw": "价格",
    "amount_raw": "收付金额",
    "balance_after_raw": "变动后余额",
    "person_name": "姓名",
    "raw_text": "原文证据",
    "guangfa": "广发材料",
    "chinaclear": "中国结算材料",
    "identity": "身份材料",
    "extract_result": "抽取结果",
    "final_declaration_fields": "最终申报字段",
    "final_field_candidates": "最终申报字段",
    "include_in_final_declaration": "最终申报归类",
    "affects_holding": "是否影响持仓",
    "review_reasons": "复核原因",
}


def resolve_case_events(
    transaction_rows: list[dict],
    holding_rows: list[dict] | None = None,
    review_items: list[dict] | None = None,
    checklist_rows: list[dict] | None = None,
) -> dict:
    """Split normalized rows and collect non-legal issues for manual review."""

    merge_audit: list[dict] = []
    raw_events = [dict(item) for item in transaction_rows]
    raw_holdings = [dict(item) for item in holding_rows or []]
    _apply_intra_file_security_references(raw_events, raw_holdings)

    events = _merge_exact_event_duplicates(raw_events, merge_audit)
    events = _merge_same_file_partial_trade_duplicates(events, merge_audit)
    events = _merge_cross_file_complementary_trades(events, merge_audit)
    events = _drop_zero_quantity_ordinary_trade_artifacts(events, merge_audit)
    _mark_event_conflicts(events, merge_audit)

    full_events: list[dict] = []
    verified_events: list[dict] = []
    pending_review_events: list[dict] = []
    review_issues: list[dict] = []

    for row in events:
        event_row = dict(row)
        _validate_event_row(event_row)
        full_events.append(event_row)
        if event_row.get("manual_review_required"):
            review_issues.append(_review_issue_from_row(event_row, "transaction"))
            pending_review_events.append(event_row)
        else:
            verified_events.append(event_row)

    verified_holdings: list[dict] = []
    pending_review_holdings: list[dict] = []
    for row in raw_holdings:
        _validate_holding_row(row)
        if row.get("manual_review_required"):
            pending_review_holdings.append(row)
            review_issues.append(_review_issue_from_row(row, "holding"))
        else:
            verified_holdings.append(row)

    review_issues.extend(
        _review_issues_from_review_items(
            _filter_stale_review_items(review_items or [], verified_events),
            review_issues,
        )
    )
    review_issues = _assign_review_issue_ids(review_issues)

    full_transaction_rows = full_events
    final_declaration_rows = [
        row for row in verified_events if is_final_declaration_row(row)
    ]

    return {
        "full_transaction_rows": full_transaction_rows,
        "final_declaration_rows": final_declaration_rows,
        "holding_rows": verified_holdings,
        "verified_events": verified_events,
        "pending_review_events": pending_review_events,
        "verified_holdings": verified_holdings,
        "pending_review_holdings": pending_review_holdings,
        "review_issues": review_issues,
        "review_issue_rows": review_issue_rows(review_issues),
        "merge_audit": merge_audit,
    }


def _apply_intra_file_security_references(*row_groups: list[dict]) -> None:
    references: dict[tuple[str, str], dict[str, str]] = {}
    ambiguous_keys: set[tuple[str, str]] = set()
    rows = [row for group in row_groups for row in group]
    holding_rows = row_groups[1] if len(row_groups) > 1 else []

    holding_references, holding_ambiguous_keys = _collect_security_references(holding_rows)
    _apply_security_references(rows, holding_references, holding_ambiguous_keys)
    holding_code_references, holding_code_ambiguous_keys = _collect_code_references(holding_rows)
    _apply_code_references(rows, holding_code_references, holding_code_ambiguous_keys)
    holding_market_references, holding_market_ambiguous_keys = _collect_market_references(holding_rows)
    _apply_market_references(rows, holding_market_references, holding_market_ambiguous_keys)

    for row in rows:
        security_name = _clean_text(row.get("security_name"))
        security_code = _clean_text(row.get("security_code"))
        if not security_name or not security_code:
            continue
        key = (_file_reference_key(row), security_name)
        candidate = {
            "security_code": security_code,
            "account_type": _clean_text(row.get("account_type")),
            "securities_account": _clean_text(row.get("securities_account")),
        }
        existing = references.setdefault(key, {})
        for field, value in candidate.items():
            if not value:
                continue
            if existing.get(field) and existing[field] != value:
                ambiguous_keys.add(key)
            else:
                existing[field] = value

    for row in rows:
        security_name = _clean_text(row.get("security_name"))
        if not security_name:
            continue
        key = (_file_reference_key(row), security_name)
        if key in ambiguous_keys:
            continue
        reference = references.get(key) or {}
        for field in ("security_code", "account_type", "securities_account"):
            if not _clean_text(row.get(field)) and reference.get(field):
                row[field] = reference[field]

    code_references, code_ambiguous_keys = _collect_code_references(rows)
    _apply_code_references(rows, code_references, code_ambiguous_keys)


def _collect_security_references(rows: list[dict]) -> tuple[dict[tuple[str, str], dict[str, str]], set[tuple[str, str]]]:
    references: dict[tuple[str, str], dict[str, str]] = {}
    ambiguous_keys: set[tuple[str, str]] = set()
    for row in rows:
        security_name = _clean_text(row.get("security_name"))
        security_code = _clean_text(row.get("security_code"))
        if not security_name or not security_code:
            continue
        key = (_file_reference_key(row), security_name)
        candidate = {
            "security_code": security_code,
            "account_type": _clean_text(row.get("account_type")),
            "securities_account": _clean_text(row.get("securities_account")),
        }
        existing = references.setdefault(key, {})
        for field, value in candidate.items():
            if not value:
                continue
            if existing.get(field) and existing[field] != value:
                ambiguous_keys.add(key)
            else:
                existing[field] = value
    return references, ambiguous_keys


def _apply_security_references(
    rows: list[dict],
    references: dict[tuple[str, str], dict[str, str]],
    ambiguous_keys: set[tuple[str, str]],
) -> None:
    for row in rows:
        security_name = _clean_text(row.get("security_name"))
        if not security_name:
            continue
        key = (_file_reference_key(row), security_name)
        if key in ambiguous_keys:
            continue
        reference = references.get(key) or {}
        for field in ("security_code", "account_type", "securities_account"):
            if not _clean_text(row.get(field)) and reference.get(field):
                row[field] = reference[field]


def _collect_code_references(rows: list[dict]) -> tuple[dict[tuple[str, str], dict[str, str]], set[tuple[str, str]]]:
    references: dict[tuple[str, str], dict[str, str]] = {}
    ambiguous_keys: set[tuple[str, str]] = set()
    for row in rows:
        security_code = _clean_text(row.get("security_code"))
        security_name = _clean_text(row.get("security_name"))
        if not security_code or not security_name or security_name == security_code:
            continue
        key = (_file_reference_key(row), security_code)
        candidate = {
            "security_name": security_name,
            "account_type": _clean_text(row.get("account_type")),
            "securities_account": _clean_text(row.get("securities_account")),
        }
        existing = references.setdefault(key, {})
        for field, value in candidate.items():
            if not value:
                continue
            if existing.get(field) and existing[field] != value:
                ambiguous_keys.add(key)
            else:
                existing[field] = value
    return references, ambiguous_keys


def _apply_code_references(
    rows: list[dict],
    references: dict[tuple[str, str], dict[str, str]],
    ambiguous_keys: set[tuple[str, str]],
) -> None:
    for row in rows:
        security_code = _clean_text(row.get("security_code"))
        if not security_code:
            continue
        key = (_file_reference_key(row), security_code)
        if key in ambiguous_keys:
            continue
        reference = references.get(key) or {}
        if _security_name_needs_reference(row) and reference.get("security_name"):
            row["security_name"] = reference["security_name"]
        for field in ("account_type", "securities_account"):
            if not _clean_text(row.get(field)) and reference.get(field):
                row[field] = reference[field]


def _security_name_needs_reference(row: dict) -> bool:
    security_name = _clean_text(row.get("security_name"))
    security_code = _clean_text(row.get("security_code"))
    return not security_name or (security_code and security_name == security_code)


def _collect_market_references(rows: list[dict]) -> tuple[dict[tuple[str, str], dict[str, str]], set[tuple[str, str]]]:
    references: dict[tuple[str, str], dict[str, str]] = {}
    ambiguous_keys: set[tuple[str, str]] = set()
    for row in rows:
        market = _row_market(row)
        account = _clean_text(row.get("securities_account"))
        if not market or not account:
            continue
        key = (_file_reference_key(row), market)
        candidate = {
            "account_type": _clean_text(row.get("account_type")),
            "securities_account": account,
        }
        existing = references.setdefault(key, {})
        for field, value in candidate.items():
            if not value:
                continue
            if existing.get(field) and existing[field] != value:
                ambiguous_keys.add(key)
            else:
                existing[field] = value
    return references, ambiguous_keys


def _apply_market_references(
    rows: list[dict],
    references: dict[tuple[str, str], dict[str, str]],
    ambiguous_keys: set[tuple[str, str]],
) -> None:
    for row in rows:
        market = _row_market(row)
        if not market:
            continue
        key = (_file_reference_key(row), market)
        if key in ambiguous_keys:
            continue
        reference = references.get(key) or {}
        for field in ("account_type", "securities_account"):
            if not _clean_text(row.get(field)) and reference.get(field):
                row[field] = reference[field]


def _row_market(row: dict) -> str:
    account_type = _clean_text(row.get("account_type"))
    if account_type.startswith("深"):
        return "SZ"
    if account_type.startswith("沪"):
        return "SH"
    if account_type == "北交所":
        return "BJ"
    code = _clean_text(row.get("security_code"))
    if code.startswith(("0", "3")):
        return "SZ"
    if code.startswith("6"):
        return "SH"
    if code.startswith(("83", "87", "88", "920")):
        return "BJ"
    return ""


def _file_reference_key(row: dict) -> str:
    return _clean_text(row.get("file_id")) or _clean_text(row.get("file_no"))


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def review_issue_rows(review_issues: list[dict]) -> list[dict]:
    return [
        {
            "序号": str(index),
            "待复核原因": _review_issue_reason(issue),
            "问题描述": _review_issue_description(issue),
            "对应材料": _review_issue_data_source(issue),
            "_meta": _review_issue_meta(issue),
        }
        for index, issue in enumerate(review_issues, start=1)
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


def _merge_cross_file_complementary_trades(
    rows: list[dict],
    merge_audit: list[dict],
) -> list[dict]:
    groups: dict[tuple, list[int]] = {}
    for index, row in enumerate(rows):
        key = _cross_file_trade_key(row)
        if key:
            groups.setdefault(key, []).append(index)

    replacements: dict[int, dict] = {}
    skipped: set[int] = set()

    for key, indices in groups.items():
        if len(indices) != 2:
            continue

        first = rows[indices[0]]
        second = rows[indices[1]]
        if not _has_distinct_files(first, second):
            continue
        if not _can_merge_complementary_trade(first, second):
            continue

        replace_index = min(indices)
        skip_index = max(indices)
        merged = _merge_complementary_trade_rows(first, second)
        replacements[replace_index] = merged
        skipped.add(skip_index)
        merge_audit.append(
            {
                "action": "merged_cross_file_complementary_trade",
                "event_key": "|".join(str(part) for part in key),
                "kept_record_id": merged.get("event_id", ""),
                "merged_record_ids": unique_list(
                    [
                        first.get("event_id") or _first_evidence_value(first, "source_row_id"),
                        second.get("event_id") or _first_evidence_value(second, "source_row_id"),
                    ]
                ),
                "file_ids": unique_list([first.get("file_id"), second.get("file_id")]),
                "reason": "跨文件匹配到同一笔交易，已合并来源证据并互补成交价、金额、余额等字段",
            }
        )

    merged_rows = []
    for index, row in enumerate(rows):
        if index in skipped:
            continue
        merged_rows.append(replacements.get(index, row))
    return merged_rows


def _merge_same_file_partial_trade_duplicates(
    rows: list[dict],
    merge_audit: list[dict],
) -> list[dict]:
    groups: dict[tuple, list[int]] = {}
    for index, row in enumerate(rows):
        key = _partial_duplicate_trade_key(row)
        if key:
            groups.setdefault(key, []).append(index)

    replacements: dict[int, dict] = {}
    skipped: set[int] = set()

    for key, indices in groups.items():
        if len(indices) <= 1:
            continue

        group = [rows[index] for index in indices]
        if not _can_merge_same_file_partial_trade_group(group):
            continue

        target_index = max(indices, key=lambda index: _trade_detail_score(rows[index]))
        merged = dict(rows[target_index])
        for index in indices:
            if index == target_index:
                continue
            merged = _merge_complementary_trade_rows(merged, rows[index])
            skipped.add(index)
        replacements[target_index] = merged
        merge_audit.append(
            {
                "action": "merged_same_file_partial_trade_duplicate",
                "event_key": "|".join(str(part) for part in key),
                "kept_record_id": merged.get("event_id", ""),
                "merged_record_ids": unique_list(
                    [
                        rows[index].get("event_id")
                        or _first_evidence_value(rows[index], "source_row_id")
                        or ""
                        for index in indices
                    ]
                ),
                "reason": "同一文件内同一流水号和交易关键字段一致，已保留字段更完整的场内交割候选",
            }
        )

    merged_rows = []
    for index, row in enumerate(rows):
        if index in skipped:
            continue
        merged_rows.append(replacements.get(index, row))
    return merged_rows


def _mark_event_conflicts(rows: list[dict], merge_audit: list[dict]) -> None:
    groups: dict[tuple, list[dict]] = {}
    for row in rows:
        key = _conflict_event_key(row)
        if key:
            groups.setdefault(key, []).append(row)

    for key, group in groups.items():
        if len(group) <= 1:
            continue

        conflict_fields = []
        for field in EVENT_CONFLICT_FIELDS:
            values = {
                str(row.get(field) or "").strip()
                for row in group
                if row.get(field) not in (None, "")
            }
            if len(values) > 1:
                conflict_fields.append(field)

        if not conflict_fields:
            continue

        for row in group:
            _mark_review_issue(
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


def _drop_zero_quantity_ordinary_trade_artifacts(
    rows: list[dict],
    merge_audit: list[dict],
) -> list[dict]:
    kept_rows = []
    for row in rows:
        if not _is_zero_quantity_ordinary_trade(row):
            kept_rows.append(row)
            continue
        merge_audit.append(
            {
                "action": "dropped_zero_quantity_ordinary_trade",
                "event_key": "|".join(
                    str(part or "")
                    for part in [
                        row.get("file_id"),
                        row.get("securities_account"),
                        row.get("event_date"),
                        row.get("security_code"),
                        row.get("security_name"),
                        row.get("event_id")
                        or _first_evidence_value(row, "source_row_id"),
                    ]
                ),
                "record_id": row.get("event_id")
                or _first_evidence_value(row, "source_row_id")
                or "",
                "reason": "普通买卖记录成交数量为0，不构成有效持仓变动，按抽取伪交易忽略",
            }
        )
    return kept_rows


def _is_zero_quantity_ordinary_trade(row: dict) -> bool:
    if str(row.get("event_type") or "").strip() != "ordinary_trade":
        return False
    if str(row.get("direction") or "").strip() not in {"buy", "sell"}:
        return False
    return _normalized_decimal_text(row.get("quantity_raw")) == "0"


def _validate_event_row(row: dict) -> None:
    if row.get("event_type") == "no_account_info":
        _validate_no_account_info_row(row)
        return
    if row.get("event_type") in {"no_trade_record", "no_holding_record", "no_account_record"}:
        _validate_empty_record_row(row)
        return
    if _is_full_only_event_row(row):
        return

    required_fields = EVENT_REQUIRED_FIELDS
    if row.get("event_type") == "subscription_allotment":
        required_fields = [
            field for field in EVENT_REQUIRED_FIELDS if field != "security_code"
        ]

    missing_fields = _missing_fields(row, required_fields)
    issue_types = []
    if missing_fields:
        issue_types.append("missing_required_fields")
    if not row.get("securities_account"):
        issue_types.append("securities_account_missing")
        _append_missing(missing_fields, "securities_account")
    if not row.get("account_type"):
        issue_types.append("account_type_missing")
        _append_missing(missing_fields, "account_type")
    if row.get("event_type") in (None, "", "unknown_event"):
        issue_types.append("unknown_event_type")
        _append_missing(missing_fields, "event_type")

    if issue_types:
        _mark_review_issue(row, issue_types, missing_fields=missing_fields)


def _is_full_only_event_row(row: dict) -> bool:
    event_type = str(row.get("event_type") or "").strip()
    transfer_type = str(row.get("transfer_type_raw") or "").strip()
    if event_type in FULL_ONLY_EVENT_TYPES:
        return True
    return any(keyword in transfer_type for keyword in FULL_ONLY_TRANSFER_KEYWORDS)


def _validate_empty_record_row(row: dict) -> None:
    missing_fields = []
    issue_types = []
    if row.get("event_type") != "no_account_record" and not row.get("securities_account"):
        issue_types.append("empty_record_account_missing")
        _append_missing(missing_fields, "securities_account")
    if not (
        row.get("event_date")
        or row.get("period_start")
        or row.get("period_end")
    ):
        issue_types.append("empty_record_period_missing")
        _append_missing(missing_fields, "event_date")
    if issue_types:
        _mark_review_issue(row, issue_types, missing_fields=missing_fields)


def _validate_no_account_info_row(row: dict) -> None:
    missing_fields = []
    issue_types = []
    if not row.get("person_name"):
        issue_types.append("person_name_missing")
        _append_missing(missing_fields, "person_name")
    if not (
        row.get("event_date")
        or row.get("period_start")
        or row.get("period_end")
    ):
        issue_types.append("empty_record_period_missing")
        _append_missing(missing_fields, "event_date")
    if not _row_has_raw_text_evidence(row):
        issue_types.append("source_evidence_missing")
        _append_missing(missing_fields, "raw_text")
    if issue_types:
        _mark_review_issue(row, issue_types, missing_fields=missing_fields)


def _row_has_raw_text_evidence(row: dict) -> bool:
    if str(row.get("raw_text") or "").strip():
        return True
    for item in as_list(row.get("source_evidence")):
        if isinstance(item, dict) and str(item.get("raw_text") or "").strip():
            return True
    return False


def _validate_holding_row(row: dict) -> None:
    missing_fields = _missing_fields(row, HOLDING_REQUIRED_FIELDS)
    issue_types = []
    if missing_fields:
        issue_types.append("missing_required_fields")
    if not row.get("securities_account"):
        issue_types.append("securities_account_missing")
        _append_missing(missing_fields, "securities_account")
    if not row.get("account_type"):
        issue_types.append("account_type_missing")
        _append_missing(missing_fields, "account_type")

    if issue_types:
        _mark_review_issue(row, issue_types, missing_fields=missing_fields)


def _review_issue_from_row(row: dict, record_category: str) -> dict:
    evidence = as_list(row.get("source_evidence"))
    return {
        "record_category": record_category,
        "issue_types": unique_list(row.get("review_issue_types")),
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
        "message": _review_issue_message(row, record_category),
        "suggestion": _review_issue_suggestion(row, record_category),
        "source_evidence": evidence,
        "record_snapshot": dict(row),
    }


def _review_issues_from_review_items(
    review_items: list[dict],
    existing_issues: list[dict] | None = None,
) -> list[dict]:
    issues = []
    seen_signatures = set()
    for issue in existing_issues or []:
        seen_signatures.update(_review_issue_signatures(issue))

    for item in review_items:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("item_type") or "")
        # Checklist is a legal/reconciliation result and remains in checklist结果.
        if item_type == "checklist":
            continue
        field = str(item.get("field") or "")
        message = str(item.get("message") or "")
        issue = {
            "record_category": _review_item_record_category(item_type),
            "issue_types": [_review_item_issue_type(item_type, field, message)],
            "severity": item.get("severity") or "warning",
            "status": "待复核",
            "related_file_ids": unique_list([item.get("file_id")]),
            "related_file_nos": unique_list([item.get("file_no")]),
            "related_file_names": unique_list([item.get("original_file_name")]),
            "related_record_id": str(item.get("event_id") or ""),
            "missing_fields": _review_item_missing_fields(field),
            "conflict_fields": [],
            "message": message or "存在需要人工复核的问题",
            "suggestion": "请回到原始材料或抽取结果确认该问题。",
            "source_evidence": [],
            "record_snapshot": dict(item),
        }
        signatures = _review_issue_signatures(issue)
        if signatures & seen_signatures:
            continue
        seen_signatures.update(signatures)
        issues.append(issue)
    return issues


def _filter_stale_review_items(
    review_items: list[dict],
    verified_events: list[dict],
) -> list[dict]:
    events_by_id = {
        str(row.get("event_id") or ""): row
        for row in verified_events
        if row.get("event_id")
    }
    filtered = []
    for item in review_items:
        if not isinstance(item, dict):
            continue
        if _is_resolved_final_field_review_item(item, events_by_id):
            continue
        filtered.append(item)
    return filtered


def _is_resolved_final_field_review_item(
    item: dict,
    events_by_id: dict[str, dict],
) -> bool:
    if item.get("item_type") != "event":
        return False
    if item.get("field") != "final_field_candidates":
        return False
    event_id = str(item.get("event_id") or "")
    row = events_by_id.get(event_id)
    if not row:
        return False
    if row.get("manual_review_required"):
        return False
    return not _missing_fields(row, EVENT_REQUIRED_FIELDS)


def _review_item_record_category(item_type: str) -> str:
    if item_type == "event":
        return "transaction"
    if item_type == "holding":
        return "holding"
    return "file"


def _assign_review_issue_ids(review_issues: list[dict]) -> list[dict]:
    assigned = []
    for index, issue in enumerate(review_issues, start=1):
        item = dict(issue)
        item["review_issue_id"] = (
            item.get("review_issue_id") or f"复核问题_{index:03d}"
        )
        assigned.append(item)
    return assigned


def _mark_review_issue(
    row: dict,
    issue_types: list[str],
    missing_fields: list[str] | None = None,
    conflict_fields: list[str] | None = None,
) -> None:
    row["manual_review_required"] = True
    row["review_issue_types"] = unique_list(
        as_list(row.get("review_issue_types")) + issue_types
    )
    row["missing_fields"] = unique_list(as_list(row.get("missing_fields")) + (missing_fields or []))
    row["conflict_fields"] = unique_list(as_list(row.get("conflict_fields")) + (conflict_fields or []))


def _missing_fields(row: dict, fields: list[str]) -> list[str]:
    return [field for field in fields if row.get(field) in (None, "")]


def _append_missing(missing_fields: list[str], field: str) -> None:
    if field not in missing_fields:
        missing_fields.append(field)


def _review_issue_message(row: dict, record_category: str) -> str:
    issue_types = set(unique_list(row.get("review_issue_types")))
    if "conflict_between_sources" in issue_types:
        return "疑似同一记录在多个来源中的字段不一致，需人工复核。"
    if row.get("event_type") == "no_account_info":
        return "材料显示无账户信息，但缺少姓名、截止日期或原文证据，请人工核对。"
    if issue_types & {"empty_record_account_missing", "empty_record_period_missing"}:
        return "空交易/空持仓记录缺少账户或查询时间，无法确认归属。"
    if {"securities_account_missing", "account_type_missing"} <= issue_types:
        return "缺少证券账号和账户类型，无法确认账户和最终申报归属。"
    if "securities_account_missing" in issue_types:
        return "缺少证券账号，无法确认账户和最终申报归属。"
    if "account_type_missing" in issue_types:
        return "缺少账户类型，无法确认账户和最终申报归属。"
    if "unknown_event_type" in issue_types:
        return "无法判断该交易/事件类型是否影响持仓。"
    if "missing_required_fields" in issue_types:
        return "缺少关键字段，无法通过自动核验。"
    review_reason = str(row.get("review_reason") or "").strip()
    if review_reason:
        return review_reason
    if record_category == "holding":
        return "持仓记录需要人工复核。"
    return "交易/事件记录需要人工复核。"


def _review_issue_suggestion(row: dict, record_category: str) -> str:
    if row.get("event_type") == "no_account_info":
        return "请核对材料中的姓名、截止日期和无账户信息原文。"
    if not row.get("securities_account") and not row.get("account_type"):
        return "请补充证券账号和账户类型；如只有资金账号，请在人工复核后确认其对应证券账号。"
    if not row.get("securities_account"):
        return "请补充证券账号；如只有资金账号，请在人工复核后确认其对应证券账号。"
    if record_category == "holding":
        return "请核对持仓日期、证券账号、证券代码、证券名称和持有数量。"
    return "请核对交易日期、证券账号、证券代码、变动类型、数量、价格和收付金额。"


def _review_item_issue_type(item_type: str, field: str, message: str) -> str:
    lowered = f"{item_type} {field} {message}".lower()
    if field == "final_field_candidates":
        return "extraction_field_incomplete"
    if field == "include_in_final_declaration":
        return "final_declaration_classification_uncertain"
    if field == "affects_holding":
        return "holding_effect_classification_uncertain"
    if "ocr_failed" in lowered or "ocr failed" in lowered:
        return "ocr_failed"
    if "schema" in lowered:
        return "schema_invalid"
    if "extract" in lowered or "抽取" in message:
        return "extract_failed"
    return "manual_review_required"


def _review_item_missing_fields(field: str) -> list[str]:
    if field == "final_field_candidates":
        return ["final_declaration_fields"]
    if field in {"include_in_final_declaration", "affects_holding"}:
        return []
    return unique_list([field]) if field else []


def _review_issue_id_label(value: Any) -> str:
    text = str(value or "")
    match = re.fullmatch(r"review_issue_(\d+)", text)
    if match:
        return f"复核问题_{match.group(1)}"
    return text


def _review_issue_reason(issue: dict) -> str:
    issue_types = _join_labels(issue.get("issue_types"), ISSUE_TYPE_LABELS)
    missing_fields = _join_labels(issue.get("missing_fields"), FIELD_LABELS)
    conflict_fields = _join_labels(issue.get("conflict_fields"), FIELD_LABELS)
    parts = []
    if issue_types:
        parts.append(issue_types)
    if missing_fields:
        parts.append(f"缺失：{missing_fields}")
    if conflict_fields:
        parts.append(f"冲突：{conflict_fields}")
    if not parts:
        message = _message_label(issue.get("message", ""))
        if message:
            parts.append(message)
    return "；".join(parts) or "需要人工复核"


def _review_issue_description(issue: dict) -> str:
    snapshot = issue.get("record_snapshot")
    if not isinstance(snapshot, dict):
        snapshot = {}

    category = _record_category_label(issue.get("record_category", ""))
    message = _message_label(issue.get("message", ""))
    suggestion = str(issue.get("suggestion") or "").strip()

    if snapshot:
        summary = _record_snapshot_summary(snapshot, category)
        subject = f"{category}记录"
        description = f"{subject}{summary}。{message}"
    else:
        description = message or "存在需要人工复核的问题。"

    if suggestion:
        description += f" 建议：{suggestion}"
    return description


def _record_snapshot_summary(row: dict, category: str) -> str:
    if category == "持仓":
        parts = [
            _field_phrase("日期", row.get("holding_date")),
            _field_phrase("证券账号", row.get("securities_account")),
            _field_phrase("证券", _security_label(row)),
            _field_phrase("持有数量", row.get("quantity_raw")),
        ]
    elif row.get("event_type") == "no_account_info":
        parts = [
            _field_phrase("姓名", row.get("person_name")),
            _field_phrase("截止日期", row.get("event_date") or row.get("period_end") or row.get("period_start")),
            _field_phrase("变动类型", _movement_label(row)),
        ]
    else:
        parts = [
            _field_phrase("日期", row.get("event_date") or row.get("period_end") or row.get("period_start")),
            _field_phrase("证券账号", row.get("securities_account")),
            _field_phrase("变动类型", _movement_label(row)),
            _field_phrase("证券", _security_label(row)),
            _field_phrase("数量", row.get("quantity_raw")),
            _field_phrase("金额", row.get("amount_raw")),
        ]
    text = "，".join(part for part in parts if part)
    return f"（{text}）" if text else ""


def _field_phrase(label: str, value: Any) -> str:
    text = str(value or "").strip()
    return f"{label}：{text}" if text else ""


def _movement_label(row: dict) -> str:
    raw = str(row.get("transfer_type_raw") or "").strip()
    if raw:
        return raw
    direction = str(row.get("direction") or "").strip()
    direction_labels = {
        "buy": "买入",
        "sell": "卖出",
        "transfer_in": "转入",
        "transfer_out": "转出",
        "registration_in": "登记入账",
        "rights_event": "权益事件",
        "subscribe": "申购",
    }
    if direction in direction_labels:
        return direction_labels[direction]
    event_type = str(row.get("event_type") or "").strip()
    event_type_labels = {
        "ordinary_trade": "普通交易",
        "security_registration": "股份登记",
        "bonus_share": "送股/转增",
        "new_share_subscription": "打新",
        "new_bond_subscription": "打新债",
        "cash_dividend": "股息/分红",
        "bond_interest": "兑息/利息",
        "cash_flow": "资金流水",
        "bank_transfer": "银证转账",
        "no_trade_record": "无交易记录",
        "no_holding_record": "无持仓记录",
        "no_account_record": "未开立账户",
        "no_account_info": "无账户信息",
        "unknown_event": "未知事件",
    }
    return event_type_labels.get(event_type, event_type)


def _security_label(row: dict) -> str:
    code = str(row.get("security_code") or "").strip()
    name = str(row.get("security_name") or "").strip()
    if code and name:
        return f"{code} {name}"
    return code or name


def _record_category_label(value: Any) -> str:
    text = str(value or "")
    return RECORD_CATEGORY_LABELS.get(text, text)


def _severity_label(value: Any) -> str:
    text = str(value or "")
    return SEVERITY_LABELS.get(text, text)


def _status_label(value: Any) -> str:
    text = str(value or "")
    if text == "pending_review":
        return "待复核"
    if text == "reviewed":
        return "已复核"
    return text


def _join_labels(value: Any, labels: dict[str, str]) -> str:
    return ",".join(labels.get(item, item) for item in unique_list(value))


def _message_label(value: Any) -> str:
    text = str(value or "")
    replacements = {
        "ocr_failed": "文字识别失败",
        "ocr failed": "文字识别失败",
        "OCR failed": "文字识别失败",
        "failed": "失败",
        "unknown": "未知",
        "schema": "结构",
        "extract_result": "抽取结果",
        "event_type": "变动类型",
        "securities_account": "证券账号",
        "account_type": "账户类型",
        "final_field_candidates": "最终申报字段",
        "include_in_final_declaration": "最终申报归类",
        "affects_holding": "是否影响持仓",
        "LLM": "智能抽取",
        "llm": "智能抽取",
        "智能抽取 判断": "智能抽取判断",
        "是否影响持仓 与": "是否影响持仓与",
        "guangfa": "广发材料",
        "chinaclear": "中国结算材料",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text


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


def _cross_file_trade_key(row: dict) -> tuple:
    if row.get("manual_review_required"):
        return ()
    event_type = str(row.get("event_type") or "").strip()
    if event_type not in CROSS_FILE_MERGE_EVENT_TYPES:
        return ()
    direction = str(row.get("direction") or "").strip()
    if event_type == "ordinary_trade" and direction not in {"buy", "sell"}:
        return ()
    direction_key = direction or event_type
    quantity = _normalized_decimal_text(row.get("quantity_raw"))
    parts = [
        row.get("securities_account"),
        row.get("account_type"),
        event_type,
        row.get("event_date"),
        row.get("security_code"),
        row.get("security_name"),
        direction_key,
        quantity,
    ]
    if any(part in (None, "") for part in parts):
        return ()
    return tuple(str(part).strip() for part in parts)


def _partial_duplicate_trade_key(row: dict) -> tuple:
    if str(row.get("event_type") or "").strip() != "ordinary_trade":
        return ()
    if str(row.get("direction") or "").strip() not in {"buy", "sell"}:
        return ()
    serial_no = str(row.get("serial_no") or "").strip()
    if not serial_no:
        return ()

    parts = [
        row.get("file_id"),
        row.get("securities_account"),
        row.get("account_type"),
        row.get("event_type"),
        row.get("event_date"),
        serial_no,
        row.get("security_code"),
        row.get("security_name"),
        row.get("direction"),
        _normalized_decimal_text(row.get("quantity_raw")),
        _normalized_decimal_text(row.get("price_raw")),
        _normalized_decimal_text(row.get("amount_raw")),
    ]
    if any(part in (None, "") for part in parts):
        return ()
    return tuple(str(part).strip() for part in parts)


def _can_merge_same_file_partial_trade_group(group: list[dict]) -> bool:
    order_nos = {
        str(row.get("order_no") or "").strip()
        for row in group
        if str(row.get("order_no") or "").strip()
    }
    if len(order_nos) > 1:
        return False

    event_times = {
        str(row.get("event_time") or "").strip()
        for row in group
        if str(row.get("event_time") or "").strip()
    }
    if len(event_times) > 1:
        return False

    return True


def _has_distinct_files(first: dict, second: dict) -> bool:
    first_file = str(first.get("file_id") or first.get("file_no") or "").strip()
    second_file = str(second.get("file_id") or second.get("file_no") or "").strip()
    return bool(first_file and second_file and first_file != second_file)


def _can_merge_complementary_trade(first: dict, second: dict) -> bool:
    for field in (
        "price_raw",
        "amount_raw",
        "event_time",
        "serial_no",
        "order_no",
        "balance_after_raw",
    ):
        first_value = first.get(field)
        second_value = second.get(field)
        if first_value in (None, "") or second_value in (None, ""):
            continue
        if field in {"price_raw", "amount_raw", "balance_after_raw"}:
            if _normalized_decimal_text(first_value) != _normalized_decimal_text(second_value):
                return False
        elif str(first_value).strip() != str(second_value).strip():
            return False
    return True


def _merge_complementary_trade_rows(first: dict, second: dict) -> dict:
    target, other = (
        (first, second)
        if _trade_detail_score(first) >= _trade_detail_score(second)
        else (second, first)
    )
    merged = dict(target)
    for field in (
        "case_id",
        "account_type",
        "document_type",
        "document_title",
        "period_start",
        "period_end",
        "holder_name",
        "one_code_account",
        "securities_account",
        "event_id",
        "event_type",
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
        "serial_no",
        "order_no",
        "review_reason",
    ):
        if merged.get(field) in (None, "") and other.get(field) not in (None, ""):
            merged[field] = other.get(field)

    merged["source_pages"] = _merge_joined_values(
        first.get("source_pages"),
        second.get("source_pages"),
    )
    merged["row_nos"] = _merge_joined_values(first.get("row_nos"), second.get("row_nos"))
    merged["source_evidence"] = _merge_evidence(
        _row_evidence(first),
        _row_evidence(second),
    )
    merged["merged_file_ids"] = unique_list([first.get("file_id"), second.get("file_id")])
    merged["merged_file_nos"] = unique_list([first.get("file_no"), second.get("file_no")])
    return merged


def _trade_detail_score(row: dict) -> int:
    score = 0
    for field in ("price_raw", "amount_raw", "event_time", "serial_no", "order_no"):
        if row.get(field) not in (None, ""):
            score += 2
    if row.get("balance_after_raw") not in (None, ""):
        score += 1
    return score


def _row_evidence(row: dict) -> list[dict]:
    evidence = _merge_evidence(row.get("source_evidence"))
    if evidence:
        return evidence
    if not (row.get("file_id") or row.get("file_no") or row.get("original_file_name")):
        return []
    return [
        {
            "file_id": row.get("file_id", ""),
            "file_no": row.get("file_no", ""),
            "file_name": row.get("original_file_name", ""),
            "source_row_id": row.get("event_id", ""),
            "source_page": row.get("source_pages", ""),
            "row_no": row.get("row_nos", ""),
            "raw_text": row.get("raw_text", ""),
        }
    ]


def _merge_joined_values(*values: Any) -> str:
    items = []
    for value in values:
        if value in (None, ""):
            continue
        if isinstance(value, (list, tuple, set)):
            items.extend(str(item).strip() for item in value if item not in (None, ""))
        else:
            items.extend(part.strip() for part in str(value).split(",") if part.strip())
    return ",".join(unique_list(items))


def _normalized_decimal_text(value: Any) -> str:
    text = str(value or "").strip().replace(",", "")
    if not text:
        return ""
    try:
        number = Decimal(text)
    except (InvalidOperation, ValueError):
        return text
    if number == 0:
        return "0"
    normalized = format(number.normalize(), "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized


def _exact_event_key(row: dict) -> tuple:
    parts = [
        row.get("securities_account"),
        row.get("account_type"),
        row.get("event_type"),
        row.get("event_date"),
        row.get("event_time"),
        row.get("security_code"),
        row.get("security_name"),
        row.get("direction"),
        row.get("quantity_raw"),
        row.get("price_raw"),
        row.get("amount_raw"),
        row.get("balance_after_raw"),
        row.get("serial_no"),
        row.get("order_no"),
    ]
    if not any(part not in (None, "") for part in parts):
        return ()
    return tuple(str(part or "").strip() for part in parts)


def _conflict_event_key(row: dict) -> tuple:
    record_id = str(row.get("event_id") or _first_evidence_value(row, "source_row_id") or "").strip()
    if not record_id or _is_weak_record_id(record_id):
        return ()
    parts = [
        row.get("file_id"),
        row.get("securities_account"),
        row.get("event_type"),
        row.get("event_date"),
        row.get("event_time"),
        row.get("security_code"),
        row.get("security_name"),
        row.get("direction"),
        _normalized_decimal_text(row.get("quantity_raw")),
        _normalized_decimal_text(row.get("price_raw")),
        _normalized_decimal_text(row.get("amount_raw")),
        _normalized_decimal_text(row.get("balance_after_raw")),
        record_id,
    ]
    if any(part in (None, "") for part in parts):
        return ()
    return tuple(str(part).strip() for part in parts)


def _is_weak_record_id(record_id: str) -> bool:
    text = str(record_id or "").strip()
    if not text:
        return True
    if text in WEAK_RECORD_IDS:
        return True
    return text.endswith("明细") and not any(char.isdigit() for char in text)


def _review_issue_data_source(issue: dict) -> str:
    evidence = as_list(issue.get("source_evidence"))
    parts = [_evidence_label(item) for item in evidence if isinstance(item, dict)]
    if parts:
        return "；".join(unique_list(parts))

    names = _join(issue.get("related_file_names"))
    nos = _join(issue.get("related_file_nos"))
    return " ".join(part for part in [nos, names] if part)


def _review_issue_meta(issue: dict) -> dict:
    file_ids = unique_list(issue.get("related_file_ids"))
    return {
        "file_id": file_ids[0] if file_ids else "",
        "source_row_id": issue.get("related_record_id", ""),
        "original_row": {
            key: value
            for key, value in issue.items()
            if key not in {"source_evidence"}
        },
        "source_evidence": as_list(issue.get("source_evidence")),
    }


def _review_issue_signatures(issue: dict) -> set[tuple[str, str, str]]:
    record_category = str(issue.get("record_category") or "")
    record_keys = _review_issue_record_keys(issue)
    fields = (
        unique_list(issue.get("missing_fields"))
        or unique_list(issue.get("conflict_fields"))
        or unique_list(issue.get("issue_types"))
        or [str(issue.get("message") or "")]
    )
    return {
        (record_category, record_key, field)
        for record_key in record_keys
        for field in fields
        if record_category or record_key or field
    }


def _review_issue_record_keys(issue: dict) -> list[str]:
    keys = []
    related_record_id = str(issue.get("related_record_id") or "").strip()
    if related_record_id:
        keys.append(f"id:{_signature_part(related_record_id)}")

    snapshot = issue.get("record_snapshot")
    if isinstance(snapshot, dict) and snapshot:
        date_value = (
            snapshot.get("event_date")
            or snapshot.get("holding_date")
            or snapshot.get("period_start")
            or snapshot.get("period_end")
        )
        record_parts = [
            issue.get("related_record_id"),
            snapshot.get("file_id"),
            snapshot.get("file_no"),
            snapshot.get("event_id") or snapshot.get("holding_id"),
            snapshot.get("securities_account"),
            snapshot.get("account_type"),
            snapshot.get("event_type"),
            date_value,
            snapshot.get("security_code"),
            snapshot.get("security_name"),
            snapshot.get("direction"),
            snapshot.get("quantity_raw"),
            snapshot.get("price_raw"),
            snapshot.get("amount_raw"),
            snapshot.get("balance_after_raw"),
            snapshot.get("transfer_type_raw"),
        ]
        for item in as_list(issue.get("source_evidence")):
            if not isinstance(item, dict):
                continue
            record_parts.extend(
                [
                    item.get("file_id"),
                    item.get("source_row_id"),
                    item.get("source_page"),
                    item.get("row_no"),
                ]
            )
        key = "|".join(_signature_part(part) for part in record_parts if part not in (None, ""))
        if key:
            keys.append(f"row:{key}")

    fallback_parts = [
        issue.get("related_record_id"),
        _join(issue.get("related_file_ids")),
        _join(issue.get("related_file_nos")),
        _join(issue.get("related_file_names")),
        issue.get("message"),
    ]
    fallback_key = "|".join(_signature_part(part) for part in fallback_parts if part not in (None, ""))
    if fallback_key:
        keys.append(f"fallback:{fallback_key}")

    return unique_list(keys) or [""]


def _first_evidence_value(row: dict, key: str) -> Any:
    for item in as_list(row.get("source_evidence")):
        if isinstance(item, dict) and item.get(key) not in (None, ""):
            return item.get(key)
    return None


def _signature_part(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _evidence_label(item: dict) -> str:
    file_label = " ".join(
        part
        for part in [item.get("file_no"), item.get("file_name")]
        if part not in (None, "")
    )
    pages = _join(item.get("source_pages") or item.get("source_page"))
    rows = _join(item.get("row_nos") or item.get("row_no"))
    suffix = []
    if pages:
        suffix.append(f"第{pages}页")
    if rows:
        suffix.append(f"行{rows}")
    return " ".join(part for part in [file_label, *suffix] if part)


def _join(value: Any) -> str:
    return ",".join(unique_list(value))
