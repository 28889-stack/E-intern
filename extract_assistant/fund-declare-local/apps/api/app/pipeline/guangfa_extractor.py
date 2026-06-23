from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from app.pipeline.document_context import (
    build_document_context,
    format_document_context,
    merge_document_info,
)
from app.pipeline.document_structure import document_structure_to_tables_payload
from app.pipeline.extraction_input_builder import build_extraction_input
from app.services import local_store
from app.services.llm_client import LLMClient
from app.services.prompt_loader import PromptLoader


GUANGFA_BATCH_ROW_LIMIT = 20
GUANGFA_BATCH_OVERLAP_ROWS = 5
GUANGFA_TEXT_BATCH_LINE_LIMIT = 50
GUANGFA_TEXT_BATCH_OVERLAP_LINES = 8
GUANGFA_BATCH_MAX_WORKERS = 4
GUANGFA_TRADE_COLUMNS = [
    "trade_id",
    "account_type",
    "securities_account",
    "trade_date",
    "trade_time",
    "serial_no",
    "capital_account",
    "security_code",
    "security_name",
    "direction",
    "quantity_raw",
    "price_raw",
    "amount_raw",
    "transfer_type_raw",
    "source_page",
    "row_no",
    "order_no",
]


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
        extract_batches_path = output_dir / "extract_batches.json"
        input_payload = build_extraction_input(output_dir)
        graph_rag_context = input_payload.get("graph_rag_context", "")
        document_context = build_document_context(output_dir)

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

        batches = self._build_batches(output_dir, input_payload)
        if len(batches) > 1:
            llm_result, batch_results = self._extract_batches(
                prompt,
                file_record,
                batches,
                document_context,
                graph_rag_context,
            )
            local_store.save_json(extract_batches_path, {"batches": batch_results})
        else:
            final_prompt = self._build_final_prompt(
                prompt,
                file_record,
                input_payload["input_text"],
                document_context,
                graph_rag_context,
            )
            llm_result = self.llm_client.extract_json(final_prompt)

        extract_result = self._normalize_result(
            case_id,
            file_record,
            llm_result,
            document_context,
        )
        extract_result["input_sources"] = input_payload["sources"]
        if len(batches) > 1:
            extract_result["batch_result_path"] = self._relative_to_project(
                extract_batches_path
            )
        local_store.save_json(extract_result_path, extract_result)
        return extract_result

    def _build_final_prompt(
        self,
        prompt: str,
        file_record: dict,
        input_text: str,
        document_context: dict | None = None,
        graph_rag_context: str = "",
    ) -> str:
        return "\n\n".join(
            [
                prompt,
                f"file_id: {file_record.get('file_id', '')}",
                f"original_file_name: {file_record.get('original_file_name', '')}",
                f"route_type: {file_record.get('route_type', '')}",
                f"content_type: {file_record.get('content_type', '')}",
                "document_context:",
                format_document_context(document_context or {}),
                "材料级上下文使用规则：如果 document_context 中有姓名、证券账号、账户类型或查询期间，后续交易行默认继承这些同一份材料的全局要素；资金账号不能当作证券账号。",
                self._graph_rag_prompt_section(graph_rag_context),
                "input_text:",
                input_text,
                self._output_contract(),
            ]
        )

    def _graph_rag_prompt_section(self, graph_rag_context: str = "") -> str:
        context = str(graph_rag_context or "").strip()
        if not context:
            return "graph_rag_context: 无"
        return "\n".join(
            [
                "graph_rag_context:",
                "以下是抽取前规则图谱检索得到的辅助证据上下文，只能用于补全同一文件内的账户、证券、页码、行号和原文证据；不得编造上下文中不存在的信息。",
                context,
            ]
        )

    def _output_contract(self) -> str:
        return "\n".join(
            [
                "最终输出约束：",
                "1. 只输出一个合法 JSON 对象，不要输出解释文字、Markdown 或代码块。",
                "2. 只有真实证券买入、真实证券卖出等普通成交交易才能输出到 trade_group.trades，使用列定义 + 行数组，不要每条输出大对象。",
                "3. 根对象优先输出 schema_version=guangfa_business_event_understanding_v1。",
                "4. 需要在根对象中包含或允许后处理补齐 source_type=guangfa，content_type=guangfa。",
                "5. trade_group.trade_columns 固定为：[\"trade_id\",\"account_type\",\"securities_account\",\"trade_date\",\"trade_time\",\"serial_no\",\"capital_account\",\"security_code\",\"security_name\",\"direction\",\"quantity_raw\",\"price_raw\",\"amount_raw\",\"transfer_type_raw\",\"source_page\",\"row_no\",\"order_no\"]。",
                "6. 普通买入/卖出不要输出 classification_reason、confidence、raw_summary 或大段 raw_text；缺值用空字符串。",
                "7. business_events 只保留 raw_business_type、inferred_event_type、event_category、final_field_candidates、source_evidence、manual_review_required、review_reasons。",
                "8. business_events 不要输出 missing_fields、classification_reason、classification_confidence、raw_summary、is_normal_trade、affects_holding、include_in_full_table、include_in_final_declaration；最终/完整表分流由后端规则处理。",
                "9. source_evidence 只保留 page、row_no、event_time、serial_no、order_no、raw_text；raw_text 不超过 120 个中文字符，只摘录本行或相邻断行，不要复制整页。",
                "10. 无法形成业务事实的乱码、断行、表头残片、遮挡问题，不要逐行输出为 business_events；写入 document_level_review_items，字段为 issue_type、page、row_no、message、source_evidence。",
                "11. 申购配号、中购配号、配号不是普通成交交易，禁止输出到 trade_group.trades；如需保留，输出到 business_events，但不要因为证券账号、证券代码、价格或金额缺失而标记人工复核。",
                "12. 股息、派息、现金分红、红利入账禁止输出到 trade_group.trades；可作为完整表事件输出到 business_events，但成交数量和成交单价可以为空。",
                "13. 如果输入是 batch，只抽取当前 batch 中可见的记录；输入可能包含 overlap 行，允许抽取，后端会按交易全要素去重。",
                "14. 广发普通交易和证券事件只从场内交割流水明细抽取；资金流水明细中的证券买入、证券卖出、股息、利息、转账等内容不要输出。",
            ]
        )

    def _build_batches(self, output_dir: Path, input_payload: dict) -> list[dict]:
        table_batches = self._build_table_batches(output_dir)
        if table_batches:
            return table_batches
        return self._build_text_batches(input_payload.get("input_sections"))

    def _build_table_batches(self, output_dir: Path) -> list[dict]:
        tables_payload = self._load_tables_payload(output_dir)
        if not isinstance(tables_payload, dict):
            return []

        rows = self._flatten_table_rows(tables_payload)
        if len(rows) <= GUANGFA_BATCH_ROW_LIMIT:
            return []

        batches = []
        start = 0
        batch_number = 1
        while start < len(rows):
            end = min(start + GUANGFA_BATCH_ROW_LIMIT, len(rows))
            batch_start = max(0, start - GUANGFA_BATCH_OVERLAP_ROWS)
            batch_end = min(len(rows), end + GUANGFA_BATCH_OVERLAP_ROWS)
            batch_rows = rows[batch_start:batch_end]
            primary_rows = rows[start:end]
            batches.append(
                {
                    "batch_id": f"batch_{batch_number:03d}",
                    "batch_type": "pdf_table_rows",
                    "row_start": self._row_label(primary_rows[0]),
                    "row_end": self._row_label(primary_rows[-1]),
                    "primary_row_keys": [
                        self._row_unique_key(row) for row in primary_rows
                    ],
                    "input_text": self._batch_rows_to_text(batch_rows),
                    "source_traces": [
                        self._source_trace_from_row(row) for row in batch_rows
                    ],
                }
            )
            start = end
            batch_number += 1
        return batches

    def _load_tables_payload(self, output_dir: Path) -> dict:
        document_structure = local_store.read_json(
            output_dir / "document_structure.json",
            {},
        )
        if isinstance(document_structure, dict):
            structured_payload = document_structure_to_tables_payload(document_structure)
            if structured_payload.get("tables"):
                return structured_payload
        return local_store.read_json(output_dir / "tables.json", {})

    def _flatten_table_rows(self, tables_payload: dict) -> list[dict]:
        flattened_rows = []
        for table in self._as_list(tables_payload.get("tables")):
            if not isinstance(table, dict):
                continue

            rows = self._as_list(table.get("rows"))
            if len(rows) < 2:
                continue

            row_metadata = self._as_list(table.get("row_metadata"))
            cell_metadata = self._as_list(table.get("cell_metadata"))
            first_row = rows[0] if isinstance(rows[0], list) else []
            header = first_row if self._looks_like_table_header(first_row) else []
            header_offset = 1 if header else 0
            data_rows = rows[header_offset:]
            data_row_metadata = row_metadata[header_offset:] if row_metadata else []
            data_cell_metadata = cell_metadata[header_offset:] if cell_metadata else []
            table_title = self._infer_table_title(header)
            current_section = table_title
            current_header = header
            for row_index, row in enumerate(data_rows, start=1):
                if not isinstance(row, list) or not any(str(cell).strip() for cell in row):
                    continue
                source_row_index = row_index - 1
                row_meta = (
                    data_row_metadata[source_row_index]
                    if source_row_index < len(data_row_metadata)
                    and isinstance(data_row_metadata[source_row_index], dict)
                    else {}
                )
                cell_meta = (
                    data_cell_metadata[source_row_index]
                    if source_row_index < len(data_cell_metadata)
                    and isinstance(data_cell_metadata[source_row_index], list)
                    else []
                )
                section_title = self._section_title_from_row(row)
                if section_title:
                    current_section = section_title
                    current_header = []
                    continue
                if self._looks_like_table_header(row):
                    current_header = row
                    current_section = self._infer_table_title(row) or current_section
                    continue
                if current_section == "资金流水明细":
                    continue
                flattened_rows.append(
                    {
                        "page": table.get("page"),
                        "table_index": table.get("table_index"),
                        "table_title": current_section,
                        "row_index": row_meta.get("row_index") or row_index,
                        "row_id": row_meta.get("row_id", ""),
                        "row_bbox": row_meta.get("bbox"),
                        "row_no": str(row[0]).strip() if row else "",
                        "header": current_header,
                        "cells": row,
                        "cell_metadata": cell_meta,
                    }
                )
        return flattened_rows

    def _section_title_from_row(self, row: list) -> str:
        values = [str(cell).strip() for cell in row if str(cell or "").strip()]
        if len(values) != 1:
            return ""
        text = values[0]
        if "场内交割流水明细" in text:
            return "场内交割流水明细"
        if "资金流水明细" in text:
            return "资金流水明细"
        if "持仓信息" in text:
            return "持仓信息"
        if "基本信息" in text:
            return "基本信息"
        return ""

    def _looks_like_table_header(self, row: list) -> bool:
        header_text = " ".join(str(cell) for cell in row if cell is not None)
        return any(
            keyword in header_text
            for keyword in (
                "业务日期",
                "成交时间",
                "业务标志",
                "委托编号",
                "证券代码",
                "证券名称",
                "持有数量",
                "资金发生额",
                "后资金额",
                "资金余额",
            )
        )

    def _infer_table_title(self, header: list) -> str:
        header_text = " ".join(str(cell) for cell in header if cell is not None)
        if any(keyword in header_text for keyword in ("持有数量", "当前数量", "市值", "基金净值", "证券余额")):
            return "持仓信息"
        if any(keyword in header_text for keyword in ("资金发生额", "发生金额", "后资金额", "资金余额")):
            return "资金流水明细"
        if any(keyword in header_text for keyword in ("成交时间", "成交数量", "成交价格", "成交金额", "业务标志", "委托编号")):
            return "场内交割流水明细"
        return ""

    def _batch_rows_to_text(self, rows: list[dict]) -> str:
        if not rows:
            return ""

        header = rows[0].get("header") or []
        parts = [
            "table_title:",
            str(rows[0].get("table_title") or ""),
            "table_header:",
            "\t".join("" if cell is None else str(cell) for cell in header),
            "rows:",
        ]
        for row in rows:
            cells_text = "\t".join(
                "" if cell is None else str(cell) for cell in row.get("cells", [])
            )
            parts.append(
                (
                    f"[page={row.get('page')} table={row.get('table_index')} "
                    f"table_title={row.get('table_title')} row_no={row.get('row_no')} "
                    f"row_index={row.get('row_index')}"
                    f"{self._row_trace_text(row)}] {cells_text}"
                )
            )
        return "\n".join(parts)

    def _build_text_batches(self, input_sections: Any) -> list[dict]:
        lines = self._flatten_text_lines(input_sections)
        if len(lines) <= GUANGFA_TEXT_BATCH_LINE_LIMIT:
            return []

        batches = []
        start = 0
        batch_number = 1
        while start < len(lines):
            end = min(start + GUANGFA_TEXT_BATCH_LINE_LIMIT, len(lines))
            batch_start = max(0, start - GUANGFA_TEXT_BATCH_OVERLAP_LINES)
            batch_end = min(len(lines), end + GUANGFA_TEXT_BATCH_OVERLAP_LINES)
            batch_lines = lines[batch_start:batch_end]
            primary_lines = lines[start:end]
            batches.append(
                {
                    "batch_id": f"batch_{batch_number:03d}",
                    "batch_type": "text_lines",
                    "row_start": str(primary_lines[0]["line_no"]),
                    "row_end": str(primary_lines[-1]["line_no"]),
                    "primary_row_keys": [
                        str(line["line_no"]) for line in primary_lines
                    ],
                    "input_text": self._batch_lines_to_text(batch_lines),
                }
            )
            start = end
            batch_number += 1
        return batches

    def _flatten_text_lines(self, input_sections: Any) -> list[dict]:
        flattened_lines = []
        line_no = 1
        for section in self._as_list(input_sections):
            if not isinstance(section, dict):
                continue
            section_type = section.get("section_type", "section")
            page = section.get("page")
            text = str(section.get("text", ""))
            for raw_line in text.splitlines():
                line_text = raw_line.strip()
                if not line_text:
                    continue
                flattened_lines.append(
                    {
                        "line_no": line_no,
                        "section_type": section_type,
                        "page": page,
                        "text": line_text,
                    }
                )
                line_no += 1
        return flattened_lines

    def _batch_lines_to_text(self, lines: list[dict]) -> str:
        parts = ["text_lines:"]
        for line in lines:
            parts.append(
                (
                    f"[page={line.get('page')} section={line.get('section_type')} "
                    f"line={line.get('line_no')}] {line.get('text')}"
                )
            )
        return "\n".join(parts)

    def _extract_batches(
        self,
        prompt: str,
        file_record: dict,
        batches: list[dict],
        document_context: dict | None = None,
        graph_rag_context: str = "",
    ) -> tuple[dict, list[dict]]:
        batch_results: list[dict] = []
        max_workers = min(GUANGFA_BATCH_MAX_WORKERS, len(batches))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    self._extract_one_batch,
                    prompt,
                    file_record,
                    batch,
                    document_context or {},
                    graph_rag_context,
                ): batch
                for batch in batches
            }
            for future in as_completed(futures):
                batch = futures[future]
                try:
                    batch_result = future.result()
                except Exception as exc:
                    batch_result = {
                        "batch_id": batch["batch_id"],
                        "extract_status": "llm_request_failed",
                        "manual_review_required": True,
                        "review_reasons": [f"批次抽取失败：{exc}"],
                    }
                batch_results.append(batch_result)

        batch_results.sort(key=lambda item: item.get("batch_id", ""))
        return self._merge_batch_results(batch_results, document_context), batch_results

    def _extract_one_batch(
        self,
        prompt: str,
        file_record: dict,
        batch: dict,
        document_context: dict | None = None,
        graph_rag_context: str = "",
    ) -> dict:
        final_prompt = self._build_batch_prompt(
            prompt,
            file_record,
            batch,
            document_context,
            graph_rag_context,
        )
        result = self.llm_client.extract_json(final_prompt)
        result["batch_id"] = batch["batch_id"]
        result["batch_row_range"] = {
            "row_start": batch["row_start"],
            "row_end": batch["row_end"],
        }
        result["batch_type"] = batch.get("batch_type", "")
        self._attach_compact_source_traces(result, batch.get("source_traces"))
        return result

    def _build_batch_prompt(
        self,
        prompt: str,
        file_record: dict,
        batch: dict,
        document_context: dict | None = None,
        graph_rag_context: str = "",
    ) -> str:
        return "\n\n".join(
            [
                prompt,
                f"file_id: {file_record.get('file_id', '')}",
                f"file_no: {file_record.get('file_no', '')}",
                f"original_file_name: {file_record.get('original_file_name', '')}",
                f"route_type: {file_record.get('route_type', '')}",
                f"content_type: {file_record.get('content_type', '')}",
                "document_context:",
                format_document_context(document_context or {}),
                "材料级上下文使用规则：如果 document_context 中有姓名、证券账号、账户类型或查询期间，当前 batch 的交易/持仓行默认继承这些同一份材料的全局要素；资金账号不能当作证券账号。",
                self._graph_rag_prompt_section(graph_rag_context),
                f"batch_id: {batch['batch_id']}",
                f"batch_type: {batch.get('batch_type', '')}",
                f"primary_row_range: {batch['row_start']} - {batch['row_end']}",
                "注意：输入中可能包含前后 overlap 行。请只基于当前输入抽取，不要补全看不到的材料内容。",
                "input_text:",
                batch["input_text"],
                self._output_contract(),
            ]
        )

    def _merge_batch_results(
        self,
        batch_results: list[dict],
        document_context: dict | None = None,
    ) -> dict:
        merged = {
            "schema_version": "guangfa_business_event_understanding_v1",
            "source_type": "guangfa",
            "file_summary": {},
            "document_info": merge_document_info(document_context, None),
            "account_candidates": [],
            "trade_group": {
                "event_type": "ordinary_trade_group",
                "trade_columns": GUANGFA_TRADE_COLUMNS,
                "trades": [],
            },
            "holding_records": [],
            "business_events": [],
            "negative_proofs": [],
            "document_level_review_items": [],
            "source_traces": [],
            "extract_status": "success",
            "manual_review_required": False,
            "review_reasons": [],
            "llm_response_metadata": {
                "batch_mode": True,
                "batch_options": {
                    "batch_row_limit": GUANGFA_BATCH_ROW_LIMIT,
                    "overlap_rows": GUANGFA_BATCH_OVERLAP_ROWS,
                    "text_batch_line_limit": GUANGFA_TEXT_BATCH_LINE_LIMIT,
                    "text_overlap_lines": GUANGFA_TEXT_BATCH_OVERLAP_LINES,
                    "max_workers": GUANGFA_BATCH_MAX_WORKERS,
                },
                "batches": [],
            },
        }
        accounts_by_key: dict[str, dict] = {}
        trades_by_key: dict[str, list[Any]] = {}
        holdings_by_key: dict[str, dict] = {}
        events_by_key: dict[str, dict] = {}
        proofs_by_key: dict[str, dict] = {}
        review_items_by_key: dict[str, dict] = {}
        source_traces_by_key: dict[str, dict] = {}

        for result in batch_results:
            batch_id = result.get("batch_id")
            status = result.get("extract_status")
            if status in {"llm_request_failed", "json_parse_failed", "failed"}:
                merged["extract_status"] = "partial_failed"
                merged["manual_review_required"] = True
                merged["review_reasons"].extend(result.get("review_reasons", []))

            if not merged["file_summary"] and isinstance(result.get("file_summary"), dict):
                merged["file_summary"] = result["file_summary"]
            if isinstance(result.get("document_info"), dict):
                merged["document_info"] = merge_document_info(
                    merged.get("document_info"),
                    result.get("document_info"),
                )

            self._merge_dict_records(accounts_by_key, result.get("account_candidates"))
            self._merge_trades(trades_by_key, result)
            self._merge_records(holdings_by_key, result.get("holding_records"), self._holding_key)
            self._merge_records(events_by_key, result.get("business_events"), self._business_event_key)
            self._merge_records(proofs_by_key, result.get("negative_proofs"), self._negative_proof_key)
            self._merge_records(
                review_items_by_key,
                result.get("document_level_review_items"),
                self._review_item_key,
            )
            self._merge_source_traces(source_traces_by_key, result.get("source_traces"))

            metadata = result.get("llm_response_metadata")
            if isinstance(metadata, dict):
                merged["llm_response_metadata"]["batches"].append(
                    {
                        "batch_id": batch_id,
                        "finish_reason": metadata.get("finish_reason"),
                        "usage": metadata.get("usage"),
                        "extract_status": status or "success",
                    }
                )

        merged["account_candidates"] = list(accounts_by_key.values())
        merged["trade_group"]["trades"] = sorted(
            trades_by_key.values(),
            key=self._trade_sort_key,
        )
        merged["holding_records"] = list(holdings_by_key.values())
        merged["business_events"] = list(events_by_key.values())
        merged["negative_proofs"] = list(proofs_by_key.values())
        merged["document_level_review_items"] = list(review_items_by_key.values())
        merged["source_traces"] = list(source_traces_by_key.values())
        self._apply_document_context(merged, document_context or {})
        merged["review_reasons"] = self._dedupe_list(merged["review_reasons"])
        return merged

    def _merge_trades(self, trades_by_key: dict[str, list[Any]], result: dict) -> None:
        trade_group = result.get("trade_group")
        if not isinstance(trade_group, dict):
            return

        columns = trade_group.get("trade_columns") or trade_group.get("columns") or GUANGFA_TRADE_COLUMNS
        for trade in self._as_list(trade_group.get("trades")):
            if isinstance(trade, dict):
                trade_record = dict(trade)
            elif isinstance(trade, list):
                trade_record = self._row_to_record(columns, trade)
            else:
                continue
            key = self._trade_key(trade_record)
            if not key:
                continue
            normalized_trade = [
                trade_record.get(column, "") for column in GUANGFA_TRADE_COLUMNS
            ]
            existing_trade = trades_by_key.get(key)
            if existing_trade is None or self._filled_count(normalized_trade) > self._filled_count(existing_trade):
                trades_by_key[key] = normalized_trade

    def _row_to_record(self, columns: list, row: list) -> dict:
        return {
            str(column): row[index] if index < len(row) else ""
            for index, column in enumerate(columns)
        }

    def _trade_key(self, trade: dict) -> str:
        return "|".join(
            self._first_text(value)
            for value in (
                trade.get("source_page"),
                trade.get("row_no"),
                trade.get("serial_no"),
                trade.get("trade_date"),
                trade.get("trade_time"),
                trade.get("security_code"),
                trade.get("security_name"),
                trade.get("direction"),
                trade.get("quantity_raw"),
                trade.get("price_raw"),
                trade.get("amount_raw"),
            )
        )

    def _trade_sort_key(self, trade: list) -> tuple[int, int, str]:
        source_page = str(
            trade[GUANGFA_TRADE_COLUMNS.index("source_page")]
            if len(trade) > GUANGFA_TRADE_COLUMNS.index("source_page")
            else ""
        )
        row_no = str(
            trade[GUANGFA_TRADE_COLUMNS.index("row_no")]
            if len(trade) > GUANGFA_TRADE_COLUMNS.index("row_no")
            else ""
        )
        return (self._to_int(source_page), self._to_int(row_no), row_no)

    def _filled_count(self, values: list[Any]) -> int:
        return sum(1 for value in values if value not in ("", None, []))

    def _to_int(self, value: str) -> int:
        try:
            return int(str(value))
        except ValueError:
            return 10**9

    def _apply_document_context(self, extract_result: dict, context: dict) -> None:
        if not context:
            return
        extract_result["document_info"] = merge_document_info(
            context,
            extract_result.get("document_info"),
        )
        securities_account = self._first_text(context.get("securities_account"))
        account_type = self._first_text(context.get("account_type"))
        holder_name = self._first_text(context.get("holder_name"))
        period_end = self._first_text(context.get("period_end"))

        for event in self._as_list(extract_result.get("business_events")):
            if not isinstance(event, dict):
                continue
            candidates = event.setdefault("final_field_candidates", {})
            if not isinstance(candidates, dict):
                candidates = {}
                event["final_field_candidates"] = candidates
            if securities_account and not self._first_text(candidates.get("证券账号"), event.get("securities_account")):
                candidates["证券账号"] = securities_account
            if account_type and not self._first_text(candidates.get("账户类型"), event.get("account_type")):
                candidates["账户类型"] = account_type
            if holder_name and not self._first_text(event.get("person_name"), event.get("holder_name"), candidates.get("姓名")):
                event["person_name"] = holder_name

        for holding in self._as_list(extract_result.get("holding_records")):
            if not isinstance(holding, dict):
                continue
            candidates = holding.setdefault("final_field_candidates", {})
            if not isinstance(candidates, dict):
                candidates = {}
                holding["final_field_candidates"] = candidates
            if securities_account and not self._first_text(candidates.get("证券账号"), holding.get("securities_account")):
                candidates["证券账号"] = securities_account
            if account_type and not self._first_text(candidates.get("账户类型"), holding.get("account_type")):
                candidates["账户类型"] = account_type
            if period_end and not self._first_text(candidates.get("查询结果所属日期"), holding.get("holding_date"), holding.get("date")):
                candidates["查询结果所属日期"] = period_end

        for proof in self._as_list(extract_result.get("negative_proofs")):
            if not isinstance(proof, dict):
                continue
            if holder_name and not self._first_text(proof.get("person_name"), proof.get("holder_name")):
                proof["person_name"] = holder_name
            if period_end and not self._first_text(proof.get("as_of_date"), proof.get("query_date"), proof.get("event_date"), proof.get("period_end")):
                proof["as_of_date"] = period_end
            if securities_account and not self._first_text(proof.get("securities_account"), proof.get("证券账号")):
                proof["securities_account"] = securities_account
            if account_type and not self._first_text(proof.get("account_type"), proof.get("账户类型")):
                proof["account_type"] = account_type

    def _merge_dict_records(self, records_by_key: dict[str, dict], records: Any) -> None:
        self._merge_records(records_by_key, records, self._generic_record_key)

    def _merge_records(
        self,
        records_by_key: dict[str, dict],
        records: Any,
        key_builder,
    ) -> None:
        for record in self._as_list(records):
            if not isinstance(record, dict):
                continue
            key = key_builder(record)
            existing = records_by_key.get(key)
            if existing is None:
                records_by_key[key] = dict(record)
            else:
                self._merge_record_into(existing, record)

    def _business_event_key(self, event: dict) -> str:
        candidates = event.get("final_field_candidates") or {}
        if not isinstance(candidates, dict):
            candidates = {}
        evidence = event.get("source_evidence") or {}
        if not isinstance(evidence, dict):
            evidence = {}
        return "|".join(
            self._first_text(value)
            for value in (
                evidence.get("file_id"),
                evidence.get("page"),
                evidence.get("row_no"),
                evidence.get("serial_no"),
                evidence.get("order_no"),
                candidates.get("证券账号"),
                candidates.get("证券代码"),
                candidates.get("证券名称"),
                candidates.get("变动类型"),
                candidates.get("日期"),
                candidates.get("成交数量"),
                candidates.get("成交单价"),
                candidates.get("收付金额"),
                event.get("raw_business_type"),
                event.get("inferred_event_type"),
            )
        )

    def _holding_key(self, holding: dict) -> str:
        return "|".join(
            self._first_text(value)
            for value in (
                holding.get("账户类型"),
                holding.get("证券账号"),
                holding.get("证券代码"),
                holding.get("证券名称"),
                holding.get("查询结果所属日期"),
                holding.get("持有数量"),
                self._source_value(holding, "page"),
                self._source_value(holding, "row_no"),
            )
        )

    def _negative_proof_key(self, proof: dict) -> str:
        return "|".join(
            self._first_text(value)
            for value in (
                proof.get("proof_type"),
                proof.get("person_name"),
                proof.get("as_of_date"),
                proof.get("query_date"),
                proof.get("period_start"),
                proof.get("period_end"),
                proof.get("account_type"),
                proof.get("securities_account"),
                self._source_value(proof, "raw_text"),
            )
        )

    def _review_item_key(self, item: dict) -> str:
        return "|".join(self._first_text(value) for value in item.values())

    def _generic_record_key(self, record: dict) -> str:
        return "|".join(self._first_text(value) for value in record.values())

    def _merge_record_into(self, target: dict, source: dict) -> None:
        for key, value in source.items():
            if key in {"review_reasons", "missing_fields"}:
                target[key] = self._dedupe_list(
                    [*self._as_list(target.get(key)), *self._as_list(value)]
                )
            elif key == "source_evidence" and isinstance(value, dict):
                existing = target.get(key)
                if not isinstance(existing, dict):
                    target[key] = dict(value)
                else:
                    self._merge_record_into(existing, value)
            elif not target.get(key) and value:
                target[key] = value

    def _source_value(self, record: dict, key: str) -> str:
        evidence = record.get("source_evidence") or {}
        if isinstance(evidence, dict):
            return self._first_text(evidence.get(key), record.get(key))
        return self._first_text(record.get(key))

    def _row_label(self, row: dict) -> str:
        return str(row.get("row_no") or row.get("row_index") or "")

    def _row_unique_key(self, row: dict) -> str:
        return "|".join(
            str(row.get(key, ""))
            for key in ("page", "table_index", "row_id", "row_no", "row_index")
        )

    def _source_trace_from_row(self, row: dict) -> dict:
        return {
            "page": str(row.get("page") or ""),
            "table": str(row.get("table_index") or ""),
            "row_no": str(row.get("row_no") or ""),
            "row_id": str(row.get("row_id") or ""),
            "bbox": row.get("row_bbox"),
            "line_ids": [
                str(cell.get("source_line_id"))
                for cell in self._as_list(row.get("cell_metadata"))
                if isinstance(cell, dict) and cell.get("source_line_id")
            ],
        }

    def _attach_compact_source_traces(self, result: dict, source_traces: Any) -> None:
        trace_index = self._source_trace_index(source_traces)
        if not trace_index:
            return

        matched_traces: dict[str, dict] = {}
        for records_key in (
            "business_events",
            "holding_records",
            "negative_proofs",
            "document_level_review_items",
        ):
            for record in self._as_list(result.get(records_key)):
                if not isinstance(record, dict):
                    continue
                trace = self._find_source_trace(record, trace_index)
                if trace:
                    record["source_trace"] = trace
                    matched_traces[self._source_trace_key(trace)] = trace

        trade_group = result.get("trade_group")
        if isinstance(trade_group, dict):
            columns = trade_group.get("trade_columns") or trade_group.get("columns") or GUANGFA_TRADE_COLUMNS
            for trade in self._as_list(trade_group.get("trades")):
                if isinstance(trade, dict):
                    trade_record = trade
                elif isinstance(trade, list):
                    trade_record = self._row_to_record(columns, trade)
                else:
                    continue
                trace = self._find_source_trace(trade_record, trace_index)
                if trace:
                    matched_traces[self._source_trace_key(trace)] = trace

        if matched_traces:
            result["source_traces"] = list(matched_traces.values())

    def _source_trace_index(self, source_traces: Any) -> dict[tuple[str, str], dict]:
        trace_index: dict[tuple[str, str], dict] = {}
        for trace in self._as_list(source_traces):
            if not isinstance(trace, dict):
                continue
            compact_trace = self._compact_source_trace(trace)
            page = self._first_text(compact_trace.get("page"))
            for key_value in (
                compact_trace.get("row_no"),
                compact_trace.get("row_id"),
            ):
                value = self._first_text(key_value)
                if value:
                    trace_index[(page, value)] = compact_trace
                    trace_index[("", value)] = compact_trace
        return trace_index

    def _find_source_trace(
        self,
        record: dict,
        trace_index: dict[tuple[str, str], dict],
    ) -> dict | None:
        evidence = record.get("source_evidence")
        if not isinstance(evidence, dict):
            evidence = {}
        page = self._first_text(
            record.get("source_page"),
            record.get("page"),
            evidence.get("page"),
        )
        row_values = [
            record.get("row_no"),
            evidence.get("row_no"),
            record.get("row_id"),
            evidence.get("row_id"),
        ]
        for value in row_values:
            row_value = self._first_text(value)
            if not row_value:
                continue
            trace = trace_index.get((page, row_value)) or trace_index.get(("", row_value))
            if trace:
                return trace
        return None

    def _compact_source_trace(self, trace: dict) -> dict:
        compact = {
            "page": self._first_text(trace.get("page")),
            "table": self._first_text(trace.get("table")),
            "row_no": self._first_text(trace.get("row_no")),
            "row_id": self._first_text(trace.get("row_id")),
            "bbox": trace.get("bbox"),
            "line_ids": self._dedupe_list(
                [
                    str(line_id)
                    for line_id in self._as_list(trace.get("line_ids"))
                    if line_id not in (None, "")
                ]
            ),
        }
        return {key: value for key, value in compact.items() if value not in ("", [], None)}

    def _merge_source_traces(
        self,
        traces_by_key: dict[str, dict],
        source_traces: Any,
    ) -> None:
        for trace in self._as_list(source_traces):
            if not isinstance(trace, dict):
                continue
            compact_trace = self._compact_source_trace(trace)
            if compact_trace:
                traces_by_key.setdefault(
                    self._source_trace_key(compact_trace),
                    compact_trace,
                )

    def _source_trace_key(self, trace: dict) -> str:
        return "|".join(
            self._first_text(trace.get(key))
            for key in ("page", "table", "row_id", "row_no")
        )

    def _row_trace_text(self, row: dict) -> str:
        parts = []
        if row.get("row_id"):
            parts.append(f"row_id={row.get('row_id')}")
        if row.get("row_bbox") is not None:
            parts.append(f"bbox={row.get('row_bbox')}")
        source_line_ids = [
            str(cell.get("source_line_id"))
            for cell in self._as_list(row.get("cell_metadata"))
            if isinstance(cell, dict) and cell.get("source_line_id")
        ]
        if source_line_ids:
            parts.append(f"source_line_ids={','.join(source_line_ids)}")
        return (" " + " ".join(parts)) if parts else ""

    def _first_text(self, *values: Any) -> str:
        for value in values:
            if value not in (None, ""):
                return str(value).strip()
        return ""

    def _dedupe_list(self, values: list) -> list:
        deduped = []
        for value in values:
            if value not in deduped:
                deduped.append(value)
        return deduped

    def _relative_to_project(self, path: Path | str) -> str:
        return str(Path(path).resolve().relative_to(local_store.PROJECT_ROOT.resolve()))

    def _as_list(self, value: Any) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        return [value]

    def _normalize_result(
        self,
        case_id: str,
        file_record: dict,
        llm_result: dict,
        document_context: dict | None = None,
    ) -> dict:
        extract_result = dict(llm_result) if isinstance(llm_result, dict) else {}
        has_business_events = isinstance(extract_result.get("business_events"), list)
        if has_business_events:
            extract_result.setdefault(
                "schema_version",
                "guangfa_business_event_understanding_v1",
            )
            extract_result.setdefault("file_summary", {})
            extract_result.setdefault("account_candidates", [])
            extract_result.setdefault("holding_records", [])
            extract_result.setdefault("negative_proofs", [])
            extract_result.setdefault("document_level_review_items", [])
        else:
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
        extract_result["document_info"] = merge_document_info(
            document_context,
            extract_result.get("document_info"),
        )
        extract_result.setdefault("accounts", [])
        extract_result.setdefault("holdings", [])
        extract_result.setdefault("transactions", [])
        extract_result.setdefault("cash_flows", [])
        extract_result.setdefault("events", [])
        extract_result.setdefault("raw_llm_output", None)
        extract_result.setdefault("manual_review_required", False)
        extract_result.setdefault("review_reasons", [])
        self._apply_document_context(extract_result, document_context or {})
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
