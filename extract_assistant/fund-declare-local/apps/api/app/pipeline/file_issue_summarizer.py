from __future__ import annotations

import json
from typing import Any

from app.services import local_store
from app.services.llm_client import LLMClient


PROMPT_PATH = local_store.PROJECT_ROOT / "prompts" / "file_issue_summary_prompt.md"

ISSUE_TYPE_LABELS = {
    "content_type_unknown": "文件类型未知",
    "ocr_failed": "OCR 失败",
    "ocr_low_confidence": "OCR 置信度低",
    "file_parse_failed": "文件无法解析",
    "extract_failed": "抽取失败",
    "extract_partial_failed": "部分抽取失败",
    "llm_request_failed": "LLM 请求失败",
    "json_parse_failed": "LLM 输出 JSON 解析失败",
    "llm_output_truncated": "LLM 输出被截断",
    "schema_invalid": "schema 不合法",
    "missing_required_fields": "缺少必填字段",
    "missing_date": "缺少日期",
    "missing_securities_account": "缺少证券账号",
    "missing_account_type": "缺少账户类型",
    "missing_security_code": "缺少证券代码",
    "missing_security_name": "缺少证券名称",
    "many_pending_review_items": "待复核记录较多",
    "pending_review_event": "存在待复核事件",
    "pending_review_holding": "存在待复核持仓",
    "unknown_event_type": "事件类型无法判断",
    "conflict_between_sources": "来源字段冲突",
    "file_review_reason": "文件处理提示",
    "no_trade_query_proof_incomplete": "无交易证明归属要素待确认",
}


def summarize_file_issues(
    file_issues: list[dict],
    problem_events: list[dict] | None,
    files_index: dict,
    *,
    llm_client: LLMClient | None = None,
) -> dict:
    if not file_issues:
        return _fallback_summary(file_issues)

    display_file_issues = _display_file_issues(file_issues)
    if not _has_actionable_file_issues(display_file_issues):
        return _fallback_summary(display_file_issues)
    if llm_client is not None:
        llm_result = _try_llm_summary(
            display_file_issues,
            problem_events or [],
            files_index,
            llm_client,
        )
        if llm_result is not None:
            return llm_result

    return _fallback_summary(display_file_issues)


def _has_actionable_file_issues(file_issues: list[dict]) -> bool:
    return any(
        bool(issue.get("issue_types"))
        for issue in file_issues
        if isinstance(issue, dict)
    )


def _try_llm_summary(
    file_issues: list[dict],
    problem_events: list[dict],
    files_index: dict,
    llm_client: LLMClient,
) -> dict | None:
    try:
        prompt = _load_prompt()
        payload = {
            "file_issues": file_issues,
            "problem_events": problem_events,
            "files_index_summary": _files_index_summary(files_index),
        }
        result = llm_client.extract_json(
            prompt,
            json.dumps(payload, ensure_ascii=False),
        )
    except Exception:
        return None

    if not isinstance(result, dict):
        return None
    checklist_rows = result.get("checklist_rows")
    summaries = result.get("file_issue_summaries")
    if not isinstance(checklist_rows, list) or not isinstance(summaries, list):
        return None
    if not all(isinstance(row, dict) for row in checklist_rows):
        return None
    if not all(isinstance(row, dict) for row in summaries):
        return None

    normalized_summaries = _normalize_summaries(summaries, file_issues)
    if not normalized_summaries and file_issues:
        return None

    return {
        "checklist_rows": _normalize_checklist_rows(checklist_rows),
        "file_issue_summaries": normalized_summaries,
    }


def _fallback_summary(file_issues: list[dict]) -> dict:
    if not file_issues:
        return {
            "checklist_rows": [
                {
                    "checklist条件": "文件级问题归纳",
                    "状态": "通过",
                    "说明": "未发现文件级 OCR、解析、抽取或关键字段缺失问题。",
                }
            ],
            "file_issue_summaries": [],
        }

    summaries = [_fallback_file_summary(issue) for issue in file_issues]
    actionable_issues = [issue for issue in file_issues if issue.get("issue_types")]
    error_count = sum(1 for issue in actionable_issues if issue.get("severity") == "error")
    warning_count = len(actionable_issues) - error_count
    status = "异常" if error_count else ("需人工复核" if warning_count else "通过")
    parts = []
    if error_count:
        parts.append(f"{error_count} 个文件存在异常")
    if warning_count:
        parts.append(f"{warning_count} 个文件需人工复核")
    issue_text = "；".join(parts) or "未发现文件级 OCR、解析、抽取或关键字段缺失问题"
    file_names = "、".join(
        issue.get("file_name") or issue.get("file_id") or "未知文件"
        for issue in file_issues[:3]
    )
    suffix = "等" if len(file_issues) > 3 else ""

    return {
        "checklist_rows": [
            {
                "checklist条件": "文件级问题归纳",
                "状态": status,
                "说明": f"{issue_text}：{file_names}{suffix}。请查看 file_issue_summaries 或待复核问题。",
            }
        ],
        "file_issue_summaries": summaries,
    }


def _fallback_file_summary(issue: dict) -> dict:
    labels = [_issue_label(item) for item in issue.get("issue_types", [])]
    status = _status_from_severity(str(issue.get("severity") or "warning"))
    issue_text = "、".join(labels) or "存在文件级问题"
    evidence = "；".join(str(item) for item in issue.get("evidence", [])[:3] if item)
    observations = "；".join(
        str(item).rstrip("。") for item in issue.get("multimodal_observations", [])[:3] if item
    )
    file_name = issue.get("file_name") or issue.get("file_id") or "未知文件"
    if issue.get("issue_types"):
        summary = f"{file_name} 存在{issue_text}。"
    else:
        status = "通过"
        summary = f"{file_name} 未发现文件级 OCR、解析、抽取或关键字段缺失问题。"
    if evidence:
        summary += f" 依据：{evidence}。"
    if observations:
        summary += f" 多模态观察：{observations}。"

    return {
        "file_id": issue.get("file_id", ""),
        "file_no": issue.get("file_no", ""),
        "file_name": issue.get("file_name", ""),
        "status": status,
        "summary": summary,
        "issue_types": list(issue.get("issue_types", [])),
        "suggested_action": issue.get("suggested_action")
        or ("可结合多模态观察核对材料版面。" if observations else "请核对该文件的处理和抽取结果。"),
    }


def _display_file_issues(file_issues: list[dict]) -> list[dict]:
    display_issues = []
    for issue in file_issues:
        if not isinstance(issue, dict):
            continue
        next_issue = dict(issue)
        issue_types = [
            str(issue_type)
            for issue_type in next_issue.get("issue_types", [])
            if issue_type not in (None, "")
        ]
        if "no_trade_query_proof_incomplete" in issue_types:
            issue_types = [
                issue_type
                for issue_type in issue_types
                if issue_type not in {"extract_failed", "manual_review_required", "file_review_reason"}
            ]
        next_issue["issue_types"] = issue_types
        display_issues.append(next_issue)
    return display_issues


def _status_from_severity(severity: str) -> str:
    if severity == "error":
        return "异常"
    if severity == "normal":
        return "通过"
    return "需人工复核"


def _issue_label(issue_type: str) -> str:
    return ISSUE_TYPE_LABELS.get(issue_type, issue_type)


def _normalize_checklist_rows(rows: list[dict]) -> list[dict]:
    normalized = []
    for row in rows:
        normalized.append(
            {
                "checklist条件": str(row.get("checklist条件") or "文件级问题归纳"),
                "状态": _normalize_status(row.get("状态")),
                "说明": str(row.get("说明") or ""),
            }
        )
    return normalized or _fallback_summary([])["checklist_rows"]


def _normalize_summaries(rows: list[dict], file_issues: list[dict]) -> list[dict]:
    allowed_issue_types_by_file_id = {
        str(issue.get("file_id") or ""): {
            str(issue_type)
            for issue_type in issue.get("issue_types", [])
            if issue_type not in (None, "")
        }
        for issue in file_issues
        if isinstance(issue, dict) and issue.get("file_id")
    }
    normalized = []
    for row in rows:
        file_id = str(row.get("file_id") or "")
        if file_id not in allowed_issue_types_by_file_id:
            continue
        raw_issue_types = row.get("issue_types", [])
        issue_types = []
        if isinstance(raw_issue_types, list):
            issue_types = [
                str(item)
                for item in raw_issue_types
                if item not in (None, "")
                and str(item) in allowed_issue_types_by_file_id[file_id]
            ]
        normalized.append(
            {
                "file_id": file_id,
                "file_no": str(row.get("file_no") or ""),
                "file_name": str(row.get("file_name") or ""),
                "status": _normalize_status(row.get("status")),
                "summary": str(row.get("summary") or ""),
                "issue_types": issue_types,
                "suggested_action": str(row.get("suggested_action") or ""),
            }
        )
    return normalized


def _normalize_status(status: Any) -> str:
    text = str(status or "").strip()
    if text in {"通过", "需人工复核", "异常"}:
        return text
    return "需人工复核"


def _files_index_summary(files_index: dict) -> list[dict]:
    summary = []
    for item in files_index.get("files", []):
        if not isinstance(item, dict):
            continue
        summary.append(
            {
                "file_id": item.get("file_id", ""),
                "file_no": item.get("file_no", ""),
                "file_name": item.get("original_file_name", ""),
                "module": item.get("module", ""),
                "content_type": item.get("content_type", ""),
                "route_type": item.get("route_type", ""),
                "process_status": item.get("process_status", ""),
                "ocr_status": item.get("ocr_status", ""),
                "extract_status": item.get("extract_status", ""),
            }
        )
    return summary


def _load_prompt() -> str:
    if PROMPT_PATH.exists():
        return PROMPT_PATH.read_text(encoding="utf-8")
    return "你是文件级审核问题归纳助手。只能输出 JSON。"
