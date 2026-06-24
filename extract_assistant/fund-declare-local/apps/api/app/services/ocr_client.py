from pathlib import Path
from typing import Any

from app.core.config import (
    OCR_DEVICE,
    OCR_TEXT_DETECTION_MODEL_NAME,
    OCR_TEXT_RECOGNITION_MODEL_NAME,
)


OCR_REQUEST_OPTIONS = {
    "visualize": False,
    "useDocOrientationClassify": False,
    "useDocUnwarping": False,
    "useTextlineOrientation": False,
    "textDetLimitSideLen": 960,
    "textDetLimitType": "max",
    "returnWordBox": False,
    "textDetectionModelName": OCR_TEXT_DETECTION_MODEL_NAME,
    "textRecognitionModelName": OCR_TEXT_RECOGNITION_MODEL_NAME,
    "device": OCR_DEVICE,
}

_PADDLE_OCR_ENGINE: Any | None = None


class OcrClient:
    def __init__(self, engine: Any | None = None) -> None:
        self.engine = engine

    def infer(self, file_path: str | Path, file_type: int) -> dict:
        try:
            input_path = str(Path(file_path))
            raw_response = self._predict(input_path, file_type=file_type)
            page_results = self._parse_page_results(raw_response)
            failed_pages = [
                page["page"]
                for page in page_results
                if page.get("status") != "success"
            ]

            return {
                "ocr_status": "success",
                "ocr_backend": "local_paddleocr",
                "request_options": dict(OCR_REQUEST_OPTIONS),
                "raw_response": raw_response,
                "page_results": page_results,
                "ocr_failed_pages": failed_pages,
                "manual_review_required": bool(failed_pages),
                "review_reasons": (
                    ["部分页面 OCR 结果为空或解析失败"] if failed_pages else []
                ),
            }
        except Exception as exc:
            return self._failed_result(f"本地 PaddleOCR 调用失败：{exc}")

    def _predict(self, input_path: str, file_type: int) -> dict:
        engine = self.engine or self._get_engine()
        results = engine.predict(input=input_path)
        serialized_results = [
            self._serialize_ocr_result(item) for item in self._as_list(results)
        ]
        return {
            "ocrResults": serialized_results,
            "input": input_path,
            "fileType": file_type,
            "backend": "local_paddleocr",
        }

    def _get_engine(self) -> Any:
        global _PADDLE_OCR_ENGINE
        if _PADDLE_OCR_ENGINE is None:
            _PADDLE_OCR_ENGINE = self._create_engine()
        return _PADDLE_OCR_ENGINE

    def _create_engine(self) -> Any:
        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:
            raise RuntimeError(
                "未安装 paddleocr，请先在 apps/api 虚拟环境中执行 pip install -r requirements.txt"
            ) from exc

        return PaddleOCR(
            text_detection_model_name=OCR_TEXT_DETECTION_MODEL_NAME,
            text_recognition_model_name=OCR_TEXT_RECOGNITION_MODEL_NAME,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            text_det_limit_side_len=OCR_REQUEST_OPTIONS["textDetLimitSideLen"],
            text_det_limit_type=OCR_REQUEST_OPTIONS["textDetLimitType"],
            device=OCR_DEVICE,
        )

    def _failed_result(self, reason: str, raw_response: Any | None = None) -> dict:
        return {
            "ocr_status": "failed",
            "ocr_backend": "local_paddleocr",
            "request_options": dict(OCR_REQUEST_OPTIONS),
            "raw_response": raw_response or {},
            "page_results": [],
            "ocr_failed_pages": [],
            "manual_review_required": True,
            "review_reasons": [reason],
        }

    def _parse_page_results(self, raw_response: dict) -> list[dict]:
        ocr_results = self._extract_ocr_results(raw_response)
        if not ocr_results:
            return [
                {
                    "page": 1,
                    "text": "",
                    "blocks": [],
                    "confidence_avg": 0,
                    "status": "failed",
                }
            ]

        page_results = []
        for page_index, page_result in enumerate(ocr_results, start=1):
            pruned_result = self._find_pruned_result(page_result)
            rec_texts = self._as_list(pruned_result.get("rec_texts"))
            rec_scores = [
                float(score)
                for score in self._as_list(pruned_result.get("rec_scores"))
                if isinstance(score, (int, float))
            ]
            boxes = self._as_list(
                self._first_present(pruned_result, "rec_boxes", "rec_polys")
            )
            blocks = self._build_blocks(rec_texts, rec_scores, boxes)
            text = "\n".join(str(item) for item in rec_texts if item is not None)

            page_results.append(
                {
                    "page": page_index,
                    "text": text,
                    "blocks": blocks,
                    "confidence_avg": (
                        round(sum(rec_scores) / len(rec_scores), 4)
                        if rec_scores
                        else 0
                    ),
                    "status": "success" if text else "failed",
                }
            )

        return page_results

    def _extract_ocr_results(self, raw_response: dict) -> list[Any]:
        result = raw_response.get("result", raw_response)
        ocr_results = result.get("ocrResults") if isinstance(result, dict) else None
        if ocr_results is None and isinstance(raw_response, dict):
            ocr_results = raw_response.get("ocrResults")
        return self._as_list(ocr_results)

    def _find_pruned_result(self, page_result: Any) -> dict:
        if not isinstance(page_result, dict):
            return {}

        if isinstance(page_result.get("prunedResult"), dict):
            return page_result["prunedResult"]

        if isinstance(page_result.get("result"), dict):
            result = page_result["result"]
            if isinstance(result.get("prunedResult"), dict):
                return result["prunedResult"]
            if isinstance(result.get("res"), dict):
                return result["res"]

        if isinstance(page_result.get("res"), dict):
            return page_result["res"]

        return page_result

    def _serialize_ocr_result(self, result: Any) -> dict:
        if isinstance(result, dict):
            return self._to_jsonable(result)

        for attr_name in ("json", "to_json"):
            value = getattr(result, attr_name, None)
            if value is None:
                continue
            serialized = value() if callable(value) else value
            if isinstance(serialized, dict):
                return self._to_jsonable(serialized)

        if hasattr(result, "__dict__"):
            return self._to_jsonable(dict(result.__dict__))

        return {"value": str(result)}

    def _first_present(self, mapping: dict, *keys: str) -> Any:
        for key in keys:
            if key in mapping and mapping[key] is not None:
                return mapping[key]
        return None

    def _to_jsonable(self, value: Any) -> Any:
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        if hasattr(value, "tolist") and not isinstance(value, (str, bytes)):
            return value.tolist()
        if isinstance(value, dict):
            return {key: self._to_jsonable(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._to_jsonable(item) for item in value]
        if isinstance(value, tuple):
            return [self._to_jsonable(item) for item in value]
        return repr(value)

    def _build_blocks(
        self,
        rec_texts: list[Any],
        rec_scores: list[float],
        boxes: list[Any],
    ) -> list[dict]:
        blocks = []
        for index, text in enumerate(rec_texts):
            block = {
                "text": str(text),
                "confidence": rec_scores[index] if index < len(rec_scores) else None,
                "bbox": boxes[index] if index < len(boxes) else None,
            }
            blocks.append(block)
        return blocks

    def _as_list(self, value: Any) -> list[Any]:
        if value is None:
            return []
        if hasattr(value, "tolist") and not isinstance(value, (str, bytes)):
            value = value.tolist()
        if isinstance(value, list):
            return value
        return [value]
