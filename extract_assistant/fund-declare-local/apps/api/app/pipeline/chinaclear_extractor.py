from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from app.pipeline.document_context import (
    build_document_context,
    format_document_context,
    merge_document_info,
)
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
            )
            local_store.save_json(extract_batches_path, {"batches": batch_results})
        else:
            final_prompt = self._build_final_prompt(
                prompt,
                file_record,
                input_payload["input_text"],
                document_context,
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
                "input_text:",
                input_text,
                self._compact_output_contract(),
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
        tables_payload = local_store.read_json(output_dir / "tables.json", {})
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
                }
            )

            start = end
            batch_number += 1

        return batches

    def _flatten_table_rows(self, tables_payload: dict) -> list[dict]:
        flattened_rows = []
        for table in self._as_list(tables_payload.get("tables")):
            if not isinstance(table, dict):
                continue

            rows = self._as_list(table.get("rows"))
            if len(rows) < 2:
                continue

            header = rows[0] if isinstance(rows[0], list) else []
            for row_index, row in enumerate(rows[1:], start=1):
                if not isinstance(row, list) or not any(str(cell).strip() for cell in row):
                    continue

                flattened_rows.append(
                    {
                        "page": table.get("page"),
                        "table_index": table.get("table_index"),
                        "row_index": row_index,
                        "row_no": str(row[0]).strip() if row else "",
                        "header": header,
                        "cells": row,
                    }
                )

        return flattened_rows

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
                    f"row_no={row.get('row_no')} row_index={row.get('row_index')}] "
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
    ) -> dict:
        final_prompt = self._build_batch_prompt(
            prompt,
            file_record,
            batch,
            document_context,
        )
        result = self.llm_client.extract_json(final_prompt)
        result["batch_id"] = batch["batch_id"]
        result["batch_row_range"] = {
            "row_start": batch["row_start"],
            "row_end": batch["row_end"],
        }
        return result

    def _build_batch_prompt(
        self,
        prompt: str,
        file_record: dict,
        batch: dict,
        document_context: dict | None = None,
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
            for key in ("page", "table_index", "row_no", "row_index")
        )

    def _filled_count(self, values: list[Any]) -> int:
        return sum(1 for value in values if value not in ("", None, []))

    def _to_int(self, value: str) -> int:
        try:
            return int(str(value))
        except ValueError:
            return 10**9

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
