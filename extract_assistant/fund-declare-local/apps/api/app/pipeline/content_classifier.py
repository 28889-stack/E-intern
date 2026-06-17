from pathlib import Path
from typing import Any

from app.services.local_store import read_json


CONTENT_KEYWORDS = {
    "identity": [
        "身份证",
        "公民身份号码",
        "姓名",
        "住址",
        "签发机关",
        "有效期限",
        "居民身份证",
    ],
    "guangfa": [
        "广发证券",
        "广发",
        "广发证券股份有限公司",
        "对账单",
        "资金账号",
        "股东卡号",
        "场内交割流水",
        "证券买入",
        "证券卖出",
        "客户号",
        "营业部",
    ],
    "chinaclear": [
        "中国证券登记结算",
        "中国结算",
        "中证登",
        "证券登记结算",
        "证券持有人",
        "证券账户",
        "过户日期",
        "发生日期",
        "证券登记入账",
        "深市",
        "沪市",
    ],
}


def classify_content(
    file_path: str | Path,
    process_output_dir: str | Path,
    original_file_name: str | None = None,
) -> dict:
    output_dir = Path(process_output_dir)
    file_name = original_file_name or Path(file_path).name
    body_text = _collect_body_text(output_dir)
    file_name_text = file_name.lower()
    body_text_lower = body_text.lower()

    scores: dict[str, int] = {}
    matches: dict[str, list[str]] = {}

    for content_type, keywords in CONTENT_KEYWORDS.items():
        score = 0
        matched_keywords = []

        for keyword in keywords:
            keyword_lower = keyword.lower()
            keyword_matched = False

            if keyword_lower in body_text_lower:
                score += 1
                keyword_matched = True

            if keyword_lower in file_name_text:
                score += 2
                keyword_matched = True

            if keyword_matched:
                matched_keywords.append(keyword)

        scores[content_type] = score
        matches[content_type] = matched_keywords

    ranked_scores = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_type, best_score = ranked_scores[0]
    second_score = ranked_scores[1][1] if len(ranked_scores) > 1 else 0

    if best_score == 0:
        content_type = "unknown"
        matched_keywords: list[str] = []
        manual_review_required = True
        review_reasons = ["未命中文件内容分流关键词"]
        reason = "未从文件名、PDF 文本、OCR 文本或表格文本中识别出材料类型关键词"
        confidence = 0.0
    else:
        content_type = best_type
        matched_keywords = matches[best_type]
        manual_review_required = (best_score - second_score) < 2
        review_reasons = (
            ["文件内容分流结果不够明确"] if manual_review_required else []
        )
        reason = (
            f"{content_type} 得分最高：{best_score}；"
            f"第二高分：{second_score}；"
            f"命中关键词：{', '.join(matched_keywords)}"
        )
        total_score = sum(scores.values())
        confidence = round(best_score / total_score, 4) if total_score else 0.0

    return {
        "content_type": content_type,
        "confidence": confidence,
        "matched_keywords": matched_keywords,
        "reason": reason,
        "manual_review_required": manual_review_required,
        "review_reasons": review_reasons,
    }


def _collect_body_text(output_dir: Path) -> str:
    text_parts = []

    raw_text = read_json(output_dir / "raw_text.json", {})
    if isinstance(raw_text, dict):
        text_parts.append(str(raw_text.get("full_text", "")))

    ocr_result = read_json(output_dir / "ocr_result.json", {})
    if isinstance(ocr_result, dict):
        for page_result in _as_list(ocr_result.get("page_results")):
            if isinstance(page_result, dict):
                text_parts.append(str(page_result.get("text", "")))

    tables = read_json(output_dir / "tables.json", {})
    if isinstance(tables, dict):
        for table in _as_list(tables.get("tables")):
            if not isinstance(table, dict):
                continue

            for row in _as_list(table.get("rows")):
                text_parts.append(_flatten_row(row))

    return "\n".join(text_part for text_part in text_parts if text_part)


def _flatten_row(row: Any) -> str:
    if isinstance(row, list):
        return " ".join("" if cell is None else str(cell) for cell in row)
    return "" if row is None else str(row)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]
