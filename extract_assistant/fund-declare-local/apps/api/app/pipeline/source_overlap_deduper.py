from __future__ import annotations

from typing import Any

from app.pipeline.normalizers.common import as_list, unique_list


def dedupe_source_overlap_rows(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Merge duplicates caused by extraction batch overlap using source trace only."""

    deduped: list[dict] = []
    rows_by_source_key: dict[tuple, dict] = {}
    audit: list[dict] = []

    for row in rows:
        candidate = dict(row)
        key = _source_overlap_key(candidate)
        if key and key in rows_by_source_key:
            target = rows_by_source_key[key]
            _merge_overlap_row(target, candidate)
            audit.append(
                {
                    "action": "merged_source_overlap_duplicate",
                    "source_key": "|".join(str(part) for part in key),
                    "kept_record_id": target.get("event_id") or "",
                    "merged_record_id": candidate.get("event_id") or "",
                    "reason": "同一原始来源行在分批 overlap 中重复抽取，已按 trace 合并",
                }
            )
            continue
        if key:
            rows_by_source_key[key] = candidate
        deduped.append(candidate)

    return deduped, audit


def _source_overlap_key(row: dict) -> tuple:
    evidence = _first_evidence(row)
    file_id = _text(evidence.get("file_id")) or _text(row.get("file_id"))
    source_row_id = _text(evidence.get("source_row_id") or evidence.get("row_id"))
    source_page = _text(evidence.get("source_page") or evidence.get("page"))
    row_no = _text(evidence.get("row_no"))
    raw_text = _text(evidence.get("raw_text"))

    if file_id and source_row_id and _looks_like_structural_row_id(source_row_id):
        return (file_id, source_row_id)
    if file_id and source_page and row_no:
        return (file_id, source_page, row_no, raw_text[:80])
    return ()


def _first_evidence(row: dict) -> dict:
    for item in as_list(row.get("source_evidence")):
        if isinstance(item, dict):
            return item
    return {}


def _looks_like_structural_row_id(value: str) -> bool:
    text = value.lower()
    return any(marker in text for marker in ("row", "line", "table", "cell", "chunk"))


def _merge_overlap_row(target: dict, source: dict) -> None:
    for field, value in source.items():
        if field == "source_evidence":
            target[field] = _merge_evidence(target.get(field), value)
            continue
        if target.get(field) in (None, "") and value not in (None, ""):
            target[field] = value
    target["overlap_merged_record_ids"] = unique_list(
        as_list(target.get("overlap_merged_record_ids"))
        + [source.get("event_id") or source.get("holding_id") or ""]
    )


def _merge_evidence(*sources: Any) -> list[dict]:
    evidence: list[dict] = []
    seen = set()
    for source in sources:
        for item in as_list(source):
            if not isinstance(item, dict):
                continue
            key = (
                item.get("file_id", ""),
                item.get("source_row_id", ""),
                item.get("source_page", ""),
                item.get("row_no", ""),
                item.get("raw_text", ""),
            )
            if key in seen:
                continue
            seen.add(key)
            evidence.append(item)
    return evidence


def _text(value: Any) -> str:
    return str(value or "").strip()
