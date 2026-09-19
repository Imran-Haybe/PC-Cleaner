"""
Fixtures.

SAFETY: every test works inside its own throw-away folder under a dedicated
root (default C:\\PCC_QA\\pytest). Nothing here ever scans or deletes outside it.
The root is deliberately NOT under AppData/Temp: the scanner treats 'AppData'
as protected, so tests living there would be skipped by the code under test.
Override with the PCC_QA_ROOT environment variable.
"""

import os
import re
import shutil
import tempfile
from pathlib import Path

import pytest

import pc_cleaner

DEFAULT_ROOT = r"C:\PCC_QA" if os.name == "nt" else os.path.join(tempfile.gettempdir(), "PCC_QA")
QA_ROOT = Path(os.environ.get("PCC_QA_ROOT", DEFAULT_ROOT)) / "pytest"


def pytest_collection_modifyitems(config, items):
    if os.name != "nt":
        skip = pytest.mark.skip(reason="Windows only")
        for item in items:
            if "windows" in item.keywords:
                item.add_marker(skip)


@pytest.fixture
def workdir(request) -> Path:
    """A fresh empty folder, unique per test, removed afterwards."""
    name = re.sub(r"[^A-Za-z0-9_.-]", "_", request.node.name)[:80]
    path = QA_ROOT / name
    assert QA_ROOT in path.parents          # never rmtree anything outside the QA root
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True)
    yield path
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def small_mb(monkeypatch):
    """
    Shrink the scanner's 'MB' to 1 KiB. Every threshold (100 MB, 10 MB, 1 MB)
    then becomes 100 KiB / 10 KiB / 1 KiB, so boundary logic is tested exactly
    but with tiny, fast files. A few @slow tests use the real sizes.
    """
    monkeypatch.setattr(pc_cleaner, "MB", 1024)
    return 1024


def feed_input(monkeypatch, answers: list[str]):
    """Script the user's typing. Raises if the app asks for MORE input than expected."""
    it = iter(answers)

    def fake_input(prompt=""):
        try:
            return next(it)
        except StopIteration:
            raise AssertionError(f"app asked for unexpected input: {prompt!r}")

    monkeypatch.setattr("builtins.input", fake_input)
    return it
