from __future__ import annotations

from typing import Sequence

from app.core.config import GRAPH_RAG_EMBEDDING_MODEL


class EmbeddingClient:
    def __init__(self, model_name: str | None = None) -> None:
        self.model_name = model_name or GRAPH_RAG_EMBEDDING_MODEL
        self._model = None

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._load_model()
        vectors = model.encode(
            list(texts),
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [
            [float(value) for value in vector]
            for vector in vectors
        ]

    def _load_model(self):
        if self._model is not None:
            return self._model
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "sentence-transformers 未安装，无法启用 Graph RAG embedding；"
                "请安装 apps/api/requirements.txt 中的可选依赖后重试。"
            ) from exc
        self._model = SentenceTransformer(self.model_name)
        return self._model
