from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.pipeline.document_context import build_document_context, merge_document_info
from app.pipeline.security_account import (
    classify_security_account,
    extract_security_account_from_text,
    infer_account_type_from_text,
)
from app.services import local_store


ACCOUNT_MATERIAL_CONTENT_TYPES = {"guangfa", "chinaclear"}
NO_ACCOUNT_EVENT_TYPES = {"no_account_info", "no_account_record"}


def collect_material_validity_issues(
    file_record: dict,
    output_dir: Path,
    extract_result: dict,
    *,
    transaction_rows: list[dict] | None = None,
    holding_rows: list[dict] | None = None,
) -> list[dict]:
    """Check file-level business validity without changing event-level rows."""

    if not _is_account_material(file_record, extract_result):
        return []

    rows = [*(transaction_rows or []), *(holding_rows or [])]
    source_text = _source_text(output_dir, extract_result)
    if _has_no_account_proof(rows, extract_result, source_text):
        return []

    document_info = merge_document_info(
        build_document_context(output_dir),
        extract_result.get("document_info"),
    )
    evidence = _material_evidence(document_info, rows, source_text)

    issues = []
    if not evidence["has_securities_account"]:
        issues.append(
            _issue(
                file_record,
                "material_missing_securities_account",
                "整份材料未识别到证券账号，无法确认交易/持仓归属。",
            )
        )
    if not evidence["has_period"]:
        issues.append(
            _issue(
                file_record,
                "material_missing_period",
                "整份材料未识别到交易日期、持仓日期或查询时间范围。",
            )
        )
    if not evidence["has_market"]:
        issues.append(
            _issue(
                file_record,
                "material_missing_market",
                "整份材料未识别到账户类型或市场信息。",
            )
        )
    return issues


def _is_account_material(file_record: dict, extract_result: dict) -> bool:
    module = str(file_record.get("module") or "").strip()
    content_type = str(
        extract_result.get("content_type") or file_record.get("content_type") or ""
    ).strip()
    if module and module != "account_info":
        return False
    return content_type in ACCOUNT_MATERIAL_CONTENT_TYPES


def _has_no_account_proof(rows: list[dict], extract_result: dict, source_text: str) -> bool:
    if any(str(row.get("event_type") or "") in NO_ACCOUNT_EVENT_TYPES for row in rows):
        return True
    for proof in _as_list(extract_result.get("negative_proofs")):
        if not isinstance(proof, dict):
            continue
        proof_type = str(proof.get("proof_type") or proof.get("type") or "")
        if any(keyword in proof_type for keyword in ("无账户", "未开户", "no_account")):
            return True
    return any(
        keyword in source_text
        for keyword in (
            "未开立证券账户",
            "未开通证券账户",
            "未开户",
            "没有开立证券账户",
            "无证券账户",
            "无账户信息",
        )
    )


def _material_evidence(document_info: dict, rows: list[dict], source_text: str) -> dict:
    account_type_hint = _first_account_type(document_info, rows, source_text)
    return {
        "has_securities_account": _has_valid_security_account(
            rows,
            document_info,
            account_type_hint,
        )
        or bool(_find_account(source_text, account_type_hint)),
        "has_period": _has_row_or_document_value(
            rows,
            document_info,
            ("event_date", "holding_date", "period_start", "period_end"),
        )
        or bool(_find_date(source_text)),
        "has_market": _has_row_or_document_value(
            rows,
            document_info,
            ("market", "account_type"),
        )
        or bool(document_info.get("securities_accounts"))
        or bool(_find_market(source_text)),
    }


def _has_row_or_document_value(
    rows: list[dict],
    document_info: dict,
    fields: tuple[str, ...],
) -> bool:
    for field in fields:
        if _usable(document_info.get(field)):
            return True
    for row in rows:
        for field in fields:
            if _usable(row.get(field)):
                return True
    return False


def _has_valid_security_account(
    rows: list[dict],
    document_info: dict,
    account_type_hint: str,
) -> bool:
    for value in _as_list(document_info.get("securities_account")):
        if classify_security_account(value, account_type_hint):
            return True
    accounts = document_info.get("securities_accounts")
    if isinstance(accounts, dict):
        for account_type, account in accounts.items():
            if classify_security_account(account, account_type):
                return True
    for row in rows:
        if classify_security_account(row.get("securities_account"), row.get("account_type") or account_type_hint):
            return True
    return False


def _first_account_type(document_info: dict, rows: list[dict], source_text: str) -> str:
    for key in ("account_type", "market"):
        value = str(document_info.get(key) or "").strip()
        if value:
            return value
    for row in rows:
        value = str(row.get("account_type") or row.get("market") or "").strip()
        if value:
            return value
    return infer_account_type_from_text(source_text)


def _source_text(output_dir: Path, extract_result: dict) -> str:
    parts = []
    for value in (
        extract_result.get("input_text"),
        extract_result.get("source_text"),
        extract_result.get("raw_text"),
    ):
        if isinstance(value, str) and value.strip():
            parts.append(value)
    for file_name in ("raw_text.json", "ocr_result.json"):
        parts.extend(_text_from_payload(local_store.read_json(output_dir / file_name, {})))
    return "\n".join(part for part in parts if part)


def _text_from_payload(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return []
    parts = []
    for key in ("text", "raw_text"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value)
    for page in payload.get("pages") or payload.get("page_results") or []:
        if isinstance(page, dict):
            value = page.get("text") or page.get("ocr_text") or ""
            if isinstance(value, str) and value.strip():
                parts.append(value)
    return parts


def _find_account(text: str, account_type_hint: str = "") -> str:
    return extract_security_account_from_text(text, account_type_hint)


def _find_date(text: str) -> str:
    return ",".join(re.findall(r"20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}日?", text))


def _find_market(text: str) -> str:
    match = re.search(r"(沪A|深A|沪B|深B|上海A|深圳A|上海B|深圳B|沪市|深市|上交所|深交所)", text)
    return match.group(1) if match else ""


def _issue(file_record: dict, issue_type: str, evidence: str) -> dict:
    return {
        "file_id": str(file_record.get("file_id") or ""),
        "issue_type": issue_type,
        "severity": "warning",
        "evidence": evidence,
        "suggested_action": "请核对原始材料是否包含证券账号、查询时间和市场/账户类型；如缺失，请补充有效材料。",
    }


def _usable(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(text and text not in {"0", "/", "-", "无", "空", "None"})


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]
