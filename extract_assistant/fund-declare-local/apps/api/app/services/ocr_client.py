import base64
from pathlib import Path
from typing import Any

import requests
from requests import Response

from app.core.config import OCR_BASE_URL, OCR_ENDPOINT, OCR_TIMEOUT_SECONDS


class OcrClient:
    def __init__(
        self,
        base_url: str = OCR_BASE_URL,
        endpoint: str = OCR_ENDPOINT,
        timeout_seconds: int = OCR_TIMEOUT_SECONDS,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()
        self.session.trust_env = False

    def read_file_as_base64(self, file_path: str | Path) -> str:
        return base64.b64encode(Path(file_path).read_bytes()).decode("utf-8")

    def infer(self, file_path: str | Path, file_type: int) -> dict:
        try:
            payload = {
                "file": self.read_file_as_base64(file_path),
                "fileType": file_type,
                "visualize": False,
            }
            response = self.session.post(
                f"{self.base_url}{self.endpoint}",
                json=payload,
                timeout=self.timeout_seconds,
            )

            if not response.ok:
                return self._failed_result(
                    f"OCR 服务调用失败：HTTP {response.status_code} {response.reason}"
                    f"，响应内容：{self._response_preview(response)}",
                    raw_response=self._safe_response_json(response),
                )

            raw_response = response.json()
            page_results = self._parse_page_results(raw_response)
            failed_pages = [
                page["page"]
                for page in page_results
                if page.get("status") != "success"
            ]

            return {
                "ocr_status": "success",
                "raw_response": raw_response,
                "page_results": page_results,
                "ocr_failed_pages": failed_pages,
                "manual_review_required": bool(failed_pages),
                "review_reasons": (
                    ["部分页面 OCR 结果为空或解析失败"] if failed_pages else []
                ),
            }
        except Exception as exc:
            return self._failed_result(f"OCR 服务调用失败：{exc}")

    def _failed_result(self, reason: str, raw_response: Any | None = None) -> dict:
        return {
            "ocr_status": "failed",
            "raw_response": raw_response or {},
            "page_results": [],
            "ocr_failed_pages": [],
            "manual_review_required": True,
            "review_reasons": [reason],
        }

    def _safe_response_json(self, response: Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return {}

    def _response_preview(self, response: Response) -> str:
        text = response.text.strip()
        if not text:
            return "空响应"
        return text[:500]

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
                pruned_result.get("rec_boxes") or pruned_result.get("rec_polys")
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

        return page_result

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
        if isinstance(value, list):
            return value
        return [value]
