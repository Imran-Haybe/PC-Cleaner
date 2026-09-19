"""Small helpers shared by the test modules."""

import contextlib
import ctypes
import os
import random
import time
from pathlib import Path

DAY = 86400


def make_file(path: Path, size: int, *, seed: int | None = None,
              age_days: float | None = None) -> Path:
    """
    Create a file of exactly `size` bytes.

    seed=None  -> zero-filled (cheap, but ALL zero files of one size are identical!)
    seed=<int> -> reproducible pseudo-random content; different seeds differ
    age_days   -> set BOTH mtime and atime this many days into the past
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    data = b"\0" * size if seed is None else random.Random(seed).randbytes(size)
    path.write_bytes(data)
    if age_days is not None:
        set_age(path, age_days)
    return path


def set_age(path: Path, mtime_days: float, atime_days: float | None = None) -> None:
    now = time.time()
    atime_days = mtime_days if atime_days is None else atime_days
    os.utime(path, (now - atime_days * DAY, now - mtime_days * DAY))


@contextlib.contextmanager
def lock_file(path: Path):
    """
    Hold `path` open with NO sharing (Windows), like a running program would.
    While held, other processes cannot open, read or delete it.
    """
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateFileW.restype = ctypes.c_void_p
    kernel32.CreateFileW.argtypes = [
        ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
        ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    GENERIC_READ, OPEN_EXISTING = 0x80000000, 3
    handle = kernel32.CreateFileW(str(path), GENERIC_READ, 0, None, OPEN_EXISTING, 0, None)
    if handle in (None, ctypes.c_void_p(-1).value):
        raise OSError(f"could not lock {path}: error {ctypes.GetLastError()}")
    try:
        yield
    finally:
        kernel32.CloseHandle(handle)
