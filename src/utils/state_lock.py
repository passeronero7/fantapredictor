"""Exclusive ownership of an auction state file shared by console and web UI."""

from __future__ import annotations

import os
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - non-Unix
    fcntl = None


class StateLock:
    """Advisory process lock on a file next to the auction state.

    The CLI holds it for the whole interactive session (``--command`` calls
    included); the web server holds it from startup to shutdown. A second
    process that tries to acquire it gets a ``RuntimeError`` and never
    touches the state. On Unix this is an ``fcntl.flock``: the lock file
    stays on disk but the lock dies with the process, so a crash cannot
    leave the state permanently locked.

    On platforms without ``fcntl`` there is no reliable lock, so acquiring
    fails with an explicit error instead of allowing two writers on the
    same CSV.
    """

    def __init__(self, state_path: Path):
        self.state_path = Path(state_path)
        self.lock_path = self.state_path.with_name(self.state_path.name + ".lock")
        self._fd: int | None = None

    @property
    def held(self) -> bool:
        return self._fd is not None

    def acquire(self) -> None:
        if fcntl is None:
            raise RuntimeError(
                "Process locking needs fcntl (Unix); on this platform keep "
                "a single console or web server at a time and never run "
                "both on the same state."
            )
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            raise RuntimeError(
                f"Another auction process holds the lock on {self.lock_path}; "
                "close it before starting this one."
            )
        self._fd = fd

    def release(self) -> None:
        if self._fd is None:
            return
        try:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        finally:
            os.close(self._fd)
            self._fd = None

    def __enter__(self) -> "StateLock":
        self.acquire()
        return self

    def __exit__(self, *exc_info) -> None:
        self.release()