from __future__ import annotations

import re
from typing import Any


ACCOUNT_TYPE_ALIASES = {
    "沪A": "沪A",
    "上海A": "沪A",
    "上海A股": "沪A",
    "沪市A股": "沪A",
    "上交所": "沪A",
    "沪B": "沪B",
    "上海B": "沪B",
    "上海B股": "沪B",
    "沪市B股": "沪B",
    "深A": "深A",
    "深圳A": "深A",
    "深圳A股": "深A",
    "深市A股": "深A",
    "深交所": "深A",
    "深B": "深B",
    "深圳B": "深B",
    "深圳B股": "深B",
    "深市B股": "深B",
    "上海信用账户": "上海信用账户",
    "深圳信用账户": "深圳信用账户",
}


def clean_security_account(value: Any) -> str:
    text = re.sub(r"\s+", "", str(value or "").strip())
    return re.sub(r"[（(].*$", "", text)


def normalize_account_type(value: Any) -> str:
    text = str(value or "").strip()
    return ACCOUNT_TYPE_ALIASES.get(text, text)


def is_security_account(value: Any, account_type_hint: Any = "") -> bool:
    return bool(classify_security_account(value, account_type_hint))


def classify_security_account(value: Any, account_type_hint: Any = "") -> str:
    account = clean_security_account(value)
    if not account:
        return ""
    hint = normalize_account_type(account_type_hint)
    inferred = _infer_account_type_from_shape(account)
    if hint in {"沪A", "沪B", "深A", "深B", "上海信用账户", "深圳信用账户"}:
        return hint if _account_type_compatible(hint, inferred, account) else ""
    return inferred


def extract_security_account_from_text(text: str, account_type_hint: Any = "") -> str:
    for pattern in (
        r"(?:证券账户|证券账号|证券子账户|股东代码|股东卡号)[:：\s]*([A-Za-z]?\d{7,10})",
    ):
        for match in re.finditer(pattern, str(text or "")):
            account = clean_security_account(match.group(1))
            if classify_security_account(account, account_type_hint):
                return account
    return ""


def infer_account_type_from_text(text: str) -> str:
    source = str(text or "")
    for label in ("沪A", "深A", "沪B", "深B"):
        if label in source:
            return label
    if "上海A" in source or "上交所" in source or "沪市" in source:
        return "沪A"
    if "深圳A" in source or "深交所" in source or "深市" in source:
        return "深A"
    if "上海B" in source:
        return "沪B"
    if "深圳B" in source:
        return "深B"
    return ""


def market_from_account_type(account_type: Any) -> str:
    text = normalize_account_type(account_type)
    if text in {"沪A", "沪B", "上海信用账户"}:
        return "上海"
    if text in {"深A", "深B", "深圳信用账户"}:
        return "深圳"
    return ""


def _infer_account_type_from_shape(account: str) -> str:
    text = account.upper()
    if re.fullmatch(r"A\d{9}", text):
        return "沪A"
    if re.fullmatch(r"E\d{9}", text):
        return "上海信用账户"
    if re.fullmatch(r"F\d{9}", text):
        return "沪A"
    if re.fullmatch(r"C\d{9,10}", text):
        return "沪B"
    if re.fullmatch(r"06\d{8}", text):
        return "深圳信用账户"
    if re.fullmatch(r"2\d{9}", text):
        return "深B"
    if re.fullmatch(r"0\d{7,9}", text):
        return "深A"
    return ""


def _account_type_compatible(hint: str, inferred: str, account: str) -> bool:
    if not inferred:
        return False
    if hint == inferred:
        return True
    if hint == "沪A" and inferred in {"上海信用账户"}:
        return True
    if hint == "深A" and inferred in {"深圳信用账户"}:
        return True
    if hint == "沪A" and account.upper().startswith("F"):
        return True
    return False
