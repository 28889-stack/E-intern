from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[4]
API_ROOT = PROJECT_ROOT / "apps" / "api"


class Settings(BaseSettings):
    llm_provider: str = "mock"
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-v4-flash"
    llm_timeout_seconds: int = 120
    llm_max_tokens: int = 8192
    enable_multimodal_review: bool = False
    multimodal_api_url: str = ""
    multimodal_api_key: str = ""
    multimodal_model: str = ""
    multimodal_timeout_seconds: int = 180
    multimodal_max_img_bytes: int = 3500000
    multimodal_max_tokens: int = 2048

    model_config = SettingsConfigDict(
        env_file=str(API_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()

OCR_BASE_URL = "http://127.0.0.1:8010"
OCR_ENDPOINT = "/ocr"
OCR_TIMEOUT_SECONDS = 120

LLM_PROVIDER = settings.llm_provider
LLM_API_KEY = settings.llm_api_key
LLM_BASE_URL = settings.llm_base_url
LLM_MODEL = settings.llm_model
LLM_TIMEOUT_SECONDS = settings.llm_timeout_seconds
LLM_MAX_TOKENS = settings.llm_max_tokens
ENABLE_MULTIMODAL_REVIEW = settings.enable_multimodal_review
MULTIMODAL_API_URL = settings.multimodal_api_url
MULTIMODAL_API_KEY = settings.multimodal_api_key
MULTIMODAL_MODEL = settings.multimodal_model
MULTIMODAL_TIMEOUT_SECONDS = settings.multimodal_timeout_seconds
MULTIMODAL_MAX_IMG_BYTES = settings.multimodal_max_img_bytes
MULTIMODAL_MAX_TOKENS = settings.multimodal_max_tokens
