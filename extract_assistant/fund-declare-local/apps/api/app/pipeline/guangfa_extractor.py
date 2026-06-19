from pathlib import Path

from app.pipeline.extraction_input_builder import build_extraction_input
from app.services import local_store
from app.services.llm_client import LLMClient
from app.services.prompt_loader import PromptLoader


class GuangfaExtractor:
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
            prompt = self.prompt_loader.load("guangfa_extract_prompt.md")
        except Exception as exc:
            extract_result = self._base_result(
                case_id,
                file_record,
                extract_status="failed",
                manual_review_required=True,
                review_reasons=[f"加载 Guangfa prompt 失败：{exc}"],
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
                self._output_contract(),
            ]
        )

    def _output_contract(self) -> str:
        return "\n".join(
            [
                "最终输出约束：",
                "1. 只输出一个合法 JSON 对象，不要输出解释文字、Markdown 或代码块。",
                "2. 保留 Guangfa prompt 中定义的来源专属 schema，不要改成 Chinaclear schema。",
                "3. 如果 prompt 定义了 position_group、trade_group、other_events，请按该结构输出。",
                "4. 需要在根对象中包含或允许后处理补齐 source_type=guangfa，content_type=guangfa。",
                "5. 无法判断字段时用空字符串，不要编造。",
            ]
        )

    def _normalize_result(
        self,
        case_id: str,
        file_record: dict,
        llm_result: dict,
    ) -> dict:
        extract_result = dict(llm_result) if isinstance(llm_result, dict) else {}
        extract_result.setdefault("schema_version", "guangfa_extract_v1")
        extract_result["source_type"] = "guangfa"
        extract_result["file_id"] = file_record.get("file_id")
        extract_result["case_id"] = case_id
        extract_result["content_type"] = "guangfa"
        extract_result["source_file"] = {
            "original_file_name": file_record.get("original_file_name", ""),
            "route_type": file_record.get("route_type", ""),
            "content_type": "guangfa",
        }
        extract_result.setdefault("extract_status", "success")
        extract_result.setdefault("document_info", {})
        extract_result.setdefault("accounts", [])
        extract_result.setdefault("holdings", [])
        extract_result.setdefault("transactions", [])
        extract_result.setdefault("cash_flows", [])
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
            "schema_version": "guangfa_extract_v1",
            "source_type": "guangfa",
            "file_id": file_record.get("file_id"),
            "case_id": case_id,
            "content_type": "guangfa",
            "extract_status": extract_status,
            "source_file": {
                "original_file_name": file_record.get("original_file_name", ""),
                "route_type": file_record.get("route_type", ""),
                "content_type": "guangfa",
            },
            "document_info": {},
            "accounts": [],
            "holdings": [],
            "transactions": [],
            "cash_flows": [],
            "events": [],
            "raw_llm_output": None,
            "manual_review_required": manual_review_required,
            "review_reasons": review_reasons,
        }
