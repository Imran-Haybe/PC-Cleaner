"""End-to-end: run the real program as a subprocess and type into it through stdin,
exactly like a user. Slower than unit tests but catches wiring mistakes."""

import subprocess
import sys
from pathlib import Path

from helpers import make_file

APP = Path(__file__).resolve().parent.parent / "pc_cleaner.py"
MB = 1024 * 1024


def run_app(stdin_lines, env_extra=None):
    import os
    env = {**os.environ, **(env_extra or {})}
    return subprocess.run([sys.executable, str(APP)], input="\n".join(stdin_lines) + "\n",
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=120, env=env)


def test_E2E_duplicate_scan_then_skip_deletion_leaves_files_alone(workdir):
    a = make_file(workdir / "a.bin", 2 * MB, seed=1, age_days=2)
    b = make_file(workdir / "b.bin", 2 * MB, seed=1, age_days=1)
    r = run_app([str(workdir), "3", "", "q"])           # root, menu 3, Enter = skip deletion, quit
    assert r.returncode == 0
    assert "Hashing 2 possible duplicates" in r.stdout
    assert f"Duplicate of {a}" in r.stdout
    assert "Bye!" in r.stdout
    assert a.exists() and b.exists()


def test_E2E_full_permanent_delete_through_the_real_prompts(workdir):
    a = make_file(workdir / "a.bin", 2 * MB, seed=1, age_days=2)
    b = make_file(workdir / "b.bin", 2 * MB, seed=1, age_days=1)
    r = run_app([str(workdir), "3", "1", "p", "DELETE", "q"])
    assert r.returncode == 0
    assert a.exists() and not b.exists()
    assert "Done. Freed 2.0 MB." in r.stdout


def test_NAV_16_unicode_filenames_do_not_crash_when_output_is_piped(workdir):
    """H11: with output piped, Python 3.14 on Windows encodes stdout with the
    locale code page (cp1252), which cannot represent Japanese. Real users hit
    this with `python pc_cleaner.py > report.txt` or any wrapper that captures output."""
    make_file(workdir / "日本語 🙂.bin", 2 * MB, seed=1, age_days=2)
    make_file(workdir / "copy 日本語 🙂.bin", 2 * MB, seed=1, age_days=1)
    stdin = ("\n".join([str(workdir), "3", "", "q"]) + "\n").encode("utf-8")
    r = subprocess.run([sys.executable, str(APP)], input=stdin,
                       capture_output=True, timeout=120,
                       env={k: v for k, v in __import__("os").environ.items() if k != "PYTHONIOENCODING"})
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")[-400:]
    assert b"Duplicate of" in r.stdout      # the scan still completed and reported
