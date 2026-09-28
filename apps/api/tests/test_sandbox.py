"""The isolated parser process: timeouts kill it, crashes and limits fail closed. No database."""

import sys
import time
from pathlib import Path

import pytest

from app.processing import ProcessingError, ProcessingLimitError, parse_pdf
from app.sandbox import ProcessingCrashed, ProcessingTimeout, run_isolated


def test_result_comes_back():
    assert run_isolated(abs, -5, timeout_seconds=60) == 5


def test_runaway_work_is_killed_at_the_timeout():
    started = time.monotonic()
    with pytest.raises(ProcessingTimeout):
        run_isolated(time.sleep, 600, timeout_seconds=1)
    assert time.monotonic() - started < 30  # did not wait for the sleep


def test_document_errors_keep_their_safe_message(tmp_path: Path):
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.7 truncated garbage")
    with pytest.raises(ProcessingError, match="could not be read"):
        run_isolated(parse_pdf, broken, timeout_seconds=60)


def test_unexpected_errors_fail_closed_without_details():
    with pytest.raises(ProcessingCrashed, match="^Document processing failed.$"):
        run_isolated(int, "not a number", timeout_seconds=60)  # ValueError in the child


@pytest.mark.skipif(sys.platform == "win32", reason="RLIMIT_AS is POSIX-only")
def test_memory_is_capped():
    with pytest.raises(ProcessingLimitError):
        run_isolated(bytearray, 2 * 1024**3, timeout_seconds=60, memory_bytes=512 * 1024**2)


@pytest.mark.skipif(sys.platform == "win32", reason="rlimits are POSIX-only")
def test_child_writes_no_core_dumps_and_has_a_cpu_limit():
    import resource

    assert run_isolated(resource.getrlimit, resource.RLIMIT_CORE, timeout_seconds=10) == (0, 0)
    assert run_isolated(resource.getrlimit, resource.RLIMIT_CPU, timeout_seconds=10) == (15, 15)


def test_read_result_regular_and_oversized(tmp_path: Path) -> None:
    from app.sandbox import _read_result

    target = tmp_path / "valid.txt"
    target.write_bytes(b"hello world")
    assert _read_result(target, 20) == b"hello world"

    # Exactly max_bytes + 1 bytes read when file is oversized
    big = tmp_path / "big.bin"
    big.write_bytes(b"x" * 1000)
    assert len(_read_result(big, 50)) == 51


def test_read_result_rejects_non_regular_and_missing_paths(tmp_path: Path) -> None:
    import os

    from app.sandbox import _read_result

    folder = tmp_path / "subfolder"
    folder.mkdir()
    with pytest.raises(ProcessingCrashed):
        _read_result(folder, 100)

    missing = tmp_path / "does_not_exist.bin"
    with pytest.raises(ProcessingCrashed):
        _read_result(missing, 100)

    if sys.platform != "win32":
        symlink = tmp_path / "symlink.bin"
        symlink.symlink_to("/dev/zero")
        with pytest.raises(ProcessingCrashed):
            _read_result(symlink, 100)

        fifo = tmp_path / "test_fifo"
        os.mkfifo(fifo)
        with pytest.raises(ProcessingCrashed):
            _read_result(fifo, 100)
