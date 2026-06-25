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


CHINACLEAR_BATCH_ROW_LIMIT = 35
CHINACLEAR_BATCH_OVERLAP_ROWS = 5
CHINACLEAR_BATCH_MAX_WORKERS = 4
TRADE_COLUMNS = [
    "trade_id",
    "market",
    "trade_date",
    "security_code",
    "security_name",
    "direction",
    "quantity_raw",
    "price_raw",
    "balance_after_raw",
    "transfer_type_raw",
    "source_page",
    "row_no",
]


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
        extract_batches_path = output_dir / "extract_batches.json"
        input_payload = build_extraction_input(output_dir)
        graph_rag_context = input_payload.get("graph_rag_context", "")
        multimodal_context = input_payload.get("multimodal_context", "")
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

        batches = self._build_table_batches(output_dir)
        if batches:
            llm_result, batch_results = self._extract_batches(
                prompt,
                file_record,
                batches,
                document_context,
                graph_rag_context,
                multimodal_context,
            )
            local_store.save_json(extract_batches_path, {"batches": batch_results})
        else:
            final_prompt = self._build_final_prompt(
                prompt,
                file_record,
                input_payload["input_text"],
                document_context,
                graph_rag_context,
                multimodal_context,
            )
            llm_result = self.llm_client.extract_json(final_prompt)

        extract_result = self._normalize_result(
            case_id,
            file_record,
            llm_result,
            document_context,
        )
        extract_result["input_sources"] = input_payload["sources"]
        if batches:
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
        multimodal_context: str = "",
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
                "材料级上下文使用规则：如果 document_context 中有持有人、证券子账户/证券账号、账户类型或查询期限，后续交易/持仓/负向证明默认继承这些同一份材料的全局要素；一码通账号不是证券账号。",
                self._graph_rag_prompt_section(graph_rag_context),
                self._multimodal_prompt_section(multimodal_context),
                "input_text:",
                input_text,
                self._compact_output_contract(),
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

    def _multimodal_prompt_section(self, multimodal_context: str = "") -> str:
        context = str(multimodal_context or "").strip()
        if not context:
            return "multimodal_context: 无"
        return "\n".join(
            [
                "multimodal_context:",
                "以下是多模态模型给出的短版面观察，只能辅助判断页面类型、查询条件区、结果表区、空结果和噪声区域；不得覆盖 OCR/表格文本。若与文本冲突，输出待复核项。",
                context,
            ]
        )

    def _compact_output_contract(self) -> str:
        return "\n".join(
            [
                "最终输出约束：",
                "1. 只输出一个合法 JSON 对象，不要输出解释文字、Markdown 或代码块。",
                "2. 使用 schema_version=chinaclear_event_understanding_v2。",
                "3. 普通交易只输出到 trade_group.trades，不要输出到 other_events。",
                "4. trade_group.trade_columns 固定为：[\"trade_id\",\"market\",\"trade_date\",\"security_code\",\"security_name\",\"direction\",\"quantity_raw\",\"price_raw\",\"balance_after_raw\",\"transfer_type_raw\",\"source_page\",\"row_no\"]。",
                "5. trade_group.trades 中每一行必须严格按 trade_columns 顺序输出；没有值的位置用空字符串。",
                "6. other_events 只放非普通交易事件：security_registration、cash_dividend、bond_interest、bonus_share、no_account_info、no_trade_record、no_holding_record、unknown_event。",
                "7. no_account_info 表示未曾开立/未查询到证券账户，不等于 no_holding_record 或 no_trade_record。",
                "8. 持仓快照输出到 holding_records；无账户、无交易、无持仓输出到 negative_proofs；文件级或跨页疑问输出到 document_level_review_items。",
                "9. no_account_info、no_trade_record、no_holding_record 必须尽量保留简短 raw_text 原文证据；其他事件不要输出 confidence、llm_confidence、related_rows、business_interpretation、calculation_policy。",
            ]
        )

    def _build_table_batches(self, output_dir: Path) -> list[dict]:
        tables_payload = self._load_tables_payload(output_dir)
        if not isinstance(tables_payload, dict):
            return []

        rows = self._flatten_table_rows(tables_payload)
        if not rows:
            return []

        batches = []
        start = 0
        batch_number = 1
        while start < len(rows):
            end = min(start + CHINACLEAR_BATCH_ROW_LIMIT, len(rows))
            batch_start = max(0, start - CHINACLEAR_BATCH_OVERLAP_ROWS)
            batch_end = min(len(rows), end + CHINACLEAR_BATCH_OVERLAP_ROWS)
            batch_rows = rows[batch_start:batch_end]
            primary_rows = rows[start:end]

            batches.append(
                {
                    "batch_id": f"batch_{batch_number:03d}",
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

                flattened_rows.append(
                    {
                        "page": table.get("page"),
                        "table_index": table.get("table_index"),
                        "row_index": row_meta.get("row_index") or row_index,
                        "row_id": row_meta.get("row_id", ""),
                        "row_bbox": row_meta.get("bbox"),
                        "row_no": str(row[0]).strip() if row else "",
                        "header": header,
                        "cells": row,
                        "cell_metadata": cell_meta,
                    }
                )

        return flattened_rows

    def _looks_like_table_header(self, row: list) -> bool:
        header_text = " ".join(str(cell) for cell in row if cell is not None)
        return any(
            keyword in header_text
            for keyword in (
                "证券代码",
                "证券名称",
                "变动日期",
                "发生日期",
                "交易日期",
                "持有数量",
                "股份余额",
                "过户类型",
                "业务类型",
            )
        )

    def _batch_rows_to_text(self, rows: list[dict]) -> str:
        if not rows:
            return ""

        header = rows[0].get("header") or []
        parts = [
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
                    f"row_no={row.get('row_no')} row_index={row.get('row_index')}"
                    f"{self._row_trace_text(row)}] "
                    f"{cells_text}"
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
        multimodal_context: str = "",
    ) -> tuple[dict, list[dict]]:
        batch_results: list[dict] = []
        max_workers = min(CHINACLEAR_BATCH_MAX_WORKERS, len(batches))

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    self._extract_one_batch,
                    prompt,
                    file_record,
                    batch,
                    document_context or {},
                    graph_rag_context,
                    multimodal_context,
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
        multimodal_context: str = "",
    ) -> dict:
        final_prompt = self._build_batch_prompt(
            prompt,
            file_record,
            batch,
            document_context,
            graph_rag_context,
            multimodal_context,
        )
        result = self.llm_client.extract_json(final_prompt)
        result["batch_id"] = batch["batch_id"]
        result["batch_row_range"] = {
            "row_start": batch["row_start"],
            "row_end": batch["row_end"],
        }
        self._attach_compact_source_traces(result, batch.get("source_traces"))
        return result

    def _build_batch_prompt(
        self,
        prompt: str,
        file_record: dict,
        batch: dict,
        document_context: dict | None = None,
        graph_rag_context: str = "",
        multimodal_context: str = "",
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
                "材料级上下文使用规则：如果 document_context 中有持有人、证券子账户/证券账号、账户类型或查询期限，当前 batch 的交易/持仓/负向证明默认继承这些同一份材料的全局要素；一码通账号不是证券账号。",
                self._graph_rag_prompt_section(graph_rag_context),
                self._multimodal_prompt_section(multimodal_context),
                f"batch_id: {batch['batch_id']}",
                f"primary_row_range: {batch['row_start']} - {batch['row_end']}",
                "注意：输入中包含前后 overlap 行。overlap 行可以抽取，后端会按 row_no 去重。",
                "input_text:",
                batch["input_text"],
                self._compact_output_contract(),
            ]
        )

    def _merge_batch_results(
        self,
        batch_results: list[dict],
        document_context: dict | None = None,
    ) -> dict:
        merged = {
            "schema_version": "chinaclear_event_understanding_v2",
            "document_info": merge_document_info(document_context, None),
            "trade_group": {
                "event_type": "ordinary_trade_group",
                "trade_columns": TRADE_COLUMNS,
                "trades": [],
            },
            "other_events": [],
            "holding_records": [],
            "negative_proofs": [],
            "document_level_review_items": [],
            "source_traces": [],
            "quality": {"warnings": []},
            "extract_status": "success",
            "manual_review_required": False,
            "review_reasons": [],
            "llm_response_metadata": {
                "batch_mode": True,
                "batch_options": {
                    "batch_row_limit": CHINACLEAR_BATCH_ROW_LIMIT,
                    "overlap_rows": CHINACLEAR_BATCH_OVERLAP_ROWS,
                    "max_workers": CHINACLEAR_BATCH_MAX_WORKERS,
                },
                "batches": [],
            },
        }

        trades_by_key: dict[str, list[Any]] = {}
        other_events_by_key: dict[str, dict] = {}
        holdings_by_key: dict[str, dict] = {}
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

            if isinstance(result.get("document_info"), dict):
                merged["document_info"] = merge_document_info(
                    merged.get("document_info"),
                    result["document_info"],
                )

            self._merge_trades(trades_by_key, result)
            self._merge_other_events(other_events_by_key, result)
            self._merge_records(
                holdings_by_key,
                result.get("holding_records"),
                self._holding_key,
            )
            self._merge_records(
                proofs_by_key,
                result.get("negative_proofs"),
                self._negative_proof_key,
            )
            self._merge_records(
                review_items_by_key,
                result.get("document_level_review_items"),
                self._review_item_key,
            )
            self._merge_source_traces(source_traces_by_key, result.get("source_traces"))
            self._merge_warnings(merged, result)

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

        merged["trade_group"]["trades"] = sorted(
            trades_by_key.values(),
            key=self._trade_sort_key,
        )
        merged["other_events"] = sorted(
            other_events_by_key.values(),
            key=self._other_event_sort_key,
        )
        merged["holding_records"] = list(holdings_by_key.values())
        merged["negative_proofs"] = list(proofs_by_key.values())
        merged["document_level_review_items"] = list(review_items_by_key.values())
        merged["source_traces"] = list(source_traces_by_key.values())
        self._apply_document_context(merged, document_context or {})
        merged["review_reasons"] = self._dedupe_list(merged["review_reasons"])
        return merged

    def _apply_document_context(self, extract_result: dict, context: dict) -> None:
        if not context:
            return
        extract_result["document_info"] = merge_document_info(
            context,
            extract_result.get("document_info"),
        )
        securities_account = str(context.get("securities_account") or "").strip()
        account_type = str(context.get("account_type") or "").strip()
        holder_name = str(context.get("holder_name") or "").strip()
        period_end = str(context.get("period_end") or "").strip()
        period_start = str(context.get("period_start") or "").strip()

        for holding in self._as_list(extract_result.get("holding_records")):
            if not isinstance(holding, dict):
                continue
            if securities_account and not self._first_text(holding.get("证券账号"), holding.get("securities_account")):
                holding["证券账号"] = securities_account
            if account_type and not self._first_text(holding.get("账户类型"), holding.get("account_type")):
                holding["账户类型"] = account_type
            if period_end and not self._first_text(holding.get("查询结果所属日期"), holding.get("holding_date"), holding.get("date")):
                holding["查询结果所属日期"] = period_end

        for proof in self._as_list(extract_result.get("negative_proofs")):
            if not isinstance(proof, dict):
                continue
            if holder_name and not self._first_text(proof.get("person_name"), proof.get("holder_name")):
                proof["person_name"] = holder_name
            if period_end and not self._first_text(proof.get("as_of_date"), proof.get("query_date"), proof.get("event_date"), proof.get("period_end")):
                proof["as_of_date"] = period_end
            if period_start and not self._first_text(proof.get("period_start")):
                proof["period_start"] = period_start
            if securities_account and not self._first_text(proof.get("securities_account"), proof.get("证券账号")):
                proof["securities_account"] = securities_account
            if account_type and not self._first_text(proof.get("account_type"), proof.get("账户类型")):
                proof["account_type"] = account_type

    def _merge_trades(self, trades_by_key: dict[str, list[Any]], result: dict) -> None:
        trade_group = result.get("trade_group")
        if not isinstance(trade_group, dict):
            return

        columns = trade_group.get("trade_columns") or TRADE_COLUMNS
        for trade in self._as_list(trade_group.get("trades")):
            if not isinstance(trade, list):
                continue

            trade_record = self._row_to_record(columns, trade)
            row_no = str(trade_record.get("row_no", "")).strip()
            source_page = str(trade_record.get("source_page", "")).strip()
            key = (
                f"{source_page}|{row_no}"
                if row_no
                else "|".join(
                    str(trade_record.get(field, ""))
                    for field in (
                        "market",
                        "trade_date",
                        "security_code",
                        "direction",
                        "quantity_raw",
                        "balance_after_raw",
                    )
                )
            )
            if not key:
                continue

            normalized_trade = [trade_record.get(column, "") for column in TRADE_COLUMNS]
            existing_trade = trades_by_key.get(key)
            if existing_trade is None or self._filled_count(
                normalized_trade
            ) > self._filled_count(existing_trade):
                trades_by_key[key] = normalized_trade

    def _merge_other_events(
        self,
        other_events_by_key: dict[str, dict],
        result: dict,
    ) -> None:
        for event in self._as_list(result.get("other_events")):
            if not isinstance(event, dict):
                continue

            key = self._other_event_key(event)
            existing_event = other_events_by_key.get(key)
            if existing_event is None:
                other_events_by_key[key] = dict(event)
            else:
                self._merge_event_into(existing_event, event)

    def _merge_warnings(self, merged: dict, result: dict) -> None:
        quality = result.get("quality")
        if not isinstance(quality, dict):
            return

        warnings = quality.get("warnings")
        if isinstance(warnings, list):
            merged["quality"]["warnings"].extend(
                warning for warning in warnings if warning
            )
            merged["quality"]["warnings"] = self._dedupe_list(
                merged["quality"]["warnings"]
            )

    def _row_to_record(self, columns: list, row: list) -> dict:
        return {
            str(column): row[index] if index < len(row) else ""
            for index, column in enumerate(columns)
        }

    def _other_event_key(self, event: dict) -> str:
        return "|".join(
            str(event.get(field, ""))
            for field in (
                "event_type",
                "market",
                "event_date",
                "security_code",
                "security_name",
                "transfer_type_raw",
            )
        )

    def _merge_event_into(self, target: dict, source: dict) -> None:
        for key, value in source.items():
            if key in {"source_pages", "row_nos"}:
                target[key] = self._dedupe_list(
                    [*self._as_list(target.get(key)), *self._as_list(value)]
                )
            elif key in {"review_reasons", "missing_fields"}:
                target[key] = self._dedupe_list(
                    [*self._as_list(target.get(key)), *self._as_list(value)]
                )
            elif key == "source_evidence" and isinstance(value, dict):
                existing = target.get(key)
                if not isinstance(existing, dict):
                    target[key] = dict(value)
                else:
                    self._merge_event_into(existing, value)
            elif not target.get(key) and value:
                target[key] = value

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
                self._merge_event_into(existing, record)

    def _holding_key(self, holding: dict) -> str:
        return "|".join(
            str(holding.get(field, ""))
            for field in (
                "holding_id",
                "账户类型",
                "证券账号",
                "证券代码",
                "证券名称",
                "持有数量",
                "查询结果所属日期",
            )
        )

    def _negative_proof_key(self, proof: dict) -> str:
        evidence = proof.get("source_evidence") or {}
        if not isinstance(evidence, dict):
            evidence = {}
        return "|".join(
            str(value or "")
            for value in (
                proof.get("proof_type"),
                proof.get("person_name"),
                proof.get("as_of_date"),
                proof.get("query_date"),
                proof.get("period_start"),
                proof.get("period_end"),
                proof.get("securities_account"),
                evidence.get("raw_text"),
            )
        )

    def _review_item_key(self, item: dict) -> str:
        return "|".join(str(value or "") for value in item.values())

    def _trade_sort_key(self, trade: list) -> tuple[int, str]:
        source_page = str(
            trade[TRADE_COLUMNS.index("source_page")] if len(trade) > 10 else ""
        )
        row_no = str(trade[TRADE_COLUMNS.index("row_no")] if len(trade) > 11 else "")
        return (self._to_int(source_page), self._to_int(row_no), row_no)

    def _other_event_sort_key(self, event: dict) -> tuple[int, str]:
        row_nos = self._as_list(event.get("row_nos"))
        first_row_no = str(row_nos[0]) if row_nos else ""
        return (self._to_int(first_row_no), first_row_no)

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
            "other_events",
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
            columns = trade_group.get("trade_columns") or trade_group.get("columns") or TRADE_COLUMNS
            for trade in self._as_list(trade_group.get("trades")):
                if not isinstance(trade, list):
                    continue
                trace = self._find_source_trace(
                    self._row_to_record(columns, trade),
                    trace_index,
                )
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

    def _filled_count(self, values: list[Any]) -> int:
        return sum(1 for value in values if value not in ("", None, []))

    def _to_int(self, value: str) -> int:
        try:
            return int(str(value))
        except ValueError:
            return 10**9

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
        extract_result.setdefault("holding_records", [])
        extract_result.setdefault("negative_proofs", [])
        extract_result.setdefault("document_level_review_items", [])
        extract_result.setdefault("transactions", [])
        extract_result.setdefault("events", [])
        extract_result.setdefault("raw_llm_output", None)
        extract_result.setdefault("manual_review_required", False)
        extract_result.setdefault("review_reasons", [])
        extract_result["document_info"] = merge_document_info(
            document_context,
            extract_result.get("document_info"),
        )
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
