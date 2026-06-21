from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from app.pipeline.case_event_resolver import REVIEW_ISSUE_COLUMNS, resolve_case_events
from app.pipeline.file_issue_collector import collect_file_issues
from app.pipeline.file_issue_summarizer import summarize_file_issues
from app.pipeline.normalizers import normalize_chinaclear, normalize_guangfa
from app.pipeline.normalizers.common import (
    as_list as normalizer_as_list,
    empty_normalized_result,
    is_final_declaration_row as normalizer_is_final_declaration_row,
    movement_type as normalizer_movement_type,
    review_item as normalizer_review_item,
    unique_list,
)
from app.services import local_store
from app.services.llm_client import LLMClient


PROMPT_SCHEMA_PATH = local_store.PROJECT_ROOT / "prompts" / "chinaclear_extract_prompt.md"
FINAL_RESULT_SCHEMA_VERSION = "final_result_v1"

SHEET_FINAL = "最终申报表"
SHEET_COMPLETE = "完整表"
SHEET_REVIEW_ISSUES = "待复核问题"
SHEET_HOLDINGS = "持仓"
SHEET_IDENTITY = "身份信息"
SHEET_CHECKLIST = "checklist结果"

DOCUMENT_COLUMNS = [
    "document_type",
    "market",
    "document_title",
    "period_start",
    "period_end",
    "holder_name",
    "one_code_account",
    "securities_account",
]

EVENT_COLUMNS = [
    "case_id",
    "file_id",
    "file_no",
    "original_file_name",
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
    "review_reason",
]

COMPLETE_EVENT_COLUMNS = EVENT_COLUMNS + ["data_source"]

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
    "account_type",
    "securities_account",
    "market",
    "holding_date",
    "security_code",
    "security_name",
    "quantity_raw",
    "security_category_raw",
    "source_pages",
    "row_nos",
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
    complete_rows: list[dict] = []
    holding_rows: list[dict] = []
    source_extract_results = []

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
                _with_file_metadata(
                    _review_item(
                        "warning",
                        "extract_result",
                        file_id,
                        "",
                        "extract_status",
                        f"抽取状态为 {extract_result.get('extract_status') or 'unknown'}，需人工复核",
                    ),
                    file_record,
                )
            )

        for reason in _as_list(extract_result.get("review_reasons")):
            if reason:
                review_items.append(
                    _with_file_metadata(
                        _review_item(
                            "warning",
                            "extract_result",
                            file_id,
                            "",
                            "review_reasons",
                            str(reason),
                        ),
                        file_record,
                    )
                )

        normalized = _normalize_source_extract_result(
            case_id,
            extract_result,
            file_record,
        )
        complete_rows.extend(normalized["full_transaction_rows"])
        holding_rows.extend(normalized["holding_rows"])
        review_items.extend(
            _with_file_metadata(item, file_record)
            for item in normalized["review_items"]
        )

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

    resolved = resolve_case_events(
        complete_rows,
        holding_rows=holding_rows,
        review_items=review_items,
    )
    complete_rows = resolved["full_transaction_rows"]
    final_rows = resolved["final_declaration_rows"]
    holding_rows = resolved["holding_rows"]
    for row in complete_rows + holding_rows:
        row["data_source"] = _data_source(row)
    complete_sheet_rows = _complete_sheet_rows(complete_rows)

    checklist_rows = _build_checklist_rows(
        complete_rows,
        holding_rows,
        pending_review_event_count=len(resolved.get("pending_review_events", [])),
        pending_review_holding_count=len(resolved.get("pending_review_holdings", [])),
        pending_review_events=resolved.get("pending_review_events", []),
        account_info_rows=final_rows,
    )
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

    review_issue_rows = resolved["review_issue_rows"]
    review_issues = resolved["review_issues"]
    file_issues = collect_file_issues(
        case_id,
        files_index,
        review_issues=review_issues,
        review_issue_rows=review_issue_rows,
        pending_review_events=resolved.get("pending_review_events", []),
        pending_review_holdings=resolved.get("pending_review_holdings", []),
    )
    review_issue_rows = [
        *review_issue_rows,
        *_review_issue_rows_from_file_issues(
            file_issues,
            start_index=len(review_issue_rows) + 1,
        ),
    ]
    file_issue_result = summarize_file_issues(
        file_issues,
        review_issue_rows,
        files_index,
        llm_client=_file_issue_llm_client(),
    )
    file_issue_summaries = file_issue_result.get("file_issue_summaries", [])
    export_audit = _build_export_audit(complete_sheet_rows, final_rows)

    sheets = {
        SHEET_FINAL: {
            "columns": EVENT_COLUMNS,
            "rows": [_select_columns(row, EVENT_COLUMNS) for row in final_rows],
        },
        SHEET_COMPLETE: {
            "columns": COMPLETE_EVENT_COLUMNS,
            "rows": [_select_columns(row, COMPLETE_EVENT_COLUMNS) for row in complete_sheet_rows],
        },
        SHEET_REVIEW_ISSUES: {
            "columns": REVIEW_ISSUE_COLUMNS,
            "rows": [
                _select_columns(row, REVIEW_ISSUE_COLUMNS)
                for row in review_issue_rows
            ],
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
    }

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
            "complete_row_count": len(complete_sheet_rows),
            "final_declaration_row_count": len(final_rows),
            "holding_row_count": len(holding_rows),
            "identity_row_count": 1,
            "review_issue_count": len(review_issue_rows),
            "review_item_count": len(review_items),
            "file_issue_count": len(file_issues),
            "manual_review_required": bool(review_items or review_issues or file_issues),
        },
        "export_audit": export_audit,
        "merge_audit": resolved.get("merge_audit", []),
        "file_issues": file_issues,
        "file_issue_summaries": file_issue_summaries,
        "sheet_order": [
            SHEET_FINAL,
            SHEET_COMPLETE,
            SHEET_REVIEW_ISSUES,
            SHEET_HOLDINGS,
            SHEET_IDENTITY,
            SHEET_CHECKLIST,
        ],
        "sheets": sheets,
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


OCR_REVIEW_ISSUE_TYPES = {
    "ocr_failed",
    "ocr_partial_failed",
    "ocr_low_confidence",
    "suspected_occlusion",
}
EXTRACT_REVIEW_ISSUE_TYPES = {
    "extract_failed",
    "extract_partial_failed",
    "llm_request_failed",
    "json_parse_failed",
    "llm_output_truncated",
    "schema_invalid",
}


def _review_issue_rows_from_file_issues(
    file_issues: list[dict],
    start_index: int,
) -> list[dict]:
    rows = []
    next_index = start_index
    for issue in file_issues:
        issue_types = set(normalizer_as_list(issue.get("issue_types")))
        for reason, type_set in (
            ("OCR问题", OCR_REVIEW_ISSUE_TYPES),
            ("抽取问题", EXTRACT_REVIEW_ISSUE_TYPES),
        ):
            matched_types = sorted(issue_types & type_set)
            if not matched_types:
                continue
            rows.append(
                {
                    "序号": str(next_index),
                    "待复核原因": reason,
                    "问题描述": _file_issue_review_description(issue, matched_types, reason),
                    "对应材料": _file_issue_source_label(issue),
                    "_meta": {
                        "file_id": issue.get("file_id", ""),
                        "source_row_id": f"file_issue_{next_index}",
                        "original_row": issue,
                    },
                }
            )
            next_index += 1
    return rows


def _file_issue_review_description(issue: dict, issue_types: list[str], reason: str) -> str:
    labels = [_file_issue_type_label(issue_type) for issue_type in issue_types]
    evidence = [
        str(item)
        for item in normalizer_as_list(issue.get("evidence"))
        if _evidence_matches_issue_types(str(item), issue_types)
    ][:3]
    if reason == "OCR问题":
        action = "请核对原文件与 OCR 识别结果；如存在遮挡或涂抹，请重新上传无遮挡材料。"
    else:
        action = "请核对抽取结果，必要时重新抽取或在人工复核页补充缺失内容。"
    details = "、".join(label for label in labels if label)
    if evidence:
        details = f"{details}（{'；'.join(evidence)}）" if details else "；".join(evidence)
    return f"该材料存在{reason}：{details or '需人工复核'}。{action}"


def _file_issue_source_label(issue: dict) -> str:
    return " ".join(
        part
        for part in [str(issue.get("file_no") or ""), str(issue.get("file_name") or "")]
        if part
    )


def _file_issue_type_label(issue_type: str) -> str:
    return {
        "ocr_failed": "OCR 失败",
        "ocr_partial_failed": "部分页面 OCR 失败",
        "ocr_low_confidence": "OCR 置信度偏低",
        "suspected_occlusion": "材料存在遮挡或涂抹",
        "extract_failed": "抽取失败",
        "extract_partial_failed": "部分抽取失败",
        "llm_request_failed": "智能抽取请求失败",
        "json_parse_failed": "结构化结果解析失败",
        "llm_output_truncated": "智能抽取输出被截断",
        "schema_invalid": "抽取结构不合法",
    }.get(issue_type, issue_type)


def _evidence_matches_issue_types(evidence: str, issue_types: list[str]) -> bool:
    if not evidence:
        return False
    if any(issue_type in {"ocr_failed", "ocr_partial_failed"} for issue_type in issue_types):
        return "OCR" in evidence or "ocr" in evidence
    if "ocr_low_confidence" in issue_types:
        return "置信度" in evidence or "confidence" in evidence
    if "suspected_occlusion" in issue_types:
        return "遮挡" in evidence or "涂抹" in evidence
    return any(keyword in evidence for keyword in ("抽取", "LLM", "JSON", "schema", "截断"))


def _build_checklist_rows(
    rows: list[dict],
    holding_rows: list[dict],
    pending_review_event_count: int = 0,
    pending_review_holding_count: int = 0,
    pending_review_events: list[dict] | None = None,
    account_info_rows: list[dict] | None = None,
) -> list[dict]:
    pending_parts = []
    if pending_review_event_count:
        pending_parts.append(f"{pending_review_event_count}条待复核交易")
    if pending_review_holding_count:
        pending_parts.append(f"{pending_review_holding_count}条待复核持仓")

    if pending_parts:
        status = "需人工复核"
        details = (
            f"当前存在{'、'.join(pending_parts)}，相关记录尚未进入自动勾稽范围，"
            "暂无法自动校验‘上次持仓 + 交易 = 本次持仓’。"
        )
    elif not rows and not holding_rows:
        status = "无需校验"
        details = "未发现交易和持仓数据，暂不执行‘上次持仓 + 交易 = 本次持仓’校验。"
    elif not rows:
        status = "无需校验"
        details = "未发现交易记录，仅有持仓数据，暂不执行‘上次持仓 + 交易 = 本次持仓’校验。"
    elif not holding_rows:
        status = "无需校验"
        details = "未发现持仓记录，仅有交易数据，暂不执行‘上次持仓 + 交易 = 本次持仓’校验。"
    else:
        status = "需人工复核"
        details = "当前已收集交易和持仓数据，但尚未实现跨材料自动勾稽，需人工复核。"
    checklist_rows = [
        {
            "checklist条件": "上次持仓 + 交易 = 本次持仓",
            "状态": status,
            "说明": details,
        }
    ]
    account_check = _account_info_checklist_row(
        account_info_rows if account_info_rows is not None else rows,
        pending_review_events or [],
    )
    if account_check:
        checklist_rows.append(account_check)
    return checklist_rows


def _account_info_checklist_row(
    account_info_rows: list[dict],
    pending_review_events: list[dict],
) -> dict | None:
    no_account_rows = [
        row for row in account_info_rows if row.get("event_type") == "no_account_info"
    ]
    if no_account_rows:
        row = no_account_rows[0]
        person_name = str(row.get("person_name") or row.get("holder_name") or "").strip()
        as_of_date = str(
            row.get("event_date") or row.get("period_end") or row.get("period_start") or ""
        ).strip()
        if person_name and as_of_date:
            return {
                "checklist条件": "账户信息检查",
                "状态": "通过",
                "说明": f"截至{as_of_date}，{person_name}无账户信息。",
            }

    if any(row.get("event_type") == "no_account_info" for row in pending_review_events):
        return {
            "checklist条件": "账户信息检查",
            "状态": "需人工复核",
            "说明": "材料显示无账户信息，但缺少姓名或截止日期，请人工核对。",
        }
    return None


def _build_export_audit(complete_rows: list[dict], final_rows: list[dict]) -> dict:
    excluded_rows = [row for row in complete_rows if not _is_final_declaration_row(row)]
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


def _complete_sheet_rows(rows: list[dict]) -> list[dict]:
    return [row for row in rows if row.get("event_type") != "no_account_info"]


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


def _data_source(row: dict) -> str:
    evidence_labels = []
    for item in normalizer_as_list(row.get("source_evidence")):
        if isinstance(item, dict):
            label = _source_evidence_label(item)
            if label:
                evidence_labels.append(label)
    if evidence_labels:
        return "；".join(unique_list(evidence_labels))

    file_label = " ".join(
        part
        for part in [row.get("file_no"), row.get("original_file_name")]
        if part not in (None, "")
    )
    pages = _join_values(row.get("source_pages"))
    row_nos = _join_values(row.get("row_nos"))
    suffix = []
    if pages:
        suffix.append(f"第{pages}页")
    if row_nos:
        suffix.append(f"行{row_nos}")
    return " ".join(part for part in [file_label, *suffix] if part)


def _source_evidence_label(item: dict) -> str:
    file_label = " ".join(
        part
        for part in [item.get("file_no"), item.get("file_name")]
        if part not in (None, "")
    )
    pages = _join_values(item.get("source_pages") or item.get("source_page"))
    row_nos = _join_values(item.get("row_nos") or item.get("row_no"))
    suffix = []
    if pages:
        suffix.append(f"第{pages}页")
    if row_nos:
        suffix.append(f"行{row_nos}")
    return " ".join(part for part in [file_label, *suffix] if part)


def _join_values(value: Any) -> str:
    return ",".join(unique_list(value))


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
        }

    prompt_text = PROMPT_SCHEMA_PATH.read_text(encoding="utf-8")
    return {
        "source_exists": True,
        "document_info_fields": _extract_object_keys(prompt_text, "document_info"),
        "trade_columns": _extract_trade_columns(prompt_text) or [],
        "other_event_fields": _extract_object_keys(prompt_text, "other_events"),
        "excel_sheets": [
            SHEET_FINAL,
            SHEET_COMPLETE,
            SHEET_REVIEW_ISSUES,
            SHEET_HOLDINGS,
            SHEET_IDENTITY,
            SHEET_CHECKLIST,
        ],
        "normalized_event_columns": EVENT_COLUMNS,
        "complete_event_columns": COMPLETE_EVENT_COLUMNS,
        "review_issue_columns": REVIEW_ISSUE_COLUMNS,
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


def _select_columns(row: dict, columns: list[str]) -> dict:
    selected = {column: row.get(column, "") for column in columns}
    if isinstance(row.get("_meta"), dict):
        selected["_meta"] = row["_meta"]
    return selected


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


def _with_file_metadata(item: dict, file_record: dict) -> dict:
    enriched = dict(item)
    if file_record:
        enriched.setdefault("file_id", file_record.get("file_id", ""))
        enriched.setdefault("file_no", file_record.get("file_no", ""))
        enriched.setdefault("original_file_name", file_record.get("original_file_name", ""))
    return enriched


def _update_status(case_id: str, final_result: dict) -> None:
    status_path = local_store.get_case_dir(case_id) / "status.json"
    status = local_store.read_json(status_path, {"case_id": case_id})
    status.update(
        {
            "current_stage": "finalized",
            "final_status": "success",
            "checklist_status": "success",
            "manual_review_required": final_result["summary"]["manual_review_required"],
            "review_reasons": _review_reasons_from_final_result(final_result),
            "updated_at": _now(),
        }
    )
    local_store.save_json(status_path, status)


def _review_reasons_from_final_result(final_result: dict) -> list[str]:
    reasons = []
    for item in final_result.get("review_items", []):
        if isinstance(item, dict) and item.get("message"):
            reasons.append(str(item.get("message")))

    sheets = final_result.get("sheets") or {}
    review_issue_sheet = sheets.get(SHEET_REVIEW_ISSUES) or {}
    for row in review_issue_sheet.get("rows", []):
        if not isinstance(row, dict):
            continue
        message = str(row.get("问题描述") or row.get("复核说明") or "").strip()
        if message:
            reasons.append(message)

    return unique_list(reasons)


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _relative_to_project(path: Path | str) -> str:
    resolved = Path(path).resolve()
    try:
        return str(resolved.relative_to(local_store.PROJECT_ROOT.resolve()))
    except ValueError:
        return str(resolved)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _file_issue_llm_client() -> LLMClient | None:
    try:
        return LLMClient()
    except Exception:
        return None
