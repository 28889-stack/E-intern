from fastapi import APIRouter

from app.core.config import settings
from app.services.llm_client import LLMClient


router = APIRouter(prefix="/api/llm", tags=["llm"])


@router.get("/health")
def llm_health() -> dict:
    if settings.llm_provider == "mock":
        return {
            "provider": "mock",
            "status": "ok",
        }

    if settings.llm_provider != "openai_compatible":
        return {
            "provider": settings.llm_provider,
            "status": "failed",
            "review_reasons": [f"不支持的 LLM_PROVIDER：{settings.llm_provider}"],
        }

    if _is_placeholder_api_key(settings.llm_api_key):
        return {
            "provider": "openai_compatible",
            "base_url": settings.llm_base_url,
            "model": settings.llm_model,
            "status": "failed",
            "review_reasons": ["LLM 密钥未配置真实值"],
        }

    result = LLMClient().extract_json(
        '你只输出 JSON。请返回 {"pong":"hello"}，不要输出解释文字。',
        '{"ping":"hello"}',
    )
    extract_status = result.get("extract_status")
    if extract_status in {"llm_request_failed", "json_parse_failed", "failed"}:
        return {
            "provider": "openai_compatible",
            "base_url": settings.llm_base_url,
            "model": settings.llm_model,
            "status": "failed",
            "extract_status": extract_status,
            "review_reasons": result.get("review_reasons", []),
        }

    return {
        "provider": "openai_compatible",
        "base_url": settings.llm_base_url,
        "model": settings.llm_model,
        "status": "ok",
    }


def _is_placeholder_api_key(api_key: str) -> bool:
    if not api_key:
        return True
    return "这里填" in api_key or "你的 DeepSeek" in api_key
