from __future__ import annotations

from app.pipeline.normalizers.common import (
    as_list,
    build_event_row,
    build_holding_row,
    build_normalized_result,
    empty_record_event_from_semantics,
    is_pure_cash_flow_event,
    review_item,
)
from app.services.local_store import read_json


def normalize_chinaclear(case_id: str, extract_result: dict, file_record: dict) -> dict:
    document_info = extract_result.get("document_info") or {}
    source_text = _source_text_from_extract_result(extract_result)
    full_rows = []
    review_items = []

    trade_group = extract_result.get("trade_group") or {}
    trade_columns = trade_group.get("trade_columns") or []
    for trade_index, trade_values in enumerate(as_list(trade_group.get("trades"))):
        if not isinstance(trade_values, list):
            continue

        trade = {
            str(column): trade_values[index] if index < len(trade_values) else ""
            for index, column in enumerate(trade_columns)
        }
        event = {
            "event_id": trade.get("trade_id") or f"trade_{trade_index + 1}",
            "event_type": "ordinary_trade",
            "market": trade.get("market", ""),
            "event_date": trade.get("trade_date", ""),
            "security_code": trade.get("security_code", ""),
            "security_name": trade.get("security_name", ""),
            "direction": trade.get("direction", ""),
            "quantity_raw": trade.get("quantity_raw", ""),
            "price_raw": trade.get("price_raw", ""),
            "balance_after_raw": trade.get("balance_after_raw", ""),
            "transfer_type_raw": trade.get("transfer_type_raw", ""),
            "source_pages": [trade.get("source_page", "")],
            "row_nos": [trade.get("row_no", "")],
            "review_reason": "",
        }
        if is_pure_cash_flow_event(event):
            continue
        full_rows.append(
            build_event_row(
                case_id,
                file_record,
                document_info,
                event,
            )
        )

    for other_event in as_list(extract_result.get("other_events")):
        if isinstance(other_event, dict):
            normalized_event = _normalize_other_event(other_event, document_info, source_text)
            if is_pure_cash_flow_event(normalized_event):
                continue
            full_rows.append(
                build_event_row(
                    case_id,
                    file_record,
                    document_info,
                    normalized_event,
                )
            )

    for legacy_event in as_list(extract_result.get("events")):
        if isinstance(legacy_event, dict) and not is_pure_cash_flow_event(legacy_event):
            full_rows.append(
                build_event_row(case_id, file_record, document_info, legacy_event)
            )

    for index, proof in enumerate(as_list(extract_result.get("negative_proofs"))):
        if isinstance(proof, dict):
            event = _negative_proof_event(proof, index)
            if event:
                full_rows.append(build_event_row(case_id, file_record, document_info, event))

    holding_rows = [
        build_holding_row(
            case_id,
            file_record,
            document_info,
            _normalize_holding_record(holding, index),
        )
        for index, holding in enumerate(as_list(extract_result.get("holding_records")))
        if isinstance(holding, dict)
    ]
    holding_rows = [
        build_holding_row(case_id, file_record, document_info, holding)
        for holding in as_list(extract_result.get("holdings"))
        if isinstance(holding, dict)
    ] + holding_rows

    for item in as_list(extract_result.get("document_level_review_items")):
        if isinstance(item, dict):
            review_items.append(_document_review_item(item, file_record))

    if not full_rows and not holding_rows:
        empty_record_event = empty_record_event_from_semantics(
            case_id,
            file_record,
            document_info,
            extract_result,
        )
        if empty_record_event:
            full_rows.append(empty_record_event)

    return build_normalized_result(full_rows, holding_rows, review_items)


def _normalize_holding_record(holding: dict, index: int) -> dict:
    source_evidence = holding.get("source_evidence") or {}
    if not isinstance(source_evidence, dict):
        source_evidence = {}
    candidates = holding.get("final_field_candidates") or {}
    if not isinstance(candidates, dict):
        candidates = {}

    def field(chinese_key: str, *holding_keys: str) -> str:
        return _first_text(
            candidates.get(chinese_key),
            holding.get(chinese_key),
            *(holding.get(key) for key in holding_keys),
        )

    return {
        "holding_id": holding.get("holding_id") or f"chinaclear_holding_{index + 1}",
        "account_type": field("账户类型", "account_type"),
        "securities_account": field("证券账号", "securities_account", "fund_account"),
        "holding_date": _first_text(
            candidates.get("查询结果所属日期"),
            holding.get("查询结果所属日期"),
            holding.get("holding_date"),
            holding.get("date"),
        ),
        "security_code": field("证券代码", "security_code"),
        "security_name": field("证券名称", "security_name"),
        "quantity_raw": field("持有数量", "quantity_raw", "quantity"),
        "market_value": field("市值", "market_value"),
        "currency": field("币种", "currency"),
        "source_page": source_evidence.get("page") or holding.get("source_page") or "",
        "row_no": source_evidence.get("row_no") or holding.get("row_no") or "",
        "review_reason": _join_reasons(holding.get("review_reasons"), holding.get("review_reason")),
    }


def _document_review_item(item: dict, file_record: dict) -> dict:
    normalized = review_item(
        item.get("severity") or "warning",
        item.get("item_type") or "extract_result",
        file_record.get("file_id", ""),
        item.get("event_id") or item.get("record_id") or "",
        item.get("field") or "",
        item.get("message") or "材料存在需要人工复核的问题",
    )
    normalized["file_no"] = file_record.get("file_no", "")
    normalized["original_file_name"] = file_record.get("original_file_name", "")
    return normalized


def _normalize_other_event(event: dict, document_info: dict, source_text: str) -> dict:
    if not _is_no_account_info_event(event, document_info, source_text):
        return event

    normalized = dict(event)
    normalized.update(
        {
            "event_type": "no_account_info",
            "event_category": "negative_proof",
            "proof_type": "无账户信息",
            "event_date": (
                event.get("event_date")
                or event.get("period_end")
                or document_info.get("period_end")
                or ""
            ),
            "person_name": (
                event.get("person_name")
                or event.get("holder_name")
                or document_info.get("holder_name")
                or _person_name_from_text(source_text)
            ),
            "security_code": "",
            "security_name": "",
            "quantity_raw": "",
            "price_raw": "",
            "amount_raw": "",
            "balance_after_raw": "",
            "transfer_type_raw": "无账户信息",
            "raw_text": event.get("raw_text") or _source_excerpt(source_text),
        }
    )
    if "source_page" not in normalized:
        normalized["source_page"] = _first_value(event.get("source_pages"))
    if "row_no" not in normalized:
        normalized["row_no"] = _first_value(event.get("row_nos"))
    return normalized


def _is_no_account_info_event(event: dict, document_info: dict, source_text: str) -> bool:
    event_type = str(event.get("event_type") or "").strip()
    event_text = "\n".join(
        str(value)
        for value in (
            event.get("event_type"),
            event.get("transfer_type_raw"),
            event.get("event_type_raw"),
            event.get("review_reason"),
        )
        if value not in (None, "")
    )
    if _has_no_account_signal(event_text):
        return True

    if event_type not in {"", "unknown_event", "no_holding_record", "no_trade_record"}:
        return False

    document_text = "\n".join(
        str(value)
        for value in (
            document_info.get("document_title"),
            source_text,
        )
        if value not in (None, "")
    )
    return _has_no_account_signal(document_text)


def _has_no_account_signal(text: str) -> bool:
    return any(
        keyword in str(text or "")
        for keyword in (
            "无账户信息",
            "未查询到证券账户",
            "未曾开立证券账户",
            "未开立证券账户",
            "未开户证明",
            "未开户",
            "无证券账户",
            "无股东账户",
        )
    )


def _source_text_from_extract_result(extract_result: dict) -> str:
    text_parts = []
    for key in ("input_text", "source_text", "raw_text"):
        value = extract_result.get(key)
        if isinstance(value, str) and value.strip():
            text_parts.append(value)

    input_sources = extract_result.get("input_sources")
    if isinstance(input_sources, dict):
        for key in ("raw_text_path", "ocr_result_path"):
            path = input_sources.get(key)
            if path:
                text_parts.append(_text_from_json_path(path))

    return "\n".join(part for part in text_parts if part)


def _text_from_json_path(path: str) -> str:
    payload = read_json(path, {})
    text_parts = []
    if isinstance(payload, dict):
        for page in as_list(payload.get("pages") or payload.get("page_results")):
            if isinstance(page, dict):
                text_parts.append(str(page.get("text") or ""))
    return "\n".join(part for part in text_parts if part)


def _source_excerpt(source_text: str) -> str:
    lines = [line.strip() for line in str(source_text or "").splitlines() if line.strip()]
    if not lines:
        return ""
    for line in lines:
        if _has_no_account_signal(line):
            return line
    return "\n".join(lines[:3])


def _person_name_from_text(text: str) -> str:
    import re

    for pattern in (
        r"申请人\s*([\u4e00-\u9fff]{1,8})",
        r"(?:姓名|客户姓名|投资者姓名)[:：\s]*([\u4e00-\u9fff]{2,8})",
        r"(?:截至|截止).*?([\u4e00-\u9fff]{1,8}).*?(?:未曾开立|未开立|无账户信息)",
    ):
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return ""


def _first_value(value) -> str:
    values = as_list(value)
    if not values:
        return ""
    first = values[0]
    return "" if first is None else str(first)


def _negative_proof_event(proof: dict, index: int) -> dict | None:
    proof_type = str(
        proof.get("proof_type")
        or proof.get("inferred_event_type")
        or proof.get("raw_business_type")
        or ""
    )
    if any(
        keyword in proof_type
        for keyword in (
            "无账户信息",
            "未查询到证券账户",
            "未曾开立证券账户",
            "未开立证券账户",
            "未开户证明",
            "未开户",
            "无证券账户",
            "无股东账户",
        )
    ):
        event_type = "no_account_info"
        raw_type = "无账户信息"
    elif any(keyword in proof_type for keyword in ("no_holding_record", "无持仓", "未持仓", "没有持仓")):
        event_type = "no_holding_record"
        raw_type = "无持仓记录"
    elif any(keyword in proof_type for keyword in ("no_trade_record", "无交易", "未交易", "没有交易")):
        event_type = "no_trade_record"
        raw_type = "无交易记录"
    else:
        return None

    source_evidence = proof.get("source_evidence") or {}
    if not isinstance(source_evidence, dict):
        source_evidence = {}
    if event_type != "no_account_info":
        return {
            "event_id": proof.get("event_id") or f"chinaclear_negative_proof_{index + 1}",
            "event_type": event_type,
            "event_category": "negative_proof",
            "event_date": (
                proof.get("event_date")
                or proof.get("query_date")
                or proof.get("as_of_date")
                or proof.get("period_end")
                or ""
            ),
            "period_start": proof.get("period_start") or "",
            "period_end": proof.get("period_end") or "",
            "account_type": proof.get("account_type") or proof.get("账户类型") or "",
            "securities_account": proof.get("securities_account") or proof.get("证券账号") or "",
            "security_code": "0",
            "security_name": "0",
            "quantity_raw": "0",
            "price_raw": "0",
            "amount_raw": "0",
            "balance_after_raw": "0",
            "transfer_type_raw": raw_type,
            "source_page": source_evidence.get("page") or proof.get("source_page") or "",
            "row_no": source_evidence.get("row_no") or proof.get("row_no") or "",
            "raw_text": source_evidence.get("raw_text")
            or proof.get("description")
            or proof.get("raw_summary")
            or "",
            "review_reason": _join_reasons(
                proof.get("review_reasons"),
                proof.get("review_reason"),
            ),
        }

    return {
        "event_id": proof.get("event_id") or f"chinaclear_no_account_info_{index + 1}",
        "event_type": "no_account_info",
        "event_category": "negative_proof",
        "proof_type": "无账户信息",
        "event_date": (
            proof.get("as_of_date")
            or proof.get("query_date")
            or proof.get("event_date")
            or proof.get("period_end")
            or ""
        ),
        "person_name": proof.get("person_name") or proof.get("holder_name") or "",
        "security_code": "",
        "security_name": "",
        "quantity_raw": "",
        "price_raw": "",
        "amount_raw": "",
        "balance_after_raw": "",
        "transfer_type_raw": "无账户信息",
        "source_page": source_evidence.get("page") or proof.get("source_page") or "",
        "row_no": source_evidence.get("row_no") or proof.get("row_no") or "",
        "raw_text": source_evidence.get("raw_text")
        or proof.get("description")
        or proof.get("raw_summary")
        or "",
        "review_reason": _join_reasons(
            proof.get("review_reasons"),
            proof.get("review_reason"),
        ),
    }


def _first_text(*values) -> str:
    for value in values:
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _join_reasons(*values) -> str:
    reasons = []
    for value in values:
        for item in as_list(value):
            if item not in (None, ""):
                text = str(item).strip()
                if text and text not in reasons:
                    reasons.append(text)
    return "；".join(reasons)
