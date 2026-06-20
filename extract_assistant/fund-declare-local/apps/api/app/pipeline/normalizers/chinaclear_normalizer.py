from __future__ import annotations

from app.pipeline.normalizers.common import (
    as_list,
    build_event_row,
    build_holding_row,
    build_normalized_result,
)


POSITION_COLUMNS = [
    "position_id",
    "market",
    "holding_date",
    "security_code",
    "security_name",
    "security_category_raw",
    "quantity_raw",
    "custody_or_trading_unit",
    "custody_or_trading_unit_name",
    "source_page",
    "row_no",
]


def normalize_chinaclear(case_id: str, extract_result: dict, file_record: dict) -> dict:
    document_info = extract_result.get("document_info") or {}
    full_rows = []

    trade_group = extract_result.get("trade_group") or {}
    trade_columns = trade_group.get("trade_columns") or []
    for trade_index, trade_values in enumerate(as_list(trade_group.get("trades"))):
        if not isinstance(trade_values, list):
            continue

        trade = {
            str(column): trade_values[index] if index < len(trade_values) else ""
            for index, column in enumerate(trade_columns)
        }
        full_rows.append(
            build_event_row(
                case_id,
                file_record,
                document_info,
                {
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
                },
            )
        )

    for other_event in as_list(extract_result.get("other_events")):
        if isinstance(other_event, dict):
            full_rows.append(
                build_event_row(case_id, file_record, document_info, other_event)
            )

    for legacy_event in as_list(extract_result.get("events")):
        if isinstance(legacy_event, dict):
            full_rows.append(
                build_event_row(case_id, file_record, document_info, legacy_event)
            )

    holding_rows = [
        build_holding_row(case_id, file_record, document_info, holding)
        for holding in _position_group_rows(extract_result.get("position_group"))
    ]
    holding_rows.extend(
        build_holding_row(case_id, file_record, document_info, holding)
        for holding in as_list(extract_result.get("holdings"))
        if isinstance(holding, dict)
    )
    return build_normalized_result(full_rows, holding_rows)


def _position_group_rows(position_group: dict | None) -> list[dict]:
    if not isinstance(position_group, dict):
        return []

    columns = (
        position_group.get("position_columns")
        or position_group.get("columns")
        or POSITION_COLUMNS
    )
    rows = []
    for position_values in as_list(position_group.get("positions")):
        if isinstance(position_values, dict):
            rows.append(_map_position(position_values))
            continue
        if not isinstance(position_values, list):
            continue

        position = {
            str(column): position_values[index] if index < len(position_values) else ""
            for index, column in enumerate(columns)
        }
        rows.append(_map_position(position))
    return rows


def _map_position(position: dict) -> dict:
    payload = dict(position)
    payload.setdefault("holding_id", payload.get("position_id") or "")
    payload.setdefault("quantity_raw", payload.get("holding_quantity_raw") or payload.get("quantity") or "")
    payload.setdefault("security_category_raw", payload.get("security_category") or "")
    return payload
