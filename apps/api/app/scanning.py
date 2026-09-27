"""Threat scanning of uploaded PDFs before they are parsed (docs/SECURITY.md §4).

DOCUMENT_SCANNER=clamav streams the file to a clamd service (INSTREAM protocol, stdlib socket);
=none records the document as "not_scanned" instead of pretending it was scanned. Production must
choose one explicitly (app/config.py). A scanner that cannot give a verdict raises
ScannerUnavailable: the worker retries a few times, then fails the document. It never falls back
to "clean".
"""

import socket
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from app.config import get_settings

CHUNK = 64 * 1024


@dataclass(frozen=True)
class ScanResult:
    verdict: Literal["clean", "infected", "not_scanned"]
    signature: str | None = None  # the scanner's threat name: logged, never shown to users


class ScannerUnavailable(Exception):
    """No verdict (scanner down, timeout, size limit, unexpected reply). Never means clean."""


class DocumentScanner(Protocol):
    def scan(self, path: Path) -> ScanResult: ...


class NoOpScanner:
    def scan(self, path: Path) -> ScanResult:
        return ScanResult("not_scanned")


class ClamAVScanner:
    """clamd over TCP. clamd's StreamMaxLength must be at least MAX_UPLOAD_BYTES, or large
    files come back as an error (and fail closed)."""

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.address, self.timeout = (host, port), timeout

    def scan(self, path: Path) -> ScanResult:
        try:
            with socket.create_connection(self.address, self.timeout) as conn:
                conn.sendall(b"zINSTREAM\0")
                with path.open("rb") as f:
                    for chunk in iter(lambda: f.read(CHUNK), b""):
                        conn.sendall(struct.pack("!I", len(chunk)) + chunk)
                conn.sendall(struct.pack("!I", 0))
                reply = b""
                while not reply.endswith(b"\0") and (data := conn.recv(4096)):
                    reply += data
        except OSError as e:
            raise ScannerUnavailable(f"clamd unreachable: {type(e).__name__}") from None
        text = reply.rstrip(b"\0").decode(errors="replace").strip()
        if text == "stream: OK":
            return ScanResult("clean")
        if text.startswith("stream: ") and text.endswith(" FOUND"):
            return ScanResult("infected", text.removeprefix("stream: ").removesuffix(" FOUND"))
        raise ScannerUnavailable(f"unexpected clamd reply: {text[:120]}")


def get_scanner() -> DocumentScanner:
    s = get_settings()
    if s.document_scanner == "clamav":
        return ClamAVScanner(s.clamav_host, s.clamav_port, s.clamav_timeout_seconds)
    return NoOpScanner()  # "none", or unset in development (production refuses unset)
