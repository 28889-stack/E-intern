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
    graph_rag_embedding_enabled: bool = False
    graph_rag_embedding_model: str = "BAAI/bge-small-zh-v1.5"
    graph_rag_vector_top_k: int = 8
    ocr_text_detection_model_name: str = "PP-OCRv5_mobile_det"
    ocr_text_recognition_model_name: str = "PP-OCRv5_mobile_rec"
    ocr_device: str = "cpu"

    model_config = SettingsConfigDict(
        env_file=str(API_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()

OCR_TEXT_DETECTION_MODEL_NAME = settings.ocr_text_detection_model_name
OCR_TEXT_RECOGNITION_MODEL_NAME = settings.ocr_text_recognition_model_name
OCR_DEVICE = settings.ocr_device

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
GRAPH_RAG_EMBEDDING_ENABLED = settings.graph_rag_embedding_enabled
GRAPH_RAG_EMBEDDING_MODEL = settings.graph_rag_embedding_model
GRAPH_RAG_VECTOR_TOP_K = settings.graph_rag_vector_top_k
