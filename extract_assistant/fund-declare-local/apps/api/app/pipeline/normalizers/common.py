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
    "securities_account",
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
