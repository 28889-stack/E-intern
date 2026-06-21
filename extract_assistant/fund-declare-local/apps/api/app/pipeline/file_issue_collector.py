from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services import local_store


OCR_CONFIDENCE_THRESHOLD = 0.85
MANY_PENDING_THRESHOLD = 5

FAILURE_STATUSES = {
    "failed",
    "error",
    "ocr_failed",
    "parse_failed",
    "partial_failed",
    "llm_request_failed",
    "json_parse_failed",
}

FIELD_ISSUE_TYPES = {
    "event_date": "missing_date",
    "holding_date": "missing_date",
    "period_start": "missing_date",
    "period_end": "missing_date",
    "securities_account": "missing_securities_account",
    "account_type": "missing_account_type",
    "security_code": "missing_security_code",
    "security_name": "missing_security_name",
}


def collect_file_issues(
    case_id: str,
    files_index: dict,
    *,
    review_issues: list[dict] | None = None,
    review_issue_rows: list[dict] | None = None,
    pending_review_events: list[dict] | None = None,
    pending_review_holdings: list[dict] | None = None,
) -> list[dict]:
    states = {
        str(file_record.get("file_id") or ""): _base_state(file_record)
        for file_record in files_index.get("files", [])
        if isinstance(file_record, dict) and file_record.get("file_id")
    }

    for file_record in files_index.get("files", []):
        if not isinstance(file_record, dict):
            continue
        file_id = str(file_record.get("file_id") or "")
        if not file_id:
            continue
        state = states[file_id]
        _collect_from_file_record(state, file_record)
        _collect_from_processed_files(case_id, state, file_record)

    for issue in review_issues or []:
        _collect_from_review_issue(states, issue)

    row_by_problem_id = {
        _problem_id(row): row
        for row in review_issue_rows or []
        if isinstance(row, dict) and _problem_id(row)
    }
    for state in states.values():
        for problem_id in list(state["related_problem_ids"]):
            row = row_by_problem_id.get(problem_id)
            if row:
                description = str(row.get("问题描述") or "").strip()
                if description:
                    _add_evidence(state, f"待复核问题 {problem_id}：{description}")

    for row in pending_review_events or []:
        _collect_pending_row(states, row, "pending_review_event")
    for row in pending_review_holdings or []:
        _collect_pending_row(states, row, "pending_review_holding")

    file_issues = []
    for state in states.values():
        pending_count = state.pop("_pending_count", 0)
        if pending_count >= MANY_PENDING_THRESHOLD:
            _add_issue(
                state,
                "many_pending_review_items",
                "warning",
                f"该文件产生 {pending_count} 条待复核记录，数量较多。",
                "请优先核对该文件的关键字段和抽取结果。",
            )
        if state["issue_types"]:
            state["issue_types"] = _unique(state["issue_types"])
            state["evidence"] = _unique(state["evidence"])
            state["related_problem_ids"] = _unique(state["related_problem_ids"])
            state["suggested_action"] = _suggested_action(state)
            file_issues.append(state)

    return file_issues


def _base_state(file_record: dict) -> dict:
    return {
        "file_id": str(file_record.get("file_id") or ""),
        "file_no": str(file_record.get("file_no") or ""),
        "file_name": str(file_record.get("original_file_name") or ""),
        "module": str(file_record.get("module") or ""),
        "content_type": str(file_record.get("content_type") or ""),
        "route_type": str(file_record.get("route_type") or ""),
        "issue_types": [],
        "severity": "normal",
        "evidence": [],
        "related_problem_ids": [],
        "suggested_action": "",
        "_pending_count": 0,
    }


def _collect_from_file_record(state: dict, file_record: dict) -> None:
    if str(file_record.get("content_type") or "") == "unknown":
        _add_issue(
            state,
            "content_type_unknown",
            "warning",
            "文件内容类型为 unknown，无法确定材料来源。",
            "请确认该文件属于身份材料、广发材料或中国结算材料。",
        )

    for field, issue_type in (
        ("process_status", "file_parse_failed"),
        ("ocr_status", "ocr_failed"),
        ("extract_status", "extract_failed"),
    ):
        status = str(file_record.get(field) or "").strip()
        _collect_status_issue(state, field, status, issue_type)

    for reason in _as_list(file_record.get("review_reasons")):
        if reason:
            _add_issue(
                state,
                "file_review_reason",
                "warning",
                str(reason),
                "请回到原始材料和中间结果核对。",
            )


def _collect_from_processed_files(case_id: str, state: dict, file_record: dict) -> None:
    output_dir = _output_dir(case_id, file_record)
    process_result = local_store.read_json(output_dir / "process_result.json", {})
    if isinstance(process_result, dict):
        for field, issue_type in (
            ("process_status", "file_parse_failed"),
            ("ocr_status", "ocr_failed"),
            ("extract_status", "extract_failed"),
            ("table_extract_status", "file_parse_failed"),
        ):
            _collect_status_issue(
                state,
                field,
                str(process_result.get(field) or "").strip(),
                issue_type,
            )
        for reason in _as_list(process_result.get("review_reasons")):
            if reason:
                _add_issue(state, "file_review_reason", "warning", str(reason), "")

    ocr_result = local_store.read_json(output_dir / "ocr_result.json", {})
    if isinstance(ocr_result, dict):
        _collect_ocr_confidence(state, ocr_result)
        _collect_status_issue(
            state,
            "ocr_status",
            str(ocr_result.get("ocr_status") or "").strip(),
            "ocr_failed",
        )

    extract_result = local_store.read_json(output_dir / "extract_result.json", {})
    if isinstance(extract_result, dict):
        _collect_extract_issues(state, extract_result)

    extract_batches = local_store.read_json(output_dir / "extract_batches.json", {})
    if isinstance(extract_batches, dict):
        _collect_extract_batch_issues(state, extract_batches)


def _collect_from_review_issue(states: dict[str, dict], issue: dict) -> None:
    file_ids = _as_list(issue.get("related_file_ids"))
    if not file_ids:
        snapshot = issue.get("record_snapshot")
        if isinstance(snapshot, dict):
            file_ids = _as_list(snapshot.get("file_id"))

    for file_id in file_ids:
        state = states.get(str(file_id))
        if not state:
            continue
        problem_id = str(issue.get("review_issue_id") or "")
        if problem_id:
            state["related_problem_ids"].append(problem_id)
        state["_pending_count"] += 1

        issue_types = _as_list(issue.get("issue_types"))
        for issue_type in issue_types:
            _add_issue(
                state,
                _file_issue_type_from_review_type(str(issue_type)),
                "warning",
                _review_issue_evidence(issue),
                "请核对该文件的关键字段。",
            )

        for field in _as_list(issue.get("missing_fields")):
            mapped = FIELD_ISSUE_TYPES.get(str(field))
            if mapped:
                _add_issue(
                    state,
                    mapped,
                    "warning",
                    f"待复核记录缺失关键字段：{_field_label(str(field))}。",
                    "请补充或确认该关键字段。",
                )


def _collect_pending_row(states: dict[str, dict], row: dict, issue_type: str) -> None:
    file_id = str(row.get("file_id") or "")
    state = states.get(file_id)
    if not state:
        return
    state["_pending_count"] += 1
    _add_issue(
        state,
        issue_type,
        "warning",
        f"文件中存在待复核记录：{row.get('event_id') or row.get('holding_id') or '未命名记录'}。",
        "请核对待复核记录。",
    )


def _collect_status_issue(
    state: dict,
    field: str,
    status: str,
    default_issue_type: str,
) -> None:
    if not status or status in {"success", "parsed", "ocr_done", "not_required", "skipped"}:
        return
    if status not in FAILURE_STATUSES:
        return

    issue_type = {
        "ocr_status": "ocr_failed",
        "process_status": "file_parse_failed",
        "extract_status": _extract_issue_type(status),
        "table_extract_status": "file_parse_failed",
    }.get(field, default_issue_type)
    severity = "error" if status in {"failed", "ocr_failed", "llm_request_failed", "json_parse_failed"} else "warning"
    _add_issue(
        state,
        issue_type,
        severity,
        f"{field}={status}",
        "请检查该文件的处理结果。",
    )


def _collect_ocr_confidence(state: dict, ocr_result: dict) -> None:
    confidences = []
    if isinstance(ocr_result.get("confidence_avg"), (int, float)):
        confidences.append(float(ocr_result["confidence_avg"]))
    for page in _as_list(ocr_result.get("page_results") or ocr_result.get("pages")):
        if isinstance(page, dict) and isinstance(page.get("confidence_avg"), (int, float)):
            confidences.append(float(page["confidence_avg"]))

    if not confidences:
        return
    confidence_avg = sum(confidences) / len(confidences)
    if confidence_avg < OCR_CONFIDENCE_THRESHOLD:
        _add_issue(
            state,
            "ocr_low_confidence",
            "warning",
            f"OCR 平均置信度 {confidence_avg:.2f} 低于 {OCR_CONFIDENCE_THRESHOLD:.2f}。",
            "请核对原文件和 OCR 结果。",
        )


def _collect_extract_issues(state: dict, extract_result: dict) -> None:
    status = str(extract_result.get("extract_status") or "").strip()
    _collect_status_issue(state, "extract_status", status, _extract_issue_type(status))

    for reason in _as_list(extract_result.get("review_reasons")):
        text = str(reason)
        issue_type = _issue_type_from_text(text)
        _add_issue(state, issue_type, "warning", text, "请核对抽取结果。")

    metadata = extract_result.get("llm_response_metadata")
    if _has_finish_reason_length(metadata):
        _add_issue(
            state,
            "llm_output_truncated",
            "error",
            "LLM 输出被截断：finish_reason=length。",
            "请重新抽取或减少单次输入后再核对。",
        )


def _collect_extract_batch_issues(state: dict, extract_batches: dict) -> None:
    for index, batch in enumerate(_as_list(extract_batches.get("batches")), start=1):
        if not isinstance(batch, dict):
            continue
        status = str(batch.get("extract_status") or "").strip()
        if status:
            _collect_status_issue(
                state,
                "extract_status",
                status,
                _extract_issue_type(status),
            )
        for reason in _as_list(batch.get("review_reasons")):
            text = str(reason)
            if text:
                _add_issue(
                    state,
                    _issue_type_from_text(text),
                    "warning",
                    f"第 {index} 批抽取提示：{text}",
                    "请核对该批次抽取结果。",
                )
        metadata = batch.get("llm_response_metadata")
        if _has_finish_reason_length(metadata):
            _add_issue(
                state,
                "llm_output_truncated",
                "error",
                f"第 {index} 批 LLM 输出被截断：finish_reason=length。",
                "请重新抽取或减少单次输入后再核对。",
            )


def _add_issue(
    state: dict,
    issue_type: str,
    severity: str,
    evidence: str,
    suggested_action: str,
) -> None:
    if issue_type:
        state["issue_types"].append(issue_type)
    if evidence:
        _add_evidence(state, evidence)
    if suggested_action:
        state["suggested_action"] = suggested_action
    state["severity"] = _max_severity(state.get("severity", "normal"), severity)


def _add_evidence(state: dict, evidence: str) -> None:
    if evidence:
        state["evidence"].append(evidence)


def _output_dir(case_id: str, file_record: dict) -> Path:
    output_dir = file_record.get("output_dir")
    if output_dir:
        path = Path(output_dir)
        return path if path.is_absolute() else local_store.PROJECT_ROOT / path
    module = file_record.get("module") or "account_info"
    return local_store.get_module_processed_dir(case_id, module) / str(file_record.get("file_id") or "")


def _extract_issue_type(status: str) -> str:
    if status == "llm_request_failed":
        return "llm_request_failed"
    if status == "json_parse_failed":
        return "json_parse_failed"
    if status == "partial_failed":
        return "extract_partial_failed"
    return "extract_failed"


def _issue_type_from_text(text: str) -> str:
    lowered = text.lower()
    if "finish_reason=length" in lowered or "截断" in text:
        return "llm_output_truncated"
    if "json" in lowered or "合法 JSON" in text:
        return "json_parse_failed"
    if "schema" in lowered or "结构" in text:
        return "schema_invalid"
    if "ocr" in lowered or "文字识别" in text:
        return "ocr_failed"
    return "extract_failed"


def _file_issue_type_from_review_type(issue_type: str) -> str:
    return {
        "missing_required_fields": "missing_required_fields",
        "securities_account_missing": "missing_securities_account",
        "account_type_missing": "missing_account_type",
        "unknown_event_type": "unknown_event_type",
        "conflict_between_sources": "conflict_between_sources",
        "empty_record_account_missing": "missing_securities_account",
        "empty_record_period_missing": "missing_date",
    }.get(issue_type, issue_type or "manual_review_required")


def _review_issue_evidence(issue: dict) -> str:
    message = str(issue.get("message") or "").strip()
    record_id = str(issue.get("related_record_id") or "").strip()
    if record_id and message:
        return f"待复核记录 {record_id}：{message}"
    return message or "存在待复核记录。"


def _has_finish_reason_length(metadata: Any) -> bool:
    if not isinstance(metadata, dict):
        return False
    if metadata.get("finish_reason") == "length":
        return True
    for batch in _as_list(metadata.get("batches")):
        if isinstance(batch, dict) and batch.get("finish_reason") == "length":
            return True
    return False


def _field_label(field: str) -> str:
    return {
        "event_date": "日期",
        "holding_date": "日期",
        "period_start": "起始日期",
        "period_end": "终止日期",
        "securities_account": "证券账号",
        "account_type": "账户类型",
        "security_code": "证券代码",
        "security_name": "证券名称",
    }.get(field, field)


def _suggested_action(state: dict) -> str:
    if state.get("suggested_action"):
        return state["suggested_action"]
    if "ocr_failed" in state["issue_types"] or "ocr_low_confidence" in state["issue_types"]:
        return "请核对原文件清晰度和 OCR 识别结果。"
    if any(issue_type.startswith("missing_") for issue_type in state["issue_types"]):
        return "请核对原文件并补充缺失关键字段。"
    if "content_type_unknown" in state["issue_types"]:
        return "请确认文件类型后重新处理。"
    return "请核对该文件的处理和抽取结果。"


def _max_severity(current: str, new: str) -> str:
    order = {"normal": 0, "warning": 1, "error": 2}
    return new if order.get(new, 0) > order.get(current, 0) else current


def _problem_id(row: dict) -> str:
    return str(row.get("序号") or row.get("复核问题ID") or "")


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _unique(values: list[Any]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value in (None, ""):
            continue
        text = str(value)
        if text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result
