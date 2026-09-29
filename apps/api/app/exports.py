"""CSV / JSON / XLSX export of the workspace payload (app/financials.Financials).

Serializes values; never calculates. Monetary values and ratios leave as exact decimal text (CSV,
JSON strings, XLSX cell text): no float conversion anywhere. XLSX is written with the standard
library (zipfile + SpreadsheetML), so no spreadsheet dependency is needed.
"""

import csv
import io
import json
import re
import uuid
import zipfile
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Literal
from xml.sax.saxutils import escape

if TYPE_CHECKING:
    from app.documents import FactOut
    from app.financials import Financials, ResultOut

Value = str | int | Decimal | date | uuid.UUID | None
Table = tuple[list[str], list[list[Value]]]

FACT_COLUMNS = [
    "metric", "metric_name", "period", "period_as_printed", "period_type", "period_end",
    "value", "currency", "currency_status", "unit", "scale_as_printed", "value_as_printed",
    "fact_status", "timeline", "document", "document_currency", "source_page", "page_label",
    "section", "source_text", "evidence_id", "evidence_link",
]  # fmt: skip
CALCULATION_COLUMNS = [
    "calculation", "name", "formula", "period", "period_type", "status", "value", "unit",
    "reason", "notes", "inputs",
]  # fmt: skip
RECONCILIATION_COLUMNS = [
    "check", "formula", "period", "status", "total_assets", "total_liabilities", "equity",
    "liabilities_plus_equity", "difference", "tolerance", "currency", "problems", "sources",
]  # fmt: skip
EVIDENCE_COLUMNS = [
    "evidence_id", "document", "page", "page_label", "section", "kind", "source_text",
    "column_header", "unit_statement", "evidence_link",
]  # fmt: skip
BALANCE_METRICS = {"total_assets", "total_liabilities", "equity"}


def tables(view: "Financials", periods: set[str], metrics: set[str]) -> dict[str, Table]:
    """Sheets filtered by period and metric (an empty set means all)."""
    facts = {f.id: f for f in view.facts}
    names = {d.id: d.filename for d in view.documents}
    document_currency = {d.id: d.document_currency for d in view.documents}
    timeline: dict[uuid.UUID, str] = {}
    for cell in view.cells:
        for fact_id in cell.fact_ids:
            timeline[fact_id] = {
                "value": "shown" if fact_id == cell.primary_fact_id else "agrees with shown value",
                "conflict": "conflict",
                "needs_review": "needs review",
            }[cell.status]

    def keep(period: str, metric: str) -> bool:
        return (not periods or period in periods) and (not metrics or metric in metrics)

    def link(f: "FactOut") -> str:
        return f"/documents/{f.document_id}/evidence/{f.evidence.id}"

    def ref(fact_id: uuid.UUID) -> str:
        f = facts[fact_id]
        return f"{f.metric} {f.period_label} (page {f.evidence.page_number})"

    fact_rows: list[list[Value]] = []
    evidence_rows: list[list[Value]] = []
    for f in view.facts:
        period = view.fact_periods.get(f.id, f.period_label)
        if not keep(period, f.metric):
            continue
        fact_rows.append([
            f.metric, f.metric_name, period, f.period_label, f.period_type.value, f.period_end,
            f.value, f.currency, f.currency_status, "absolute", f.scale, f.original_text,
            f.status.value, timeline.get(f.id, "not in annual timeline"), names[f.document_id],
            document_currency[f.document_id], f.evidence.page_number, f.evidence.page_label,
            f.evidence.section_title, f.evidence.content, f.evidence.id, link(f),
        ])  # fmt: skip
        evidence_rows.append([
            f.evidence.id, names[f.document_id], f.evidence.page_number, f.evidence.page_label,
            f.evidence.section_title, f.evidence.kind, f.evidence.content, f.evidence.header,
            f.evidence.unit, link(f),
        ])  # fmt: skip

    def calculation_row(key: str, name: str, r: "ResultOut") -> list[Value]:
        return [
            key, name, r.formula, r.period, r.period_type.value, r.status, r.value, r.unit,
            r.reason, "; ".join(r.notes), "; ".join(ref(i) for i in r.input_fact_ids),
        ]  # fmt: skip

    calculation_rows = [
        calculation_row(r.metric, r.name, r) for r in view.calculations if keep(r.period, r.metric)
    ]
    metric_names = {m.key: m.name for m in view.metrics}
    for cell in view.cells:
        if cell.change and keep(cell.period, cell.metric):
            name = f"{metric_names[cell.metric]}, year-over-year change"
            calculation_rows.append(calculation_row(f"yoy_change:{cell.metric}", name, cell.change))

    reconciliation_rows: list[list[Value]] = []
    for rec in view.reconciliations:
        if periods and rec.period not in periods:
            continue
        if metrics and not metrics & (BALANCE_METRICS | {"reconciliation"}):
            continue
        values = {m: facts[i].value for m, i in rec.fact_ids.items()}
        reconciliation_rows.append([
            rec.check, rec.formula, rec.period, rec.status, values.get("total_assets"),
            values.get("total_liabilities"), values.get("equity"), rec.liabilities_plus_equity,
            rec.difference, rec.tolerance, rec.currency, "; ".join(rec.problems),
            "; ".join(ref(i) for i in rec.fact_ids.values()),
        ])  # fmt: skip

    return {
        "Financial Facts": (FACT_COLUMNS, fact_rows),
        "Calculations": (CALCULATION_COLUMNS, calculation_rows),
        "Reconciliation": (RECONCILIATION_COLUMNS, reconciliation_rows),
        "Evidence": (EVIDENCE_COLUMNS, evidence_rows),
    }


def _text(value: Value) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return format(value, "f")  # exact, never scientific notation
    return value.isoformat() if isinstance(value, date) else str(value)


_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _csv(table: Table) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(table[0])
    for row in table[1]:
        # Text from a PDF must never become a spreadsheet formula (CSV injection). Numbers are
        # Decimals, not text, so a negative value is never altered.
        writer.writerow(
            "'" + v if isinstance(v, str) and v.startswith(_FORMULA_START) else _text(v)
            for v in row
        )
    return out.getvalue().encode("utf-8-sig")  # BOM: Excel reads the file as UTF-8


def _json(sheets: dict[str, Table], view: "Financials", exported_at: datetime) -> bytes:
    def records(table: Table) -> list[dict[str, str | int | None]]:
        return [
            {
                k: v if isinstance(v, int) or v is None else _text(v)
                for k, v in zip(table[0], row, strict=True)
            }
            for row in table[1]
        ]

    payload = {
        "exported_at": exported_at.isoformat(),
        "scope": view.scope,
        "company_name": view.company_name,
        "documents": [
            {"id": str(d.id), "name": d.filename, "fiscal_year": d.fiscal_year}
            for d in view.documents
        ],
        "notes": "Monetary values are decimal strings in full currency units. Calculated values "
        "are plain ratios (0.181 = 18.1%). Nothing here was produced by an AI model.",
        "financial_facts": records(sheets["Financial Facts"]),
        "calculations": records(sheets["Calculations"]),
        "reconciliation": records(sheets["Reconciliation"]),
        "evidence": records(sheets["Evidence"]),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


_ILLEGAL_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_XML = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
_OOXML = "application/vnd.openxmlformats-officedocument.spreadsheetml"


def _column(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        letters = chr(65 + rest) + letters
    return letters


def _sheet_xml(table: Table) -> str:
    rows = []
    header: list[Value] = list(table[0])
    for r, row in enumerate([header, *table[1]], start=1):
        cells = []
        for c, value in enumerate(row):
            ref = f"{_column(c)}{r}"
            if isinstance(value, Decimal | int) and not isinstance(value, bool):
                cells.append(f'<c r="{ref}"><v>{_text(value)}</v></c>')  # exact decimal text
            elif value is not None:
                text = escape(_ILLEGAL_XML.sub("", _text(value)))
                style = ' s="1"' if r == 1 else ""
                cells.append(
                    f'<c r="{ref}" t="inlineStr"{style}>'
                    f'<is><t xml:space="preserve">{text}</t></is></c>'
                )
        rows.append(f'<row r="{r}">{"".join(cells)}</row>')
    return (
        f'{_XML}<worksheet xmlns="{_MAIN}">'
        '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" '
        'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
        f"<sheetData>{''.join(rows)}</sheetData></worksheet>"
    )


def _xlsx(sheets: dict[str, Table]) -> bytes:
    names = list(sheets)
    numbered = list(enumerate(names, start=1))
    content_types = (
        f'{_XML}<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        f'<Override PartName="/xl/workbook.xml" ContentType="{_OOXML}.sheet.main+xml"/>'
        f'<Override PartName="/xl/styles.xml" ContentType="{_OOXML}.styles+xml"/>'
        + "".join(
            f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
            f'ContentType="{_OOXML}.worksheet+xml"/>'
            for i, _ in numbered
        )
        + "</Types>"
    )
    workbook = (
        f'{_XML}<workbook xmlns="{_MAIN}" xmlns:r="{_REL}"><sheets>'
        + "".join(f'<sheet name="{escape(n)}" sheetId="{i}" r:id="rId{i}"/>' for i, n in numbered)
        + "</sheets></workbook>"
    )
    workbook_rels = (
        f'{_XML}<Relationships xmlns="{_PKG_REL}">'
        + "".join(
            f'<Relationship Id="rId{i}" Type="{_REL}/worksheet" Target="worksheets/sheet{i}.xml"/>'
            for i, _ in numbered
        )
        + f'<Relationship Id="rId{len(names) + 1}" Type="{_REL}/styles" Target="styles.xml"/>'
        "</Relationships>"
    )
    styles = (  # style 1: bold header row
        f'{_XML}<styleSheet xmlns="{_MAIN}">'
        '<fonts count="2"><font/><font><b/></font></fonts>'
        '<fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
        '<borders count="1"><border/></borders>'
        '<cellStyleXfs count="1"><xf/></cellStyleXfs>'
        '<cellXfs count="2"><xf/><xf fontId="1" applyFont="1"/></cellXfs>'
        "</styleSheet>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr(
            "_rels/.rels",
            f'{_XML}<Relationships xmlns="{_PKG_REL}">'
            f'<Relationship Id="rId1" Type="{_REL}/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>",
        )
        z.writestr("xl/workbook.xml", workbook)
        z.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        z.writestr("xl/styles.xml", styles)
        for i, name in numbered:
            z.writestr(f"xl/worksheets/sheet{i}.xml", _sheet_xml(sheets[name]))
    return buffer.getvalue()


MEDIA_TYPES = {
    "csv": "text/csv; charset=utf-8",
    "json": "application/json",
    "xlsx": f"{_OOXML}.sheet",
}


def serialize(
    sheets: dict[str, Table],
    view: "Financials",
    format: Literal["csv", "json", "xlsx"],
    exported_at: datetime,
) -> tuple[bytes, str]:
    """CSV carries the facts table (with source page and text); JSON and XLSX carry every sheet."""
    if format == "csv":
        body = _csv(sheets["Financial Facts"])
    elif format == "json":
        body = _json(sheets, view, exported_at)
    else:
        body = _xlsx(sheets)
    return body, MEDIA_TYPES[format]
