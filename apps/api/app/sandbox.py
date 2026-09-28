"""Run untrusted-input work (PDF parsing) in a child process that can be killed.

The worker never parses a PDF in its own process: a malicious file that loops, recurses or
exhausts memory takes down only the child. The parent waits at most `timeout_seconds`, then
kills the child. On Linux the child also gets an address-space limit (RLIMIT_AS). Results and
errors come back over a pipe; only ProcessingError messages (written to be user-safe) cross it.
"""

import math
import multiprocessing
import sys
from collections.abc import Callable
from multiprocessing.connection import Connection
from typing import Any

from app.processing import ProcessingError, ProcessingLimitError


class ProcessingTimeout(ProcessingError):
    def __init__(self) -> None:
        super().__init__("Document processing took too long and was stopped.")


class ProcessingCrashed(ProcessingLimitError):
    def __init__(self) -> None:
        super().__init__("Document processing failed.")


def _child(
    conn: Connection,
    fn: Callable[[Any], Any],
    arg: Any,
    memory_bytes: int | None,
    cpu_seconds: int,
) -> None:
    # POSIX only; on Windows (development) the parent's timeout still applies, these do not.
    if sys.platform != "win32":
        import resource

        # No core dumps: a crash must not write the parsed financial document to disk.
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        # CPU time, a second bound besides the parent's wall-clock kill.
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
        if memory_bytes:
            resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
    try:
        conn.send(("ok", fn(arg)))
    except ProcessingLimitError as e:
        conn.send(("limit", str(e)))
    except ProcessingError as e:
        conn.send(("rejected", str(e)))
    except MemoryError:
        conn.send(("limit", "The document exceeds the processing memory limit."))
    except BaseException as e:  # a parser bug or a crafted file: fail closed, name only
        conn.send(("crashed", type(e).__name__))
    finally:
        conn.close()


def run_isolated(
    fn: Callable[[Any], Any], arg: Any, timeout_seconds: float, memory_bytes: int | None = None
) -> Any:
    """fn(arg) in a fresh process. Raises ProcessingTimeout / ProcessingLimitError /
    ProcessingError / ProcessingCrashed; never leaves the child running."""
    context = multiprocessing.get_context("spawn")  # no inherited DB connections or locks
    receive, send = context.Pipe(duplex=False)
    cpu_seconds = math.ceil(timeout_seconds) + 5
    child = context.Process(
        target=_child, args=(send, fn, arg, memory_bytes, cpu_seconds), daemon=True
    )
    child.start()
    send.close()  # the parent keeps only the reading end, so a dead child reads as EOF
    try:
        if not receive.poll(timeout_seconds):
            raise ProcessingTimeout()
        try:
            kind, payload = receive.recv()
        except EOFError:  # killed (e.g. by the OS for memory) before it could answer
            raise ProcessingCrashed() from None
    finally:
        receive.close()
        if child.is_alive():
            child.kill()
        child.join(timeout=10)
    if kind == "ok":
        return payload
    if kind == "limit":
        raise ProcessingLimitError(payload)
    if kind == "rejected":
        raise ProcessingError(payload)
    raise ProcessingCrashed()
