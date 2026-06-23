from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image

from app.services.local_store import ensure_dir


PDF_RENDER_SCALE = 1.5


def build_visual_evidence(
    file_path: str | Path,
    output_dir: str | Path,
    *,
    route_type: str | None = None,
) -> dict[str, Any]:
    evidence_dir = ensure_dir(Path(output_dir) / "visual_evidence")
    pages: list[dict[str, Any]] = []

    try:
        for page_no, image in _iter_page_images(Path(file_path), route_type):
            page_path = evidence_dir / f"page_{page_no:03d}.png"
            image.save(page_path)
            pages.append(
                {
                    "page_no": page_no,
                    "path": str(page_path),
                    "type": "page",
                    "width": image.width,
                    "height": image.height,
                }
            )
    except Exception as exc:
        return {
            "visual_evidence_status": "failed",
            "pages": pages,
            "review_reasons": [f"视觉证据生成失败：{exc}"],
        }

    return {
        "visual_evidence_status": "success" if pages else "empty",
        "pages": pages,
        "review_reasons": [],
    }


def _iter_page_images(file_path: Path, route_type: str | None):
    if route_type == "image" or file_path.suffix.lower() in {
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".bmp",
        ".tif",
        ".tiff",
    }:
        with Image.open(file_path) as image:
            yield 1, image.convert("RGB")
        return

    if route_type not in {None, "direct_pdf", "scanned_pdf"}:
        return

    if file_path.suffix.lower() != ".pdf":
        return

    import fitz

    with fitz.open(file_path) as doc:
        for page_index in range(doc.page_count):
            page = doc.load_page(page_index)
            pixmap = page.get_pixmap(
                matrix=fitz.Matrix(PDF_RENDER_SCALE, PDF_RENDER_SCALE),
                alpha=False,
            )
            image = Image.open(BytesIO(pixmap.tobytes("png"))).convert("RGB")
            yield page_index + 1, image
