import mimetypes
import re
from pathlib import Path

import fitz


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}


def route_file(file_path: str | Path, original_file_name: str | None = None) -> dict:
    path = Path(file_path)
    file_name = original_file_name or path.name
    file_ext = Path(file_name).suffix.lower()
    mime_type = mimetypes.guess_type(file_name)[0] or "application/octet-stream"

    base_result = {
        "route_type": "failed",
        "file_ext": file_ext,
        "mime_type": mime_type,
        "page_count": 0,
        "text_char_count": 0,
        "router_status": "failed",
        "manual_review_required": False,
        "review_reasons": [],
    }

    if file_ext in IMAGE_EXTENSIONS:
        return {
            **base_result,
            "route_type": "image",
            "router_status": "success",
        }

    if file_ext != ".pdf":
        return {
            **base_result,
            "route_type": "unsupported",
            "router_status": "success",
            "manual_review_required": True,
            "review_reasons": ["暂不支持的文件格式"],
        }

    try:
        with fitz.open(path) as doc:
            page_count = doc.page_count
            text_parts = []
            for page_index in range(min(3, page_count)):
                page = doc.load_page(page_index)
                text_parts.append(page.get_text("text"))

            text_char_count = len(re.sub(r"\s+", "", "".join(text_parts)))
            route_type = "direct_pdf" if text_char_count >= 80 else "scanned_pdf"

            return {
                **base_result,
                "route_type": route_type,
                "page_count": page_count,
                "text_char_count": text_char_count,
                "router_status": "success",
            }
    except Exception:
        return {
            **base_result,
            "route_type": "failed",
            "manual_review_required": True,
            "review_reasons": ["PDF 文件无法打开"],
        }
