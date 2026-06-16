from pathlib import Path

import fitz


def extract_pdf_text(file_path: str | Path) -> dict:
    try:
        pages = []
        full_text_parts = []

        with fitz.open(file_path) as doc:
            for page_index, page in enumerate(doc, start=1):
                text = page.get_text("text")
                full_text_parts.append(text)
                pages.append(
                    {
                        "page": page_index,
                        "text": text,
                        "char_count": len(text),
                    }
                )

        return {
            "extract_status": "success",
            "page_count": len(pages),
            "pages": pages,
            "full_text": "\n".join(full_text_parts),
            "manual_review_required": False,
            "review_reasons": [],
        }
    except Exception as exc:
        return {
            "extract_status": "failed",
            "page_count": 0,
            "pages": [],
            "full_text": "",
            "manual_review_required": True,
            "review_reasons": [f"PDF 文本提取失败：{exc}"],
        }
