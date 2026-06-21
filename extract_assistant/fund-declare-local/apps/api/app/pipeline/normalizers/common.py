from __future__ import annotations

import re
from typing import Any


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

NO_RECORD_EVENT_TYPES = {
    "no_trade_record",
    "no_holding_record",
    "no_account_record",
}

FINAL_DECLARATION_EVENT_TYPES = {
    "ordinary_trade",
    "security_registration",
    "bonus_share",
    "new_share_subscription",
    "new_bond_subscription",
    "no_trade_record",
    "no_holding_record",
    "no_account_record",
}
FINAL_DECLARATION_DIRECTIONS = {
    "buy",
    "sell",
    "transfer_in",
    "transfer_out",
    "registration_in",
    "rights_event",
    "subscribe",
}
EXCLUDED_FINAL_EVENT_TYPES = {
    "cash_dividend",
    "bond_interest",
    "cash_flow",
    "bank_transfer",
    "fund_transfer",
    "interest",
}
EXCLUDED_TRANSFER_KEYWORDS = (
    "红利",
    "分红",
    "股息",
    "派息",
    "兑息",
    "利息",
    "资金流水",
    "资金存取",
    "银证转账",
    "银行转账",
    "转入",
    "转出",
)


def empty_normalized_result(review_items: list[dict] | None = None) -> dict:
    return {
        "full_transaction_rows": [],
        "final_declaration_rows": [],
        "holding_rows": [],
        "review_items": review_items or [],
    }


def build_normalized_result(
    full_transaction_rows: list[dict],
    holding_rows: list[dict] | None = None,
    review_items: list[dict] | None = None,
) -> dict:
    final_rows = []
    normalized_review_items = list(review_items or [])

    for row in full_transaction_rows:
        if is_final_declaration_row(row):
            final_rows.append(row)
        elif needs_uncertain_type_review(row):
            normalized_review_items.append(
                review_item(
                    "warning",
                    "event",
                    str(row.get("file_id") or ""),
                    str(row.get("event_id") or ""),
                    "event_type",
                    "无法判断该变动类型是否影响持仓，已保留在完整表并排除出最终申报表",
                )
            )

    return {
        "full_transaction_rows": full_transaction_rows,
        "final_declaration_rows": final_rows,
        "holding_rows": holding_rows or [],
        "review_items": normalized_review_items,
    }


def build_event_row(
    case_id: str,
    file_record: dict,
    document_info: dict,
    event: dict,
) -> dict:
    row = {
        "case_id": case_id,
        "file_id": file_record.get("file_id") or event.get("file_id") or "",
        "file_no": file_record.get("file_no", ""),
        "original_file_name": file_record.get("original_file_name")
        or document_info.get("file_name")
        or "",
    }
    for column in DOCUMENT_COLUMNS:
        row[column] = document_info.get(column, "")

    row.update(
        {
            "account_type": event.get("account_type")
            or document_info.get("account_type")
            or file_record.get("account_type")
            or "",
            "securities_account": event.get("securities_account")
            or event.get("fund_account")
            or document_info.get("securities_account")
            or document_info.get("fund_account")
            or file_record.get("securities_account")
            or file_record.get("fund_account")
            or "",
            "event_id": event.get("event_id")
            or event.get("trade_id")
            or event.get("transaction_id")
            or event.get("cash_flow_id")
            or "",
            "event_type": normalize_event_type(event),
            "market": event.get("market") or document_info.get("market") or "",
            "event_date": event.get("event_date")
            or event.get("trade_date")
            or event.get("transaction_date")
            or event.get("business_date")
            or "",
            "security_code": event.get("security_code", ""),
            "security_name": event.get("security_name", ""),
            "direction": normalize_direction(event),
            "quantity_raw": event.get("quantity_raw")
            or event.get("quantity")
            or event.get("volume_raw")
            or event.get("share_quantity_raw")
            or "",
            "price_raw": event.get("price_raw")
            or event.get("price")
            or event.get("trade_price_raw")
            or "",
            "amount_raw": event.get("amount_raw")
            or event.get("amount")
            or event.get("settlement_amount_raw")
            or event.get("settlement_amount")
            or event.get("clearing_amount_raw")
            or event.get("clearing_amount")
            or event.get("net_amount_raw")
            or event.get("net_amount")
            or "",
            "balance_after_raw": event.get("balance_after_raw")
            or event.get("holding_balance_raw")
            or event.get("stock_balance_raw")
            or "",
            "transfer_type_raw": event.get("transfer_type_raw")
            or event.get("transaction_type_raw")
            or event.get("business_type_raw")
            or event.get("event_type_raw")
            or "",
            "rights_category_raw": event.get("rights_category_raw", ""),
            "security_category_raw": event.get("security_category_raw")
            or event.get("instrument_type")
            or "",
            "source_pages": join_values(
                event.get("source_pages")
                if "source_pages" in event
                else [event.get("source_page", "")]
            ),
            "row_nos": join_values(
                event.get("row_nos") if "row_nos" in event else [event.get("row_no", "")]
            ),
            "review_reason": event.get("review_reason", ""),
            "source_evidence": [
                {
                    "file_id": file_record.get("file_id") or event.get("file_id") or "",
                    "file_no": file_record.get("file_no", ""),
                    "file_name": file_record.get("original_file_name")
                    or document_info.get("file_name")
                    or "",
                    "source_row_id": event.get("event_id")
                    or event.get("trade_id")
                    or event.get("transaction_id")
                    or event.get("cash_flow_id")
                    or "",
                    "source_page": event.get("source_page", ""),
                    "row_no": event.get("row_no", ""),
                    "source_pages": event.get("source_pages", ""),
                    "row_nos": event.get("row_nos", ""),
                }
            ],
        }
    )
    return row


def build_holding_row(
    case_id: str,
    file_record: dict,
    document_info: dict,
    holding: dict,
) -> dict:
    return {
        "case_id": case_id,
        "file_id": file_record.get("file_id") or holding.get("file_id") or "",
        "file_no": file_record.get("file_no", ""),
        "original_file_name": file_record.get("original_file_name")
        or document_info.get("file_name")
        or "",
        "account_type": holding.get("account_type")
        or document_info.get("account_type")
        or file_record.get("account_type")
        or "",
        "securities_account": holding.get("securities_account")
        or holding.get("fund_account")
        or document_info.get("securities_account")
        or document_info.get("fund_account")
        or file_record.get("securities_account")
        or file_record.get("fund_account")
        or "",
        "holding_id": holding.get("holding_id") or "",
        "market": holding.get("market") or document_info.get("market") or "",
        "holding_date": holding.get("holding_date")
        or holding.get("date")
        or document_info.get("period_end")
        or "",
        "security_code": holding.get("security_code", ""),
        "security_name": holding.get("security_name", ""),
        "quantity_raw": holding.get("quantity_raw")
        or holding.get("quantity")
        or holding.get("holding_quantity_raw")
        or holding.get("stock_balance_raw")
        or holding.get("balance_raw")
        or "",
        "security_category_raw": holding.get("security_category_raw")
        or holding.get("instrument_type")
        or "",
        "source_pages": join_values(
            holding.get("source_pages")
            if "source_pages" in holding
            else [holding.get("source_page", "")]
        ),
        "row_nos": join_values(
            holding.get("row_nos") if "row_nos" in holding else [holding.get("row_no", "")]
        ),
        "review_reason": holding.get("review_reason", ""),
        "source_evidence": [
            {
                "file_id": file_record.get("file_id") or holding.get("file_id") or "",
                "file_no": file_record.get("file_no", ""),
                "file_name": file_record.get("original_file_name")
                or document_info.get("file_name")
                or "",
                "source_row_id": holding.get("holding_id") or "",
                "source_page": holding.get("source_page", ""),
                "row_no": holding.get("row_no", ""),
                "source_pages": holding.get("source_pages", ""),
                "row_nos": holding.get("row_nos", ""),
            }
        ],
    }


def normalize_event_type(event: dict) -> str:
    event_type = str(event.get("event_type") or "").strip()
    if event_type:
        return event_type

    raw_type = str(
        event.get("transfer_type_raw")
        or event.get("transaction_type_raw")
        or event.get("business_type_raw")
        or event.get("event_type_raw")
        or ""
    )
    if raw_type in {"买入", "卖出", "证券买入", "证券卖出", "交易过户"}:
        return "ordinary_trade"
    if "股份登记" in raw_type or "申购中签" in raw_type or "新股入账" in raw_type:
        return "security_registration"
    if any(keyword in raw_type for keyword in ("送股", "转增", "红股")):
        return "bonus_share"
    if any(keyword in raw_type for keyword in ("分红", "红利", "股息", "派息")):
        return "cash_dividend"
    if any(keyword in raw_type for keyword in ("兑息", "利息", "付息")):
        return "bond_interest"
    if any(keyword in raw_type for keyword in ("银证", "资金", "银行")):
        return "cash_flow"
    return "unknown_event"


def normalize_direction(event: dict) -> str:
    direction = normalize_direction_value(event.get("direction"))
    if direction:
        return direction

    raw_type = str(
        event.get("transfer_type_raw")
        or event.get("transaction_type_raw")
        or event.get("business_type_raw")
        or event.get("event_type_raw")
        or ""
    )
    if "买入" in raw_type:
        return "buy"
    if "卖出" in raw_type:
        return "sell"
    if "股份登记" in raw_type or "中签" in raw_type or "新股" in raw_type:
        return "registration_in"
    if any(keyword in raw_type for keyword in ("送股", "转增", "红股")):
        return "rights_event"
    if any(keyword in raw_type for keyword in ("分红", "红利", "股息", "派息")):
        return "cash_income"
    return ""


def normalize_direction_value(value: Any) -> str:
    direction = str(value or "").strip()
    if not direction:
        return ""
    if direction in {"buy", "sell", "transfer_in", "transfer_out", "registration_in"}:
        return direction
    if direction in {"买", "买入", "证券买入", "申购", "转入"}:
        return "buy"
    if direction in {"卖", "卖出", "证券卖出", "赎回", "转出"}:
        return "sell"
    return direction


def is_final_declaration_row(row: dict) -> bool:
    event_type = str(row.get("event_type") or "")
    direction = str(row.get("direction") or "")
    transfer_type = str(row.get("transfer_type_raw") or "")

    if event_type in EXCLUDED_FINAL_EVENT_TYPES:
        return False
    if any(keyword in transfer_type for keyword in EXCLUDED_TRANSFER_KEYWORDS):
        return False
    if event_type in FINAL_DECLARATION_EVENT_TYPES:
        return True
    return direction in FINAL_DECLARATION_DIRECTIONS


def needs_uncertain_type_review(row: dict) -> bool:
    event_type = str(row.get("event_type") or "")
    transfer_type = str(row.get("transfer_type_raw") or "")
    if event_type in EXCLUDED_FINAL_EVENT_TYPES:
        return False
    if any(keyword in transfer_type for keyword in EXCLUDED_TRANSFER_KEYWORDS):
        return False
    return event_type in {"", "unknown_event"}


def empty_record_event_from_semantics(
    case_id: str,
    file_record: dict,
    document_info: dict,
    extract_result: dict,
) -> dict | None:
    """Build a normal zero-quantity event when source text explicitly says no records."""

    source_text = _semantic_source_text(extract_result)
    if not _has_empty_record_signal(source_text):
        return None

    event_type, raw_type, event_id = _empty_record_type(source_text)
    account = _semantic_account(document_info, extract_result, source_text)
    if event_type == "no_account_record" and not account:
        account = "未开立"
    period_start = _semantic_date(document_info, source_text, "period_start")
    period_end = _semantic_date(document_info, source_text, "period_end")
    event_date = (
        str(document_info.get("event_date") or "").strip()
        or period_end
        or period_start
        or _last_date(source_text)
    )

    semantic_document_info = dict(document_info)
    if account:
        semantic_document_info["securities_account"] = account
    if period_start:
        semantic_document_info["period_start"] = period_start
    if period_end:
        semantic_document_info["period_end"] = period_end

    event = {
        "event_id": event_id,
        "event_type": event_type,
        "event_date": event_date,
        "securities_account": account,
        "security_code": "0",
        "security_name": "0",
        "quantity_raw": "0",
        "price_raw": "0",
        "amount_raw": "0",
        "balance_after_raw": "0",
        "transfer_type_raw": raw_type,
        "source_page": 1,
        "review_reason": "",
    }
    return build_event_row(case_id, file_record, semantic_document_info, event)


def movement_type(row: dict) -> str:
    return (
        str(row.get("transfer_type_raw") or "").strip()
        or str(row.get("event_type") or "").strip()
        or str(row.get("direction") or "").strip()
        or "unknown"
    )


def review_item(
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


def join_values(value: Any) -> str:
    values = as_list(value)
    return ",".join(str(item) for item in values if item not in (None, ""))


def as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def unique_list(value: Any) -> list[str]:
    values: list[str] = []
    seen = set()
    for item in as_list(value):
        if item in (None, ""):
            continue
        text = str(item)
        if text in seen:
            continue
        seen.add(text)
        values.append(text)
    return values


def _semantic_source_text(extract_result: dict) -> str:
    text_parts = []
    for value in (
        extract_result.get("input_text"),
        extract_result.get("source_text"),
        extract_result.get("raw_text"),
    ):
        if isinstance(value, str) and value.strip():
            text_parts.append(value)

    input_sources = extract_result.get("input_sources")
    if isinstance(input_sources, dict):
        for key in ("ocr_result_path", "raw_text_path"):
            path = input_sources.get(key)
            if path:
                text_parts.append(_text_from_json_path(path))

    return "\n".join(part for part in text_parts if part)


def _text_from_json_path(path: str) -> str:
    try:
        from app.services.local_store import read_json

        payload = read_json(path, {})
    except Exception:
        return ""

    text_parts = []
    if isinstance(payload, dict):
        for page_result in as_list(payload.get("page_results") or payload.get("pages")):
            if isinstance(page_result, dict):
                text_parts.append(str(page_result.get("text") or ""))
    return "\n".join(part for part in text_parts if part)


def _has_empty_record_signal(text: str) -> bool:
    return any(
        keyword in text
        for keyword in (
            "共0条",
            "共 0 条",
            "没有相应的查询信息",
            "没有相应查询信息",
            "暂无记录",
            "无记录",
            "没有持仓",
            "无持仓",
            "暂无持仓",
            "未持仓",
            "未开立账户",
            "未开立证券账户",
            "未开通账户",
            "未开通证券账户",
            "未开户",
            "没有开立证券账户",
            "无证券账户",
            "无账户",
        )
    )


def _empty_record_type(text: str) -> tuple[str, str, str]:
    if _looks_like_no_account_query(text):
        return "no_account_record", "未开立账户", "no_account_record_1"
    if _looks_like_empty_trade_query(text):
        return "no_trade_record", "无交易记录", "no_trade_record_1"
    if _looks_like_empty_holding_query(text):
        return "no_holding_record", "无持仓记录", "no_holding_record_1"
    return "unknown_event", "空查询结果但无法判断类型", "empty_record_unknown_1"


def _looks_like_no_account_query(text: str) -> bool:
    return any(
        keyword in text
        for keyword in (
            "未开立账户",
            "未开立证券账户",
            "未开通账户",
            "未开通证券账户",
            "未开户",
            "没有开立证券账户",
            "无证券账户",
            "无账户",
        )
    )


def _looks_like_empty_trade_query(text: str) -> bool:
    return any(
        keyword in text
        for keyword in (
            "历史成交",
            "成交日期",
            "成交时间",
            "成交编号",
            "买卖标志",
            "成交金额",
            "交易流水",
            "持有变更",
            "证券持有变更",
        )
    )


def _looks_like_empty_holding_query(text: str) -> bool:
    return any(
        keyword in text
        for keyword in (
            "持仓信息",
            "我的持仓",
            "证券持有信息",
            "当前数量",
            "持有数量",
            "没有持仓",
            "无持仓",
            "暂无持仓",
            "未持仓",
        )
    )


def _semantic_account(document_info: dict, extract_result: dict, text: str) -> str:
    for source in (document_info, extract_result):
        for key in (
            "securities_account",
            "fund_account",
            "one_code_account",
            "account_no",
            "account_number",
        ):
            value = str(source.get(key) or "").strip()
            if value:
                return value

    patterns = [
        r"(?:证券账户|证券账号|资金账号|资金帐号|一码通账户|一码通账号|股东代码)[:：\s]*([A-Za-z0-9\-]{5,})",
        r"多帐号\s*([A-Za-z0-9]{5,})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return ""


def _semantic_date(document_info: dict, text: str, field: str) -> str:
    value = str(document_info.get(field) or "").strip()
    if value:
        return _normalize_date(value)

    labels = {
        "period_start": ("起始日期", "开始日期", "起始日", "开始日"),
        "period_end": ("终止日期", "结束日期", "截止日期", "查询日期", "终止日", "结束日"),
    }.get(field, ())
    for label in labels:
        match = re.search(rf"{label}\s*[:：]?\s*(20\d{{2}}[-/.]\d{{1,2}}[-/.]\d{{1,2}})", text)
        if match:
            return _normalize_date(match.group(1))
    return ""


def _last_date(text: str) -> str:
    matches = re.findall(r"20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}", text)
    if not matches:
        return ""
    return _normalize_date(matches[-1])


def _normalize_date(value: str) -> str:
    parts = re.split(r"[-/.]", value)
    if len(parts) != 3:
        return value.replace("/", "-").replace(".", "-")
    year, month, day = parts
    return f"{year}-{int(month):02d}-{int(day):02d}"
