from __future__ import annotations

from collections import deque
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps


MAX_IMAGE_SIDE = 360
DARK_PIXEL_THRESHOLD = 55
OCCLUSION_DARK_RATIO_THRESHOLD = 0.16
OCCLUSION_COMPONENT_RATIO_THRESHOLD = 0.01
OCCLUSION_COMPONENT_WIDTH_RATIO_THRESHOLD = 0.25
OCCLUSION_COMPONENT_HEIGHT_RATIO_THRESHOLD = 0.08
MAX_PDF_PAGES_TO_CHECK = 3


def inspect_ocr_quality(file_path: str | Path, route_type: str) -> dict:
    page_metrics = []
    quality_issues = []

    for page_no, image in _iter_page_images(Path(file_path), route_type):
        metrics = _analyze_dark_components(image)
        metrics["page"] = page_no
        page_metrics.append(metrics)

        if _has_suspected_occlusion(metrics):
            quality_issues.append(
                {
                    "issue_type": "suspected_occlusion",
                    "severity": "warning",
                    "page": page_no,
                    "message": (
                        f"第 {page_no} 页存在疑似遮挡或涂抹，"
                        "可能影响交易流水、持仓明细或关键字段识别。"
                    ),
                    "metrics": metrics,
                }
            )

    issue_types = _unique(issue.get("issue_type") for issue in quality_issues)
    return {
        "quality_status": "warning" if quality_issues else "normal",
        "manual_review_required": bool(quality_issues),
        "issue_types": issue_types,
        "quality_issues": quality_issues,
        "review_reasons": [
            issue.get("message", "")
            for issue in quality_issues
            if issue.get("message")
        ],
        "metrics": {"pages": page_metrics},
    }


def _iter_page_images(file_path: Path, route_type: str):
    if route_type == "image":
        try:
            with Image.open(file_path) as image:
                yield 1, image.convert("RGB")
        except Exception:
            return
        return

    if route_type != "scanned_pdf":
        return

    try:
        import fitz  # type: ignore
    except Exception:
        return

    try:
        with fitz.open(file_path) as doc:
            for page_index in range(min(doc.page_count, MAX_PDF_PAGES_TO_CHECK)):
                page = doc.load_page(page_index)
                pixmap = page.get_pixmap(matrix=fitz.Matrix(1.0, 1.0), alpha=False)
                image = Image.open(BytesIO(pixmap.tobytes("png"))).convert("RGB")
                yield page_index + 1, image
    except Exception:
        return


def _analyze_dark_components(image: Image.Image) -> dict[str, Any]:
    gray = ImageOps.grayscale(image)
    gray.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE), Image.Resampling.LANCZOS)
    width, height = gray.size
    total_pixels = max(width * height, 1)
    pixels = gray.load()
    dark = bytearray(total_pixels)
    dark_count = 0

    for y in range(height):
        for x in range(width):
            index = y * width + x
            if pixels[x, y] <= DARK_PIXEL_THRESHOLD:
                dark[index] = 1
                dark_count += 1

    visited = bytearray(total_pixels)
    largest = {
        "area_ratio": 0.0,
        "width_ratio": 0.0,
        "height_ratio": 0.0,
    }
    long_component_count = 0

    for index, value in enumerate(dark):
        if not value or visited[index]:
            continue
        component = _component_metrics(index, dark, visited, width, height, total_pixels)
        if component["area_ratio"] > largest["area_ratio"]:
            largest = component
        if (
            component["area_ratio"] >= OCCLUSION_COMPONENT_RATIO_THRESHOLD
            and component["width_ratio"] >= OCCLUSION_COMPONENT_WIDTH_RATIO_THRESHOLD
            and component["height_ratio"] >= OCCLUSION_COMPONENT_HEIGHT_RATIO_THRESHOLD
        ):
            long_component_count += 1

    return {
        "dark_pixel_ratio": round(dark_count / total_pixels, 4),
        "largest_dark_component_area_ratio": round(largest["area_ratio"], 4),
        "largest_dark_component_width_ratio": round(largest["width_ratio"], 4),
        "largest_dark_component_height_ratio": round(largest["height_ratio"], 4),
        "long_dark_component_count": long_component_count,
    }


def _component_metrics(
    start_index: int,
    dark: bytearray,
    visited: bytearray,
    width: int,
    height: int,
    total_pixels: int,
) -> dict[str, float]:
    queue = deque([start_index])
    visited[start_index] = 1
    count = 0
    min_x = width
    min_y = height
    max_x = 0
    max_y = 0

    while queue:
        index = queue.popleft()
        y, x = divmod(index, width)
        count += 1
        min_x = min(min_x, x)
        min_y = min(min_y, y)
        max_x = max(max_x, x)
        max_y = max(max_y, y)

        for nx, ny in (
            (x - 1, y),
            (x + 1, y),
            (x, y - 1),
            (x, y + 1),
            (x - 1, y - 1),
            (x + 1, y - 1),
            (x - 1, y + 1),
            (x + 1, y + 1),
        ):
            if nx < 0 or ny < 0 or nx >= width or ny >= height:
                continue
            neighbor_index = ny * width + nx
            if dark[neighbor_index] and not visited[neighbor_index]:
                visited[neighbor_index] = 1
                queue.append(neighbor_index)

    return {
        "area_ratio": count / total_pixels,
        "width_ratio": (max_x - min_x + 1) / max(width, 1),
        "height_ratio": (max_y - min_y + 1) / max(height, 1),
    }


def _has_suspected_occlusion(metrics: dict) -> bool:
    if metrics["dark_pixel_ratio"] >= OCCLUSION_DARK_RATIO_THRESHOLD:
        return True
    return metrics["long_dark_component_count"] >= 1


def _unique(values) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value in (None, "") or value in seen:
            continue
        seen.add(value)
        result.append(str(value))
    return result
