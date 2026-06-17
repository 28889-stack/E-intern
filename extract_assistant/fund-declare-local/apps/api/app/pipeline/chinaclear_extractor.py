from pathlib import Path

from app.pipeline.extraction_input_builder import build_extraction_input
from app.services import local_store
from app.services.llm_client import LLMClient
from app.services.prompt_loader import PromptLoader


class ChinaclearExtractor:
    def __init__(
        self,
        prompt_loader: PromptLoader | None = None,
        llm_client: LLMClient | None = None,
    ) -> None:
        self.prompt_loader = prompt_loader or PromptLoader()
        self.llm_client = llm_client or LLMClient()

    def extract(self, case_id: str, file_record: dict, process_output_dir: str | Path) -> dict:
        output_dir = local_store.ensure_dir(process_output_dir)
        extract_result_path = output_dir / "extract_result.json"
        input_payload = build_extraction_input(output_dir)

        if not input_payload["input_text"].strip():
            extract_result = self._base_result(
                case_id,
                file_record,
                extract_status="failed",
                manual_review_required=True,
                review_reasons=["抽取输入文本为空"],
            )
            local_store.save_json(extract_result_path, extract_result)
            return extract_result

        try:
            prompt = self.prompt_loader.load("chinaclear_extract_prompt.md")
        except Exception as exc:
            extract_result = self._base_result(
                case_id,
                file_record,
                extract_status="failed",
                manual_review_required=True,
                review_reasons=[f"加载 Chinaclear prompt 失败：{exc}"],
            )
            local_store.save_json(extract_result_path, extract_result)
            return extract_result

        final_prompt = self._build_final_prompt(
            prompt,
            file_record,
            input_payload["input_text"],
        )
        llm_result = self.llm_client.extract_json(final_prompt)
        extract_result = self._normalize_result(case_id, file_record, llm_result)
        extract_result["input_sources"] = input_payload["sources"]

        local_store.save_json(extract_result_path, extract_result)
        return extract_result

    def _build_final_prompt(self, prompt: str, file_record: dict, input_text: str) -> str:
        return "\n\n".join(
            [
                prompt,
                f"file_id: {file_record.get('file_id', '')}",
                f"original_file_name: {file_record.get('original_file_name', '')}",
                f"route_type: {file_record.get('route_type', '')}",
                f"content_type: {file_record.get('content_type', '')}",
                "input_text:",
                input_text,
                "请只输出 JSON，不要输出解释文字、Markdown、代码块或多余文本。",
            ]
        )

    def _normalize_result(
        self,
        case_id: str,
        file_record: dict,
        llm_result: dict,
    ) -> dict:
        extract_result = dict(llm_result) if isinstance(llm_result, dict) else {}
        extract_result.setdefault("schema_version", "chinaclear_extract_v1")
        extract_result["file_id"] = file_record.get("file_id")
        extract_result["case_id"] = case_id
        extract_result["content_type"] = "chinaclear"
        extract_result["source_file"] = {
            "original_file_name": file_record.get("original_file_name", ""),
            "route_type": file_record.get("route_type", ""),
            "content_type": "chinaclear",
        }
        extract_result.setdefault("extract_status", "success")
        extract_result.setdefault("accounts", [])
        extract_result.setdefault("holdings", [])
        extract_result.setdefault("transactions", [])
        extract_result.setdefault("events", [])
        extract_result.setdefault("raw_llm_output", None)
        extract_result.setdefault("manual_review_required", False)
        extract_result.setdefault("review_reasons", [])
        return extract_result

    def _base_result(
        self,
        case_id: str,
        file_record: dict,
        extract_status: str,
        manual_review_required: bool,
        review_reasons: list[str],
    ) -> dict:
        return {
            "schema_version": "chinaclear_extract_v1",
            "file_id": file_record.get("file_id"),
            "case_id": case_id,
            "content_type": "chinaclear",
            "extract_status": extract_status,
            "source_file": {
                "original_file_name": file_record.get("original_file_name", ""),
                "route_type": file_record.get("route_type", ""),
                "content_type": "chinaclear",
            },
            "accounts": [],
            "holdings": [],
            "transactions": [],
            "events": [],
            "raw_llm_output": None,
            "manual_review_required": manual_review_required,
            "review_reasons": review_reasons,
        }
