"""JNK-xx. The junk scanner reads TEMP/LOCALAPPDATA/home from the environment,
so tests point those at a fake profile inside the QA workdir. The REAL temp
folders are never touched."""

import pytest

import pc_cleaner
from pc_cleaner import get_junk_locations, scan_junk


@pytest.fixture
def profile(workdir, monkeypatch):
    """A fake user profile:  <workdir>/home/AppData/Local/{Temp,CrashDumps,...}"""
    home = workdir / "home"
    local = home / "AppData" / "Local"
    temp = local / "Temp"
    temp.mkdir(parents=True)
    for var in ("USERPROFILE", "HOME"):
        monkeypatch.setenv(var, str(home))
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("TEMP", str(temp))
    monkeypatch.setenv("TMP", str(temp))
    return home


@pytest.fixture
def only_fake_locations(monkeypatch, profile):
    """Isolate scan_junk from the real C:\\Windows\\Temp that is hard-coded in the app."""
    local = profile / "AppData" / "Local"
    monkeypatch.setattr(pc_cleaner, "get_junk_locations", lambda: [local / "Temp"])


def names(results):
    return sorted(r["path"].name for r in results)


# ---- get_junk_locations (environment handling) --------------------------------
def test_JNK_04_05_crashdumps_and_inetcache_included_only_when_they_exist(profile):
    local = profile / "AppData" / "Local"
    assert local / "CrashDumps" not in get_junk_locations()          # missing -> silently absent
    (local / "CrashDumps").mkdir()
    (local / "Microsoft" / "Windows" / "INetCache").mkdir(parents=True)
    locs = get_junk_locations()
    assert local / "CrashDumps" in locs
    assert local / "Microsoft" / "Windows" / "INetCache" in locs


def test_JNK_07_temp_and_tmp_pointing_at_same_folder_listed_once(profile):
    temp = profile / "AppData" / "Local" / "Temp"
    assert [str(p).lower() for p in get_junk_locations()].count(str(temp).lower()) == 1


# ---- files in the known junk folders -----------------------------------------
def test_JNK_01_02_03_temp_files_including_nested_and_protected_named_folders(profile, only_fake_locations):
    temp = profile / "AppData" / "Local" / "Temp"
    (temp / "a" / "b" / "c").mkdir(parents=True)
    (temp / "windows").mkdir()
    (temp / "t1.dat").write_bytes(b"x")
    (temp / "a" / "b" / "c" / "deep.dat").write_bytes(b"x")
    (temp / "windows" / "w.dat").write_bytes(b"x")      # protected name, but known-junk folders aren't filtered
    results = scan_junk()
    assert names(results) == ["deep.dat", "t1.dat", "w.dat"]
    assert all("In temp/cache folder (Temp)" in r["reason"] for r in results)


def test_JNK_11_sorted_by_size_and_capped_at_50(profile, only_fake_locations):
    temp = profile / "AppData" / "Local" / "Temp"
    for i in range(60):
        (temp / f"f{i:02}.dat").write_bytes(b"x" * (i + 1))
    results = scan_junk()
    assert len(results) == 50
    assert results[0]["path"].name == "f59.dat"


# ---- junk extensions in the home folder ---------------------------------------
@pytest.fixture
def home_only(monkeypatch, profile):
    monkeypatch.setattr(pc_cleaner, "get_junk_locations", lambda: [])
    return profile


def test_JNK_08_all_eight_junk_extensions_are_found(home_only):
    docs = home_only / "PCC_QA_home"
    docs.mkdir()
    for ext in (".tmp", ".temp", ".log", ".bak", ".old", ".dmp", ".chk", ".cache"):
        (docs / f"file{ext}").write_bytes(b"x")
    results = scan_junk()
    assert len(results) == 8
    assert all(r["reason"].startswith("Junk extension") for r in results)


def test_JNK_09_case_insensitive_and_no_false_positives(home_only):
    docs = home_only / "docs"
    docs.mkdir()
    for name in ("A.TMP", "b.Log", "notes.tmp.txt", ".tmp", "keep.txt", "tmp"):
        (docs / name).write_bytes(b"x")
    assert names(scan_junk()) == ["A.TMP", "b.Log"]


def test_JNK_10_junk_extension_inside_appdata_is_ignored(home_only):
    roaming = home_only / "AppData" / "Roaming"
    roaming.mkdir(parents=True)
    (roaming / "x.tmp").write_bytes(b"x")
    assert scan_junk() == []


def test_JNK_no_duplicates_when_file_matches_both_rules(profile, monkeypatch):
    """A .tmp file inside a known junk folder AND under home is reported once."""
    folder = profile / "tmpdir"
    folder.mkdir()
    (folder / "x.tmp").write_bytes(b"x")
    monkeypatch.setattr(pc_cleaner, "get_junk_locations", lambda: [folder])
    assert len(scan_junk()) == 1
