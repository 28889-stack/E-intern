from __future__ import annotations

import re

from app.pipeline.normalizers.common import (
    as_list,
    build_event_row,
    build_holding_row,
    build_normalized_result,
    empty_record_event_from_semantics,
    is_pure_cash_flow_event,
    is_security_registration_text,
    review_item,
)


FINAL_FIELD_KEYS = [
    "账户类型",
    "证券账号",
    "证券代码",
    "证券名称",
    "变动类型",
    "日期",
    "成交数量",
    "成交单价",
    "收付金额",
]

FINAL_ONLY_REQUIRED_KEYS = FINAL_FIELD_KEYS

ACCOUNT_TYPES = {
    "深A",
    "沪A",
    "深B",
    "沪B",
    "北交所",
    "深圳信用账户",
    "上海信用账户",
}

FINAL_EVENT_KEYWORDS = (
    "买入",
    "卖出",
    "打新",
    "新股申购",
    "新股中签",
    "证券登记入账",
    "股份登记入账",
    "股份入账",
    "股份登记",
    "登记入账",
    "转债入账",
    "可转债入账",
    "债券入账",
    "中签入账",
    "送股",
    "转增",
    "配股入账",
)

FULL_ONLY_EVENT_KEYWORDS = (
    "申购配号",
    "中购配号",
    "股息",
    "派息",
    "现金分红",
    "红利",
    "利息",
    "银证转账",
    "资金流水",
    "费用",
    "税费",
    "结息",
)

SOURCE_DEDUPE_EVENT_TYPES = {
    "security_registration",
    "bonus_share",
}

IGNORED_NON_HOLDING_EVENT_KEYWORDS = (
    "银行转证券",
    "证券转银行",
    "银证转账",
    "资金转入",
    "资金转出",
    "资金存入",
    "资金取出",
    "资金存取",
    "银行转存",
    "银行转取",
    "转账冻结取消",
    "转账冻结",
    "银行利息",
    "资金利息",
    "利息归本",
    "利息入账",
    "结息归本",
    "结息",
)


def normalize_guangfa(case_id: str, extract_result: dict, file_record: dict) -> dict:
    document_info = extract_result.get("document_info") or {}
    full_rows = []
    review_items = []

    business_events = [
        event
        for event in as_list(extract_result.get("business_events"))
        if isinstance(event, dict)
    ]
    holding_records = [
        holding
        for holding in as_list(extract_result.get("holding_records"))
        if isinstance(holding, dict)
    ]
    negative_proofs = [
        proof
        for proof in as_list(extract_result.get("negative_proofs"))
        if isinstance(proof, dict)
    ]
    review_items.extend(
        _map_document_level_review_items(
            extract_result.get("document_level_review_items"),
            file_record,
        )
    )

    for index, trade in enumerate(
        _rows_from_group(extract_result.get("trade_group"), "trades")
    ):
        event = _map_group_event(trade)
        event.setdefault("event_id", _event_id(trade, f"guangfa_trade_{index + 1}"))
        event.setdefault("event_type", "ordinary_trade")
        full_rows.append(build_event_row(case_id, file_record, document_info, event))

    if business_events or holding_records or negative_proofs:
        for index, event in enumerate(business_events):
            event_payload, event_review_items = _map_business_event(
                event,
                index,
                file_record,
                document_info,
            )
            if _reclassify_fund_flow_trade_if_needed(event_payload):
                event_review_items = []
            review_items.extend(event_review_items)
            if (
                event.get("include_in_full_table") is False
                and event_payload.get("event_type") != "no_account_info"
            ):
                continue
            full_rows.append(
                build_event_row(case_id, file_record, document_info, event_payload)
            )

        for index, proof in enumerate(negative_proofs):
            full_rows.append(
                build_event_row(
                    case_id,
                    file_record,
                    document_info,
                    _map_negative_proof(proof, index),
                )
            )

        holding_rows = []
        for index, holding in enumerate(holding_records):
            mapped_holding = _map_business_holding(
                holding,
                index,
                document_info,
                file_record,
            )
            if _is_blank_holding_record(mapped_holding):
                continue
            holding_rows.append(
                build_holding_row(case_id, file_record, document_info, mapped_holding)
            )

        full_rows = _dedupe_same_source_event_rows(full_rows)
        return build_normalized_result(full_rows, holding_rows, review_items)

    for index, transaction in enumerate(as_list(extract_result.get("transactions"))):
        if not isinstance(transaction, dict):
            continue
        event = _map_group_event(transaction)
        event.setdefault("event_id", _event_id(transaction, f"guangfa_txn_{index + 1}"))
        full_rows.append(build_event_row(case_id, file_record, document_info, event))

    for index, other_event in enumerate(as_list(extract_result.get("other_events"))):
        if not isinstance(other_event, dict):
            continue
        event_payload = _map_group_event(other_event)
        event_payload.setdefault(
            "event_id",
            _event_id(other_event, f"guangfa_other_event_{index + 1}"),
        )
        full_rows.append(
            build_event_row(case_id, file_record, document_info, event_payload)
        )

    for index, event in enumerate(as_list(extract_result.get("events"))):
        if not isinstance(event, dict):
            continue
        event_payload = _map_group_event(event)
        event_payload.setdefault("event_id", _event_id(event, f"guangfa_event_{index + 1}"))
        if _should_ignore_non_holding_event(event_payload):
            ignored_non_holding_count += 1
            continue
        full_rows.append(
            build_event_row(case_id, file_record, document_info, event_payload)
        )

    for index, cash_flow in enumerate(as_list(extract_result.get("cash_flows"))):
        if not isinstance(cash_flow, dict):
            continue
        event = _map_group_event(cash_flow)
        event.setdefault(
            "event_id",
            cash_flow.get("cash_flow_id") or f"cash_flow_{index + 1}",
        )
        event.setdefault("event_type", "cash_flow")
        full_rows.append(build_event_row(case_id, file_record, document_info, event))

    holding_rows = [
        build_holding_row(case_id, file_record, document_info, _map_group_holding(holding))
        for holding in _rows_from_group(extract_result.get("position_group"), "positions")
    ]
    holding_rows = [
        build_holding_row(case_id, file_record, document_info, holding)
        for holding in as_list(extract_result.get("holdings"))
        if isinstance(holding, dict)
    ] + holding_rows

    if (
        not full_rows
        and not holding_rows
        and not review_items
    ):
        empty_record_event = empty_record_event_from_semantics(
            case_id,
            file_record,
            document_info,
            extract_result,
        )
        if empty_record_event:
            full_rows.append(empty_record_event)
        else:
            item = review_item(
                "warning",
                "extract_result",
                file_record.get("file_id") or extract_result.get("file_id") or "",
                "",
                "guangfa",
                "广发抽取结果中未发现 trade_group、position_group、other_events、transactions、events、cash_flows 或 holdings",
            )
            item["file_no"] = file_record.get("file_no", "")
            item["original_file_name"] = file_record.get("original_file_name", "")
            review_items.append(item)

    full_rows = _dedupe_same_source_event_rows(full_rows)
    return build_normalized_result(full_rows, holding_rows, review_items)


def _map_document_level_review_items(items, file_record: dict) -> list[dict]:
    mapped_items: list[dict] = []
    file_id = file_record.get("file_id") or ""
    for index, item in enumerate(as_list(items), start=1):
        if not isinstance(item, dict):
            continue
        if _is_non_business_document_review_item(item):
            continue
        message = _first_text(
            item.get("message"),
            item.get("reason"),
            item.get("review_reason"),
            item.get("issue_type"),
            item.get("raw_summary"),
        )
        if not message:
            continue
        page = _first_text(item.get("page"), item.get("source_page"))
        row_no = _first_text(item.get("row_no"), item.get("source_row_no"))
        issue_type = _first_text(item.get("issue_type"), item.get("field"))
        location = " ".join(
            part
            for part in [
                f"page={page}" if page else "",
                f"row_no={row_no}" if row_no else "",
                issue_type,
            ]
            if part
        )
        review_message = f"{location}：{message}" if location else message
        mapped = review_item(
            "warning",
            "extract_result",
            file_id,
            f"document_level_review_{index}",
            "document_level_review_items",
            review_message,
        )
        mapped["file_no"] = file_record.get("file_no", "")
        mapped["original_file_name"] = file_record.get("original_file_name", "")
        mapped_items.append(mapped)
    return mapped_items


def _is_non_business_document_review_item(item: dict) -> bool:
    issue_type = _first_text(item.get("issue_type"), item.get("field"))
    message = _first_text(
        item.get("message"),
        item.get("reason"),
        item.get("review_reason"),
        item.get("raw_summary"),
    )
    text = f"{issue_type} {message}"
    non_business_issue_types = (
        "表头残片",
        "空表",
        "非交易行",
        "页脚/非业务文本",
    )
    if any(issue in issue_type for issue in non_business_issue_types):
        return True
    return any(
        keyword in text
        for keyword in (
            "非业务记录",
            "无业务信息",
            "无业务数据",
            "无数据行",
            "使用注意事项",
            "页码行",
            "空行或分隔行",
            "仅含分隔符",
            "表内全为'/'",
            '表内全为"/"',
        )
    )


def _dedupe_same_source_event_rows(rows: list[dict]) -> list[dict]:
    deduped = []
    rows_by_key: dict[tuple, dict] = {}
    for row in rows:
        key = _same_source_event_key(row)
        if key and key in rows_by_key:
            _merge_same_source_event_row(rows_by_key[key], row)
            continue
        if key:
            rows_by_key[key] = row
        deduped.append(row)
    return deduped


def _same_source_event_key(row: dict) -> tuple:
    event_type = _first_text(row.get("event_type"))
    if event_type not in SOURCE_DEDUPE_EVENT_TYPES:
        return ()
    file_id = _first_text(row.get("file_id"), row.get("file_no"))
    event_date = _first_text(row.get("event_date"))
    security_code = _first_text(row.get("security_code"))
    quantity = _first_text(row.get("quantity_raw"))
    if not (file_id and event_date and security_code and quantity):
        return ()
    return (
        file_id,
        event_type,
        event_date,
        security_code,
        _first_text(row.get("direction")),
        quantity,
        _first_text(row.get("price_raw")),
    )


def _merge_same_source_event_row(target: dict, source: dict) -> None:
    for field, value in source.items():
        if field == "source_evidence":
            target[field] = _merge_evidence_rows(
                target.get("source_evidence"),
                source.get("source_evidence"),
            )
            continue
        if field in {"row_nos", "source_pages"}:
            target[field] = _merge_delimited_values(target.get(field), value)
            continue
        if field == "security_name" and _security_name_needs_source(target, source):
            target[field] = value
            continue
        if field in {
            "account_type",
            "securities_account",
        } and _source_account_is_better_for_security(target, source):
            target[field] = value
            continue
        if not _first_text(target.get(field)) and _first_text(value):
            target[field] = value


def _source_account_is_better_for_security(target: dict, source: dict) -> bool:
    security_code = _first_text(target.get("security_code"), source.get("security_code"))
    if not security_code:
        return False
    target_market = _account_market(_first_text(target.get("account_type")))
    source_market = _account_market(_first_text(source.get("account_type")))
    code_market = _account_market(_account_type_from_security_code(security_code))
    return bool(code_market and source_market == code_market and target_market != code_market)


def _security_name_needs_source(target: dict, source: dict) -> bool:
    target_name = _first_text(target.get("security_name"))
    source_name = _first_text(source.get("security_name"))
    security_code = _first_text(target.get("security_code"), source.get("security_code"))
    return bool(source_name and (not target_name or target_name == security_code))


def _merge_evidence_rows(left, right) -> list[dict]:
    merged = []
    seen = set()
    for item in [*as_list(left), *as_list(right)]:
        if not isinstance(item, dict):
            continue
        signature = tuple(sorted((str(key), str(value)) for key, value in item.items()))
        if signature in seen:
            continue
        seen.add(signature)
        merged.append(dict(item))
    return merged


def _merge_delimited_values(left, right) -> str:
    values = []
    seen = set()
    for value in [*str(left or "").split(","), *str(right or "").split(",")]:
        text = value.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        values.append(text)
    return ",".join(values)


def _map_business_event(
    event: dict,
    index: int,
    file_record: dict,
    document_info: dict,
) -> tuple[dict, list[dict]]:
    candidates = event.get("final_field_candidates") or {}
    if not isinstance(candidates, dict):
        candidates = {}

    auxiliary = _business_event_auxiliary_fields(event, candidates)
    raw_movement = _first_text(
        candidates.get("变动类型"),
        event.get("inferred_event_type"),
        event.get("raw_business_type"),
        event.get("event_category"),
    )
    event_type, direction = _classify_business_event(raw_movement)
    full_only = _is_full_only_event(raw_movement, event_type)

    securities_account = _first_text(
        candidates.get("证券账号"),
        event.get("securities_account"),
    )
    security_name = _first_text(candidates.get("证券名称"), event.get("security_name"))
    raw_text = _source_value(event, "raw_text")
    security_code = _first_text(
        candidates.get("证券代码"),
        event.get("security_code"),
        _infer_security_code_from_raw_text(raw_text, security_name),
    )
    review_reasons = [
        str(reason)
        for reason in as_list(event.get("review_reasons"))
        if reason not in (None, "")
    ]
    account_type = _infer_account_type(
        _first_text(candidates.get("账户类型"), event.get("account_type")),
        securities_account,
        security_code,
        review_reasons,
    )
    blocking_review_reasons = [
        reason
        for reason in review_reasons
        if not (full_only and _is_full_only_non_blocking_review_reason(reason))
    ]

    event_id = _business_event_id(event, index, auxiliary)
    payload = {
        "event_id": event_id,
        "account_type": account_type,
        "securities_account": securities_account,
        "person_name": _first_text(
            event.get("person_name"),
            event.get("holder_name"),
            candidates.get("姓名"),
        ),
        "proof_type": "无账户信息" if event_type == "no_account_info" else "",
        "event_category": event.get("event_category") or ("negative_proof" if event_type == "no_account_info" else ""),
        "event_type": event_type,
        "event_date": _first_text(candidates.get("日期"), event.get("event_date")),
        "event_time": auxiliary.get("event_time", ""),
        "serial_no": auxiliary.get("serial_no", ""),
        "order_no": auxiliary.get("order_no", ""),
        "security_code": security_code,
        "security_name": security_name,
        "direction": direction,
        "quantity_raw": _first_text(candidates.get("成交数量"), event.get("quantity")),
        "price_raw": _first_text(candidates.get("成交单价"), event.get("price")),
        "amount_raw": _first_text(candidates.get("收付金额"), event.get("amount")),
        "transfer_type_raw": raw_movement,
        "event_type_raw": raw_movement,
        "source_page": _source_value(event, "page"),
        "row_no": _source_value(event, "row_no"),
        "raw_text": raw_text,
        "review_reason": "；".join(blocking_review_reasons),
    }

    mapped_review_items: list[dict] = []

    for reason in blocking_review_reasons:
        mapped_review_items.append(
            _event_review_item(file_record, event_id, "review_reasons", reason)
        )

    if event.get("manual_review_required") is True and blocking_review_reasons:
        payload["manual_review_required"] = True
        payload["allow_full_table_with_review"] = True

    return payload, mapped_review_items


def _is_fund_flow_source(event: dict) -> bool:
    evidence = event.get("source_evidence") or {}
    if not isinstance(evidence, dict):
        evidence = {}
    text = "\n".join(
        _first_text(value)
        for value in (
            evidence.get("row_no"),
            evidence.get("raw_text"),
            event.get("row_no"),
            event.get("raw_text"),
            event.get("raw_summary"),
            event.get("review_reason"),
        )
        if _first_text(value)
    )
    return "资金流水明细" in text or "资金流水" in text


def _should_ignore_guangfa_fund_flow_trade(event: dict) -> bool:
    return (
        event.get("event_type") == "ordinary_trade"
        and event.get("direction") in {"buy", "sell"}
        and _is_fund_flow_source(event)
    )


def _reclassify_fund_flow_trade_if_needed(event: dict) -> bool:
    if not _should_ignore_guangfa_fund_flow_trade(event):
        return False
    event["event_type"] = "cash_flow"
    event["direction"] = ""
    event["event_category"] = event.get("event_category") or "fund_flow"
    event["review_reason"] = ""
    return True


def _map_negative_proof(proof: dict, index: int) -> dict:
    proof_type = _first_text(
        proof.get("inferred_event_type"),
        proof.get("proof_type"),
        proof.get("raw_business_type"),
        proof.get("raw_summary"),
    )
    if any(keyword in proof_type for keyword in ("无账户信息", "未查询到证券账户", "未开户", "无账户", "未开立", "无证券账户", "无股东账户")):
        event_type = "no_account_info"
        raw_type = "无账户信息"
    elif any(keyword in proof_type for keyword in ("持仓", "未持仓", "无持仓")):
        event_type = "no_holding_record"
        raw_type = "无持仓记录"
    else:
        event_type = "no_trade_record"
        raw_type = "无交易记录"

    source_evidence = proof.get("source_evidence") or {}
    if not isinstance(source_evidence, dict):
        source_evidence = {}
    if event_type == "no_account_info":
        return {
            "event_id": proof.get("event_id") or f"guangfa_no_account_info_{index + 1}",
            "event_type": event_type,
            "event_category": "negative_proof",
            "proof_type": "无账户信息",
            "event_date": _first_text(
                proof.get("as_of_date"),
                proof.get("query_date"),
                proof.get("event_date"),
                proof.get("period_end"),
            ),
            "person_name": _first_text(
                proof.get("person_name"),
                proof.get("holder_name"),
                proof.get("姓名"),
            ),
            "security_code": "",
            "security_name": "",
            "quantity_raw": "",
            "price_raw": "",
            "amount_raw": "",
            "balance_after_raw": "",
            "transfer_type_raw": raw_type,
            "source_page": _source_value(proof, "page"),
            "row_no": _source_value(proof, "row_no"),
            "raw_text": _first_text(
                source_evidence.get("raw_text"),
                proof.get("description"),
                proof.get("raw_summary"),
            ),
        }

    return {
        "event_id": proof.get("event_id") or f"guangfa_negative_proof_{index + 1}",
        "event_type": event_type,
        "event_date": _first_text(proof.get("event_date"), proof.get("period_end")),
        "period_start": _first_text(proof.get("period_start")),
        "period_end": _first_text(proof.get("period_end")),
        "account_type": _first_text(proof.get("account_type")),
        "securities_account": _first_text(proof.get("securities_account")),
        "security_code": "0",
        "security_name": "0",
        "quantity_raw": "0",
        "price_raw": "0",
        "amount_raw": "0",
        "balance_after_raw": "0",
        "transfer_type_raw": raw_type,
        "source_page": _source_value(proof, "page"),
        "row_no": _source_value(proof, "row_no"),
    }


def _map_business_holding(
    holding: dict,
    index: int,
    document_info: dict,
    file_record: dict,
) -> dict:
    candidates = holding.get("final_field_candidates") or {}
    if not isinstance(candidates, dict):
        candidates = {}

    def field(chinese_key: str, *holding_keys: str) -> str:
        return _first_text(
            candidates.get(chinese_key),
            holding.get(chinese_key),
            *(holding.get(key) for key in holding_keys),
        )

    security_code = field("证券代码", "security_code")
    securities_account = _first_text(
        candidates.get("证券账号"),
        holding.get("证券账号"),
        holding.get("securities_account"),
        holding.get("fund_account"),
    )
    review_reasons: list[str] = []
    account_type = _infer_account_type(
        field("账户类型", "account_type"),
        securities_account,
        security_code,
        review_reasons,
    )
    return {
        "holding_id": holding.get("holding_id") or f"guangfa_holding_{index + 1}",
        "account_type": account_type or document_info.get("account_type") or "",
        "securities_account": securities_account,
        "holding_date": _first_text(
            candidates.get("查询结果所属日期"),
            holding.get("查询结果所属日期"),
            holding.get("holding_date"),
            holding.get("date"),
        ),
        "security_code": security_code,
        "security_name": field("证券名称", "security_name"),
        "quantity_raw": field("持有数量", "quantity_raw", "quantity"),
        "market_value": field("市值", "market_value"),
        "currency": field("币种", "currency"),
        "source_page": _source_value(holding, "page"),
        "row_no": _source_value(holding, "row_no"),
        "review_reason": "；".join(review_reasons),
    }


def _is_blank_holding_record(holding: dict) -> bool:
    return not any(
        _first_text(holding.get(key))
        for key in ("security_code", "security_name", "quantity_raw")
    )


def _classify_business_event(raw_movement: str) -> tuple[str, str]:
    text = str(raw_movement or "").strip()
    if not text:
        return "unknown_event", ""
    if _is_ignored_non_holding_text(text):
        return "cash_flow", ""
    if any(keyword in text for keyword in ("无交易", "未交易", "没有交易", "历史成交为0")):
        return "no_trade_record", ""
    if any(keyword in text for keyword in ("无持仓", "未持仓", "没有持仓")):
        return "no_holding_record", ""
    if any(keyword in text for keyword in ("无账户信息", "未查询到证券账户", "未开户", "未开立", "无账户", "无证券账户", "无股东账户")):
        return "no_account_info", ""
    if "卖" in text:
        return "ordinary_trade", "sell"
    if "买" in text:
        return "ordinary_trade", "buy"
    if any(keyword in text for keyword in ("申购配号", "中购配号", "配号")):
        return "subscription_allotment", "subscribe"
    if any(keyword in text for keyword in ("打新", "新股申购", "新股中签")):
        return "new_share_subscription", "subscribe"
    if is_security_registration_text(text):
        return "security_registration", "registration_in"
    if any(keyword in text for keyword in ("送股", "转增", "配股入账")):
        return "bonus_share", "rights_event"
    if any(keyword in text for keyword in ("股息", "派息", "现金分红", "红利")):
        return "cash_dividend", "cash_income"
    if any(keyword in text for keyword in ("利息", "结息")):
        return "bond_interest", "cash_income"
    if any(keyword in text for keyword in ("银证转账", "银行转证券", "证券转银行", "资金流水", "费用", "税费")):
        return "cash_flow", ""
    return "unknown_event", ""


def _business_rule_should_be_final(event_type: str, raw_movement: str) -> bool:
    if _is_full_only_event(raw_movement, event_type):
        return False
    if event_type in {
        "ordinary_trade",
        "security_registration",
        "bonus_share",
        "new_share_subscription",
        "no_trade_record",
        "no_holding_record",
        "no_account_record",
        "no_account_info",
    }:
        return True
    return any(keyword in raw_movement for keyword in FINAL_EVENT_KEYWORDS)


def _is_full_only_event(raw_movement: str, event_type: str) -> bool:
    if event_type in {"subscription_allotment", "cash_dividend", "bond_interest", "cash_flow", "bank_transfer", "fund_transfer", "interest"}:
        return True
    return any(keyword in raw_movement for keyword in FULL_ONLY_EVENT_KEYWORDS)


def _is_full_only_non_blocking_review_reason(reason: str) -> bool:
    text = str(reason or "")
    if not text:
        return True
    if not any(keyword in text for keyword in ("缺少", "缺失", "不完整")):
        return False
    return any(
        field in text
        for field in (
            "证券代码",
            "证券名称",
            "账户类型",
            "证券账号",
            "成交数量",
            "成交单价",
            "单价",
            "收付金额",
            "金额",
        )
    )


def _should_ignore_non_holding_event(event: dict) -> bool:
    if is_pure_cash_flow_event(event):
        return True
    text = " ".join(
        _first_text(value)
        for value in (
            event.get("transfer_type_raw"),
            event.get("event_type_raw"),
            event.get("raw_business_type"),
            event.get("raw_summary"),
            event.get("review_reason"),
        )
        if _first_text(value)
    )
    return _is_ignored_non_holding_text(text)


def _is_ignored_non_holding_text(text: str) -> bool:
    value = str(text or "")
    return any(keyword in value for keyword in IGNORED_NON_HOLDING_EVENT_KEYWORDS)


def _missing_final_payload_fields(payload: dict, full_only: bool) -> list[str]:
    field_values = {
        "账户类型": payload.get("account_type"),
        "证券账号": payload.get("securities_account"),
        "证券代码": payload.get("security_code"),
        "证券名称": payload.get("security_name"),
        "变动类型": payload.get("transfer_type_raw") or payload.get("event_type"),
        "日期": payload.get("event_date"),
        "成交数量": payload.get("quantity_raw"),
        "成交单价": payload.get("price_raw"),
        "收付金额": payload.get("amount_raw"),
    }
    required = list(FINAL_ONLY_REQUIRED_KEYS)
    if full_only:
        required = [field for field in required if field not in {"成交数量", "成交单价"}]
    if payload.get("event_type") in {
        "security_registration",
        "bonus_share",
        "new_share_subscription",
        "new_bond_subscription",
    }:
        required = [
            field
            for field in required
            if field not in {"成交单价", "收付金额"}
        ]
    return [field for field in required if not _first_text(field_values.get(field))]


def _infer_account_type(
    explicit_account_type: str,
    securities_account: str,
    security_code: str,
    review_reasons: list[str],
) -> str:
    explicit = _normalize_account_type(explicit_account_type)
    if explicit:
        return explicit

    account_based = _account_type_from_securities_account(securities_account)
    code_based = _account_type_from_security_code(security_code)
    if account_based:
        if code_based and _account_market(account_based) != _account_market(code_based):
            review_reasons.append("证券账号推断账户类型与证券代码市场推断结果不一致")
        return account_based
    return code_based


def _normalize_account_type(value: str) -> str:
    text = str(value or "").strip()
    if text in ACCOUNT_TYPES:
        return text
    aliases = {
        "深圳A股": "深A",
        "上海A股": "沪A",
        "深市A股": "深A",
        "沪市A股": "沪A",
        "深圳信用": "深圳信用账户",
        "上海信用": "上海信用账户",
    }
    return aliases.get(text, "")


def _account_type_from_securities_account(securities_account: str) -> str:
    account = str(securities_account or "").strip()
    if account.startswith("06"):
        return "深圳信用账户"
    if account.startswith(("E", "e")):
        return "上海信用账户"
    return ""


def _account_type_from_security_code(security_code: str) -> str:
    code = str(security_code or "").strip()
    if code.startswith("6"):
        return "沪A"
    if code.startswith("7"):
        return "沪A"
    if code.startswith(("0", "3")):
        return "深A"
    if code.startswith(("83", "87", "88", "920")):
        return "北交所"
    return ""


def _account_market(account_type: str) -> str:
    if account_type in {"深A", "深B", "深圳信用账户"}:
        return "SZ"
    if account_type in {"沪A", "沪B", "上海信用账户"}:
        return "SH"
    if account_type == "北交所":
        return "BJ"
    return ""


def _business_event_auxiliary_fields(event: dict, candidates: dict) -> dict:
    evidence = event.get("source_evidence") or {}
    if not isinstance(evidence, dict):
        evidence = {}
    raw_text = _first_text(evidence.get("raw_text"), event.get("raw_text"), event.get("raw_summary"))
    parsed = _parse_auxiliary_from_raw_text(raw_text)
    return {
        "event_time": _normalize_time(
            _first_text(
                candidates.get("发生时间"),
                candidates.get("交易时间"),
                event.get("event_time"),
                event.get("trade_time"),
                parsed.get("event_time"),
            )
        ),
        "serial_no": _first_text(
            candidates.get("流水号"),
            candidates.get("流水序号"),
            event.get("serial_no"),
            event.get("transaction_id"),
            parsed.get("serial_no"),
        ),
        "order_no": _first_text(
            candidates.get("委托编号"),
            candidates.get("委托号"),
            event.get("order_no"),
            parsed.get("order_no"),
        ),
    }


def _infer_security_code_from_raw_text(raw_text: str, security_name: str) -> str:
    text = str(raw_text or "")
    name_key = _security_name_key(security_name)
    if not text or not name_key:
        return ""

    for match in re.finditer(r"(?<!\d)(\d{6})(?!\d)\s*([^\s\d,，。；;:：]{1,16})", text):
        candidate_name = _security_name_key(match.group(2))
        if candidate_name and (candidate_name == name_key or candidate_name in name_key or name_key in candidate_name):
            return match.group(1)
    return ""


def _security_name_key(value: str) -> str:
    text = re.sub(r"\s+", "", str(value or ""))
    for suffix in ("配号", "证券", "股票"):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
    return text


def _parse_auxiliary_from_raw_text(raw_text: str) -> dict:
    text = str(raw_text or "")
    result: dict[str, str] = {}
    match = re.search(
        r"\b20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}\s+(\d{6})\s+([A-Za-z0-9]{5,})",
        text,
    )
    if match:
        result["event_time"] = _normalize_time(match.group(1))
        result["serial_no"] = match.group(2)

    tokens = re.findall(r"\b[A-Za-z0-9]{4,}\b", text)
    if tokens:
        result["order_no"] = tokens[-1]
    return result


def _normalize_time(value: str) -> str:
    text = str(value or "").strip()
    if re.fullmatch(r"\d{6}", text):
        return f"{text[0:2]}:{text[2:4]}:{text[4:6]}"
    return text


def _business_event_id(event: dict, index: int, auxiliary: dict | None = None) -> str:
    auxiliary = auxiliary or {}
    evidence = event.get("source_evidence") or {}
    if not isinstance(evidence, dict):
        evidence = {}
    return (
        event.get("event_id")
        or auxiliary.get("serial_no")
        or auxiliary.get("order_no")
        or evidence.get("source_row_id")
        or evidence.get("row_no")
        or f"guangfa_business_event_{index + 1}"
    )


def _source_value(event: dict, key: str) -> str:
    evidence = event.get("source_evidence") or {}
    if not isinstance(evidence, dict):
        evidence = {}
    aliases = {
        "page": ("page", "source_page"),
        "row_no": ("row_no", "source_row_no"),
    }.get(key, (key,))
    for alias in aliases:
        value = event.get(alias)
        if value not in (None, ""):
            return str(value)
        value = evidence.get(alias)
        if value not in (None, ""):
            return str(value)
    return ""


def _event_review_item(
    file_record: dict,
    event_id: str,
    field: str,
    message: str,
) -> dict:
    item = review_item(
        "warning",
        "event",
        file_record.get("file_id") or "",
        event_id,
        field,
        message,
    )
    item["file_no"] = file_record.get("file_no", "")
    item["original_file_name"] = file_record.get("original_file_name", "")
    return item


def _first_text(*values) -> str:
    for value in values:
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _rows_from_group(group: dict | None, rows_key: str) -> list[dict]:
    if not isinstance(group, dict):
        return []

    columns = group.get("trade_columns") or group.get("columns") or []
    rows = []
    for values in as_list(group.get(rows_key)):
        if isinstance(values, dict):
            rows.append(values)
            continue
        if not isinstance(values, list):
            continue
        rows.append(
            {
                str(column): values[index] if index < len(values) else ""
                for index, column in enumerate(columns)
            }
        )
    return rows


def _map_group_event(event: dict) -> dict:
    payload = dict(event)
    payload.setdefault(
        "transaction_id",
        payload.get("trade_id")
        or payload.get("serial_no")
        or payload.get("order_no")
        or "",
    )
    payload.setdefault("transaction_date", payload.get("event_date") or payload.get("trade_date") or "")
    payload.setdefault("event_date", payload.get("trade_date") or payload.get("transaction_date") or "")
    payload.setdefault("event_time", payload.get("trade_time") or "")
    payload.setdefault(
        "transaction_type_raw",
        payload.get("transfer_type_raw") or payload.get("event_type_raw") or "",
    )
    payload.setdefault("event_type_raw", payload.get("transfer_type_raw") or payload.get("transaction_type_raw") or "")
    payload.setdefault("quantity_raw", payload.get("quantity") or "")
    payload.setdefault("price_raw", payload.get("price") or "")
    payload.setdefault("amount_raw", payload.get("amount") or payload.get("settlement_amount") or "")
    payload.setdefault("security_category_raw", payload.get("instrument_type") or "")
    _reclassify_group_event_by_business_type(payload)
    return payload


def _reclassify_group_event_by_business_type(payload: dict) -> None:
    raw_type = _first_text(
        payload.get("transfer_type_raw"),
        payload.get("transaction_type_raw"),
        payload.get("business_type_raw"),
        payload.get("event_type_raw"),
    )
    if _is_full_only_event(raw_type, _classify_business_event(raw_type)[0]):
        event_type, direction = _classify_business_event(raw_type)
        payload["event_type"] = event_type
        payload["direction"] = direction
        return
    if is_security_registration_text(raw_type):
        payload["event_type"] = "security_registration"
        payload["direction"] = "registration_in"


def _map_group_holding(holding: dict) -> dict:
    payload = dict(holding)
    payload.setdefault("quantity_raw", payload.get("quantity") or "")
    payload.setdefault("security_category_raw", payload.get("instrument_type") or "")
    return payload


def _event_id(event: dict, fallback: str) -> str:
    return (
        event.get("event_id")
        or event.get("transaction_id")
        or event.get("serial_no")
        or event.get("order_no")
        or event.get("cash_flow_id")
        or fallback
    )
