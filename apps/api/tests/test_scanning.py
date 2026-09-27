"""ClamAV client against a fake clamd speaking the INSTREAM protocol. No database."""

import socket
import struct
import threading

import pytest

from app.scanning import ClamAVScanner, NoOpScanner, ScannerUnavailable, ScanResult


def fake_clamd(reply: bytes) -> tuple[int, list[bytes]]:
    """One-shot clamd: reads the INSTREAM command and chunks, answers `reply`."""
    server = socket.create_server(("127.0.0.1", 0))
    received: list[bytes] = []

    def serve() -> None:
        conn, _ = server.accept()
        with conn, server:
            data = b""
            while chunk := conn.recv(65536):
                data += chunk
                rest, body = data[len(b"zINSTREAM\0") :], b""
                while len(rest) >= 4:
                    (size,) = struct.unpack("!I", rest[:4])
                    if size == 0:
                        received.append(body)
                        conn.sendall(reply)
                        return
                    if len(rest) < 4 + size:
                        break
                    body, rest = body + rest[4 : 4 + size], rest[4 + size :]

    threading.Thread(target=serve, daemon=True).start()
    return server.getsockname()[1], received


@pytest.fixture
def pdf(tmp_path):
    path = tmp_path / "d.pdf"
    path.write_bytes(b"%PDF-1.4 " + b"x" * 100_000)  # more than one chunk
    return path


def test_clean_file(pdf):
    port, received = fake_clamd(b"stream: OK\0")
    assert ClamAVScanner("127.0.0.1", port, 5).scan(pdf) == ScanResult("clean")
    assert received == [pdf.read_bytes()]  # the whole file was streamed


def test_infected_file(pdf):
    port, _ = fake_clamd(b"stream: Eicar-Test-Signature FOUND\0")
    assert ClamAVScanner("127.0.0.1", port, 5).scan(pdf) == ScanResult(
        "infected", "Eicar-Test-Signature"
    )


@pytest.mark.parametrize("reply", [b"INSTREAM size limit exceeded. ERROR\0", b"", b"garbage\0"])
def test_no_verdict_is_never_clean(pdf, reply):
    port, _ = fake_clamd(reply)
    with pytest.raises(ScannerUnavailable):
        ClamAVScanner("127.0.0.1", port, 5).scan(pdf)


def test_unreachable_scanner_fails_closed(pdf):
    with socket.create_server(("127.0.0.1", 0)) as s:
        port = s.getsockname()[1]  # closed once this block ends: nothing listens
    with pytest.raises(ScannerUnavailable):
        ClamAVScanner("127.0.0.1", port, 2).scan(pdf)


def test_noop_scanner_never_claims_a_scan(pdf):
    assert NoOpScanner().scan(pdf).verdict == "not_scanned"
