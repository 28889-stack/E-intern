from __future__ import annotations

import re
import struct
from pathlib import Path
from typing import Any

from app.core.config import (
    GRAPH_RAG_EMBEDDING_ENABLED,
    GRAPH_RAG_EMBEDDING_MODEL,
    GRAPH_RAG_VECTOR_TOP_K,
)
from app.services.embedding_client import EmbeddingClient
from app.services import local_store


GRAPH_SCHEMA_VERSION = "graph_rag_v1"
MAX_CONTEXT_BLOCKS = 20
MAX_CONTEXT_TEXT_CHARS = 200
MAX_PROMPT_CONTEXT_CHARS = 6000
MAX_RECORD_CANDIDATES = 12
MAX_RECORD_CONTEXT_CANDIDATES = 8
MAX_RECORD_SOURCE_TEXT_CHARS = 160
VECTOR_QUERIES = (
    "证券交易记录，买入，卖出，申购，送股，成交数量，成交金额",
    "股息，派息，现金分红，红利，兑息，利息，资金流水，银证转账",
    "证券账号，资金账号，股东账号，账户类型",
    "持仓，证券代码，证券名称，持有数量，市值",
)

EVENT_KEYWORDS = (
    "买入",
    "卖出",
    "证券买入",
    "证券卖出",
    "申购",
    "打新",
    "新股",
    "中签",
    "入账",
    "送股",
    "转增",
    "配股",
    "交易过户",
    "权益登记",
    "权益挂牌",
)
CASH_EVENT_KEYWORDS = (
    "股息",
    "派息",
    "红利",
    "分红",
    "兑息",
    "利息",
    "银证转账",
    "银行转证券",
    "证券转银行",
    "资金流水",
)
NOISE_ROW_KEYWORDS = (
    "自选",
    "行情",
    "资讯",
    "理财",
    "热门主题",
    "新股日历",
    "沪深新股新债申购",
    "菜单",
    "刷新",
    "设置",
)
SECURITY_CODE_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")
DATE_RE = re.compile(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})日?")
ACCOUNT_RE = re.compile(r"\b([A-Za-z]\d{8,12}|\d{8,12})\b")


def run_graph_rag_sidecar(
    file_record: dict,
    output_dir: str | Path,
    embedding_client: Any | None = None,
) -> dict[str, Any]:
    output_path = Path(output_dir)
    graph_dir = local_store.ensure_dir(output_path / "graph_rag")
    rows, source_priority = _load_source_rows(output_path)
    chunks = _build_chunks(rows, file_record)
    record_candidates = _build_record_candidates(rows, file_record)

    nodes_by_id: dict[str, dict] = {}
    relationships_by_key: dict[tuple, dict] = {}
    file_id = str(file_record.get("file_id") or output_path.name)

    document = _node(
        f"document:{file_id}",
        "Document",
        file_record.get("original_file_name") or file_id,
        aliases=[file_id],
    )
    nodes_by_id[document["id"]] = document

    for row in rows:
        page_no = row.get("page_no") or 1
        page = _node(f"page:{file_id}:{page_no}", "Page", f"第 {page_no} 页")
        nodes_by_id.setdefault(page["id"], page)
        _add_relationship(
            relationships_by_key,
            document["id"],
            page["id"],
            "CONTAINS",
            1.0,
        )

        accounts = _account_entities(row, file_record)
        securities = _security_entities(row, file_record)
        holder = _holder_entity(row, file_record)
        event = None if _is_noise_row(row) else _event_entity(row, file_record)

        for account in accounts:
            _merge_node(nodes_by_id, account)
            _add_relationship(
                relationships_by_key,
                page["id"],
                account["id"],
                "MENTIONS",
                0.75,
            )
        for security in securities:
            _merge_node(nodes_by_id, security)
            _add_relationship(
                relationships_by_key,
                page["id"],
                security["id"],
                "MENTIONS",
                0.75,
            )
        if holder:
            _merge_node(nodes_by_id, holder)
            _add_relationship(
                relationships_by_key,
                page["id"],
                holder["id"],
                "MENTIONS",
                0.7,
            )

        if event:
            _merge_node(nodes_by_id, event)
            _add_relationship(
                relationships_by_key,
                page["id"],
                event["id"],
                "CONTAINS",
                0.85,
            )
            _add_relationship(
                relationships_by_key,
                event["id"],
                page["id"],
                "HAS_SOURCE",
                1.0,
            )
            for account in accounts:
                _add_relationship(
                    relationships_by_key,
                    event["id"],
                    account["id"],
                    "BELONGS_TO_ACCOUNT",
                    0.8,
                )
            for security in securities:
                _add_relationship(
                    relationships_by_key,
                    event["id"],
                    security["id"],
                    "AFFECTS_SECURITY",
                    0.85,
                )
            if holder:
                _add_relationship(
                    relationships_by_key,
                    event["id"],
                    holder["id"],
                    "RELATED_TO",
                    0.55,
                )

    for candidate in record_candidates:
        record_node = _record_candidate_node(candidate, file_record)
        _merge_node(nodes_by_id, record_node)
        page_no = candidate.get("page_no") or 1
        page_id = f"page:{file_id}:{page_no}"
        if page_id in nodes_by_id:
            _add_relationship(
                relationships_by_key,
                page_id,
                record_node["id"],
                "CONTAINS",
                0.9,
            )
            _add_relationship(
                relationships_by_key,
                record_node["id"],
                page_id,
                "HAS_SOURCE",
                1.0,
            )
        account_number = str(candidate.get("fields", {}).get("account_number") or "")
        security_code = str(candidate.get("fields", {}).get("security_code") or "")
        if account_number and f"account:{account_number}" in nodes_by_id:
            _add_relationship(
                relationships_by_key,
                record_node["id"],
                f"account:{account_number}",
                "BELONGS_TO_ACCOUNT",
                0.85,
            )
        if security_code and f"security:{security_code}" in nodes_by_id:
            _add_relationship(
                relationships_by_key,
                record_node["id"],
                f"security:{security_code}",
                "AFFECTS_SECURITY",
                0.9,
            )

    graph = {
        "schema_version": GRAPH_SCHEMA_VERSION,
        "file_id": file_id,
        "graph_rag_status": "success",
        "nodes": list(nodes_by_id.values()),
        "relationships": list(relationships_by_key.values()),
    }
    entities = {
        "schema_version": GRAPH_SCHEMA_VERSION,
        "file_id": file_id,
        "entities": list(nodes_by_id.values()),
    }
    relationships = {
        "schema_version": GRAPH_SCHEMA_VERSION,
        "file_id": file_id,
        "relationships": list(relationships_by_key.values()),
    }
    embedding_result = _build_embedding_retrieval(
        chunks,
        nodes_by_id,
        graph_dir,
        embedding_client,
    )
    retrieval_result = _build_retrieval_result(
        nodes_by_id,
        relationships_by_key,
        embedding_result.get("vector_context_blocks", []),
        record_candidates,
    )
    build_debug = {
        "schema_version": GRAPH_SCHEMA_VERSION,
        "file_id": file_id,
        "graph_rag_status": "success",
        "source_priority": source_priority,
        "row_count": len(rows),
        "chunk_count": len(chunks),
        "record_candidate_count": len(record_candidates),
        "entity_count": len(nodes_by_id),
        "relationship_count": len(relationships_by_key),
        "embedding_enabled": bool(GRAPH_RAG_EMBEDDING_ENABLED),
        "embedding_status": embedding_result.get("embedding_status"),
        "embedding_model": embedding_result.get("embedding_model"),
        "embedding_error": embedding_result.get("embedding_error"),
    }

    local_store.save_json(graph_dir / "chunks.json", {
        "schema_version": GRAPH_SCHEMA_VERSION,
        "file_id": file_id,
        "chunks": chunks,
    })
    local_store.save_json(graph_dir / "graph.json", graph)
    local_store.save_json(graph_dir / "entities.json", entities)
    local_store.save_json(graph_dir / "relationships.json", relationships)
    local_store.save_json(graph_dir / "retrieval_result.json", retrieval_result)
    local_store.save_json(graph_dir / "build_debug.json", build_debug)

    return {
        "graph_rag_status": "success",
        "graph_path": _relative(graph_dir / "graph.json"),
        "entities_path": _relative(graph_dir / "entities.json"),
        "relationships_path": _relative(graph_dir / "relationships.json"),
        "retrieval_result_path": _relative(graph_dir / "retrieval_result.json"),
        "build_debug_path": _relative(graph_dir / "build_debug.json"),
        "chunks_path": _relative(graph_dir / "chunks.json"),
        "embeddings_path": (
            _relative(graph_dir / "embeddings.npy")
            if (graph_dir / "embeddings.npy").exists()
            else None
        ),
        "embedding_status": embedding_result.get("embedding_status"),
        "embedding_model": embedding_result.get("embedding_model"),
        "entity_count": len(nodes_by_id),
        "relationship_count": len(relationships_by_key),
        "context_block_count": len(retrieval_result["context_blocks"]),
    }


def format_graph_rag_context(output_dir: str | Path) -> str:
    retrieval_path = Path(output_dir) / "graph_rag" / "retrieval_result.json"
    retrieval = local_store.read_json(retrieval_path, {})
    if not isinstance(retrieval, dict):
        return ""
    if not retrieval.get("record_candidates") and not retrieval.get("context_blocks"):
        return ""

    parts = [
        f"query: {retrieval.get('query', '')}",
        "matched_entities: " + ", ".join(_as_list(retrieval.get("matched_entities"))[:30]),
    ]
    record_candidates = _as_list(retrieval.get("record_candidates"))[:MAX_RECORD_CONTEXT_CANDIDATES]
    if record_candidates:
        parts.append("record_candidates:")
        for candidate in record_candidates:
            if not isinstance(candidate, dict):
                continue
            fields = candidate.get("fields") if isinstance(candidate.get("fields"), dict) else {}
            compact_fields = []
            for key in (
                "event_date",
                "account_number",
                "security_code",
                "security_name",
                "movement_type",
                "quantity_raw",
                "price_raw",
                "amount_raw",
                "balance_after_raw",
            ):
                value = str(fields.get(key) or "").strip()
                if value:
                    compact_fields.append(f"{key}={value}")
            parts.append(
                "\n".join(
                    [
                        f"[record page={candidate.get('page_no', '')} row_no={candidate.get('row_no', '')}]",
                        "fields: " + "; ".join(compact_fields),
                        "source_text: "
                        + _compact_text(candidate.get("source_text"), MAX_RECORD_SOURCE_TEXT_CHARS),
                    ]
                )
            )
    if retrieval.get("context_blocks"):
        parts.append("context_blocks:")
    for block in _as_list(retrieval.get("context_blocks"))[:MAX_CONTEXT_BLOCKS]:
        if not isinstance(block, dict):
            continue
        source_text = _compact_text(block.get("source_text"), MAX_CONTEXT_TEXT_CHARS)
        parts.append(
            "\n".join(
                [
                    f"[page={block.get('page_no', '')} row_no={block.get('row_no', '')}]",
                    f"retrieval_method: {block.get('retrieval_method', '')}",
                    f"vector_query: {block.get('query', '')}" if block.get("query") else "",
                    f"reason: {block.get('reason', '')}",
                    "related_entities: "
                    + ", ".join(_as_list(block.get("related_entities"))[:12]),
                    f"source_text: {source_text}",
                ]
            )
        )
    return _compact_text("\n".join(parts), MAX_PROMPT_CONTEXT_CHARS)


def _load_source_rows(output_path: Path) -> tuple[list[dict], str]:
    document_structure = local_store.read_json(output_path / "document_structure.json", {})
    if isinstance(document_structure, dict) and document_structure.get("pages"):
        return _rows_from_document_structure(document_structure), "document_structure"

    tables = local_store.read_json(output_path / "tables.json", {})
    if isinstance(tables, dict) and tables.get("tables"):
        return _rows_from_tables(tables), "tables"

    raw_text = local_store.read_json(output_path / "raw_text.json", {})
    if isinstance(raw_text, dict) and raw_text.get("pages"):
        return _rows_from_text_pages(raw_text.get("pages"), "raw_text"), "raw_text"

    ocr_result = local_store.read_json(output_path / "ocr_result.json", {})
    if isinstance(ocr_result, dict):
        pages = ocr_result.get("pages") or ocr_result.get("page_results") or []
        if pages:
            return _rows_from_text_pages(pages, "ocr_result"), "ocr_result"

    return [], "empty"


def _build_chunks(rows: list[dict], file_record: dict) -> list[dict]:
    chunks = []
    file_id = str(file_record.get("file_id") or "")
    for index, row in enumerate(rows, start=1):
        chunk_id = f"chunk_{index:04d}"
        row["chunk_id"] = chunk_id
        text = _compact_text(row.get("text"), MAX_CONTEXT_TEXT_CHARS)
        if not text:
            continue
        chunks.append(
            {
                "chunk_id": chunk_id,
                "file_id": file_id,
                "page_no": row.get("page_no"),
                "row_no": row.get("row_no"),
                "row_id": row.get("row_id", ""),
                "text": text,
                "source_type": row.get("source", ""),
                "source_ref": _source_ref(row, file_record),
            }
        )
    return chunks


def _rows_from_document_structure(document_structure: dict) -> list[dict]:
    rows = []
    for page in _as_list(document_structure.get("pages")):
        if not isinstance(page, dict):
            continue
        page_no = page.get("page_no") or page.get("page") or 1
        for table in _as_list(page.get("tables")):
            if not isinstance(table, dict):
                continue
            headers: list[str] = []
            for row_index, row in enumerate(_as_list(table.get("rows")), start=1):
                if not isinstance(row, dict):
                    continue
                cells = [
                    str(cell.get("text") or "").strip()
                    for cell in _as_list(row.get("cells"))
                    if isinstance(cell, dict)
                ]
                if not any(cells):
                    continue
                if _looks_like_header(cells):
                    headers = cells
                    continue
                rows.append(
                    {
                        "page_no": page_no,
                        "table_index": table.get("table_index"),
                        "row_no": _row_no(cells, row.get("row_id")),
                        "row_id": row.get("row_id", ""),
                        "headers": headers,
                        "cells": cells,
                        "text": " ".join(cell for cell in cells if cell),
                        "source": "document_structure",
                    }
                )
    return rows


def _rows_from_tables(tables: dict) -> list[dict]:
    rows = []
    for table in _as_list(tables.get("tables")):
        if not isinstance(table, dict):
            continue
        headers: list[str] = []
        for row_index, row in enumerate(_as_list(table.get("rows")), start=1):
            if not isinstance(row, list):
                continue
            cells = [str(cell or "").strip() for cell in row]
            if not any(cells):
                continue
            if _looks_like_header(cells):
                headers = cells
                continue
            rows.append(
                {
                    "page_no": table.get("page") or 1,
                    "table_index": table.get("table_index"),
                    "row_no": _row_no(cells, str(row_index)),
                    "row_id": str(row_index),
                    "headers": headers,
                    "cells": cells,
                    "text": " ".join(cell for cell in cells if cell),
                    "source": "tables",
                }
            )
    return rows


def _rows_from_text_pages(pages: Any, source: str) -> list[dict]:
    rows = []
    for page in _as_list(pages):
        if not isinstance(page, dict):
            continue
        page_no = page.get("page") or page.get("page_no") or 1
        text = str(page.get("text") or page.get("page_text") or "")
        for line_index, line in enumerate(text.splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            rows.append(
                {
                    "page_no": page_no,
                    "table_index": "",
                    "row_no": str(line_index),
                    "row_id": f"line_{line_index}",
                    "headers": [],
                    "cells": [line],
                    "text": line,
                    "source": source,
                }
            )
    return rows


def _account_entities(row: dict, file_record: dict) -> list[dict]:
    entities = []
    for header, value in _header_values(row):
        if not _looks_like_account_header(header):
            continue
        for account in ACCOUNT_RE.findall(value):
            entities.append(
                _node(
                    f"account:{account}",
                    "Account",
                    account,
                    aliases=[account, header],
                    source_refs=[_source_ref(row, file_record)],
                )
            )
    text = str(row.get("text") or "")
    for match in re.finditer(r"(证券账号|证券账户|股东卡号|资金账号|资金账户)[:：\s]*([A-Za-z]?\d{8,12})", text):
        account = match.group(2)
        entities.append(
            _node(
                f"account:{account}",
                "Account",
                account,
                aliases=[account, match.group(1)],
                source_refs=[_source_ref(row, file_record)],
            )
        )
    return _unique_nodes(entities)


def _security_entities(row: dict, file_record: dict) -> list[dict]:
    entities = []
    values = list(_header_values(row))
    code_from_header = ""
    name_from_header = ""
    for header, value in values:
        if _looks_like_non_security_code_header(header):
            continue
        if "证券代码" in header:
            match = SECURITY_CODE_RE.search(value)
            if match:
                code_from_header = match.group(1)
        if any(keyword in header for keyword in ("证券名称", "证券简称")):
            name_from_header = value.strip()
    if code_from_header:
        aliases = [code_from_header]
        if name_from_header:
            aliases.append(name_from_header)
        entities.append(
            _node(
                f"security:{code_from_header}",
                "Security",
                name_from_header or code_from_header,
                aliases=aliases,
                source_refs=[_source_ref(row, file_record)],
            )
        )
    if not entities:
        text = str(row.get("text") or "")
        for match in re.finditer(r"(?<!\d)(\d{6})(?!\d)\s+([\u4e00-\u9fffA-Za-z]{2,16})", text):
            code = match.group(1)
            name = match.group(2)
            if _text_near_non_security_label(text, code):
                continue
            entities.append(
                _node(
                    f"security:{code}",
                    "Security",
                    name,
                    aliases=[code, name],
                    source_refs=[_source_ref(row, file_record)],
                )
            )
    return _unique_nodes(entities)


def _holder_entity(row: dict, file_record: dict) -> dict | None:
    text = str(row.get("text") or "")
    match = re.search(r"(客户姓名|持有人名称|姓名)[:：\s]*([\u4e00-\u9fff]{1,12})", text)
    if not match:
        return None
    name = match.group(2)
    return _node(
        f"holder:{name}",
        "Holder",
        name,
        aliases=[name],
        source_refs=[_source_ref(row, file_record)],
    )


def _event_entity(row: dict, file_record: dict) -> dict | None:
    text = str(row.get("text") or "")
    event_type = _event_type(text)
    if not event_type:
        return None
    node_type = "CashEvent" if _contains_any(text, CASH_EVENT_KEYWORDS) else "Transaction"
    row_identity = row.get("row_id") or row.get("row_no")
    event_id = (
        f"{node_type.lower()}:{file_record.get('file_id') or 'file'}:"
        f"page_{row.get('page_no')}:row_{row_identity}"
    )
    return _node(
        event_id,
        node_type,
        event_type,
        aliases=[event_type],
        source_refs=[_source_ref(row, file_record)],
        properties={
            "event_type": event_type,
            "date": _date_from_text(text),
            "source": row.get("source", ""),
        },
    )


def _build_record_candidates(rows: list[dict], file_record: dict) -> list[dict]:
    candidates = []
    seen = set()
    for index, row in enumerate(rows, start=1):
        candidate = _record_candidate_from_row(row, file_record, index)
        if not candidate:
            continue
        signature = (
            candidate.get("page_no"),
            candidate.get("row_no"),
            candidate.get("source_text"),
        )
        if signature in seen:
            continue
        seen.add(signature)
        candidates.append(candidate)
        if len(candidates) >= MAX_RECORD_CANDIDATES:
            break
    return candidates


def _record_candidate_from_row(row: dict, file_record: dict, index: int) -> dict | None:
    if _is_noise_row(row):
        return None

    text = str(row.get("text") or "")
    event_type = _event_type(text)
    fields = _record_fields(row)
    has_business_signal = bool(fields.get("security_code") or fields.get("movement_type")) and any(
        fields.get(key)
        for key in ("event_date", "security_name", "quantity_raw", "amount_raw", "balance_after_raw")
    )
    if not event_type and not has_business_signal:
        return None

    if not fields.get("movement_type") and event_type:
        fields["movement_type"] = event_type

    file_id = str(file_record.get("file_id") or "file")
    row_identity = row.get("row_id") or row.get("row_no") or index
    return {
        "record_id": f"record:{file_id}:page_{row.get('page_no')}:row_{row_identity}",
        "record_type": "trade_or_event_candidate",
        "page_no": row.get("page_no"),
        "row_no": row.get("row_no"),
        "row_id": row.get("row_id", ""),
        "table_index": row.get("table_index"),
        "source_type": row.get("source", ""),
        "fields": fields,
        "source_text": _compact_text(text, MAX_RECORD_SOURCE_TEXT_CHARS),
    }


def _record_fields(row: dict) -> dict[str, str]:
    text = str(row.get("text") or "")
    values = list(_header_values(row))
    fields = {
        "event_date": _date_from_text(text),
        "account_number": "",
        "security_code": "",
        "security_name": "",
        "movement_type": "",
        "quantity_raw": "",
        "price_raw": "",
        "amount_raw": "",
        "balance_after_raw": "",
    }

    for header, value in values:
        value = str(value or "").strip()
        if not value:
            continue
        if not fields["event_date"] and any(keyword in header for keyword in ("日期", "发生日期", "成交日期", "业务日期", "过户日期")):
            fields["event_date"] = _date_from_text(value)
        if not fields["account_number"] and _looks_like_account_header(header):
            account = _first_account_number(value)
            if account:
                fields["account_number"] = account
        if not fields["security_code"] and "证券代码" in header and not _looks_like_non_security_code_header(header):
            code = _first_security_code(value)
            if code:
                fields["security_code"] = code
        if not fields["security_name"] and any(keyword in header for keyword in ("证券名称", "证券简称")):
            fields["security_name"] = value
        if not fields["movement_type"] and any(keyword in header for keyword in ("业务标志", "业务名称", "变动类型", "过户类型", "摘要", "权益类别")):
            fields["movement_type"] = _compact_text(value, 40)
        if not fields["quantity_raw"] and any(keyword in header for keyword in ("成交数量", "发生数量", "过户数量", "股份数量", "持有数量")):
            fields["quantity_raw"] = value
        if not fields["price_raw"] and any(keyword in header for keyword in ("成交价格", "成交单价", "成交均价", "成交价")):
            fields["price_raw"] = value
        if not fields["amount_raw"] and any(keyword in header for keyword in ("清算金额", "发生金额", "成交金额", "收付金额", "金额")):
            fields["amount_raw"] = value
        if not fields["balance_after_raw"] and any(keyword in header for keyword in ("期末余额", "本次余额", "股份余额", "余额")):
            fields["balance_after_raw"] = value

    if not fields["account_number"]:
        fields["account_number"] = _first_account_number(text)
    if not fields["security_code"]:
        fields["security_code"] = _first_security_code(text)
    if fields["security_code"] and not fields["security_name"]:
        fields["security_name"] = _security_name_near_code(text, fields["security_code"])
    if not fields["movement_type"]:
        fields["movement_type"] = _event_type(text)

    return fields


def _record_candidate_node(candidate: dict, file_record: dict) -> dict:
    fields = candidate.get("fields") if isinstance(candidate.get("fields"), dict) else {}
    name = " ".join(
        item
        for item in (
            str(fields.get("event_date") or ""),
            str(fields.get("security_code") or ""),
            str(fields.get("security_name") or ""),
            str(fields.get("movement_type") or ""),
        )
        if item
    )
    return _node(
        str(candidate.get("record_id") or ""),
        "RecordCandidate",
        name or str(candidate.get("record_id") or ""),
        aliases=[name] if name else [],
        source_refs=[
            {
                "file_id": file_record.get("file_id", ""),
                "chunk_id": "",
                "page_no": candidate.get("page_no"),
                "row_no": candidate.get("row_no"),
                "row_id": candidate.get("row_id", ""),
                "text": _compact_text(candidate.get("source_text"), MAX_CONTEXT_TEXT_CHARS),
            }
        ],
        properties={
            "record_type": candidate.get("record_type"),
            "fields": fields,
        },
    )


def _build_retrieval_result(
    nodes_by_id: dict[str, dict],
    relationships_by_key: dict[tuple, dict],
    vector_context_blocks: list[dict] | None = None,
    record_candidates: list[dict] | None = None,
) -> dict:
    matched_entities = [
        node_id
        for node_id, node in nodes_by_id.items()
        if node.get("type") in {"Account", "Security", "Holder"}
    ][:40]
    rule_context_blocks = []
    event_nodes = [
        node
        for node in nodes_by_id.values()
        if node.get("type") in {"Transaction", "CashEvent"}
    ]
    for node in event_nodes[:MAX_CONTEXT_BLOCKS]:
        source_ref = (_as_list(node.get("source_refs")) or [{}])[0]
        related = _related_entity_labels(node["id"], nodes_by_id, relationships_by_key)
        relation_types = _related_relation_types(node["id"], relationships_by_key)
        rule_context_blocks.append(
            {
                "page_no": source_ref.get("page_no"),
                "row_no": source_ref.get("row_no"),
                "chunk_id": source_ref.get("chunk_id"),
                "source_text": _compact_text(
                    source_ref.get("text"),
                    MAX_CONTEXT_TEXT_CHARS,
                ),
                "related_entities": related,
                "reason": _retrieval_reason(relation_types),
                "retrieval_method": "rule_graph",
            }
        )
    vector_context_blocks = vector_context_blocks or []
    context_blocks = _merge_context_blocks(rule_context_blocks, vector_context_blocks)
    return {
        "schema_version": GRAPH_SCHEMA_VERSION,
        "query": "抽取交易类事件",
        "matched_entities": matched_entities,
        "rule_context_blocks": rule_context_blocks,
        "vector_context_blocks": vector_context_blocks,
        "context_blocks": context_blocks,
        "record_candidates": record_candidates or [],
    }


def _build_embedding_retrieval(
    chunks: list[dict],
    nodes_by_id: dict[str, dict],
    graph_dir: Path,
    embedding_client: Any | None = None,
) -> dict:
    if not GRAPH_RAG_EMBEDDING_ENABLED:
        return {
            "embedding_status": "disabled",
            "embedding_model": None,
            "embedding_error": None,
            "vector_context_blocks": [],
        }
    if not chunks:
        return {
            "embedding_status": "skipped_empty_chunks",
            "embedding_model": GRAPH_RAG_EMBEDDING_MODEL,
            "embedding_error": None,
            "vector_context_blocks": [],
        }

    client = embedding_client or EmbeddingClient()
    model_name = str(getattr(client, "model_name", GRAPH_RAG_EMBEDDING_MODEL))
    try:
        chunk_texts = [str(chunk.get("text") or "") for chunk in chunks]
        chunk_embeddings = _normalize_vectors(client.encode(chunk_texts))
        query_embeddings = _normalize_vectors(client.encode(VECTOR_QUERIES))
        _save_npy_float32(graph_dir / "embeddings.npy", chunk_embeddings)
        vector_context_blocks = _vector_context_blocks(
            chunks,
            chunk_embeddings,
            query_embeddings,
            nodes_by_id,
        )
        return {
            "embedding_status": "success",
            "embedding_model": model_name,
            "embedding_error": None,
            "vector_context_blocks": vector_context_blocks,
        }
    except Exception as exc:
        return {
            "embedding_status": "failed",
            "embedding_model": model_name,
            "embedding_error": str(exc),
            "vector_context_blocks": [],
        }


def _vector_context_blocks(
    chunks: list[dict],
    chunk_embeddings: list[list[float]],
    query_embeddings: list[list[float]],
    nodes_by_id: dict[str, dict],
) -> list[dict]:
    blocks_by_key: dict[str, dict] = {}
    for query, query_embedding in zip(VECTOR_QUERIES, query_embeddings):
        scored = []
        for index, chunk_embedding in enumerate(chunk_embeddings):
            score = _dot(query_embedding, chunk_embedding)
            scored.append((score, index))
        scored.sort(key=lambda item: item[0], reverse=True)
        for score, index in scored[: max(1, GRAPH_RAG_VECTOR_TOP_K)]:
            if score <= 0:
                continue
            chunk = chunks[index]
            chunk_id = str(chunk.get("chunk_id") or "")
            block_key = f"{query}|{chunk_id}"
            blocks_by_key[block_key] = {
                "query": query,
                "page_no": chunk.get("page_no"),
                "row_no": chunk.get("row_no"),
                "chunk_id": chunk_id,
                "source_text": _compact_text(chunk.get("text"), MAX_CONTEXT_TEXT_CHARS),
                "related_entities": _entities_for_chunk(chunk_id, nodes_by_id),
                "reason": "vector top-k + graph expansion",
                "retrieval_method": "vector",
                "score": round(float(score), 6),
            }
    return list(blocks_by_key.values())[:MAX_CONTEXT_BLOCKS]


def _entities_for_chunk(chunk_id: str, nodes_by_id: dict[str, dict]) -> list[str]:
    labels = []
    for node in nodes_by_id.values():
        if node.get("type") not in {"Account", "Security", "Holder"}:
            continue
        for source_ref in _as_list(node.get("source_refs")):
            if not isinstance(source_ref, dict) or source_ref.get("chunk_id") != chunk_id:
                continue
            for alias in _as_list(node.get("aliases")):
                if alias and alias not in labels:
                    labels.append(str(alias))
    return labels[:12]


def _merge_context_blocks(
    rule_context_blocks: list[dict],
    vector_context_blocks: list[dict],
) -> list[dict]:
    merged = []
    seen = set()
    rule_quota = 12 if vector_context_blocks else MAX_CONTEXT_BLOCKS
    ordered_blocks = [
        *rule_context_blocks[:rule_quota],
        *vector_context_blocks,
        *rule_context_blocks[rule_quota:],
    ]
    for block in ordered_blocks:
        signature = (
            str(block.get("chunk_id") or ""),
            str(block.get("source_text") or ""),
            str(block.get("retrieval_method") or ""),
        )
        if signature in seen:
            continue
        seen.add(signature)
        merged.append(block)
        if len(merged) >= MAX_CONTEXT_BLOCKS:
            break
    return merged


def _normalize_vectors(vectors: Any) -> list[list[float]]:
    normalized = []
    for vector in _as_list(vectors):
        values = [float(value) for value in vector]
        norm = sum(value * value for value in values) ** 0.5
        if norm > 0:
            values = [value / norm for value in values]
        normalized.append(values)
    return normalized


def _dot(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def _save_npy_float32(path: Path, vectors: list[list[float]]) -> None:
    row_count = len(vectors)
    col_count = len(vectors[0]) if vectors else 0
    header = (
        "{'descr': '<f4', 'fortran_order': False, "
        f"'shape': ({row_count}, {col_count}), }}"
    )
    header_bytes = header.encode("latin1")
    padding = 16 - ((10 + len(header_bytes) + 1) % 16)
    header_bytes = header_bytes + b" " * padding + b"\n"
    payload = bytearray()
    for vector in vectors:
        for value in vector:
            payload.extend(struct.pack("<f", float(value)))
    path.write_bytes(
        b"\x93NUMPY"
        + bytes([1, 0])
        + struct.pack("<H", len(header_bytes))
        + header_bytes
        + bytes(payload)
    )


def _related_entity_labels(
    node_id: str,
    nodes_by_id: dict[str, dict],
    relationships_by_key: dict[tuple, dict],
) -> list[str]:
    labels = []
    for edge in relationships_by_key.values():
        if edge.get("source") != node_id:
            continue
        if edge.get("type") not in {"BELONGS_TO_ACCOUNT", "AFFECTS_SECURITY", "RELATED_TO"}:
            continue
        target = nodes_by_id.get(edge.get("target")) or {}
        for alias in _as_list(target.get("aliases")):
            if alias and alias not in labels:
                labels.append(str(alias))
    return labels[:12]


def _related_relation_types(
    node_id: str,
    relationships_by_key: dict[tuple, dict],
) -> set[str]:
    return {
        str(edge.get("type"))
        for edge in relationships_by_key.values()
        if edge.get("source") == node_id
        and edge.get("type") in {"BELONGS_TO_ACCOUNT", "AFFECTS_SECURITY", "RELATED_TO"}
    }


def _retrieval_reason(relation_types: set[str]) -> str:
    has_account = "BELONGS_TO_ACCOUNT" in relation_types
    has_security = "AFFECTS_SECURITY" in relation_types
    if has_account and has_security:
        return "same account and same security"
    if has_security:
        return "same security"
    if has_account:
        return "same account"
    return "source row event candidate"


def _node(
    node_id: str,
    node_type: str,
    name: str,
    *,
    aliases: list[str] | None = None,
    source_refs: list[dict] | None = None,
    properties: dict | None = None,
) -> dict:
    return {
        "id": node_id,
        "type": node_type,
        "name": str(name or ""),
        "aliases": _dedupe([str(item) for item in aliases or [] if item]),
        "source_refs": source_refs or [],
        "properties": properties or {},
    }


def _merge_node(nodes_by_id: dict[str, dict], node: dict) -> None:
    existing = nodes_by_id.get(node["id"])
    if existing is None:
        nodes_by_id[node["id"]] = node
        return
    existing["aliases"] = _dedupe([*existing.get("aliases", []), *node.get("aliases", [])])
    existing["source_refs"] = _dedupe_source_refs(
        [*existing.get("source_refs", []), *node.get("source_refs", [])]
    )
    if not existing.get("name") and node.get("name"):
        existing["name"] = node["name"]


def _add_relationship(
    relationships_by_key: dict[tuple, dict],
    source: str,
    target: str,
    relationship_type: str,
    confidence: float,
) -> None:
    key = (source, target, relationship_type)
    relationships_by_key[key] = {
        "source": source,
        "target": target,
        "type": relationship_type,
        "confidence": confidence,
    }


def _source_ref(row: dict, file_record: dict) -> dict:
    return {
        "file_id": file_record.get("file_id", ""),
        "chunk_id": row.get("chunk_id", ""),
        "page_no": row.get("page_no"),
        "row_no": row.get("row_no"),
        "row_id": row.get("row_id", ""),
        "text": _compact_text(row.get("text"), MAX_CONTEXT_TEXT_CHARS),
    }


def _header_values(row: dict):
    headers = _as_list(row.get("headers"))
    cells = _as_list(row.get("cells"))
    for index, cell in enumerate(cells):
        header = str(headers[index] if index < len(headers) else "")
        yield header, str(cell or "")


def _looks_like_header(cells: list[str]) -> bool:
    text = " ".join(cells)
    return any(keyword in text for keyword in ("证券代码", "证券名称", "业务日期", "成交数量", "证券账号"))


def _is_noise_row(row: dict) -> bool:
    text = str(row.get("text") or "")
    if not text:
        return True
    has_business_anchor = bool(
        DATE_RE.search(text)
        or SECURITY_CODE_RE.search(text)
        or any(header for header, _value in _header_values(row) if header)
    )
    if has_business_anchor:
        return False
    return sum(1 for keyword in NOISE_ROW_KEYWORDS if keyword in text) >= 2


def _looks_like_account_header(header: str) -> bool:
    return any(keyword in header for keyword in ("证券账号", "证券账户", "股东卡号", "资金账号", "资金账户"))


def _looks_like_non_security_code_header(header: str) -> bool:
    return any(
        keyword in header
        for keyword in ("流水", "委托", "时间", "日期", "资金账号", "资金账户", "客户号")
    )


def _text_near_non_security_label(text: str, code: str) -> bool:
    position = text.find(code)
    if position < 0:
        return False
    window = text[max(0, position - 8): position + len(code) + 8]
    return any(keyword in window for keyword in ("流水", "委托", "时间", "日期", "资金账号"))


def _first_account_number(text: str) -> str:
    match = ACCOUNT_RE.search(str(text or ""))
    return match.group(1) if match else ""


def _first_security_code(text: str) -> str:
    match = SECURITY_CODE_RE.search(str(text or ""))
    return match.group(1) if match else ""


def _security_name_near_code(text: str, code: str) -> str:
    if not code:
        return ""
    match = re.search(rf"{re.escape(code)}\s+([\u4e00-\u9fffA-Za-z]{{2,16}})", text)
    if not match:
        return ""
    return match.group(1)


def _event_type(text: str) -> str:
    for keyword in [*EVENT_KEYWORDS, *CASH_EVENT_KEYWORDS]:
        if keyword in text:
            return keyword
    return ""


def _date_from_text(text: str) -> str:
    match = DATE_RE.search(text)
    if not match:
        return ""
    year, month, day = match.groups()
    return f"{year}-{int(month):02d}-{int(day):02d}"


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _row_no(cells: list[str], fallback: Any) -> str:
    for cell in cells:
        if DATE_RE.search(cell):
            return cell
    return str(fallback or "")


def _unique_nodes(nodes: list[dict]) -> list[dict]:
    unique = {}
    for node in nodes:
        _merge_node(unique, node)
    return list(unique.values())


def _dedupe(values: list[str]) -> list[str]:
    result = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _dedupe_source_refs(values: list[dict]) -> list[dict]:
    result = []
    seen = set()
    for value in values:
        signature = tuple(sorted((str(key), str(val)) for key, val in value.items()))
        if signature in seen:
            continue
        seen.add(signature)
        result.append(value)
    return result


def _compact_text(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _relative(path: str | Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(local_store.PROJECT_ROOT.resolve()))
    except ValueError:
        return str(path)
