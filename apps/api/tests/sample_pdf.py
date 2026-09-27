"""Builds a small, synthetic annual-report PDF (no third-party content) for processing tests."""

from pathlib import Path

import pymupdf

LONG_PARAGRAPH = " ".join(
    f"Revenue in segment {i} grew because of higher volumes and stable pricing." for i in range(40)
)
TABLE = [
    ["(Rp billion)", "2025", "2024"],
    ["Revenue", "12,400", "10,500"],
    ["Gross profit", "4,960", "4,100"],
    ["Operating income", "2,480", "2,050"],
    ["Net income", "1,740", "1,400"],
]
# Balance sheet in Indonesian number format, with a Notes column and dated headers.
BALANCE_SHEET = [
    ["", "Notes", "31 December 2025", "31 December 2024"],
    ["Cash and cash equivalents", "4", "3.120.500", "2.840.250"],
    ["Total assets", "", "45.600.000", "41.200.000"],
    ["Total borrowings", "12", "8.300.000", "9.100.000"],
    ["Total liabilities", "", "20.100.000", "19.300.000"],
    ["Retained earnings (deficit)", "", "(1.250.000)", "(980.000)"],
    ["Total equity", "", "25.500.000", "21.900.000"],
    ["Total liabilities and equity", "", "45.600.000", "41.200.000"],
]


def _text(page: pymupdf.Page, y: float, text: str, size: float = 10, bold: bool = False) -> float:
    font = "hebo" if bold else "helv"
    rect = pymupdf.Rect(72, y, 540, 780)
    page.insert_textbox(rect, text, fontsize=size, fontname=font)
    lines = max(1, int(pymupdf.get_text_length(text, fontname=font, fontsize=size) / 460) + 1)
    return y + lines * size * 1.4 + 12


def _table(page: pymupdf.Page, y: float, rows=TABLE, col_x=(72, 272, 372, 472)) -> float:
    row_h = 20
    for r, row in enumerate(rows):
        top = y + r * row_h
        for c, cell in enumerate(row):
            page.insert_text((col_x[c] + 4, top + 14), cell, fontsize=10, fontname="helv")
    for r in range(len(rows) + 1):  # ruled grid so the table is detectable
        page.draw_line((col_x[0], y + r * row_h), (col_x[-1], y + r * row_h))
    for x in col_x:
        page.draw_line((x, y), (x, y + len(rows) * row_h))
    return y + len(rows) * row_h + 20


def build_sample_report(path: Path) -> Path:
    doc = pymupdf.open()

    p1 = doc.new_page()
    y = _text(p1, 72, "This report is presented to the shareholders of PT Contoh Sejahtera Tbk.")
    y = _text(p1, y, "Management Discussion and Analysis", size=16, bold=True)
    _text(p1, y, LONG_PARAGRAPH)

    p2 = doc.new_page()
    y = _text(p2, 72, "Consolidated Statement of Profit or Loss", size=16, bold=True)
    y = _text(p2, y, "For the years ended 31 December 2025 and 2024")
    y = _table(p2, y)
    _text(p2, y, "The accompanying notes form an integral part of these financial statements.")

    p3 = doc.new_page()
    y = _text(p3, 72, "1. General Information", bold=True)
    _text(p3, y, "The Company was established in Indonesia and is listed on the stock exchange.")

    p4 = doc.new_page()  # image only: stands in for a scanned page
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 8, 8), False)
    pix.clear_with(200)
    p4.insert_image(pymupdf.Rect(72, 72, 300, 300), pixmap=pix)

    p5 = doc.new_page()
    y = _text(p5, 72, "Consolidated Statement of Financial Position", size=16, bold=True)
    y = _text(p5, y, "As at 31 December 2025 and 2024 (expressed in millions of Rupiah)")
    _table(p5, y, BALANCE_SHEET, col_x=(72, 242, 292, 412, 532))

    # Printed labels differ from physical numbers, like a real report (cover "i", then 86…).
    doc.set_page_labels(
        [
            {"startpage": 0, "prefix": "", "style": "r", "firstpagenum": 1},
            {"startpage": 1, "prefix": "", "style": "D", "firstpagenum": 86},
        ]
    )
    doc.save(path)
    return path
