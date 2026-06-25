from __future__ import annotations

from pathlib import Path
from typing import Any

from app.pipeline.difficult_block_detector import detect_difficult_blocks
from app.pipeline.document_blocks import build_document_blocks
from app.core.config import (
    MULTIMODAL_API_KEY,
    MULTIMODAL_API_URL,
    MULTIMODAL_MAX_IMG_BYTES,
    MULTIMODAL_MAX_TOKENS,
    MULTIMODAL_MODEL,
    MULTIMODAL_TIMEOUT_SECONDS,
)
from app.services import local_store
from app.services.llm_client import LLMClient
from app.pipeline.text_compaction import compact_string_list


def run_multimodal_review_sidecar(
    file_record: dict,
    output_dir: str | Path,
    *,
    llm_client: LLMClient | None = None,
) -> dict[str, Any]:
    output_path = Path(output_dir)
    hints_path = output_path / "multimodal_review_hints.json"
    difficult_blocks_path = output_path / "difficult_blocks.json"

    try:
        document_blocks = build_document_blocks(
            file_path=_file_path(file_record),
            output_dir=output_path,
            route_type=file_record.get("route_type"),
        )
        difficult_blocks = detect_difficult_blocks(document_blocks)
        local_store.save_json(difficult_blocks_path, difficult_blocks)

        if difficult_blocks.get("difficulty_status") != "has_difficult_blocks":
            result = {
                "multimodal_review_status": "no_difficult_blocks",
                "visual_observations": [],
                "event_candidates": [],
                "merge_suggestions": [],
                "column_mapping_hints": [],
                "uncertainty_reasons": [],
            }
        else:
            result = _extract_hints(
                document_blocks=document_blocks,
                difficult_blocks=difficult_blocks,
                llm_client=llm_client or _multimodal_llm_client(),
            )

        result = {
            **_empty_hint_payload(),
            **result,
            "document_blocks_path": _relative(output_path / "document_blocks.json"),
            "difficult_blocks_path": _relative(difficult_blocks_path),
            "multimodal_review_hints_path": _relative(hints_path),
        }
        local_store.save_json(hints_path, result)
        return result
    except Exception as exc:
        result = {
            **_empty_hint_payload(),
            "multimodal_review_status": "failed",
            "manual_review_required": True,
            "review_reasons": [f"多模态疑难块旁路失败：{exc}"],
            "multimodal_review_hints_path": _relative(hints_path),
        }
        local_store.save_json(hints_path, result)
        return result


def _extract_hints(
    *,
    document_blocks: dict[str, Any],
    difficult_blocks: dict[str, Any],
    llm_client: LLMClient,
) -> dict[str, Any]:
    prompt_path = local_store.PROJECT_ROOT / "prompts" / "multimodal_review_prompt.md"
    prompt = prompt_path.read_text(encoding="utf-8")
    input_text = _build_hint_input(document_blocks, difficult_blocks)
    image_paths = _image_paths_from_difficult_blocks(difficult_blocks)
    if image_paths and hasattr(llm_client, "extract_json_with_images"):
        result = llm_client.extract_json_with_images(
            prompt,
            input_text=input_text,
            image_paths=image_paths,
        )
    else:
        result = llm_client.extract_json(prompt, input_text=input_text)
    status = result.get("extract_status") or "success"

    if status in {"failed", "llm_request_failed", "json_parse_failed"}:
        return {
            **_empty_hint_payload(),
            "multimodal_review_status": status,
            "manual_review_required": True,
            "review_reasons": result.get("review_reasons", ["多模态疑难块抽取失败"]),
            "raw_llm_output": result.get("raw_llm_output"),
        }

    return {
        "multimodal_review_status": "success",
        "visual_observations": compact_string_list(
            result.get("visual_observations") or result.get("uncertainty_reasons"),
            140,
        ),
        "event_candidates": _compact_hint_items(result.get("event_candidates")),
        "merge_suggestions": _compact_hint_items(result.get("merge_suggestions")),
        "column_mapping_hints": _compact_hint_items(result.get("column_mapping_hints")),
        "uncertainty_reasons": compact_string_list(result.get("uncertainty_reasons"), 140),
        "image_ref_count": len(image_paths),
        "llm_response_metadata": result.get("llm_response_metadata", {}),
    }


def _multimodal_llm_client() -> LLMClient:
    return LLMClient(
        provider="openai_compatible",
        api_key=MULTIMODAL_API_KEY,
        base_url=MULTIMODAL_API_URL,
        model=MULTIMODAL_MODEL,
        timeout_seconds=MULTIMODAL_TIMEOUT_SECONDS,
        max_tokens=MULTIMODAL_MAX_TOKENS,
        max_image_bytes=MULTIMODAL_MAX_IMG_BYTES,
    )


def _build_hint_input(
    document_blocks: dict[str, Any],
    difficult_blocks: dict[str, Any],
) -> str:
    blocks_by_id = {
        block.get("block_id"): block for block in document_blocks.get("blocks", [])
    }
    parts = []
    for item in difficult_blocks.get("difficult_blocks", []):
        block = blocks_by_id.get(item.get("block_id"), {})
        parts.append(
            "\n".join(
                [
                    f"block_id: {item.get('block_id', '')}",
                    f"page_no: {item.get('page_no', '')}",
                    f"block_type: {item.get('block_type', '')}",
                    f"difficulty_reasons: {', '.join(item.get('difficulty_reasons', []))}",
                    f"image_refs: {item.get('image_refs', [])}",
                    "text:",
                    str(block.get("text", ""))[:4000],
                    "table_rows:",
                    str(block.get("table_rows", []))[:4000],
                ]
            )
        )
    return "\n\n---\n\n".join(parts)


def _file_path(file_record: dict) -> Path | None:
    storage_path = file_record.get("storage_path")
    if not storage_path:
        return None
    path = Path(storage_path)
    if not path.is_absolute():
        path = local_store.PROJECT_ROOT / path
    return path


def _image_paths_from_difficult_blocks(difficult_blocks: dict[str, Any]) -> list[str]:
    paths = []
    seen = set()
    for block in difficult_blocks.get("difficult_blocks", []) or []:
        for image_ref in block.get("image_refs", []) or []:
            if not isinstance(image_ref, dict):
                continue
            path = str(image_ref.get("path") or "").strip()
            if not path or path in seen:
                continue
            seen.add(path)
            paths.append(path)
    return paths


def _relative(path: str | Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(local_store.PROJECT_ROOT.resolve()))
    except ValueError:
        return str(path)


def _empty_hint_payload() -> dict[str, Any]:
    return {
        "multimodal_review_status": "skipped",
        "visual_observations": [],
        "event_candidates": [],
        "merge_suggestions": [],
        "column_mapping_hints": [],
        "uncertainty_reasons": [],
        "manual_review_required": False,
        "review_reasons": [],
    }


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _compact_hint_items(value: Any, limit: int = 5) -> list:
    return [_compact_hint_item(item) for item in _as_list(value)[:limit]]


def _compact_hint_item(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _compact_hint_item(item)
            for key, item in value.items()
            if key not in (None, "")
        }
    if isinstance(value, list):
        return [_compact_hint_item(item) for item in value[:5]]
    if isinstance(value, str):
        return compact_string_list([value], 120)[0] if value.strip() else ""
    return value
