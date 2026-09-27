"""PDF → pages → blocks → sections → chunks. Pure and deterministic: no database, no network.

Page numbers are 1-based physical page indexes, i.e. the page a PDF viewer shows. The printed
page label (e.g. "iv" or "87"), when the PDF defines one, is kept separately in page metadata.
"""

import logging
import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import pymupdf

log = logging.getLogger("prospect.processing")

CHUNK_TARGET_CHARS = 1200  # flush a chunk once adding the next piece would pass this
CHUNK_MAX_CHARS = 2000  # text blocks longer than this are split at sentence boundaries
HEADING_SIZE_RATIO = 1.2  # heading font must be this much larger than the page's body text
# Text-only extraction flags: skip embedded image bytes to keep memory flat.
TEXT_FLAGS = pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES

KNOWN_HEADING = re.compile(
    r"^(?:consolidated\s+)?(?:"
    r"statements?\s+of\s+(?:financial\s+position|profit\s+or\s+loss|comprehensive\s+income"
    r"|income|changes\s+in\s+equity|cash\s+flows)"
    r"|balance\s+sheets?|income\s+statements?|cash\s+flow\s+statements?"
    r"|notes\s+to\s+the\s+(?:consolidated\s+)?financial\s+statements"
    r"|independent\s+auditor'?s'?\s+report|management'?s?\s+discussion\s+and\s+analysis"
    r"|laporan\s+(?:posisi\s+keuangan|laba\s+rugi|arus\s+kas|perubahan\s+ekuitas|auditor)"
    r"|catatan\s+atas\s+laporan\s+keuangan"
    r")\b",
    re.IGNORECASE,
)
NUMBERED_HEADING = re.compile(r"^(?:\d+(?:\.\d+)*\.?|[IVXLC]+\.|[A-Z]\.)\s+\S")


class ProcessingError(Exception):
    """A permanent problem with the document itself. The message is safe to show users."""


class ProcessingLimitError(ProcessingError):
    """The document exceeds a configured resource limit (pages, text, table cells, facts)."""


@dataclass
class _Budget:
    """What the rest of the document may still consume. None = unlimited."""

    text_bytes: int | None
    table_cells: int | None

    def spend_text(self, size: int) -> None:
        if self.text_bytes is not None:
            self.text_bytes -= size
            if self.text_bytes < 0:
                raise ProcessingLimitError("The document exceeds the extracted-text limit.")

    def spend_cells(self, cells: int) -> None:
        if self.table_cells is not None:
            self.table_cells -= cells
            if self.table_cells < 0:
                raise ProcessingLimitError("The document exceeds the table-size limit.")


@dataclass(frozen=True)
class Block:
    index: int  # reading order within the page
    kind: Literal["text", "table"]
    bbox: tuple[float, float, float, float]  # PDF points, origin top-left of the page
    text: str
    font_size: float  # largest span size; 0 for tables
    bold: bool
    heading: bool

    def to_json(self) -> dict:
        return {
            "index": self.index,
            "kind": self.kind,
            "bbox": list(self.bbox),
            "text": self.text,
            "font_size": self.font_size,
            "bold": self.bold,
            "heading": self.heading,
        }


@dataclass(frozen=True)
class ParsedPage:
    number: int
    blocks: list[Block]
    extraction_status: Literal["success", "partial", "failed"]
    metadata: dict = field(default_factory=dict)

    @property
    def text(self) -> str:
        return "\n\n".join(b.text for b in self.blocks)


@dataclass
class Section:
    ordinal: int
    title: str | None  # verbatim heading text; None = no heading detected (generic section)
    start_page: int
    end_page: int


@dataclass(frozen=True)
class Chunk:
    page_number: int
    chunk_index: int  # order within the page
    section_ordinal: int
    block_start: int
    block_end: int  # inclusive
    content: str


# --- Parsing -----------------------------------------------------------------------------


def parse_pdf(
    path: Path,
    *,
    max_pages: int | None = None,
    max_text_bytes: int | None = None,
    max_table_cells: int | None = None,
) -> list[ParsedPage]:
    """Parse a PDF within limits (None = unlimited). Run untrusted files via app/sandbox.py."""
    try:
        doc = pymupdf.open(path)
    except Exception:
        raise ProcessingError("The PDF could not be read. It may be damaged.") from None
    budget = _Budget(max_text_bytes, max_table_cells)
    with doc:
        if doc.needs_pass:
            raise ProcessingError("The PDF is password-protected.")
        if doc.page_count == 0:
            raise ProcessingError("The PDF has no pages.")
        if max_pages is not None and doc.page_count > max_pages:
            raise ProcessingLimitError(f"The PDF has more than {max_pages} pages.")
        # Pages load one at a time; only extracted text is kept.
        pages = []
        for i in range(doc.page_count):
            page = _parse_page(doc, i, budget)
            budget.spend_text(len(page.text.encode()))
            pages.append(page)
    if not any(p.blocks for p in pages):
        raise ProcessingError(
            "No extractable text was found. Scanned PDFs need OCR, which is not supported yet."
        )
    return pages


def _parse_page(doc: pymupdf.Document, index: int, budget: _Budget) -> ParsedPage:
    number = index + 1
    try:
        page = doc.load_page(index)
        blocks = _extract_blocks(page, budget)
        has_images = bool(page.get_images())
        metadata = {
            "label": page.get_label() or None,
            "width": round(page.rect.width, 2),
            "height": round(page.rect.height, 2),
            "rotation": page.rotation,
            "has_images": has_images,
            "table_count": sum(b.kind == "table" for b in blocks),
        }
    except ProcessingLimitError:
        raise
    except Exception:
        log.exception("page extraction failed", extra={"fields": {"page_number": number}})
        return ParsedPage(number, [], "failed", {})
    # No text but images: probably a scanned page, so the text we have is incomplete.
    status: Literal["success", "partial"] = "partial" if not blocks and has_images else "success"
    return ParsedPage(number, blocks, status, metadata)


def _clean(text: str) -> str:
    return " ".join(text.replace("\x00", "").split())  # Postgres TEXT rejects NUL


def _extract_blocks(page: pymupdf.Page, budget: _Budget) -> list[Block]:
    try:
        tables = page.find_tables().tables
    except Exception:
        tables = []  # table detection is best-effort; text is still extracted
    for table in tables:  # before extracting any cell text
        budget.spend_cells(table.row_count * table.col_count)
    table_rects = [pymupdf.Rect(t.bbox) for t in tables]

    # Stream (authoring) order, not geometric sort: keeps multi-column text in column order.
    raw = [b for b in page.get_text("dict", flags=TEXT_FLAGS)["blocks"] if b.get("type") == 0]
    body_size = _body_font_size(raw)

    items: list[tuple] = []
    emitted_tables: set[int] = set()
    for b in raw:
        rect = pymupdf.Rect(b["bbox"])
        center = (rect.tl + rect.br) / 2
        table_index = next((i for i, r in enumerate(table_rects) if center in r), None)
        if table_index is not None:
            # Replace the table's text blocks with one structured table block, in place.
            if table_index not in emitted_tables:
                emitted_tables.add(table_index)
                items.append(("table", tables[table_index]))
            continue
        items.append(("text", b))
    items += [("table", t) for i, t in enumerate(tables) if i not in emitted_tables]

    blocks: list[Block] = []
    for kind, item in items:
        block = (
            _table_block(len(blocks), item)
            if kind == "table"
            else _text_block(len(blocks), item, body_size)
        )
        if block is not None:
            blocks.append(block)
    return blocks


def _spans(raw_block: dict) -> list[dict]:
    return [s for line in raw_block["lines"] for s in line["spans"] if s["text"].strip()]


def _body_font_size(raw_blocks: list[dict]) -> float:
    sizes = [s["size"] for b in raw_blocks for s in _spans(b) for _ in range(len(s["text"]))]
    return statistics.median(sizes) if sizes else 0.0


def _text_block(index: int, raw: dict, body_size: float) -> Block | None:
    lines = [_clean("".join(s["text"] for s in line["spans"])) for line in raw["lines"]]
    text = "\n".join(line for line in lines if line)
    spans = _spans(raw)
    if not text or not spans:
        return None
    size = round(max(s["size"] for s in spans), 2)
    bold = all(s["flags"] & pymupdf.TEXT_FONT_BOLD or "bold" in s["font"].lower() for s in spans)
    larger = body_size > 0 and size >= body_size * HEADING_SIZE_RATIO
    return Block(
        index=index,
        kind="text",
        bbox=_round_bbox(raw["bbox"]),
        text=text,
        font_size=size,
        bold=bold,
        heading=is_heading(text, larger=larger, bold=bold),
    )


def _table_block(index: int, table) -> Block | None:
    rows = [" | ".join(_clean(cell or "") for cell in row) for row in table.extract()]
    text = "\n".join(row for row in rows if row.strip(" |"))
    if not text:
        return None
    return Block(index, "table", _round_bbox(table.bbox), text, 0.0, False, False)


def _round_bbox(bbox) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = bbox
    return (round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2))


def is_heading(text: str, *, larger: bool, bold: bool) -> bool:
    """Conservative: short, word-like, and backed by typography or a known report heading."""
    flat = " ".join(text.split())
    letters = sum(c.isalpha() for c in flat)
    heading_like = (
        text.count("\n") <= 1
        and len(flat) <= 120
        and len(flat.split()) <= 12
        and letters >= 3
        and letters >= 0.5 * len(flat.replace(" ", ""))
        and not flat.endswith((",", ";"))
    )
    if not heading_like:
        return False
    known = bool(KNOWN_HEADING.match(flat))
    return larger or known or (bold and bool(NUMBERED_HEADING.match(flat)))


# --- Sections ----------------------------------------------------------------------------


def detect_sections(pages: list[ParsedPage]) -> tuple[list[Section], dict[tuple[int, int], int]]:
    """Split the document at detected headings.

    Returns sections and a map (page_number, block_index) → section ordinal. Text before the
    first detected heading goes to a generic section with no title; titles are never invented.
    """
    sections: list[Section] = []
    assignment: dict[tuple[int, int], int] = {}
    for page in pages:
        for block in page.blocks:
            title = " ".join(block.text.split()) if block.heading else None
            current = sections[-1] if sections else None
            same_title = (
                current is not None
                and title is not None
                and current.title is not None
                and title.casefold() == current.title.casefold()
            )
            if current is None or (title is not None and not same_title):
                current = Section(len(sections), title, page.number, page.number)
                sections.append(current)
            current.end_page = page.number
            assignment[(page.number, block.index)] = current.ordinal
    return sections, assignment


# --- Chunking ----------------------------------------------------------------------------


def chunk_pages(pages: list[ParsedPage], assignment: dict[tuple[int, int], int]) -> list[Chunk]:
    """Deterministic chunks that never cross a page or section and never split a table."""
    return [chunk for page in pages for chunk in _chunk_page(page, assignment)]


def _chunk_page(page: ParsedPage, assignment: dict[tuple[int, int], int]) -> list[Chunk]:
    groups: list[list[tuple[Block, str]]] = []
    buffer: list[tuple[Block, str]] = []

    def section_of(block: Block) -> int:
        return assignment[(page.number, block.index)]

    for block in page.blocks:
        if buffer and section_of(block) != section_of(buffer[-1][0]):
            groups.append(buffer)  # new section starts: never mix sections in one chunk
            buffer = []
        pieces = (
            [block.text]
            if block.kind == "table" or len(block.text) <= CHUNK_MAX_CHARS
            else split_sentences(block.text, CHUNK_MAX_CHARS)
        )
        for piece in pieces:
            size = sum(len(t) + 2 for _, t in buffer)
            only_headings = all(b.heading for b, _ in buffer)  # keep headings with their text
            if buffer and size + len(piece) > CHUNK_TARGET_CHARS and not only_headings:
                groups.append(buffer)
                buffer = []
            buffer.append((block, piece))
    if buffer:
        groups.append(buffer)

    return [
        Chunk(
            page_number=page.number,
            chunk_index=i,
            section_ordinal=section_of(group[0][0]),
            block_start=group[0][0].index,
            block_end=group[-1][0].index,
            content="\n\n".join(text for _, text in group),
        )
        for i, group in enumerate(groups)
    ]


def split_sentences(text: str, max_chars: int) -> list[str]:
    """Verbatim slices of `text`, each at most max_chars, cut at sentence ends when possible.

    Slicing (not re-joining) keeps every piece an exact substring of the source, which later
    evidence quotes depend on. Words are cut only when one sentence exceeds max_chars.
    """
    sentence_cuts = [m.end() for m in re.finditer(r"(?<=[.!?])\s+", text)] + [len(text)]
    pieces: list[str] = []
    start = 0
    while start < len(text):
        fits = [c for c in sentence_cuts if c > start and len(text[start:c].rstrip()) <= max_chars]
        if fits:
            end = fits[-1]
        else:  # one very long sentence: cut at the last whitespace that fits
            spaces = [m.start() for m in re.finditer(r"\s", text[start : start + max_chars + 1])]
            end = start + (spaces[-1] if spaces and spaces[-1] > 0 else max_chars)
        piece = text[start:end].strip()
        if piece:
            pieces.append(piece)
        start = end
    return pieces
