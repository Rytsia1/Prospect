"""Parser, sectioning, and chunking on a synthetic annual report. Pure: no DB, no network."""

import pymupdf
import pytest
from sample_pdf import build_sample_report

from app.processing import (
    CHUNK_MAX_CHARS,
    ProcessingError,
    chunk_pages,
    detect_sections,
    is_heading,
    parse_pdf,
    split_sentences,
)


@pytest.fixture(scope="module")
def pages(tmp_path_factory):
    return parse_pdf(build_sample_report(tmp_path_factory.mktemp("pdf") / "report.pdf"))


def test_pages_are_numbered_physically_with_printed_labels_kept(pages):
    assert [p.number for p in pages] == [1, 2, 3, 4]
    assert [p.metadata["label"] for p in pages] == ["i", "86", "87", "88"]
    assert pages[0].metadata["width"] == 595.0


def test_text_is_extracted_per_page(pages):
    assert "shareholders of PT Contoh Sejahtera Tbk" in pages[0].text
    assert "Consolidated Statement of Profit or Loss" in pages[1].text
    assert "listed on the stock exchange" in pages[2].text
    assert "stock exchange" not in pages[1].text


def test_table_is_one_structured_block_in_reading_order(pages):
    kinds = [b.kind for b in pages[1].blocks]
    assert kinds == ["text", "table", "text"]
    table = pages[1].blocks[1]
    assert "Revenue | 12,400 | 10,500" in table.text
    assert "Net income | 1,740 | 1,400" in table.text
    x0, y0, x1, y1 = table.bbox
    assert x0 < x1 and y0 < y1


def test_blocks_keep_order_and_bounding_boxes(pages):
    for page in pages:
        assert [b.index for b in page.blocks] == list(range(len(page.blocks)))
        for b in page.blocks:
            assert 0 <= b.bbox[0] < b.bbox[2] <= page.metadata["width"]


def test_image_only_page_is_partial_not_silently_empty(pages):
    assert pages[3].blocks == []
    assert pages[3].extraction_status == "partial"
    assert pages[3].metadata["has_images"] is True


def test_sections_use_verbatim_headings_and_generic_fallback(pages):
    sections, assignment = detect_sections(pages)
    assert [(s.title, s.start_page, s.end_page) for s in sections] == [
        (None, 1, 1),  # text before the first heading: generic, no invented title
        ("Management Discussion and Analysis", 1, 1),
        ("Consolidated Statement of Profit or Loss", 2, 2),
        ("1. General Information", 3, 3),
    ]
    assert len(assignment) == sum(len(p.blocks) for p in pages)


def test_chunks_are_deterministic_and_traceable(pages):
    sections, assignment = detect_sections(pages)
    chunks = chunk_pages(pages, assignment)
    assert chunks == chunk_pages(pages, detect_sections(pages)[1])

    by_page = {p.number: p for p in pages}
    for c in chunks:
        page = by_page[c.page_number]
        blocks = page.blocks[c.block_start : c.block_end + 1]
        # A chunk stays inside one page and one section, and its text comes from its blocks.
        assert {assignment[(c.page_number, b.index)] for b in blocks} == {c.section_ordinal}
        assert all(line in page.text for line in c.content.split("\n\n"))
    order = [(c.page_number, c.chunk_index) for c in chunks]
    assert order == sorted(order)


def test_headings_stay_with_their_text_and_tables_are_never_split(pages):
    chunks = chunk_pages(pages, detect_sections(pages)[1])
    mdna = [c for c in chunks if c.content.startswith("Management Discussion and Analysis")]
    assert mdna and len(mdna[0].content) > len("Management Discussion and Analysis")
    table_text = pages[1].blocks[1].text
    assert sum(table_text in c.content for c in chunks) == 1


def test_long_text_splits_on_sentence_boundaries(pages):
    chunks = chunk_pages(pages, detect_sections(pages)[1])
    long_parts = [c for c in chunks if "segment" in c.content]
    assert len(long_parts) > 1
    assert all(c.content.rstrip().endswith(".") for c in long_parts)


def test_split_sentences():
    assert split_sentences("One. Two. Three.", 9) == ["One. Two.", "Three."]
    parts = split_sentences("word " * 1000, CHUNK_MAX_CHARS)
    assert all(len(p) <= CHUNK_MAX_CHARS for p in parts)


@pytest.mark.parametrize(
    ("text", "larger", "bold", "expected"),
    [
        ("Consolidated Statements of Cash Flows", False, False, True),  # known report heading
        ("Laporan Posisi Keuangan Konsolidasian", False, False, True),
        ("2. Significant Accounting Policies", False, True, True),  # bold + numbered
        ("2. Significant Accounting Policies", False, False, False),  # numbered alone: not enough
        ("Company Overview", True, False, True),  # larger font
        ("Company Overview", False, True, False),  # bold alone: not enough
        ("The company recorded revenue growth in 2025, driven by exports,", True, False, False),
        ("12,400 10,500", True, False, False),  # numbers are not headings
    ],
)
def test_heading_rules_are_conservative(text, larger, bold, expected):
    assert is_heading(text, larger=larger, bold=bold) is expected


def test_unreadable_pdfs_fail_with_safe_reasons(tmp_path):
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.7\nthis is not really a pdf")
    with pytest.raises(ProcessingError, match="could not be read"):
        parse_pdf(broken)

    scanned = tmp_path / "scanned.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_image(
        pymupdf.Rect(0, 0, 100, 100),
        pixmap=pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 4, 4), False),
    )
    doc.save(scanned)
    with pytest.raises(ProcessingError, match="OCR"):
        parse_pdf(scanned)

    locked = tmp_path / "locked.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "secret")
    doc.save(locked, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="pw", owner_pw="pw")
    with pytest.raises(ProcessingError, match="password"):
        parse_pdf(locked)
