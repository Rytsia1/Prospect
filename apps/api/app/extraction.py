"""Deterministic financial fact extraction from parsed pages. Pure: no DB, no network, no LLM.

Candidate rows (table rows, or one-line text rows) → metric label match → period from column
headers + the page's "year(s) ended ..." wording → amount parsing (sign, separators, scale,
currency) → validation → facts, each pinned to the exact source row on its page.

Nothing is guessed: a row whose period, number format, or value cannot be read unambiguously is
rejected; a value whose currency or scale is not stated, or that conflicts with another page, is
kept only as needs_review and is never presented as a fact.
"""

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Literal

from app.processing import KNOWN_HEADING, Block, Chunk, ParsedPage, Section

PeriodType = Literal["annual", "quarter", "interim", "instant"]
MetricKind = Literal["flow", "stock"]

# key → (name, category, kind, label patterns). A pattern must match the whole row label, so
# "Total liabilities and equity" never matches equity and "Profit attributable to ..." never
# matches net income. total_debt is taken only when the report states a total; components are
# never summed here.
METRICS: dict[str, tuple[str, str, MetricKind, list[str]]] = {
    "revenue": (
        "Revenue",
        "income_statement",
        "flow",
        [
            r"(?:total |net )?revenues?",
            r"(?:net )?sales",
            r"pendapatan(?: usaha| bersih)?",
            r"penjualan(?: bersih)?",
        ],
    ),
    "gross_profit": (
        "Gross profit",
        "income_statement",
        "flow",
        [r"gross profit", r"laba (?:bruto|kotor)"],
    ),
    "operating_income": (
        "Operating income",
        "income_statement",
        "flow",
        [
            r"operating (?:income|profit)",
            r"(?:income|profit) from operations",
            r"laba (?:usaha|operasi)",
        ],
    ),
    "net_income": (
        "Net income",
        "income_statement",
        "flow",
        [
            r"net (?:income|profit)(?: for the year)?",
            r"profit for the year",
            r"laba (?:bersih )?tahun berjalan",
            r"laba bersih",
        ],
    ),
    "total_assets": (
        "Total assets",
        "balance_sheet",
        "stock",
        [r"total assets", r"(?:jumlah|total) aset"],
    ),
    "total_liabilities": (
        "Total liabilities",
        "balance_sheet",
        "stock",
        [r"total liabilities", r"(?:jumlah|total) liabilitas"],
    ),
    "equity": (
        "Total equity",
        "balance_sheet",
        "stock",
        [r"total (?:equity|ekuitas)", r"jumlah ekuitas"],
    ),
    "cash": (
        "Cash and cash equivalents",
        "balance_sheet",
        "stock",
        [r"cash and cash equivalents", r"kas dan setara kas"],
    ),
    "total_debt": (
        "Total debt",
        "debt",
        "stock",
        [r"total (?:debt|borrowings)", r"(?:jumlah|total) pinjaman"],
    ),
}
# Metrics that cannot be negative in a set of accounts; a negative value needs human review.
NON_NEGATIVE = {"revenue", "total_assets", "total_liabilities", "cash", "total_debt"}
MAX_ABS_VALUE = Decimal("1e18")  # larger than any real reported line item: a parsing error

SCALES = {
    "units": Decimal(1),
    "thousands": Decimal(10) ** 3,
    "millions": Decimal(10) ** 6,
    "billions": Decimal(10) ** 9,
    "trillions": Decimal(10) ** 12,
}
_SCALE_WORDS = {
    "thousands": r"thousands?|ribu(?:an)?",
    "millions": r"millions?|juta(?:an)?|mn",
    "billions": r"billions?|miliar(?:an)?|milyar(?:an)?|bn",
    "trillions": r"trillions?|triliun",
}
_VALUE_SUFFIX = {  # single-letter abbreviations only directly after a number
    "thousands": _SCALE_WORDS["thousands"] + r"|k",
    "millions": _SCALE_WORDS["millions"] + r"|m",
    "billions": _SCALE_WORDS["billions"] + r"|b",
    "trillions": _SCALE_WORDS["trillions"] + r"|tn|t",
}
_CURRENCY_WORDS = {"IDR": r"rupiah|rp\.?|idr", "USD": r"us\s?dollars?|us\$|usd"}

_MONTH_NAMES = [
    ("january", "januari", "jan"),
    ("february", "februari", "feb"),
    ("march", "maret", "mar"),
    ("april", "apr"),
    ("may", "mei"),
    ("june", "juni", "jun"),
    ("july", "juli", "jul"),
    ("august", "agustus", "aug", "agu"),
    ("september", "sept", "sep"),
    ("october", "oktober", "oct", "okt"),
    ("november", "nov"),
    ("december", "desember", "dec", "des"),
]
_MONTHS = {name: i + 1 for i, names in enumerate(_MONTH_NAMES) for name in names}
_MONTH = "|".join(sorted(_MONTHS, key=len, reverse=True))
_YEAR = r"(?:19|20)\d{2}"
_DATE = re.compile(
    rf"(?P<d1>\d{{1,2}})\s+(?P<m1>{_MONTH})\.?\s+(?P<y1>{_YEAR})\b"
    rf"|\b(?P<m2>{_MONTH})\.?\s+(?P<d2>\d{{1,2}}),?\s+(?P<y2>{_YEAR})\b"
    rf"|\b(?P<y3>{_YEAR})-(?P<m3>\d{{2}})-(?P<d3>\d{{2}})\b",
    re.IGNORECASE,
)
_QUARTER = re.compile(rf"\bQ([1-4])\s*(?:FY)?\s*({_YEAR})\b|\b({_YEAR})\s*Q([1-4])\b", re.I)
_FISCAL_YEAR = re.compile(rf"\bFY\s?({_YEAR})\b|\b({_YEAR})\b", re.I)
_ANY_PERIOD = re.compile(
    rf"{_DATE.pattern}|\bQ[1-4]\s*(?:FY)?\s*{_YEAR}\b|\b{_YEAR}\s*Q[1-4]\b|\bFY\s?{_YEAR}\b|\b{_YEAR}\b",
    re.I,
)
# Words that may sit in a header line besides the periods themselves.
_HEADER_FILLER = re.compile(
    r"\b(?:notes?|catatan|restated|disajikan|kembali|audited|unaudited)\b|[()*,/|]", re.I
)
_DURATION = [
    (12, re.compile(r"\byears?\s+ended\b|\btahun\s+yang\s+berakhir\b|\bfinancial\s+year\b", re.I)),
    (3, re.compile(r"\bthree[- ]months?\s+ended\b|\bquarter\s+ended\b|\btiga\s+bulan\b", re.I)),
    (6, re.compile(r"\bsix[- ]months?\s+ended\b|\benam\s+bulan\b", re.I)),
    (9, re.compile(r"\bnine[- ]months?\s+ended\b|\bsembilan\s+bulan\b", re.I)),
]
_PERIOD_END_WORDING = re.compile(
    r"\b(?:ended|as\s+(?:at|of)|berakhir(?:\s+pada)?|per(?:\s+tanggal)?)\s+(?:on\s+)?", re.I
)
_NIL = {"-", "–", "—", "nil", "n/a", ""}
_MINUS = "-−–"


@dataclass(frozen=True)
class Period:
    type: PeriodType
    label: str  # FY2025, Q4 2025, 2025-12-31, 9M ended 2025-09-30
    end: date | None  # None when the document states only the year
    fiscal_year: int | None
    explicit_date: bool  # the end date is printed next to the figures, not inferred


@dataclass(frozen=True)
class Amount:
    value: Decimal  # normalized: full value in currency units, sign preserved
    scale: str  # the presentation scale the value was stated in
    currency: str | None
    original_text: str


@dataclass(frozen=True)
class Candidate:
    metric: str
    amount: Amount
    period: Period
    page_number: int
    block_index: int
    row_index: int  # line within the block
    column_index: int | None  # table column; None for text lines
    source_text: str  # the verbatim row, an exact substring of the page text
    header_text: str  # the period header the value sits under
    unit_text: str | None  # the unit/currency statement the scale came from
    source_kind: Literal["table_row", "text_line"]
    in_statement: bool  # found under a financial-statement heading
    review_reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Fact:
    candidate: Candidate
    section_ordinal: int
    chunk_index: int
    status: Literal["accepted", "needs_review"]
    confidence: Decimal
    review_reasons: list[str]


@dataclass(frozen=True)
class Rejection:
    page_number: int
    source_text: str
    reason: str


# --- Numbers -----------------------------------------------------------------------------

Convention = Literal["comma_thousands", "dot_thousands"] | None


class AmountError(ValueError):
    pass


def detect_convention(texts: list[str]) -> Convention:
    """Which mark groups thousands, judged only from unambiguous numbers."""
    comma = dot = 0
    for text in texts:
        comma += len(re.findall(r"\d{1,3}(?:,\d{3}){2,}(?![\d,])|\d,\d{3}\.\d", text))
        dot += len(re.findall(r"\d{1,3}(?:\.\d{3}){2,}(?![\d.])|\d\.\d{3},\d", text))
    if comma and not dot:
        return "comma_thousands"
    if dot and not comma:
        return "dot_thousands"
    return None


def parse_amount(raw: str, convention: Convention = None) -> Amount | None:
    """Parse one reported amount. None means explicitly nil ("-"): missing, never zero.

    Raises AmountError when the text is not an unambiguous number.
    """
    text = raw.strip()
    if text.lower() in _NIL:
        return None
    body, negative = text, False
    if body.startswith("(") and body.endswith(")"):
        negative, body = True, body[1:-1].strip()
    if body[:1] and body[0] in _MINUS:
        negative, body = True, body[1:].strip()
    currency = None
    for code, words in _CURRENCY_WORDS.items():
        if m := re.match(rf"(?:{words})\s*", body, re.I):
            currency, body = code, body[m.end() :]
            break
    if body[:1] and body[0] in _MINUS and not negative:  # Rp -1,250
        negative, body = True, body[1:].strip()
    scale = "units"
    if m := re.fullmatch(r"([\d.,]+)\s*([a-z]+)\.?", body, re.I):
        body, suffix = m.group(1), m.group(2)
        found = [s for s, words in _VALUE_SUFFIX.items() if re.fullmatch(words, suffix, re.I)]
        if not found:
            raise AmountError(f"unknown unit {suffix!r}")
        scale = found[0]
    if not re.fullmatch(r"\d[\d.,]*", body) or body[-1] in ".,":
        raise AmountError(f"not a number: {raw!r}")
    number = _normalize_digits(body, convention)
    try:
        value = Decimal(number) * SCALES[scale]
    except InvalidOperation:
        raise AmountError(f"not a number: {raw!r}") from None
    if abs(value) >= MAX_ABS_VALUE:
        raise AmountError(f"implausibly large: {raw!r}")
    return Amount(-value if negative else value, scale, currency, text)


def _normalize_digits(body: str, convention: Convention) -> str:
    if "." in body and "," in body:  # both present: the last one is the decimal mark
        decimal_mark = "." if body.rfind(".") > body.rfind(",") else ","
        group_mark = "," if decimal_mark == "." else "."
        _check_groups(body.split(decimal_mark)[0], group_mark, body)
        return body.replace(group_mark, "").replace(decimal_mark, ".")
    for mark in (",", "."):
        if mark not in body:
            continue
        parts = body.split(mark)
        if len(parts) > 2:  # 1.740.000.000 — a repeated mark is always grouping
            _check_groups(body, mark, body)
            return body.replace(mark, "")
        if len(parts[1]) != 3:  # 1.74 / 12,5 → decimal mark
            return body.replace(mark, ".")
        # One mark then exactly three digits (1,250 / 1.250): grouping or decimal?
        grouping = "comma_thousands" if mark == "," else "dot_thousands"
        if convention == grouping or (convention is None and mark == ","):
            return body.replace(mark, "")
        if convention is None:
            raise AmountError(f"ambiguous separator in {body!r}")
        return body.replace(mark, ".")
    return body


def _check_groups(integer_part: str, mark: str, original: str) -> None:
    parts = integer_part.split(mark)
    if not 1 <= len(parts[0]) <= 3 or any(len(p) != 3 for p in parts[1:]):
        raise AmountError(f"malformed digit grouping in {original!r}")


# --- Periods -----------------------------------------------------------------------------


@dataclass(frozen=True)
class Header:
    kind: Literal["date", "year", "quarter"]
    year: int
    end: date | None = None
    quarter: int | None = None
    text: str = ""


def parse_header(text: str) -> Header | None:
    """The first period named in a header, e.g. '2025', 'FY2025', '31 December 2025'."""
    flat = " ".join(text.split())
    if m := _DATE.search(flat):
        y = int(m["y1"] or m["y2"] or m["y3"])
        month = m["m1"] or m["m2"] or m["m3"]
        mo = int(month) if month.isdigit() else _MONTHS[month.lower().rstrip(".")]
        try:
            return Header("date", y, date(y, mo, int(m["d1"] or m["d2"] or m["d3"])), text=flat)
        except ValueError:
            return None  # e.g. 31 February: malformed, not a period
    if m := _QUARTER.search(flat):
        quarter, year = (m[1], m[2]) if m[1] else (m[4], m[3])
        return Header("quarter", int(year), quarter=int(quarter), text=flat)
    if m := _FISCAL_YEAR.search(flat):
        return Header("year", int(m[1] or m[2]), text=flat)
    return None


def header_line(text: str) -> list[Header] | None:
    """All periods in a line that holds nothing but period headers (e.g. '2025   2024')."""
    matches = list(_ANY_PERIOD.finditer(text))
    rest = _HEADER_FILLER.sub(" ", _ANY_PERIOD.sub(" ", text))
    if not matches or re.search(r"[A-Za-z0-9]", rest):
        return None
    headers = [parse_header(m.group(0)) for m in matches]
    return None if any(h is None for h in headers) else headers  # type: ignore[return-value]


def page_duration(page_text: str) -> tuple[int | None, bool]:
    """Months covered by the page's flow figures, and whether the wording is contradictory."""
    found = {months for months, pattern in _DURATION if pattern.search(page_text)}
    if len(found) > 1:
        return None, True
    return (found.pop() if found else None), False


def page_period_end(page_text: str) -> tuple[int, int] | None:
    """(day, month) from wording like 'years ended 31 December 2025' or 'as at 31 Dec 2025'."""
    ends = set()
    for m in _PERIOD_END_WORDING.finditer(page_text):
        if (d := _DATE.match(page_text, m.end())) and (h := parse_header(d.group(0))) and h.end:
            ends.add((h.end.day, h.end.month))
    return ends.pop() if len(ends) == 1 else None  # two different year-ends: don't pick one


def resolve_period(
    header: Header, kind: MetricKind, months: int | None, end_hint: tuple[int, int] | None
) -> Period | None:
    """Combine a column header with page context. None = ambiguous; never guessed."""

    def hinted(year: int) -> date | None:
        try:
            return date(year, end_hint[1], end_hint[0]) if end_hint else None
        except ValueError:
            return None

    if kind == "stock":
        if header.kind == "date" and header.end:
            return Period("instant", header.end.isoformat(), header.end, header.year, True)
        if header.kind == "year":
            return Period("instant", f"FY{header.year}", hinted(header.year), header.year, False)
        return None  # a balance under a quarter label: which date?
    if header.kind == "quarter":
        if months not in (None, 3):
            return None
        return Period("quarter", f"Q{header.quarter} {header.year}", None, header.year, False)
    if header.kind == "year":
        if months not in (None, 12):
            return None  # a bare year on an interim page: which months?
        return Period("annual", f"FY{header.year}", hinted(header.year), header.year, False)
    if header.end is None or months is None:
        return None  # a date alone does not say how long the period is
    if months == 12:
        return Period("annual", f"FY{header.year}", header.end, header.year, True)
    label = f"{months}M ended {header.end.isoformat()}"
    return Period("quarter" if months == 3 else "interim", label, header.end, header.year, True)


# --- Units -------------------------------------------------------------------------------


@dataclass(frozen=True)
class UnitStatement:
    scale: str | None
    currency: str | None
    text: str | None
    conflicting: bool


def unit_statement(text: str) -> UnitStatement:
    """Scale and currency declared on a page, e.g. '(expressed in millions of Rupiah)'."""
    scale_alt = "|".join(_SCALE_WORDS.values())
    currency_alt = "|".join(_CURRENCY_WORDS.values())
    patterns = [
        rf"\b(?:in|dalam)\s+(?P<s>{scale_alt})\s+(?:of\s+)?(?P<c>{currency_alt})(?![a-z])",
        rf"\(\s*(?:expressed\s+|dinyatakan\s+)?(?:in|dalam)\s+(?P<s>{scale_alt})\b[^)]*\)",
        rf"\(\s*(?P<c>{currency_alt})\s*(?P<s>{scale_alt})\s*\)",
    ]
    scales: set[str] = set()
    currencies: set[str] = set()
    snippets: list[str] = []
    for pattern in patterns:
        for m in re.finditer(pattern, text, re.I):
            scales.add(_scale_of(m["s"]))
            if c := m.groupdict().get("c"):
                currencies.add(_currency_of(c))
            snippets.append(m.group(0))
    for m in re.finditer(rf"\b(?:{currency_alt})(?![a-z])", text, re.I):
        currencies.add(_currency_of(m.group(0)))
    return UnitStatement(
        scale=scales.pop() if len(scales) == 1 else None,
        currency=currencies.pop() if len(currencies) == 1 else None,
        text=snippets[0] if snippets else None,
        conflicting=len(scales) > 1 or len(currencies) > 1,
    )


def _scale_of(word: str) -> str:
    return next(s for s, words in _SCALE_WORDS.items() if re.fullmatch(words, word, re.I))


def _currency_of(word: str) -> str:
    return next(c for c, w in _CURRENCY_WORDS.items() if re.fullmatch(w, word.strip(), re.I))


# --- Rows --------------------------------------------------------------------------------


def match_metric(label: str) -> str | None:
    """Metric whose label pattern matches the whole row label (note references ignored)."""
    cleaned = re.sub(r"\((?:note|catatan)[^)]*\)", " ", label, flags=re.I)
    for part in [cleaned, *cleaned.split("/")]:  # bilingual labels: "Pendapatan / Revenue"
        flat = re.sub(r"\b(?:notes?|catatan)\b", " ", re.sub(r"[^a-z ]", " ", part.lower()))
        flat = " ".join(flat.split())
        for key, (_, _, _, patterns) in METRICS.items():
            if any(re.fullmatch(p, flat) for p in patterns):
                return key
    return None


_AMOUNT = (
    r"\(?\s*[-−–]?\s*(?:rp\.?\s?|idr\s?|us\$\s?|usd\s?)?[-−–]?\d[\d.,]*"
    r"(?:\s?(?:trillion|billion|million|thousand|tn|bn|mn|t|b|m|k))?\s*\)?"
)
_AMOUNT_CELL = re.compile(rf"{_AMOUNT}|[-–—]", re.I)
_TRAILING_AMOUNTS = re.compile(rf"(?:\s+(?:{_AMOUNT}|[-–—]))+\s*$", re.I)


def _is_amount_cell(cell: str) -> bool:
    return bool(_AMOUNT_CELL.fullmatch(cell.strip()))


def _rows(block: Block) -> list[tuple[int, list[str]]]:
    """(line index, cells). Table rows are split on '|'; a text line becomes
    [label, amount, amount, ...] when it ends in amounts, else a single cell."""
    rows = []
    for i, line in enumerate(block.text.split("\n")):
        if block.kind == "table":
            rows.append((i, [c.strip() for c in line.split("|")]))
            continue
        m = _TRAILING_AMOUNTS.search(line)
        label = line[: m.start()].strip() if m else ""
        if m and label:
            amounts = re.findall(rf"{_AMOUNT}|(?<!\S)[-–—](?!\S)", m.group(0), re.I)
            rows.append((i, [label, *(a.strip() for a in amounts if a.strip())]))
        else:
            rows.append((i, [line]))
    return rows


def extract_candidates(
    pages: list[ParsedPage], sections: list[Section], assignment: dict[tuple[int, int], int]
) -> tuple[list[Candidate], list[Rejection]]:
    statement_sections = {
        s.ordinal for s in sections if s.title and KNOWN_HEADING.match(" ".join(s.title.split()))
    }
    candidates: list[Candidate] = []
    rejections: list[Rejection] = []
    for page in pages:
        # Per page, never per document: reports mix "12,400" and "12.400.000" styles across
        # sections, and applying one page's convention to another misreads values by 1000x.
        convention = detect_convention([page.text])
        months, contradictory = page_duration(page.text)
        end_hint = page_period_end(page.text)
        units = unit_statement(page.text)
        periods: list[Header] = []  # the latest period header line on the page
        header_text = ""
        for block in page.blocks:
            columns: dict[int, Header] = {}  # table column → header, for this table only
            for row_index, cells in _rows(block):
                source = block.text.split("\n")[row_index]
                metric = match_metric(cells[0]) if cells[0] else None
                if metric is None:
                    if block.kind == "table":
                        found = {i: h for i, c in enumerate(cells) if (h := parse_header(c))}
                        if found and not any(
                            _is_amount_cell(c) and not parse_header(c) for c in cells
                        ):
                            columns, periods, header_text = found, list(found.values()), source
                    elif (line_periods := header_line(source)) is not None:
                        periods, header_text = line_periods, source
                    continue
                values = _values(cells, columns, periods)
                if values is None:
                    reason = (
                        "no period header above row"
                        if not periods
                        else "values do not line up with period columns"
                    )
                    rejections.append(Rejection(page.number, source, reason))
                    continue
                kind = METRICS[metric][2]
                for column, cell, header in values:
                    period = (
                        None if contradictory else resolve_period(header, kind, months, end_hint)
                    )
                    if period is None:
                        rejections.append(
                            Rejection(page.number, source, f"ambiguous period {header.text!r}")
                        )
                        continue
                    try:
                        amount = parse_amount(cell, convention)
                    except AmountError as e:
                        rejections.append(Rejection(page.number, source, str(e)))
                        continue
                    if amount is None:
                        continue  # reported as nil: missing, never zero
                    candidates.append(
                        _candidate(
                            metric,
                            amount,
                            period,
                            page.number,
                            block,
                            row_index,
                            column,
                            source,
                            header_text,
                            units,
                            assignment[(page.number, block.index)] in statement_sections,
                        )
                    )
    return candidates, rejections


def _values(
    cells: list[str], columns: dict[int, Header], periods: list[Header]
) -> list[tuple[int, str, Header]] | None:
    """(column index, cell text, header) for each period the row reports."""
    if columns:  # a header row in the same table: use its column positions
        return [(i, cells[i], h) for i, h in sorted(columns.items()) if i < len(cells)]
    if not periods:
        return None
    # No column positions: amounts are right-aligned under the periods of the header line.
    amount_cells = [i for i, c in enumerate(cells) if i > 0 and _is_amount_cell(c)]
    if len(amount_cells) < len(periods):
        return None
    positions = amount_cells[-len(periods) :]
    return [(i, cells[i], h) for i, h in zip(positions, periods, strict=True)]


def _candidate(
    metric: str,
    amount: Amount,
    period: Period,
    page_number: int,
    block: Block,
    row_index: int,
    column: int,
    source: str,
    header_text: str,
    units: UnitStatement,
    in_statement: bool,
) -> Candidate:
    reasons: list[str] = []
    scale, value = amount.scale, amount.value
    if scale == "units":  # a bare number: the page must say what unit it is in
        if units.conflicting:
            reasons.append("page states more than one unit or currency")
        elif units.scale:
            scale, value = units.scale, value * SCALES[units.scale]
        else:
            reasons.append("unit scale not stated")
    currency = amount.currency or units.currency
    if amount.currency and units.currency and amount.currency != units.currency:
        reasons.append("currency conflicts with the page's unit statement")
    if currency is None:
        reasons.append("currency not stated")
    if metric in NON_NEGATIVE and value < 0:
        reasons.append(f"negative {METRICS[metric][0].lower()}")
    return Candidate(
        metric=metric,
        amount=Amount(value, scale, currency, amount.original_text),
        period=period,
        page_number=page_number,
        block_index=block.index,
        row_index=row_index,
        column_index=column if block.kind == "table" else None,
        source_text=source,
        header_text=header_text,
        unit_text=units.text,
        source_kind="table_row" if block.kind == "table" else "text_line",
        in_statement=in_statement,
        review_reasons=reasons,
    )


# --- Validation, de-duplication, evidence --------------------------------------------------


def confidence(c: Candidate) -> Decimal:
    """Deterministic score from how the value was found; not a probability."""
    score = Decimal("0.95") if c.source_kind == "table_row" else Decimal("0.85")
    if not c.in_statement:
        score -= Decimal("0.10")  # highlights or narrative pages
    if not c.period.explicit_date:
        score -= Decimal("0.05")
    if c.review_reasons:
        score -= Decimal("0.30")
    return max(Decimal(0), min(Decimal(1), score)).quantize(Decimal("0.0001"))


def build_facts(
    candidates: list[Candidate],
    pages: list[ParsedPage],
    chunks: list[Chunk],
    assignment: dict[tuple[int, int], int],
) -> tuple[list[Fact], list[Rejection]]:
    """Check evidence, resolve duplicates and conflicts, and pin each fact to its chunk."""
    page_text = {p.number: p.text for p in pages}
    rejections: list[Rejection] = []
    groups: dict[tuple[str, str, str], list[Candidate]] = {}
    for c in candidates:
        if c.source_text not in page_text.get(c.page_number, ""):  # evidence must exist verbatim
            rejections.append(Rejection(c.page_number, c.source_text, "evidence text not on page"))
            continue
        groups.setdefault((c.metric, c.period.type, c.period.label), []).append(c)

    facts: list[Fact] = []
    for group in groups.values():
        ranked = sorted(group, key=confidence, reverse=True)
        clean = [c for c in ranked if not c.review_reasons]
        chosen: list[tuple[Candidate, Literal["accepted", "needs_review"], list[str], Decimal]]
        if len({c.amount.value for c in clean}) > 1:
            pages_seen = ", ".join(str(p) for p in sorted({c.page_number for c in clean}))
            reason = f"different values reported on pages {pages_seen}"
            chosen = [(c, "needs_review", [reason], confidence(c)) for c in clean]
        elif clean:  # one value, possibly repeated on several pages: keep the best source
            bonus = Decimal("0.03") if len(clean) > 1 else Decimal(0)
            chosen = [(clean[0], "accepted", [], min(Decimal(1), confidence(clean[0]) + bonus))]
        else:
            chosen = [(ranked[0], "needs_review", ranked[0].review_reasons, confidence(ranked[0]))]
        for c, status, reasons, score in chosen:
            chunk = _chunk_for(c, chunks)
            if chunk is None:
                rejections.append(
                    Rejection(c.page_number, c.source_text, "no chunk contains the row")
                )
                continue
            facts.append(
                Fact(
                    candidate=c,
                    section_ordinal=assignment[(c.page_number, c.block_index)],
                    chunk_index=chunk.chunk_index,
                    status=status,
                    confidence=score,
                    review_reasons=reasons,
                )
            )
    return facts, rejections


def _chunk_for(c: Candidate, chunks: list[Chunk]) -> Chunk | None:
    return next(
        (
            k
            for k in chunks
            if k.page_number == c.page_number
            and k.block_start <= c.block_index <= k.block_end
            and c.source_text in k.content
        ),
        None,
    )


def extract_facts(
    pages: list[ParsedPage],
    sections: list[Section],
    assignment: dict[tuple[int, int], int],
    chunks: list[Chunk],
) -> tuple[list[Fact], list[Rejection]]:
    candidates, rejected = extract_candidates(pages, sections, assignment)
    facts, more = build_facts(candidates, pages, chunks, assignment)
    return facts, rejected + more
