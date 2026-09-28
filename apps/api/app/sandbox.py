"""Run untrusted-input work (PDF parsing) in a separate, minimally privileged process.

The worker never parses a PDF in its own process. The child is a fresh interpreter started with
subprocess, deliberately not multiprocessing: spawn re-imports the worker module in the child,
and with it every setting and credential. Here the child gets:

- an environment of a few harmless variables only: no DATABASE_URL, storage keys, APP_SECRET or
  any other secret exists in its environment or memory (it never imports app.config);
- no stdout/stderr to anyone (discarded), and its own temporary working directory;
- on Linux: no core dumps, a CPU-time, address-space and file-size limit, and, where the kernel
  allows unprivileged user namespaces, an empty network namespace, i.e. no network at all
  (PROCESSING_NETWORK_ISOLATION=required refuses to parse without it).

The result comes back as a file of bounded size, unpickled with an allowlist of the result types
(never plain pickle.loads on child output), so a compromised child cannot run code in the worker.

This is defense in depth, not a sandbox: the child runs as the worker's OS user, can read what
that user can read, and reaches the network where namespaces are unavailable.
docs/SECURITY_P2_5.md lists what is and is not enforced.
"""

import contextlib
import io
import logging
import os
import pickle
import signal
import socket
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from app.processing import ProcessingError, ProcessingLimitError

log = logging.getLogger("prospect.sandbox")
NetworkIsolation = Literal["required", "best_effort", "off"]
APP_ROOT = str(Path(__file__).resolve().parent.parent)  # the directory holding the app package
# The only variables the child inherits: enough to start Python and nothing else.
ENV_ALLOWLIST = ("PATH", "SYSTEMROOT", "LANG", "LC_ALL", "TZ")
MESSAGE_MAX = 300  # a child's error message is shown to the user; keep it short
TOO_LARGE = "The document's extracted data exceeds the processing limit."
_warned_no_network_isolation = False


class ProcessingTimeout(ProcessingError):
    def __init__(self) -> None:
        super().__init__("Document processing took too long and was stopped.")


class ProcessingCrashed(ProcessingLimitError):
    def __init__(self) -> None:
        super().__init__("Document processing failed.")


# --- Parent side ------------------------------------------------------------------------------

# Everything a parse result may contain. Anything else in the child's output is refused.
_RESULT_GLOBALS = {
    ("app.pipeline", "Analysis"),
    ("app.processing", "ParsedPage"),
    ("app.processing", "Block"),
    ("app.processing", "Section"),
    ("app.processing", "Chunk"),
    ("app.extraction", "Fact"),
    ("app.extraction", "Rejection"),
    ("app.extraction", "Candidate"),
    ("app.extraction", "Amount"),
    ("app.extraction", "Period"),
    ("decimal", "Decimal"),
    ("datetime", "date"),
}


class _ResultUnpickler(pickle.Unpickler):
    def find_class(self, module: str, name: str) -> Any:
        if (module, name) not in _RESULT_GLOBALS:
            raise pickle.UnpicklingError(f"refused global {module}.{name}")
        return super().find_class(module, name)


def load_result(data: bytes) -> Any:
    """Unpickle a child's output, allowing only the result types above."""
    return _ResultUnpickler(io.BytesIO(data)).load()


def run_isolated(
    fn: Callable[[Any], Any],
    arg: Any,
    timeout_seconds: float,
    memory_bytes: int | None = None,
    *,
    max_result_bytes: int = 256 * 1024**2,
    network: NetworkIsolation = "best_effort",
) -> Any:
    """fn(arg) in a fresh, secret-free process; fn and arg must be picklable by reference/value.
    Raises ProcessingTimeout / ProcessingLimitError / ProcessingError / ProcessingCrashed; never
    leaves the child running."""
    global _warned_no_network_isolation
    with tempfile.TemporaryDirectory(prefix="prospect-parse-", ignore_cleanup_errors=True) as tmp:
        result_path = Path(tmp) / "result"
        request = pickle.dumps((fn, arg, memory_bytes, timeout_seconds, max_result_bytes, network))
        env = {k: os.environ[k] for k in ENV_ALLOWLIST if k in os.environ}
        child = subprocess.Popen(  # noqa: S603 (fixed argv, no shell; the job travels on stdin)
            [sys.executable, "-I", "-B", "-c", _CHILD_BOOT, APP_ROOT, str(result_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
            cwd=tmp,
            start_new_session=sys.platform != "win32",
        )
        try:
            child.communicate(request, timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            raise ProcessingTimeout() from None
        finally:
            _kill(child)
        data = _read_result(result_path, max_result_bytes)
        if len(data) > max_result_bytes:
            raise ProcessingLimitError(TOO_LARGE)
        try:
            (kind, payload), network_isolated = load_result(data)
        except Exception:  # malformed or hostile output: the child is not trusted
            log.warning("parser output refused")
            raise ProcessingCrashed() from None
    if network != "off" and not network_isolated and not _warned_no_network_isolation:
        _warned_no_network_isolation = True
        log.warning("parser runs without network isolation (no unprivileged user namespaces)")
    if kind == "ok":
        return payload
    message = str(payload)[:MESSAGE_MAX]
    if kind == "limit":
        raise ProcessingLimitError(message)
    if kind == "rejected":
        raise ProcessingError(message)
    raise ProcessingCrashed()


def _kill(child: subprocess.Popen) -> None:
    """The child and anything it started in its session (a fork left behind after it answered)."""
    if sys.platform != "win32":
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(child.pid, signal.SIGKILL)
    if child.poll() is None:
        child.kill()
    child.wait(timeout=10)


def _read_result(path: Path, max_bytes: int) -> bytes:
    """At most max_bytes + 1 bytes of a regular file. The child controls what is at `path`: a
    symlink to /dev/zero, a FIFO or a huge file must not hang or exhaust the worker."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
    except OSError:  # missing (killed before it answered) or a symlink
        raise ProcessingCrashed() from None
    with os.fdopen(fd, "rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise ProcessingCrashed()
        return f.read(max_bytes + 1)


def can_connect(address: tuple[str, int]) -> bool:
    """Whether this process can open a TCP connection (verifies network isolation)."""
    try:
        with socket.create_connection(address, timeout=2):
            return True
    except OSError:
        return False


# --- Child side -------------------------------------------------------------------------------

_CHILD_BOOT = (
    "import sys; sys.path.insert(0, sys.argv[1]); from app.sandbox import _child; _child()"
)


def _isolate_network() -> bool:
    """Move into new, empty user + network namespaces: afterwards no interface is up."""
    unshare = getattr(os, "unshare", None)
    if sys.platform != "linux" or unshare is None:
        return False
    try:
        unshare(os.CLONE_NEWUSER | os.CLONE_NEWNET)
        return True
    except OSError:  # unprivileged user namespaces disabled (sysctl, AppArmor, seccomp)
        return False


def _limit_resources(memory_bytes: int | None, cpu_seconds: int, file_bytes: int) -> None:
    if sys.platform == "win32":  # development only; the parent's timeout still applies
        return
    import resource

    # No core dumps: a crash must not write the parsed financial document to disk.
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
    # Bounds every file the child writes (only its result file): disk use and result size.
    resource.setrlimit(resource.RLIMIT_FSIZE, (file_bytes, file_bytes))
    if memory_bytes:
        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))


def _child() -> None:
    fn, arg, memory_bytes, timeout, max_result_bytes, network = pickle.loads(  # noqa: S301
        sys.stdin.buffer.read()  # from the parent, which is trusted
    )
    isolated = _isolate_network() if network != "off" else False
    _limit_resources(memory_bytes, int(timeout) + 5, max_result_bytes)
    envelope: tuple[str, Any]
    if network == "required" and not isolated:
        envelope = ("crashed", "network isolation unavailable")
    else:
        try:
            envelope = ("ok", fn(arg))
        except ProcessingLimitError as e:
            envelope = ("limit", str(e))
        except ProcessingError as e:
            envelope = ("rejected", str(e))
        except MemoryError:
            envelope = ("limit", "The document exceeds the processing memory limit.")
        except BaseException as e:  # a parser bug or a crafted file: fail closed, name only
            envelope = ("crashed", type(e).__name__)
    try:
        data = pickle.dumps((envelope, isolated))
    except Exception:  # an unpicklable result is a bug; report it without detail
        data = pickle.dumps((("crashed", "unpicklable result"), isolated))
    if len(data) > max_result_bytes:
        data = pickle.dumps((("limit", TOO_LARGE), isolated))
    Path(sys.argv[2]).write_bytes(data)
