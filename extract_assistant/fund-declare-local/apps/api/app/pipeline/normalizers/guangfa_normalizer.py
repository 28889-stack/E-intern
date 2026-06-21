from __future__ import annotations

from app.pipeline.normalizers.common import (
    as_list,
    build_event_row,
    build_holding_row,
    build_normalized_result,
    empty_record_event_from_semantics,
    review_item,
)


def normalize_guangfa(case_id: str, extract_result: dict, file_record: dict) -> dict:
    document_info = extract_result.get("document_info") or {}
    full_rows = []
    review_items = []

    for index, trade in enumerate(
        _rows_from_group(extract_result.get("trade_group"), "trades")
    ):
        event = _map_group_event(trade)
        event.setdefault("event_id", _event_id(trade, f"guangfa_trade_{index + 1}"))
        event.setdefault("event_type", "ordinary_trade")
        full_rows.append(build_event_row(case_id, file_record, document_info, event))

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

    if not full_rows and not holding_rows:
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

    return build_normalized_result(full_rows, holding_rows, review_items)


def _rows_from_group(group: dict | None, rows_key: str) -> list[dict]:
    if not isinstance(group, dict):
        return []

    columns = group.get("columns") or []
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
    payload.setdefault("transaction_id", payload.get("serial_no") or payload.get("order_no") or "")
    payload.setdefault("transaction_date", payload.get("event_date") or "")
    payload.setdefault("transaction_type_raw", payload.get("event_type_raw") or "")
    payload.setdefault("quantity_raw", payload.get("quantity") or "")
    payload.setdefault("price_raw", payload.get("price") or "")
    payload.setdefault("security_category_raw", payload.get("instrument_type") or "")
    return payload


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
