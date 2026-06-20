from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape, quoteattr

from app.pipeline.final_result_builder import (
    SHEET_CHECKLIST,
    SHEET_COMPLETE,
    SHEET_FINAL,
    SHEET_HOLDINGS,
    SHEET_IDENTITY,
    SHEET_PROBLEMS,
)
from app.services import local_store


DEFAULT_SHEET_ORDER = [
    SHEET_FINAL,
    SHEET_COMPLETE,
    SHEET_HOLDINGS,
    SHEET_IDENTITY,
    SHEET_CHECKLIST,
    SHEET_PROBLEMS,
]

REVIEW_SHEET_COLUMNS = {
    SHEET_FINAL: [
        "账户类型",
        "证券账号",
        "证券代码",
        "证券名称",
        "变动类型",
        "日期",
        "成交数量",
        "成交单价",
        "收付金额",
    ],
    SHEET_COMPLETE: [
        "账户类型",
        "证券账号",
        "证券代码",
        "证券名称",
        "变动类型",
        "日期",
        "成交数量",
        "成交单价",
        "收付金额",
    ],
    SHEET_HOLDINGS: [
        "账户类型",
        "证券账号",
        "证券代码",
        "证券名称",
        "持有数量",
        "市值",
        "查询结果所属日期",
        "币种",
    ],
    SHEET_IDENTITY: [
        "姓名",
        "电话",
        "关系类型",
        "身份证姓名",
        "身份证号码",
        "地址",
        "有效期起",
        "有效期止",
    ],
    SHEET_CHECKLIST: [
        "checklist条件",
        "状态",
        "说明",
    ],
    SHEET_PROBLEMS: [
        "问题ID",
        "问题对象类型",
        "问题类型",
        "严重程度",
        "状态",
        "关联文件编号",
        "关联文件名",
        "关联记录ID",
        "缺失字段",
        "冲突字段",
        "问题说明",
        "处理建议",
    ],
}


def export_excel_from_final_result(final_result_path: str | Path, output_path: str | Path) -> Path:
    final_result = local_store.read_json(final_result_path)
    if not isinstance(final_result, dict):
        raise ValueError("final_result.json is missing or invalid")

    return export_excel(final_result, output_path)


def export_excel(final_result: dict, output_path: str | Path) -> Path:
    output = Path(output_path)
    local_store.ensure_dir(output.parent)
    sheets = _build_sheet_payloads(final_result)
    _write_xlsx(output, sheets)
    return output


def _build_sheet_payloads(final_result: dict) -> list[dict]:
    if isinstance(final_result.get("review_data"), dict):
        return _build_review_sheet_payloads(final_result["review_data"])

    result_sheets = final_result.get("sheets") or {}
    sheet_order = final_result.get("sheet_order") or DEFAULT_SHEET_ORDER
    payloads = []

    for sheet_name in sheet_order:
        sheet_data = result_sheets.get(sheet_name) or {}
        columns = [str(column) for column in sheet_data.get("columns", [])]
        rows = sheet_data.get("rows", [])
        matrix = [columns]
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            matrix.append([_cell_value(row.get(column, "")) for column in columns])

        payloads.append(
            {
                "name": _safe_sheet_name(sheet_name),
                "matrix": matrix,
            }
        )

    return payloads


def _build_review_sheet_payloads(review_data: dict) -> list[dict]:
    return [
        _review_rows_payload(SHEET_FINAL, review_data.get(SHEET_FINAL)),
        _review_rows_payload(SHEET_COMPLETE, review_data.get(SHEET_COMPLETE)),
        _review_rows_payload(SHEET_HOLDINGS, review_data.get(SHEET_HOLDINGS)),
        _review_identity_payload(review_data.get(SHEET_IDENTITY)),
        _review_rows_payload(SHEET_CHECKLIST, review_data.get(SHEET_CHECKLIST)),
        _review_rows_payload(SHEET_PROBLEMS, review_data.get(SHEET_PROBLEMS)),
    ]


def _review_rows_payload(sheet_name: str, rows: Any) -> dict:
    source_rows = rows if isinstance(rows, list) else []
    columns = _review_columns(sheet_name, source_rows)
    matrix = [columns]

    for row in source_rows:
        if not isinstance(row, dict):
            continue
        matrix.append([_cell_value(row.get(column, "")) for column in columns])

    return {
        "name": _safe_sheet_name(sheet_name),
        "matrix": matrix,
    }


def _review_identity_payload(identity_info: Any) -> dict:
    identity = identity_info if isinstance(identity_info, dict) else {}
    rows = [identity] if identity else []
    columns = _review_columns(SHEET_IDENTITY, rows)
    matrix = [columns]
    if identity:
        matrix.append([_cell_value(identity.get(column, "")) for column in columns])
    return {
        "name": _safe_sheet_name(SHEET_IDENTITY),
        "matrix": matrix,
    }


def _review_columns(sheet_name: str, rows: list[dict]) -> list[str]:
    columns = list(REVIEW_SHEET_COLUMNS[sheet_name])
    for row in rows:
        if not isinstance(row, dict):
            continue
        for column in row:
            if column.startswith("_") or column in columns:
                continue
            columns.append(column)
    return columns


def _write_xlsx(output_path: Path, sheets: list[dict]) -> None:
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as workbook:
        workbook.writestr("[Content_Types].xml", _content_types_xml(len(sheets)))
        workbook.writestr("_rels/.rels", _root_relationships_xml())
        workbook.writestr("docProps/core.xml", _core_props_xml())
        workbook.writestr("docProps/app.xml", _app_props_xml(sheets))
        workbook.writestr("xl/workbook.xml", _workbook_xml(sheets))
        workbook.writestr("xl/_rels/workbook.xml.rels", _workbook_relationships_xml(len(sheets)))
        workbook.writestr("xl/styles.xml", _styles_xml())

        for index, sheet in enumerate(sheets, start=1):
            workbook.writestr(
                f"xl/worksheets/sheet{index}.xml",
                _worksheet_xml(sheet["matrix"]),
            )


def _worksheet_xml(matrix: list[list[Any]]) -> str:
    max_cols = max((len(row) for row in matrix), default=1)
    max_rows = max(len(matrix), 1)
    dimension = f"A1:{_column_name(max_cols)}{max_rows}"
    row_xml = []

    for row_index, row in enumerate(matrix, start=1):
        cells = []
        for col_index in range(1, max_cols + 1):
            value = row[col_index - 1] if col_index <= len(row) else ""
            cell_ref = f"{_column_name(col_index)}{row_index}"
            cells.append(
                f'<c r="{cell_ref}" t="inlineStr"><is><t xml:space="preserve">'
                f"{escape(str(value))}</t></is></c>"
            )
        row_xml.append(f'<row r="{row_index}">{"".join(cells)}</row>')

    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<dimension ref="{dimension}"/>'
        '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" '
        'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
        f"<sheetData>{''.join(row_xml)}</sheetData>"
        "</worksheet>"
    )


def _workbook_xml(sheets: list[dict]) -> str:
    sheet_nodes = []
    for index, sheet in enumerate(sheets, start=1):
        sheet_nodes.append(
            f"<sheet name={quoteattr(sheet['name'])} sheetId=\"{index}\" r:id=\"rId{index}\"/>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        "<sheets>"
        f"{''.join(sheet_nodes)}"
        "</sheets>"
        "</workbook>"
    )


def _workbook_relationships_xml(sheet_count: int) -> str:
    relationships = []
    for index in range(1, sheet_count + 1):
        relationships.append(
            f'<Relationship Id="rId{index}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            f'Target="worksheets/sheet{index}.xml"/>'
        )
    relationships.append(
        f'<Relationship Id="rId{sheet_count + 1}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/>'
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f"{''.join(relationships)}"
        "</Relationships>"
    )


def _content_types_xml(sheet_count: int) -> str:
    overrides = [
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
        '<Override PartName="/xl/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>',
        '<Override PartName="/docProps/core.xml" '
        'ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>',
        '<Override PartName="/docProps/app.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>',
    ]
    for index in range(1, sheet_count + 1):
        overrides.append(
            f'<Override PartName="/xl/worksheets/sheet{index}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        f"{''.join(overrides)}"
        "</Types>"
    )


def _root_relationships_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        '<Relationship Id="rId2" '
        'Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" '
        'Target="docProps/core.xml"/>'
        '<Relationship Id="rId3" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" '
        'Target="docProps/app.xml"/>'
        "</Relationships>"
    )


def _styles_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="1"><font><sz val="11"/><color theme="1"/><name val="Calibri"/></font></fonts>'
        '<fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        "</styleSheet>"
    )


def _core_props_xml() -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:dcmitype="http://purl.org/dc/dcmitype/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        "<dc:creator>fund-declare-local</dc:creator>"
        "<cp:lastModifiedBy>fund-declare-local</cp:lastModifiedBy>"
        f'<dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created>'
        f'<dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified>'
        "</cp:coreProperties>"
    )


def _app_props_xml(sheets: list[dict]) -> str:
    sheet_names = "".join(f"<vt:lpstr>{escape(sheet['name'])}</vt:lpstr>" for sheet in sheets)
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
        'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
        "<Application>fund-declare-local</Application>"
        "<TitlesOfParts>"
        f'<vt:vector size="{len(sheets)}" baseType="lpstr">{sheet_names}</vt:vector>'
        "</TitlesOfParts>"
        "</Properties>"
    )


def _cell_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return ",".join(str(item) for item in value if item not in (None, ""))
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _column_name(index: int) -> str:
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name or "A"


def _safe_sheet_name(name: str) -> str:
    safe_name = "".join("_" if char in "[]:*?/\\" else char for char in str(name))
    return (safe_name or "Sheet")[:31]
