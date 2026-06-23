from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re
from typing import Any

from app.pipeline.security_account import (
    classify_security_account,
    extract_security_account_from_text,
    infer_account_type_from_text,
    market_from_account_type,
    normalize_account_type as normalize_security_account_type,
)


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
    "no_account_info",
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
    "no_account_info",
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
    "subscription_allotment",
    "cash_dividend",
    "bond_interest",
    "cash_flow",
    "bank_transfer",
    "fund_transfer",
    "interest",
}
EXCLUDED_TRANSFER_KEYWORDS = (
    "申购配号",
    "中购配号",
    "配号",
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
PURE_CASH_FLOW_TRANSFER_KEYWORDS = (
    "银证转账",
    "银行转取",
    "银行转存",
    "银行转证券",
    "证券转银行",
    "资金转入",
    "资金转出",
    "资金存入",
    "资金取出",
    "资金存取",
    "转账冻结取消",
    "转账冻结",
)
PURE_CASH_FLOW_INTEREST_KEYWORDS = (
    "账户利息",
    "资金利息",
    "银行利息",
    "利息归本",
    "利息入账",
    "结息归本",
    "结息",
)
SECURITY_INCOME_KEYWORDS = (
    "兑息",
    "派息",
    "股息",
    "红利",
    "分红",
    "债券",
    "转债",
    "固收",
)

SECURITY_REGISTRATION_KEYWORDS = (
    "股份登记",
    "股份入账",
    "证券登记",
    "证券登记入账",
    "登记入账",
    "新股入账",
    "债券入账",
    "转债入账",
    "可转债入账",
    "中签入账",
    "申购中签",
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
    # Keep this key for older callers, but official final-table routing belongs to
    # case_event_resolver so field mapping and business filtering stay decoupled.
    return {
        "full_transaction_rows": full_transaction_rows,
        "final_declaration_rows": [],
        "holding_rows": holding_rows or [],
        "review_items": list(review_items or []),
    }


def build_event_row(
    case_id: str,
    file_record: dict,
    document_info: dict,
    event: dict,
) -> dict:
    account_type = (
        event.get("account_type")
        or document_info.get("account_type")
        or file_record.get("account_type")
        or _account_type_from_security_code(event.get("security_code"))
        or ""
    )
    securities_account = (
        event.get("securities_account")
        or event.get("fund_account")
        or _document_securities_account(document_info, event, account_type)
        or document_info.get("securities_account")
        or document_info.get("fund_account")
        or file_record.get("securities_account")
        or file_record.get("fund_account")
        or ""
    )
    if not account_type:
        account_type = _account_type_from_securities_account(securities_account)

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
            "account_type": account_type,
            "securities_account": securities_account,
            "event_id": event.get("event_id")
            or event.get("trade_id")
            or event.get("transaction_id")
            or event.get("cash_flow_id")
            or "",
            "person_name": event.get("person_name")
            or event.get("holder_name")
            or document_info.get("holder_name")
            or "",
            "proof_type": event.get("proof_type", ""),
            "event_category": event.get("event_category", ""),
            "event_type": normalize_event_type(event),
            "market": event.get("market") or document_info.get("market") or "",
            "event_date": event.get("event_date")
            or event.get("trade_date")
            or event.get("transaction_date")
            or event.get("business_date")
            or "",
            "event_time": event.get("event_time")
            or event.get("trade_time")
            or event.get("transaction_time")
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
            "serial_no": event.get("serial_no")
            or event.get("transaction_id")
            or event.get("trade_id")
            or "",
            "order_no": event.get("order_no") or "",
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
                    "raw_text": event.get("raw_text", ""),
                }
            ],
        }
    )
    for control_field in (
        "manual_review_required",
        "review_issue_types",
        "missing_fields",
        "conflict_fields",
    ):
        if control_field in event:
            row[control_field] = event[control_field]
    return row


def build_holding_row(
    case_id: str,
    file_record: dict,
    document_info: dict,
    holding: dict,
) -> dict:
    account_type = (
        holding.get("account_type")
        or document_info.get("account_type")
        or file_record.get("account_type")
        or _account_type_from_security_code(holding.get("security_code"))
        or ""
    )
    securities_account = (
        holding.get("securities_account")
        or holding.get("fund_account")
        or _document_securities_account(document_info, holding, account_type)
        or document_info.get("securities_account")
        or document_info.get("fund_account")
        or file_record.get("securities_account")
        or file_record.get("fund_account")
        or ""
    )
    if not account_type:
        account_type = _account_type_from_securities_account(securities_account)

    row = {
        "case_id": case_id,
        "file_id": file_record.get("file_id") or holding.get("file_id") or "",
        "file_no": file_record.get("file_no", ""),
        "original_file_name": file_record.get("original_file_name")
        or document_info.get("file_name")
        or "",
        "account_type": account_type,
        "securities_account": securities_account,
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
        "market_value": holding.get("market_value")
        or holding.get("market_value_raw")
        or "",
        "currency": holding.get("currency") or document_info.get("currency") or "人民币",
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
                "raw_text": holding.get("raw_text", ""),
            }
        ],
    }
    for control_field in (
        "manual_review_required",
        "review_issue_types",
        "missing_fields",
        "conflict_fields",
    ):
        if control_field in holding:
            row[control_field] = holding[control_field]
    return row


def _document_securities_account(
    document_info: dict,
    row: dict,
    account_type: str,
) -> str:
    accounts = document_info.get("securities_accounts")
    if not isinstance(accounts, dict):
        accounts = {}

    normalized_type = _normalize_account_type(account_type)
    if normalized_type and accounts.get(normalized_type):
        return str(accounts[normalized_type]).strip()

    code_type = _account_type_from_security_code(row.get("security_code"))
    if code_type and accounts.get(code_type):
        return str(accounts[code_type]).strip()

    if len(accounts) == 1:
        return str(next(iter(accounts.values()))).strip()
    return ""


def _normalize_account_type(value: Any) -> str:
    text = str(value or "").strip()
    aliases = {
        "深圳A股": "深A",
        "深市A股": "深A",
        "深圳": "深A",
        "深A": "深A",
        "深圳B股": "深B",
        "深市B股": "深B",
        "深B": "深B",
        "上海A股": "沪A",
        "沪市A股": "沪A",
        "上海": "沪A",
        "沪A": "沪A",
        "上海B股": "沪B",
        "沪市B股": "沪B",
        "沪B": "沪B",
        "深圳信用账户": "深圳信用账户",
        "上海信用账户": "上海信用账户",
    }
    return aliases.get(text, text)


def _account_type_from_security_code(value: Any) -> str:
    code = str(value or "").strip()
    if not re.fullmatch(r"\d{6}", code):
        return ""
    if code.startswith("200"):
        return "深B"
    if code.startswith("900"):
        return "沪B"
    if code.startswith(("0", "3")):
        return "深A"
    if code.startswith("7"):
        return "沪A"
    if code.startswith("6"):
        return "沪A"
    if code.startswith(("83", "87", "88", "920")):
        return "北交所"
    return ""


def _account_type_from_securities_account(value: Any) -> str:
    return classify_security_account(value)


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
    if is_pure_cash_flow_event(event):
        return "cash_flow"
    if raw_type in {"买入", "卖出", "证券买入", "证券卖出", "交易过户"}:
        return "ordinary_trade"
    if any(keyword in raw_type for keyword in ("申购配号", "中购配号", "配号")):
        return "subscription_allotment"
    if is_security_registration_text(raw_type):
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


def is_pure_cash_flow_event(event: dict) -> bool:
    text = " ".join(
        str(value).strip()
        for value in (
            event.get("transfer_type_raw"),
            event.get("transaction_type_raw"),
            event.get("business_type_raw"),
            event.get("event_type_raw"),
            event.get("raw_business_type"),
            event.get("raw_summary"),
            event.get("review_reason"),
        )
        if value not in (None, "")
    )
    if not text:
        return False
    if any(keyword in text for keyword in PURE_CASH_FLOW_TRANSFER_KEYWORDS):
        return True
    if any(keyword in text for keyword in PURE_CASH_FLOW_INTEREST_KEYWORDS):
        return not any(keyword in text for keyword in SECURITY_INCOME_KEYWORDS)
    event_type = str(event.get("event_type") or "").strip()
    return event_type in {"cash_flow", "bank_transfer", "fund_transfer", "interest"} and not any(
        keyword in text for keyword in SECURITY_INCOME_KEYWORDS
    )


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
    if is_security_registration_text(raw_type):
        return "registration_in"
    if any(keyword in raw_type for keyword in ("申购配号", "中购配号", "配号")):
        return "subscribe"
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


def is_security_registration_text(value: Any) -> bool:
    text = str(value or "")
    return any(keyword in text for keyword in SECURITY_REGISTRATION_KEYWORDS)


def is_final_declaration_row(row: dict) -> bool:
    event_type = str(row.get("event_type") or "")
    direction = str(row.get("direction") or "")
    transfer_type = str(row.get("transfer_type_raw") or "")

    if event_type in EXCLUDED_FINAL_EVENT_TYPES:
        return False
    if any(keyword in transfer_type for keyword in EXCLUDED_TRANSFER_KEYWORDS):
        return False
    if event_type == "ordinary_trade" and _is_zero_number(row.get("quantity_raw")):
        return False
    if event_type in FINAL_DECLARATION_EVENT_TYPES:
        return True
    return direction in FINAL_DECLARATION_DIRECTIONS


def _is_zero_number(value: Any) -> bool:
    text = str(value or "").replace(",", "").strip()
    if not text:
        return False
    try:
        return Decimal(text) == 0
    except (InvalidOperation, ValueError):
        return False


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
    account_type = _semantic_account_type(document_info, source_text)
    account = _semantic_account(document_info, extract_result, source_text, account_type)
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
    if account_type:
        semantic_document_info["account_type"] = account_type
        semantic_document_info["market"] = market_from_account_type(account_type)

    if event_type == "no_account_info":
        event = {
            "event_id": event_id,
            "event_type": event_type,
            "event_category": "negative_proof",
            "proof_type": "无账户信息",
            "event_date": event_date,
            "person_name": _semantic_person_name(document_info, extract_result, source_text),
            "security_code": "",
            "security_name": "",
            "quantity_raw": "",
            "price_raw": "",
            "amount_raw": "",
            "balance_after_raw": "",
            "transfer_type_raw": raw_type,
            "source_page": 1,
            "raw_text": _first_line(source_text),
            "review_reason": "",
        }
        return build_event_row(case_id, file_record, semantic_document_info, event)

    event = {
        "event_id": event_id,
        "event_type": event_type,
        "event_date": event_date,
        "securities_account": account,
        "account_type": account_type,
        "market": market_from_account_type(account_type),
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
        return "no_account_info", "无账户信息", "no_account_info_1"
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


def _semantic_person_name(document_info: dict, extract_result: dict, text: str) -> str:
    for source in (document_info, extract_result):
        for key in ("person_name", "holder_name", "name", "姓名"):
            value = str(source.get(key) or "").strip()
            if value:
                return value

    for pattern in (
        r"(?:姓名|客户姓名|投资者姓名)[:：\s]*([\u4e00-\u9fff]{2,8})",
        r"(?:截至|截止).*?([\u4e00-\u9fff]{2,8})无账户信息",
    ):
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return ""


def _first_line(text: str) -> str:
    for line in str(text or "").splitlines():
        line = line.strip()
        if line:
            return line
    return ""


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


def _semantic_account(
    document_info: dict,
    extract_result: dict,
    text: str,
    account_type_hint: str = "",
) -> str:
    for source in (document_info, extract_result):
        for key in (
            "securities_account",
            "stockholder_account",
            "shareholder_account",
        ):
            value = str(source.get(key) or "").strip()
            if value and classify_security_account(value, account_type_hint):
                return value

    return extract_security_account_from_text(text, account_type_hint)


def _semantic_account_type(document_info: dict, text: str) -> str:
    for key in ("account_type", "market"):
        value = str(document_info.get(key) or "").strip()
        if value:
            return normalize_security_account_type(value)
    return infer_account_type_from_text(text)


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
