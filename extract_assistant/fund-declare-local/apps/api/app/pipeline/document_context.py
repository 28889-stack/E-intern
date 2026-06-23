from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.services import local_store


CONTEXT_TEXT_LIMIT = 1800


def build_document_context(output_dir: Path) -> dict:
    text = _read_source_text(output_dir)
    lines = _non_empty_lines(text)

    securities_accounts = _extract_securities_accounts(text, lines)
    securities_account, account_type = _extract_securities_account(
        text,
        lines,
        securities_accounts,
    )
    period_start, period_end = _extract_period(text)
    context = {
        "document_title": _extract_document_title(lines),
        "holder_name": _extract_holder_name(text, lines),
        "one_code_account": _extract_one_code_account(text, lines),
        "securities_account": securities_account,
        "securities_accounts": securities_accounts,
        "account_type": account_type,
        "capital_account": _extract_labeled_value(lines, ("资金账号", "资金帐号")),
        "period_start": period_start,
        "period_end": period_end,
        "context_excerpt": text[:CONTEXT_TEXT_LIMIT].strip(),
    }
    return {key: value for key, value in context.items() if value}


def format_document_context(context: dict) -> str:
    if not context:
        return "{}"
    compact_context = {
        key: value
        for key, value in context.items()
        if key != "context_excerpt"
    }
    return json.dumps(compact_context, ensure_ascii=False, indent=2)


def merge_document_info(primary: dict | None, secondary: dict | None) -> dict:
    merged = {}
    for source in (primary or {}, secondary or {}):
        if not isinstance(source, dict):
            continue
        for key, value in source.items():
            if key == "context_excerpt":
                continue
            if key not in merged or not merged[key]:
                merged[key] = value
    return merged


def _read_source_text(output_dir: Path) -> str:
    text_parts: list[str] = []
    for file_name in ("raw_text.json", "ocr_result.json"):
        payload = local_store.read_json(output_dir / file_name, {})
        text_parts.extend(_text_from_payload(payload))
    return "\n".join(part for part in text_parts if part).strip()


def _text_from_payload(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return []

    text_parts = []
    for key in ("text", "raw_text"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            text_parts.append(value)

    for page in payload.get("pages") or payload.get("page_results") or []:
        if isinstance(page, dict):
            value = page.get("text") or page.get("ocr_text") or ""
            if isinstance(value, str) and value.strip():
                page_no = page.get("page") or page.get("page_no")
                prefix = f"[PAGE {page_no}]\n" if page_no else ""
                text_parts.append(prefix + value)
    return text_parts


def _non_empty_lines(text: str) -> list[str]:
    return [line.strip() for line in str(text or "").splitlines() if line.strip()]


def _extract_document_title(lines: list[str]) -> str:
    for line in lines[:20]:
        if any(keyword in line for keyword in ("对账单", "证券持有变更信息", "开户证明", "账户")):
            return line
    return lines[0] if lines else ""


def _extract_holder_name(text: str, lines: list[str]) -> str:
    labeled = _extract_labeled_value(
        lines,
        ("客户姓名", "账户姓名", "持有人名称", "投资者姓名", "姓名"),
    )
    if _looks_like_person_name(labeled):
        return labeled

    split_layout_name = _extract_split_layout_holder_name(lines)
    if split_layout_name:
        return split_layout_name

    for pattern in (
        r"(?:客户姓名|账户姓名|持有人名称|投资者姓名|姓名)[:： \t]*([\u4e00-\u9fff]{1,8})",
        r"(?:截至|截止).*?([\u4e00-\u9fff]{1,8}).*?(?:无账户信息|未开立|未开户)",
    ):
        match = re.search(pattern, text)
        if match and _looks_like_person_name(match.group(1)):
            return match.group(1).strip()

    for index, line in enumerate(lines):
        if "一码通账户号码" in line and index > 0 and _looks_like_person_name(lines[index - 1]):
            return lines[index - 1]
    return ""


def _extract_split_layout_holder_name(lines: list[str]) -> str:
    for index, line in enumerate(lines):
        if "持有人名称" not in line and "投资者姓名" not in line and "客户姓名" not in line:
            continue

        for offset in range(1, 7):
            for candidate_index in (index + offset, index - offset):
                if candidate_index < 0 or candidate_index >= len(lines):
                    continue
                candidate = lines[candidate_index]
                if _looks_like_label(candidate):
                    continue
                if _looks_like_person_name(candidate):
                    return candidate
    return ""


def _extract_one_code_account(text: str, lines: list[str]) -> str:
    value = _extract_labeled_value(lines, ("一码通账户号码", "一码通账号", "一码通账户"))
    if _looks_like_account(value):
        return value
    match = re.search(r"一码通账户(?:号码|账号)?[:：\s]*([A-Za-z0-9]{6,})", text)
    return match.group(1).strip() if match else ""


def _extract_securities_accounts(text: str, lines: list[str]) -> dict[str, str]:
    market_labels = (
        ("上海A股东卡号", "沪A"),
        ("上海B股东卡号", "沪B"),
        ("深圳A股东卡号", "深A"),
        ("深圳B股东卡号", "深B"),
    )
    accounts = {}
    for label, account_type in market_labels:
        value = _extract_labeled_value(lines, (label,))
        if _looks_like_account(value):
            accounts[account_type] = _clean_account(value)

    table_accounts = _extract_basic_info_account_table(lines)
    for account_type, account in table_accounts.items():
        accounts.setdefault(account_type, account)

    return accounts


def _extract_securities_account(
    text: str,
    lines: list[str],
    securities_accounts: dict[str, str] | None = None,
) -> tuple[str, str]:
    accounts = securities_accounts or {}
    if len(accounts) == 1:
        account_type, account = next(iter(accounts.items()))
        return account, account_type

    for pattern in (
        r"([A-Za-z]?\d{6,12})（非定向资管账户）",
        r"证券子账户(?:号码|账号)?[:：\s]*([A-Za-z]?\d{6,12})",
        r"证券账户(?:号码|账号)?[:：\s]*([A-Za-z]?\d{6,12})",
    ):
        match = re.search(pattern, text)
        if match:
            account = _clean_account(match.group(1))
            return account, _infer_account_type(account, text)

    value = _extract_labeled_value(lines, ("证券子账户", "证券子账户号码", "证券账号", "证券账户"))
    if _looks_like_account(value):
        account = _clean_account(value)
        return account, _infer_account_type(account, text)
    return "", ""


def _extract_basic_info_account_table(lines: list[str]) -> dict[str, str]:
    labels = [
        ("上海A股东卡号", "沪A"),
        ("上海B股东卡号", "沪B"),
        ("深圳A股东卡号", "深A"),
        ("深圳B股东卡号", "深B"),
    ]
    label_to_type = {label: account_type for label, account_type in labels}
    label_indices = {
        label: index
        for index, line in enumerate(lines)
        for label in label_to_type
        if line == label
    }
    if not label_indices:
        return {}

    first_label_index = min(label_indices.values())
    while first_label_index > 0 and _looks_like_basic_info_label(lines[first_label_index - 1]):
        first_label_index -= 1
    table_labels = []
    index = first_label_index
    while index < len(lines) and _looks_like_basic_info_label(lines[index]):
        table_labels.append(lines[index])
        index += 1

    values = []
    while index < len(lines) and len(values) < len(table_labels):
        line = lines[index]
        if _looks_like_section_title(line):
            break
        values.append(line)
        index += 1

    accounts = {}
    for label, value in zip(table_labels, values):
        account_type = label_to_type.get(label)
        if account_type and _looks_like_account(value):
            accounts[account_type] = _clean_account(value)
    return accounts


def _looks_like_basic_info_label(value: str) -> bool:
    return any(
        keyword in str(value or "")
        for keyword in (
            "账户姓名",
            "资金账号",
            "资金帐号",
            "股东卡号",
            "证件类型",
            "证件号码",
            "客户姓名",
        )
    )


def _looks_like_section_title(value: str) -> bool:
    text = str(value or "").strip()
    return text in {"资产信息", "持仓信息", "资金流水明细", "场内交割流水明细"}


def _extract_period(text: str) -> tuple[str, str]:
    match = re.search(
        r"(20\d{2}[-/]\d{1,2}[-/]\d{1,2})\s*(?:至|到|--|—|-)\s*(20\d{2}[-/]\d{1,2}[-/]\d{1,2})",
        text,
    )
    if match:
        return _normalize_date(match.group(1)), _normalize_date(match.group(2))

    date = _extract_labeled_date(
        text,
        ("查询日期", "截止日期", "截至日期", "持有日期", "打印日期"),
    )
    return "", date


def _extract_labeled_date(text: str, labels: tuple[str, ...]) -> str:
    label_pattern = "|".join(re.escape(label) for label in labels)
    match = re.search(rf"(?:{label_pattern})[:：\s]*(20\d{{2}}[-/年]\d{{1,2}}[-/月]\d{{1,2}}日?)", text)
    return _normalize_date(match.group(1)) if match else ""


def _extract_labeled_value(lines: list[str], labels: tuple[str, ...]) -> str:
    for index, line in enumerate(lines):
        for label in labels:
            if label not in line:
                continue
            after_label = line.split(label, 1)[1].strip(" ：:")
            if _usable_value(after_label):
                return _clean_value(after_label)
            for next_line in lines[index + 1 : index + 5]:
                if _looks_like_label(next_line):
                    continue
                if _usable_value(next_line):
                    return _clean_value(next_line)
    return ""


def _usable_value(value: str) -> bool:
    text = str(value or "").strip()
    return bool(text and text not in {"/", "-", "无", "空"})


def _looks_like_label(value: str) -> bool:
    return bool(re.search(r"(账号|帐号|号码|卡号|姓名|名称|类型|日期|区间|条件|类别)[:：]?$", value))


def _looks_like_account(value: str) -> bool:
    text = _clean_account(value)
    return bool(re.fullmatch(r"[A-Za-z]?\d{5,15}", text))


def _looks_like_person_name(value: str) -> bool:
    text = str(value or "").strip()
    if text in {"证件号码", "证券子账户号码", "一码通账户号码", "持有人名称", "客户姓名"}:
        return False
    return bool(re.fullmatch(r"[\u4e00-\u9fff]{1,8}", text))


def _clean_value(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "").strip())


def _clean_account(value: str) -> str:
    text = _clean_value(value)
    return re.sub(r"[（(].*$", "", text).strip()


def _normalize_date(value: str) -> str:
    text = str(value or "").strip().replace("年", "-").replace("月", "-").replace("日", "")
    match = re.fullmatch(r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})", text)
    if not match:
        return text
    return f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"


def _infer_account_type(account: str, text: str) -> str:
    if "深市B股" in text or "深圳B股东卡号" in text:
        return "深B"
    if "沪市B股" in text or "上海B股东卡号" in text:
        return "沪B"
    if "深市" in text or "深圳A股东卡号" in text:
        return "深A"
    if "沪市" in text or "上海A股东卡号" in text:
        return "沪A"
    if str(account or "").startswith("02"):
        return "深A"
    return ""
