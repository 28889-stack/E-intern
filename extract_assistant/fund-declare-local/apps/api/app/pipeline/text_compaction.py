from __future__ import annotations

import re
from typing import Any


DEFAULT_TEXT_LIMIT = 120
DEFAULT_MESSAGE_LIMIT = 180
DEFAULT_EVIDENCE_LIMIT = 220
MAX_EVIDENCE_ITEMS = 5


def compact_text(value: Any, limit: int = DEFAULT_TEXT_LIMIT) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}..."


def compact_review_message(value: Any) -> str:
    return compact_text(value, DEFAULT_MESSAGE_LIMIT)


def compact_evidence_text(value: Any) -> str:
    return compact_text(value, DEFAULT_EVIDENCE_LIMIT)


def compact_source_evidence(value: Any) -> list[dict]:
    evidence_items = value if isinstance(value, list) else ([value] if value else [])
    compacted = []
    for item in evidence_items[:MAX_EVIDENCE_ITEMS]:
        if not isinstance(item, dict):
            continue
        next_item = dict(item)
        if "raw_text" in next_item:
            next_item["raw_text"] = compact_text(next_item.get("raw_text"))
        compacted.append(next_item)
    return compacted


def compact_string_list(values: Any, limit: int = DEFAULT_EVIDENCE_LIMIT) -> list[str]:
    if values is None:
        return []
    items = values if isinstance(values, list) else [values]
    return [
        compact_text(item, limit)
        for item in items[:MAX_EVIDENCE_ITEMS]
        if str(item or "").strip()
    ]
