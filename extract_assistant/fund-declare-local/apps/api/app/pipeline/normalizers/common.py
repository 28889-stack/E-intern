from __future__ import annotations

from typing import Any


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

FINAL_DECLARATION_EVENT_TYPES = {
    "ordinary_trade",
    "security_registration",
    "bonus_share",
    "new_share_subscription",
    "new_bond_subscription",
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
    market = event.get("market") or document_info.get("market") or ""
    securities_account = (
        event.get("securities_account")
        or event.get("stock_account")
        or document_info.get("securities_account")
        or ""
    )
    account_type = derive_account_type(
        event.get("account_type") or document_info.get("account_type"),
        market,
        securities_account,
    )
    event_id = (
        event.get("event_id")
        or event.get("trade_id")
        or event.get("transaction_id")
        or event.get("cash_flow_id")
        or ""
    )
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
            "fund_account": event.get("fund_account")
            or event.get("capital_account")
            or document_info.get("fund_account")
            or "",
            "securities_account": securities_account,
            "account_type": account_type,
            "event_id": event_id,
            "event_type": normalize_event_type(event),
            "event_type_raw": event.get("event_type_raw")
            or event.get("transaction_type_raw")
            or event.get("business_type_raw")
            or event.get("transfer_type_raw")
            or "",
            "market": market,
            "event_date": event.get("event_date")
            or event.get("trade_date")
            or event.get("transaction_date")
            or event.get("business_date")
            or "",
            "event_time": event.get("event_time") or event.get("time") or "",
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
            or event.get("settlement_amount_raw")
            or event.get("settlement_amount")
            or event.get("clearing_amount_raw")
            or event.get("clearing_amount")
            or event.get("amount")
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
            "manual_review_required": bool(event.get("manual_review_required", False)),
            "problem_types": unique_list(event.get("problem_types")),
            "missing_fields": unique_list(event.get("missing_fields")),
            "conflict_fields": unique_list(event.get("conflict_fields")),
        }
    )
    row["source_evidence"] = build_source_evidence(file_record, event, event_id)
    return row


def build_holding_row(
    case_id: str,
    file_record: dict,
    document_info: dict,
    holding: dict,
) -> dict:
    market = holding.get("market") or document_info.get("market") or ""
    securities_account = (
        holding.get("securities_account")
        or holding.get("stock_account")
        or document_info.get("securities_account")
        or ""
    )
    account_type = derive_account_type(
        holding.get("account_type") or document_info.get("account_type"),
        market,
        securities_account,
    )
    holding_id = holding.get("holding_id") or holding.get("position_id") or ""
    row = {
        "case_id": case_id,
        "file_id": file_record.get("file_id") or holding.get("file_id") or "",
        "file_no": file_record.get("file_no", ""),
        "original_file_name": file_record.get("original_file_name")
        or document_info.get("file_name")
        or "",
        "document_type": document_info.get("document_type", ""),
        "holder_name": document_info.get("holder_name", ""),
        "one_code_account": document_info.get("one_code_account", ""),
        "fund_account": holding.get("fund_account")
        or holding.get("capital_account")
        or document_info.get("fund_account")
        or "",
        "securities_account": securities_account,
        "market": market,
        "account_type": account_type,
        "holding_id": holding_id,
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
        "market_value_raw": holding.get("market_value_raw")
        or holding.get("market_value")
        or holding.get("valuation_raw")
        or "",
        "currency": holding.get("currency", ""),
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
        "manual_review_required": bool(holding.get("manual_review_required", False)),
        "problem_types": unique_list(holding.get("problem_types")),
        "missing_fields": unique_list(holding.get("missing_fields")),
        "conflict_fields": unique_list(holding.get("conflict_fields")),
    }
    row["source_evidence"] = build_source_evidence(file_record, holding, holding_id)
    return row


def derive_account_type(explicit_account_type: Any, market: Any, securities_account: Any) -> str:
    explicit = str(explicit_account_type or "").strip()
    if explicit:
        return explicit

    account = str(securities_account or "").strip()
    if not account:
        return ""

    normalized_market = str(market or "").strip().upper()
    if normalized_market in {"SH", "SSE"} or str(market or "").strip() in {"上海", "沪市"}:
        return "沪A" if "B" not in account.upper() else "沪B"
    if normalized_market in {"SZ", "SZSE"} or str(market or "").strip() in {"深圳", "深市"}:
        return "深A" if "B" not in account.upper() else "深B"
    if "沪A" in account or "上海A" in account:
        return "沪A"
    if "深A" in account or "深圳A" in account:
        return "深A"
    return ""


def build_source_evidence(file_record: dict, raw_record: dict, source_row_id: Any) -> list[dict]:
    return [
        {
            "file_id": file_record.get("file_id") or raw_record.get("file_id") or "",
            "file_no": file_record.get("file_no", ""),
            "file_name": file_record.get("original_file_name", ""),
            "source_type": file_record.get("content_type") or file_record.get("source_type") or "",
            "source_page": join_values(
                raw_record.get("source_pages")
                if "source_pages" in raw_record
                else [raw_record.get("source_page", "")]
            ),
            "row_no": join_values(
                raw_record.get("row_nos")
                if "row_nos" in raw_record
                else [raw_record.get("row_no", "")]
            ),
            "source_row_id": str(source_row_id or ""),
            "raw_record": raw_record,
        }
    ]


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


def unique_list(value: Any) -> list:
    seen = set()
    items = []
    for item in as_list(value):
        if item in (None, ""):
            continue
        text = str(item)
        if text in seen:
            continue
        seen.add(text)
        items.append(text)
    return items


def as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]
