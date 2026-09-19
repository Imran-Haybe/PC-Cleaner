"""DUP-xx. small_mb makes the '1 MB' minimum 1 KiB, so files stay tiny."""

import hashlib
import os
import random
from collections import defaultdict
from pathlib import Path

import pytest

import pc_cleaner
from helpers import lock_file, make_file
from pc_cleaner import scan_duplicates

K = 1024
MIN = 1 * K   # "1 MB"


def flagged(results):
    return {r["path"] for r in results}


# ---- basic detection --------------------------------------------------------
def test_DUP_01_07_pair_with_different_names_and_folders(small_mb, workdir):
    a = make_file(workdir / "x" / "a.jpg", 5 * K, seed=1, age_days=10)
    b = make_file(workdir / "y" / "b.txt", 5 * K, seed=1, age_days=5)
    results = scan_duplicates(workdir)
    assert flagged(results) == {b}                      # newer copy flagged
    assert str(a) in results[0]["reason"]               # ...pointing at the original


def test_DUP_02_three_copies_flag_exactly_two_and_never_the_oldest(small_mb, workdir):
    oldest = make_file(workdir / "1.bin", 5 * K, seed=1, age_days=30)
    mid = make_file(workdir / "2.bin", 5 * K, seed=1, age_days=20)
    new = make_file(workdir / "3.bin", 5 * K, seed=1, age_days=10)
    assert flagged(scan_duplicates(workdir)) == {mid, new}
    assert oldest not in flagged(scan_duplicates(workdir))


def test_DUP_03_same_size_different_content_is_not_a_duplicate(small_mb, workdir):
    """The case that proves the hash step is needed: size alone is not enough."""
    data = random.Random(7).randbytes(5 * K)
    (workdir / "a.bin").write_bytes(data)
    (workdir / "b.bin").write_bytes(data[:-1] + bytes([data[-1] ^ 1]))   # last byte differs
    assert scan_duplicates(workdir) == []


def test_DUP_08_one_byte_longer_is_not_a_duplicate(small_mb, workdir):
    make_file(workdir / "a.bin", 5 * K, seed=1)
    make_file(workdir / "b.bin", 5 * K + 1, seed=1)
    assert scan_duplicates(workdir) == []


def test_DUP_09_two_groups_sorted_largest_first(small_mb, workdir):
    make_file(workdir / "s1.bin", 5 * K, seed=1, age_days=2)
    make_file(workdir / "s2.bin", 5 * K, seed=1, age_days=1)
    make_file(workdir / "b1.bin", 8 * K, seed=2, age_days=2)
    make_file(workdir / "b2.bin", 8 * K, seed=2, age_days=1)
    assert [r["path"].name for r in scan_duplicates(workdir)] == ["b2.bin", "s2.bin"]


def test_DUP_10_cap_of_50(small_mb, workdir):
    for i in range(60):
        make_file(workdir / f"a{i}.bin", 2 * K + i, seed=i, age_days=2)
        make_file(workdir / f"b{i}.bin", 2 * K + i, seed=i, age_days=1)
    results = scan_duplicates(workdir)
    assert len(results) == 50
    assert results[0]["size"] == 2 * K + 59


def test_DUP_12_identical_mtimes_still_flag_exactly_n_minus_1(small_mb, workdir):
    for name in "abc":
        make_file(workdir / f"{name}.bin", 5 * K, seed=1, age_days=10)
    assert len(scan_duplicates(workdir)) == 2


# ---- thresholds / exclusions ------------------------------------------------
def test_DUP_05_06_minimum_size_boundary(small_mb, workdir):
    for name in ("a", "b"):
        make_file(workdir / "below" / f"{name}.bin", MIN - 1, seed=1)
        make_file(workdir / "exact" / f"{name}.bin", MIN, seed=2)
    assert {p.parent.name for p in flagged(scan_duplicates(workdir))} == {"exact"}


def test_DUP_11_copy_inside_protected_folder_is_invisible(small_mb, workdir):
    make_file(workdir / "a.bin", 5 * K, seed=1)
    make_file(workdir / "node_modules" / "a.bin", 5 * K, seed=1)
    assert scan_duplicates(workdir) == []


# ---- the size-grouping optimisation (developer angle) ------------------------
def test_DUP_04_unique_sizes_means_nothing_is_ever_hashed(small_mb, workdir, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(pc_cleaner, "file_hash", lambda p, *a, **k: calls.append(p) or "h")
    for i in range(20):
        make_file(workdir / f"f{i}.bin", 2 * K + i, seed=i)
    assert scan_duplicates(workdir) == []
    assert calls == []
    assert "Hashing 0 possible duplicates" in capsys.readouterr().out


def test_DUP_19_only_files_that_share_a_size_are_hashed(small_mb, workdir, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(pc_cleaner, "file_hash", lambda p, *a, **k: calls.append(p) or "h")
    a = make_file(workdir / "a.bin", 5 * K, seed=1)
    b = make_file(workdir / "b.bin", 5 * K, seed=2)
    make_file(workdir / "loner.bin", 9 * K, seed=3)
    scan_duplicates(workdir)
    assert set(calls) == {a, b}
    assert "Hashing 2 possible duplicates" in capsys.readouterr().out


# ---- Windows / error handling ----------------------------------------------
@pytest.mark.windows
def test_DUP_14_exclusively_locked_file_is_skipped_without_crashing(small_mb, workdir):
    a = make_file(workdir / "a.bin", 5 * K, seed=1, age_days=2)
    b = make_file(workdir / "b.bin", 5 * K, seed=1, age_days=1)
    with lock_file(b):
        assert scan_duplicates(workdir) == []       # b unreadable -> pair cannot be confirmed
    assert flagged(scan_duplicates(workdir)) == {b}  # once released, found normally


def test_DUP_15_file_vanishing_mid_scan_does_not_crash(small_mb, workdir, monkeypatch):
    """H6: group.sort() calls .stat() with no error handling."""
    make_file(workdir / "a.bin", 5 * K, seed=1, age_days=2)
    b = make_file(workdir / "b.bin", 5 * K, seed=1, age_days=1)
    real_hash = pc_cleaner.file_hash

    def hash_then_delete(path, *a, **k):
        digest = real_hash(path, *a, **k)
        if path == b:
            path.unlink()
        return digest

    monkeypatch.setattr(pc_cleaner, "file_hash", hash_then_delete)
    scan_duplicates(workdir)        # must not raise


@pytest.mark.windows
def test_DUP_20_junction_makes_a_file_its_own_duplicate(small_mb, workdir):
    """H12 (data loss): a junction lets the walker reach ONE file by two paths.
    Identical bytes -> flagged as 'duplicate of itself'; deleting the flagged
    path deletes the only real copy."""
    import subprocess
    make_file(workdir / "real" / "photo.bin", 5 * K, seed=1)
    r = subprocess.run(["cmd", "/c", "mklink", "/J", str(workdir / "alias"), str(workdir / "real")],
                       capture_output=True)
    if r.returncode != 0:
        pytest.skip(f"mklink failed: {r.stdout!r}")
    assert scan_duplicates(workdir) == []


def test_DUP_13_hard_links_are_not_reported_as_duplicates(small_mb, workdir):
    """H7: hard links are one physical file. Deleting one frees nothing, so the
    file-identity check must keep them out of the results."""
    a = make_file(workdir / "a.bin", 5 * K, seed=1)
    os.link(a, workdir / "b.bin")
    assert scan_duplicates(workdir) == []


def test_DUP_13b_hard_link_plus_a_real_copy_reports_only_the_real_copy(small_mb, workdir):
    a = make_file(workdir / "a.bin", 5 * K, seed=1, age_days=10)
    os.link(a, workdir / "a_link.bin")
    real_copy = make_file(workdir / "copy.bin", 5 * K, seed=1, age_days=1)
    assert flagged(scan_duplicates(workdir)) == {real_copy}


# ---- ORACLE: optimised scanner vs slow brute force ---------------------------
def brute_force_duplicates(root: Path, min_size: int) -> set[Path]:
    """Trusted-by-simplicity reference: hash EVERY file, no size shortcut."""
    groups = defaultdict(list)
    for p in root.rglob("*"):
        if p.is_file() and p.stat().st_size >= min_size:
            groups[hashlib.sha256(p.read_bytes()).hexdigest()].append(p)
    out = set()
    for paths in groups.values():
        paths.sort(key=lambda p: p.stat().st_mtime)
        out.update(paths[1:])
    return out


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_DUP_18_oracle_matches_brute_force(small_mb, workdir, monkeypatch, seed):
    monkeypatch.setattr(pc_cleaner, "MAX_RESULTS_PER_CATEGORY", 10_000)
    rng = random.Random(seed)
    sizes = [2 * K, 3 * K, 3 * K + 1, 5 * K]     # few sizes -> many same-size collisions
    for i in range(150):
        size = rng.choice(sizes)
        content_seed = rng.randrange(25)          # small pool -> planted duplicates
        folder = workdir / f"d{rng.randrange(6)}" / f"e{rng.randrange(3)}"
        # unique mtime per file so "which copy is the original" is deterministic
        make_file(folder / f"f{i}.bin", size, seed=content_seed * 100 + size, age_days=1000 - i)
    expected = brute_force_duplicates(workdir, MIN)
    assert expected, "test data should contain duplicates"
    assert flagged(scan_duplicates(workdir)) == expected
