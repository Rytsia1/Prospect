"""Everything the worker computes from a PDF file, as one pure function run in the sandbox.

Parse → sections → chunks → facts, with every resource limit applied. No database, no network,
so it can run in a killable child process (app/sandbox.py) and its only input is the file.
"""

from dataclasses import dataclass
from pathlib import Path

from app.extraction import Fact, Rejection, extract_facts
from app.processing import (
    Chunk,
    ParsedPage,
    ProcessingLimitError,
    Section,
    chunk_pages,
    detect_sections,
    parse_pdf,
)


@dataclass(frozen=True)
class Limits:
    max_pages: int
    max_text_bytes: int
    max_table_cells: int
    max_facts: int
    max_evidence: int
    max_row_chars: int
    max_objects: int | None = None


@dataclass
class Analysis:
    pages: list[ParsedPage]
    sections: list[Section]
    assignment: dict[tuple[int, int], int]
    chunks: list[Chunk]
    facts: list[Fact]
    rejections: list[Rejection]


def analyze(job: tuple[Path, Limits]) -> Analysis:
    path, limits = job
    pages = parse_pdf(
        path,
        max_pages=limits.max_pages,
        max_text_bytes=limits.max_text_bytes,
        max_table_cells=limits.max_table_cells,
        max_objects=limits.max_objects,
    )
    sections, assignment = detect_sections(pages)
    chunks = chunk_pages(pages, assignment)
    facts, rejections = extract_facts(pages, sections, assignment, chunks, limits.max_row_chars)
    # Fail rather than keep a subset: financial data is never silently truncated.
    if len(facts) > limits.max_facts:
        raise ProcessingLimitError("The document has more financial facts than the limit.")
    if len(facts) > limits.max_evidence:  # one evidence row per fact
        raise ProcessingLimitError("The document has more evidence items than the limit.")
    return Analysis(pages, sections, assignment, chunks, facts, rejections)
