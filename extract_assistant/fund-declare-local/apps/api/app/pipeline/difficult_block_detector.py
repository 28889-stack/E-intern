from __future__ import annotations

from collections import Counter
from typing import Any


OCR_CONFIDENCE_THRESHOLD = 0.85


def detect_difficult_blocks(document_blocks: dict[str, Any]) -> dict[str, Any]:
    difficult_blocks = []

    for block in document_blocks.get("blocks", []) or []:
        reasons = _difficulty_reasons(block)
        if not reasons:
            continue
        difficult_blocks.append(
            {
                "block_id": block.get("block_id", ""),
                "page_no": block.get("page_no"),
                "block_type": block.get("block_type", ""),
                "difficulty_reasons": reasons,
                "image_refs": block.get("image_refs", []),
            }
        )

    return {
        "difficulty_status": (
            "has_difficult_blocks" if difficult_blocks else "no_difficult_blocks"
        ),
        "difficult_block_count": len(difficult_blocks),
        "difficult_blocks": difficult_blocks,
    }


def _difficulty_reasons(block: dict[str, Any]) -> list[str]:
    reasons = []
    if _is_low_confidence_ocr(block):
        reasons.append("ocr_low_confidence")
    if _has_unstable_table_columns(block):
        reasons.append("unstable_table_columns")
    if _looks_like_broken_text(block):
        reasons.append("possible_broken_text")
    return reasons


def _is_low_confidence_ocr(block: dict[str, Any]) -> bool:
    if block.get("block_type") != "ocr_text":
        return False
    confidence = (block.get("source") or {}).get("confidence_avg")
    try:
        return confidence is not None and float(confidence) < OCR_CONFIDENCE_THRESHOLD
    except (TypeError, ValueError):
        return False


def _has_unstable_table_columns(block: dict[str, Any]) -> bool:
    if block.get("block_type") != "pdf_table":
        return False
    row_lengths = [
        len(row)
        for row in block.get("table_rows", []) or []
        if isinstance(row, list) and any(str(cell).strip() for cell in row)
    ]
    if len(row_lengths) < 3:
        return False

    most_common_length, count = Counter(row_lengths).most_common(1)[0]
    short_or_long_rows = [
        length for length in row_lengths if abs(length - most_common_length) >= 1
    ]
    return count < len(row_lengths) and bool(short_or_long_rows)


def _looks_like_broken_text(block: dict[str, Any]) -> bool:
    text = str(block.get("text") or "")
    if block.get("block_type") not in {"pdf_text", "ocr_text"} or len(text) < 40:
        return False

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 6:
        return False

    very_short_lines = [line for line in lines if len(line) <= 4]
    return len(very_short_lines) / len(lines) >= 0.35
