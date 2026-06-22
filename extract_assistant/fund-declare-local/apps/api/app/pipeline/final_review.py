from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from app.pipeline.final_result_builder import (
    SHEET_CHECKLIST,
    SHEET_COMPLETE,
    SHEET_FINAL,
    SHEET_HOLDINGS,
    SHEET_IDENTITY,
    SHEET_REVIEW_ISSUES,
)
from app.services import local_store


REVIEWED_FINAL_RESULT_NAME = "reviewed_final_result.json"
REVIEW_STATUS_NAME = "review_status.json"
REVIEWED_SCHEMA_VERSION = "reviewed_final_result_v1"


def get_review_payload(case_id: str) -> dict:
    final_result_path = _final_result_path(case_id)
    if not final_result_path.exists():
        raise FileNotFoundError("final_result.json 不存在，请先执行 finalize")

    review_status = get_or_create_review_status(case_id)
    reviewed_path = reviewed_final_result_path(case_id)
    if reviewed_path.exists():
        reviewed = local_store.read_json(reviewed_path, {})
        review_data = reviewed.get("review_data") if isinstance(reviewed, dict) else None
        if isinstance(review_data, dict):
            return {
                "case_id": case_id,
                "review_status": review_status,
                "data": review_data,
                "trace": reviewed.get("trace", {}),
                "file_issues": reviewed.get("file_issues", []),
                "file_issue_summaries": reviewed.get("file_issue_summaries", []),
            }

    final_result = local_store.read_json(final_result_path, {})
    return {
        "case_id": case_id,
        "review_status": review_status,
        "data": build_review_data_from_final_result(case_id, final_result),
        "trace": _trace_from_final_result(final_result, final_result_path, None),
        "file_issues": final_result.get("file_issues", []),
        "file_issue_summaries": final_result.get("file_issue_summaries", []),
    }


def save_review_payload(case_id: str, payload: dict) -> dict:
    final_result_path = _final_result_path(case_id)
    if not final_result_path.exists():
        raise FileNotFoundError("final_result.json 不存在，请先执行 finalize")

    final_result = local_store.read_json(final_result_path, {})
    server_review_data = build_review_data_from_final_result(case_id, final_result)
    input_data = _extract_review_data(payload)
    review_saved_at = _now()

    review_data = {
        SHEET_FINAL: _sanitize_rows(_sheet_payload(input_data, SHEET_FINAL)),
        SHEET_COMPLETE: _sanitize_rows(_sheet_payload(input_data, SHEET_COMPLETE)),
        SHEET_REVIEW_ISSUES: _sanitize_rows(
            _sheet_payload(input_data, SHEET_REVIEW_ISSUES)
        ),
        SHEET_HOLDINGS: _sanitize_rows(_sheet_payload(input_data, SHEET_HOLDINGS)),
        SHEET_IDENTITY: _sanitize_object(_sheet_payload(input_data, SHEET_IDENTITY)),
        SHEET_CHECKLIST: server_review_data.get(SHEET_CHECKLIST, []),
    }

    reviewed = {
        "schema_version": REVIEWED_SCHEMA_VERSION,
        "case_id": case_id,
        "review_data": review_data,
        "trace": _trace_from_final_result(
            final_result,
            final_result_path,
            review_saved_at,
        ),
        "file_issues": final_result.get("file_issues", []),
        "file_issue_summaries": final_result.get("file_issue_summaries", []),
    }
    reviewed_path = reviewed_final_result_path(case_id)
    local_store.save_json(reviewed_path, reviewed)

    review_status = {
        "case_id": case_id,
        "review_saved": True,
        "review_saved_at": review_saved_at,
        "review_source": REVIEWED_FINAL_RESULT_NAME,
        "excel_export_allowed": True,
    }
    local_store.save_json(_review_status_path(case_id), review_status)
    update_case_review_status(
        case_id,
        review_status_value="reviewed",
        excel_status="ready_to_export",
    )

    return {
        "case_id": case_id,
        "review_status": review_status,
        "reviewed_final_result_path": _relative_to_project(reviewed_path),
    }


def reset_review_status(case_id: str, remove_reviewed_result: bool = True) -> dict:
    reviewed_path = reviewed_final_result_path(case_id)
    if remove_reviewed_result and reviewed_path.exists():
        reviewed_path.unlink()

    review_status = _default_unsaved_review_status(case_id)
    local_store.save_json(_review_status_path(case_id), review_status)
    update_case_review_status(
        case_id,
        review_status_value="pending_review",
        excel_status="blocked_pending_review",
    )
    return review_status


def get_or_create_review_status(case_id: str) -> dict:
    status_path = _review_status_path(case_id)
    review_status = local_store.read_json(status_path, None)
    if isinstance(review_status, dict):
        return review_status

    reviewed_path = reviewed_final_result_path(case_id)
    if reviewed_path.exists():
        reviewed = local_store.read_json(reviewed_path, {})
        trace = reviewed.get("trace", {}) if isinstance(reviewed, dict) else {}
        review_status = {
            "case_id": case_id,
            "review_saved": True,
            "review_saved_at": trace.get("review_saved_at"),
            "review_source": REVIEWED_FINAL_RESULT_NAME,
            "excel_export_allowed": True,
        }
    else:
        review_status = _default_unsaved_review_status(case_id)

    local_store.save_json(status_path, review_status)
    return review_status


def update_case_review_status(
    case_id: str,
    review_status_value: str | None = None,
    excel_status: str | None = None,
) -> None:
    status_path = local_store.get_case_dir(case_id) / "status.json"
    status = local_store.read_json(status_path, {"case_id": case_id})
    if review_status_value is not None:
        status["review_status"] = review_status_value
    if excel_status is not None:
        status["excel_status"] = excel_status
    status["updated_at"] = _now()
    local_store.save_json(status_path, status)


def reviewed_final_result_path(case_id: str) -> Path:
    return _final_dir(case_id) / REVIEWED_FINAL_RESULT_NAME


def build_review_data_from_final_result(case_id: str, final_result: dict) -> dict:
    source_by_file_id = {
        item.get("file_id"): item
        for item in final_result.get("source_extract_results", [])
        if isinstance(item, dict) and item.get("file_id")
    }
    final_rows = _sheet_rows(final_result, SHEET_FINAL)
    complete_rows = _sheet_rows(final_result, SHEET_COMPLETE)
    review_issue_rows = _sheet_rows(final_result, SHEET_REVIEW_ISSUES)
    holding_rows = _sheet_rows(final_result, SHEET_HOLDINGS)
    identity_rows = _sheet_rows(final_result, SHEET_IDENTITY)
    checklist_rows = _legal_checklist_rows(_sheet_rows(final_result, SHEET_CHECKLIST))

    return {
        SHEET_FINAL: [
            _event_review_row(row, source_by_file_id, index)
            for index, row in enumerate(final_rows, start=1)
        ],
        SHEET_COMPLETE: [
            _event_review_row(row, source_by_file_id, index)
            for index, row in enumerate(complete_rows, start=1)
        ],
        SHEET_REVIEW_ISSUES: [
            _review_issue_review_row(row, source_by_file_id, index)
            for index, row in enumerate(review_issue_rows, start=1)
        ],
        SHEET_HOLDINGS: [
            _holding_review_row(row, source_by_file_id, index)
            for index, row in enumerate(holding_rows, start=1)
        ],
        SHEET_IDENTITY: _identity_review_object(case_id, identity_rows),
        SHEET_CHECKLIST: [_checklist_review_row(row) for row in checklist_rows],
    }


def _event_review_row(row: dict, source_by_file_id: dict[str, dict], index: int) -> dict:
    review_row = {
        "账户类型": row.get("account_type", ""),
        "证券账号": row.get("securities_account") or "",
        "证券代码": row.get("security_code", ""),
        "证券名称": row.get("security_name", ""),
        "变动类型": _change_type(row),
        "起始日期": row.get("period_start", ""),
        "终止日期": row.get("period_end", ""),
        "日期": row.get("event_date", ""),
        "成交数量": row.get("quantity_raw", ""),
        "成交单价": row.get("price_raw", ""),
        "收付金额": row.get("amount_raw") or row.get("amount") or "",
        "_meta": _row_meta(
            row,
            source_by_file_id,
            row.get("event_id") or f"event_{index}",
        ),
    }
    if row.get("data_source"):
        review_row["数据来源"] = row.get("data_source", "")
    return review_row


def _review_issue_review_row(
    row: dict,
    source_by_file_id: dict[str, dict],
    index: int,
) -> dict:
    return {
        "序号": row.get("序号", str(index)),
        "待复核原因": row.get("待复核原因", ""),
        "问题描述": row.get("问题描述", ""),
        "对应材料": row.get("对应材料", ""),
        "_meta": _row_meta(
            row,
            source_by_file_id,
            row.get("关联记录ID")
            or row.get("复核问题ID")
            or row.get("序号")
            or f"review_issue_{index}",
        ),
    }


def _holding_review_row(
    row: dict,
    source_by_file_id: dict[str, dict],
    index: int,
) -> dict:
    return {
        "账户类型": row.get("account_type", ""),
        "证券账号": row.get("securities_account") or "",
        "证券代码": row.get("security_code", ""),
        "证券名称": row.get("security_name", ""),
        "持有数量": row.get("quantity_raw", ""),
        "市值": row.get("market_value") or row.get("market_value_raw") or "",
        "查询结果所属日期": row.get("holding_date", ""),
        "币种": row.get("currency", ""),
        "_meta": _row_meta(
            row,
            source_by_file_id,
            row.get("holding_id") or f"holding_{index}",
        ),
    }


def _identity_review_object(case_id: str, identity_rows: list[dict]) -> dict:
    source = identity_rows[0] if identity_rows else {}
    return {
        "姓名": source.get("name", ""),
        "电话": source.get("phone", ""),
        "关系类型": source.get("relation_type_label") or source.get("relation_type") or "",
        "身份证姓名": source.get("id_card_name", ""),
        "身份证号码": source.get("id_number", ""),
        "地址": source.get("address", ""),
        "有效期起": source.get("valid_from", ""),
        "有效期止": source.get("valid_to", ""),
        "_meta": {
            "case_id": case_id,
            "original_row": source,
        },
    }


def _checklist_review_row(row: dict) -> dict:
    return {
        "checklist条件": row.get("checklist条件", ""),
        "状态": row.get("状态", ""),
        "说明": row.get("说明", ""),
    }


def _row_meta(row: dict, source_by_file_id: dict[str, dict], source_row_id: str) -> dict:
    existing_meta = row.get("_meta") if isinstance(row.get("_meta"), dict) else {}
    file_id = existing_meta.get("file_id") or row.get("file_id") or ""
    source = source_by_file_id.get(file_id, {})
    return {
        "file_id": file_id,
        "source_type": existing_meta.get("source_type")
        or source.get("source_type")
        or source.get("content_type")
        or "",
        "source_row_id": existing_meta.get("source_row_id") or source_row_id,
        "original_row": existing_meta.get("original_row") or row,
        "source_evidence": existing_meta.get("source_evidence") or row.get("source_evidence") or [],
    }


def _extract_review_data(payload: dict) -> dict:
    if not isinstance(payload, dict):
        return {}

    review_data = payload.get("review_data")
    if isinstance(review_data, dict):
        return review_data
    return payload


def _sheet_payload(review_data: dict, sheet_name: str) -> Any:
    if not isinstance(review_data, dict):
        return None

    if sheet_name in review_data:
        return review_data[sheet_name]

    api_keys = {
        SHEET_FINAL: "final_declaration_rows",
        SHEET_COMPLETE: "full_transaction_rows",
        SHEET_REVIEW_ISSUES: "review_issue_rows",
        SHEET_HOLDINGS: "holding_rows",
        SHEET_IDENTITY: "identity_info",
        SHEET_CHECKLIST: "checklist_rows",
    }
    return review_data.get(api_keys[sheet_name])


def _sanitize_rows(value: Any) -> list[dict]:
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def _sanitize_object(value: Any) -> dict:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                return dict(item)
    return {}


def _sheet_rows(final_result: dict, sheet_name: str) -> list[dict]:
    sheets = final_result.get("sheets") or {}
    sheet = sheets.get(sheet_name) or {}
    rows = sheet.get("rows", [])
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _legal_checklist_rows(rows: list[dict]) -> list[dict]:
    return [
        row
        for row in rows
        if str(row.get("checklist条件") or "").strip() != "文件级问题归纳"
    ]


def _change_type(row: dict) -> str:
    raw = str(row.get("transfer_type_raw") or "").strip()
    if raw:
        return raw
    direction = str(row.get("direction") or "").strip()
    if direction == "buy":
        return "买入"
    if direction == "sell":
        return "卖出"
    event_type = str(row.get("event_type") or "").strip()
    event_type_map = {
        "cash_dividend": "股息/分红",
        "bond_interest": "兑息/利息",
        "bonus_share": "送股",
        "security_registration": "股份登记",
        "ordinary_trade": "普通交易",
        "new_share_subscription": "打新",
        "new_bond_subscription": "打新债",
        "cash_flow": "资金流水",
        "bank_transfer": "银证转账",
        "no_trade_record": "无交易记录",
        "no_holding_record": "无持仓记录",
        "no_account_record": "未开立账户",
        "no_account_info": "无账户信息",
    }
    return event_type_map.get(event_type, event_type)


def _trace_from_final_result(
    final_result: dict,
    final_result_path: Path,
    review_saved_at: str | None,
) -> dict:
    return {
        "source_final_result_path": _relative_to_project(final_result_path),
        "review_saved_at": review_saved_at,
        "review_saved_by": "local_user",
        "source_extract_results": final_result.get("source_extract_results", []),
        "export_audit": final_result.get("export_audit", {}),
        "summary": final_result.get("summary", {}),
        "file_issues": final_result.get("file_issues", []),
        "file_issue_summaries": final_result.get("file_issue_summaries", []),
    }


def _default_unsaved_review_status(case_id: str) -> dict:
    return {
        "case_id": case_id,
        "review_saved": False,
        "review_saved_at": None,
        "review_source": "final_result.json",
        "excel_export_allowed": False,
    }


def _final_dir(case_id: str) -> Path:
    return local_store.ensure_dir(local_store.get_case_dir(case_id) / "final")


def _final_result_path(case_id: str) -> Path:
    return _final_dir(case_id) / "final_result.json"


def _review_status_path(case_id: str) -> Path:
    return _final_dir(case_id) / REVIEW_STATUS_NAME


def _relative_to_project(path: Path | str) -> str:
    return str(Path(path).resolve().relative_to(local_store.PROJECT_ROOT.resolve()))


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
