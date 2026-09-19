"""LRG-xx and OLD-xx. Thresholds are shrunk via the small_mb fixture:
'100 MB' -> 100 KiB, '10 MB' -> 10 KiB, so boundary logic is exact but files are tiny."""

import os
import subprocess
import time

import pytest

import pc_cleaner
from helpers import DAY, lock_file, make_file, set_age
from pc_cleaner import human_age, scan_largest, scan_old

K = 1024
LARGE = 100 * K      # 100 "MB"
OLD_MIN = 10 * K     # 10 "MB"


def names(results):
    return [r["path"].name for r in results]


# ============================== LRG ==========================================
def test_LRG_01_02_03_threshold_boundaries(small_mb, workdir):
    make_file(workdir / "below.bin", LARGE - 1)
    make_file(workdir / "exact.bin", LARGE)
    make_file(workdir / "above.bin", LARGE + 1)
    assert sorted(names(scan_largest(workdir))) == ["above.bin", "exact.bin"]


def test_LRG_04_sorted_largest_first(small_mb, workdir):
    for name, size in [("a", LARGE + 1), ("b", LARGE + 300), ("c", LARGE + 200)]:
        make_file(workdir / name, size)
    assert names(scan_largest(workdir)) == ["b", "c", "a"]


def test_LRG_05_cap_is_25_and_keeps_the_largest(small_mb, workdir):
    for i in range(1, 31):
        make_file(workdir / f"f{i:02}.bin", LARGE + i)
    results = scan_largest(workdir)
    assert len(results) == 25
    assert names(results) == [f"f{i:02}.bin" for i in range(30, 5, -1)]


def test_LRG_06_nested_files_are_found(small_mb, workdir):
    make_file(workdir / "a" / "b" / "c" / "deep.bin", LARGE)
    assert names(scan_largest(workdir)) == ["deep.bin"]


def test_LRG_07_empty_folder(small_mb, workdir):
    assert scan_largest(workdir) == []


@pytest.mark.windows
def test_LRG_09_folder_with_denied_access_is_skipped_not_fatal(small_mb, workdir):
    locked = workdir / "locked"
    make_file(locked / "hidden.bin", LARGE)
    make_file(workdir / "visible.bin", LARGE)
    who = f"{os.environ['USERDOMAIN']}\\{os.environ['USERNAME']}"
    r = subprocess.run(["icacls", str(locked), "/deny", f"{who}:(RX)"], capture_output=True)
    if r.returncode != 0:
        pytest.skip(f"icacls failed: {r.stdout!r}")
    try:
        assert names(scan_largest(workdir)) == ["visible.bin"]
    finally:
        subprocess.run(["icacls", str(locked), "/remove:d", who], capture_output=True)


@pytest.mark.windows
def test_LRG_11_junction_loop_does_not_double_count(small_mb, workdir):
    """A directory junction pointing back up the tree must not be followed."""
    make_file(workdir / "big.bin", LARGE)
    r = subprocess.run(["cmd", "/c", "mklink", "/J", str(workdir / "loop"), str(workdir)],
                       capture_output=True)
    if r.returncode != 0:
        pytest.skip(f"mklink failed: {r.stdout!r}")
    assert names(scan_largest(workdir)) == ["big.bin"]


@pytest.mark.windows
def test_LRG_12_files_reachable_only_through_a_junction_are_not_scanned(small_mb, workdir):
    """Documents the trade-off of skipping junctions (H12 fix, option A): a real
    folder outside the scan root, linked in by a junction, is deliberately ignored."""
    outside = workdir / "outside"
    scan_root = workdir / "root"
    make_file(outside / "hidden.bin", LARGE)
    make_file(scan_root / "visible.bin", LARGE)
    r = subprocess.run(["cmd", "/c", "mklink", "/J", str(scan_root / "link"), str(outside)],
                       capture_output=True)
    if r.returncode != 0:
        pytest.skip(f"mklink failed: {r.stdout!r}")
    assert names(scan_largest(scan_root)) == ["visible.bin"]


@pytest.mark.slow
def test_LRG_real_100MB_boundary(workdir):
    """No monkeypatching: the real 104,857,600-byte threshold."""
    real = 100 * 1024 * 1024
    for name, size in [("below.bin", real - 1), ("exact.bin", real), ("above.bin", real + 1)]:
        with open(workdir / name, "wb") as f:
            f.truncate(size)
    assert sorted(names(scan_largest(workdir))) == ["above.bin", "exact.bin"]


# ============================== OLD ==========================================
def test_OLD_01_old_and_big_is_listed(small_mb, workdir):
    make_file(workdir / "old.bin", OLD_MIN + K, age_days=3 * 365)
    results = scan_old(workdir)
    assert names(results) == ["old.bin"]
    assert "Untouched for 3y" in results[0]["reason"]


def test_OLD_02_03_size_boundaries(small_mb, workdir):
    make_file(workdir / "below.bin", OLD_MIN - 1, age_days=3 * 365)
    make_file(workdir / "exact.bin", OLD_MIN, age_days=3 * 365)
    assert names(scan_old(workdir)) == ["exact.bin"]


def test_OLD_04_05_age_boundaries_around_730_days(small_mb, workdir):
    make_file(workdir / "d729.bin", OLD_MIN, age_days=729)
    make_file(workdir / "d731.bin", OLD_MIN, age_days=731)
    assert names(scan_old(workdir)) == ["d731.bin"]


def test_OLD_06_recent_file_not_listed(small_mb, workdir):
    make_file(workdir / "new.bin", OLD_MIN * 5, age_days=365)
    assert scan_old(workdir) == []


def test_OLD_07_old_mtime_but_recent_atime_is_not_listed(small_mb, workdir):
    p = make_file(workdir / "read_recently.bin", OLD_MIN)
    set_age(p, mtime_days=3 * 365, atime_days=0)
    assert scan_old(workdir) == []


def test_OLD_08_recent_mtime_but_old_atime_is_not_listed(small_mb, workdir):
    p = make_file(workdir / "edited_recently.bin", OLD_MIN)
    set_age(p, mtime_days=0, atime_days=3 * 365)
    assert scan_old(workdir) == []


def test_OLD_10_sorted_by_size_and_capped_at_50(small_mb, workdir):
    for i in range(60):
        make_file(workdir / f"f{i:02}.bin", OLD_MIN + i, age_days=3 * 365)
    results = scan_old(workdir)
    assert len(results) == 50
    assert names(results)[0] == "f59.bin"
    assert [r["size"] for r in results] == sorted((r["size"] for r in results), reverse=True)


def test_OLD_12_age_text():
    assert human_age(time.time() - (3 * 365 + 120) * DAY) == "3y 4m ago"
    assert human_age(time.time() - 45 * DAY) == "1m ago"
    assert human_age(time.time() - 3 * DAY) == "3d ago"
