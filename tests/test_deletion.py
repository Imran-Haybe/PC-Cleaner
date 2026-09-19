"""DEL-xx. Flow logic runs against a FAKE Recycle Bin (send2trash is replaced),
so nothing is recycled. A couple of @windows tests use the real one."""

import os
import stat
import subprocess

import pytest

import pc_cleaner
from conftest import feed_input
from helpers import lock_file, make_file
from pc_cleaner import delete_files, human_size, offer_deletion, scan_duplicates

K = 1024


def item(path):
    return {"path": path, "size": path.stat().st_size, "reason": "test"}


@pytest.fixture
def files(workdir):
    return [make_file(workdir / f"f{i}.bin", 1000 * i) for i in (1, 2, 3)]


@pytest.fixture
def fake_bin(monkeypatch):
    """Records what would be sent to the Recycle Bin, and removes the file."""
    sent = []

    def fake(path):
        sent.append(path)
        os.remove(path)

    monkeypatch.setattr(pc_cleaner, "send2trash", fake)
    return sent


# ---- prompts that must NOT delete ---------------------------------------------
def test_DEL_01_enter_skips(monkeypatch, files, fake_bin):
    feed_input(monkeypatch, [""])
    offer_deletion([item(p) for p in files])
    assert fake_bin == [] and all(p.exists() for p in files)


def test_DEL_02_invalid_selection_deletes_nothing(monkeypatch, files, fake_bin, capsys):
    feed_input(monkeypatch, ["abc"])
    offer_deletion([item(p) for p in files])
    assert "Invalid selection - nothing deleted." in capsys.readouterr().out
    assert all(p.exists() for p in files)


@pytest.mark.parametrize("mode", ["c", "x", ""])
def test_DEL_03_cancel_or_junk_at_mode_prompt(monkeypatch, files, fake_bin, mode, capsys):
    feed_input(monkeypatch, ["1", mode])
    offer_deletion([item(p) for p in files])
    assert "Cancelled - nothing deleted." in capsys.readouterr().out
    assert all(p.exists() for p in files)


def test_DEL_04_recycle_then_decline(monkeypatch, files, fake_bin):
    feed_input(monkeypatch, ["1", "r", "n"])
    offer_deletion([item(p) for p in files])
    assert fake_bin == [] and all(p.exists() for p in files)


@pytest.mark.parametrize("confirm", ["delete", "yes", "", "Delete", "DELET"])
def test_DEL_06_permanent_needs_exact_DELETE(monkeypatch, files, fake_bin, confirm):
    feed_input(monkeypatch, ["1", "p", confirm])
    offer_deletion([item(p) for p in files])
    assert all(p.exists() for p in files)


# ---- prompts that DO delete ---------------------------------------------------
def test_DEL_05_recycle_confirm_sends_selected_files_and_reports_freed(monkeypatch, files, fake_bin, capsys):
    feed_input(monkeypatch, ["1,3", "r", "y"])
    offer_deletion([item(p) for p in files])
    assert fake_bin == [str(files[0]), str(files[2])]
    assert files[1].exists()                                     # unselected file untouched
    assert f"Freed {human_size(1000 + 3000)}" in capsys.readouterr().out


def test_DEL_07_permanent_with_DELETE(monkeypatch, files):
    feed_input(monkeypatch, ["all", "p", "DELETE"])
    offer_deletion([item(p) for p in files])
    assert not any(p.exists() for p in files)


@pytest.mark.parametrize("mode", ["R", "P"])
def test_DEL_08_mode_is_case_insensitive(monkeypatch, files, fake_bin, mode):
    feed_input(monkeypatch, ["1", mode, "y" if mode == "R" else "DELETE"])
    offer_deletion([item(files[0])])
    assert not files[0].exists()


def test_DEL_15_without_send2trash_falls_back_to_permanent_and_still_confirms(monkeypatch, files, capsys):
    monkeypatch.setattr(pc_cleaner, "send2trash", None)
    feed_input(monkeypatch, ["1", "DELETE"])                     # no R/P/C prompt is shown
    offer_deletion([item(files[0])])
    out = capsys.readouterr().out
    assert "send2trash" in out and not files[0].exists()


def test_DEL_15b_without_send2trash_wrong_confirmation_deletes_nothing(monkeypatch, files):
    monkeypatch.setattr(pc_cleaner, "send2trash", None)
    feed_input(monkeypatch, ["1", "no"])
    offer_deletion([item(files[0])])
    assert files[0].exists()


def test_empty_results_never_prompt(monkeypatch):
    feed_input(monkeypatch, [])                                   # any input() call fails the test
    offer_deletion([])


# ---- failures -----------------------------------------------------------------
def test_DEL_09_file_already_gone_fails_alone_and_is_not_counted_as_freed(files, capsys):
    items = [item(p) for p in files]
    files[1].unlink()
    freed, failures = delete_files(items, permanent=True)
    assert failures == 1
    assert freed == 1000 + 3000
    assert "FAILED:" in capsys.readouterr().out


@pytest.mark.windows
def test_DEL_10_18_locked_file_fails_others_continue_and_summary_reports_it(monkeypatch, files, capsys):
    feed_input(monkeypatch, ["all", "p", "DELETE"])
    with lock_file(files[1]):
        offer_deletion([item(p) for p in files])
    out = capsys.readouterr().out
    assert files[1].exists() and not files[0].exists() and not files[2].exists()
    assert "(1 failed)" in out and "FAILED:" in out


@pytest.mark.windows
def test_DEL_11_read_only_file_permanent_delete_fails_safely(files, capsys):
    """Characterisation: os.remove refuses read-only files on Windows. Safe (nothing
    lost) but the user sees a raw error. Decide: clear the flag first, or explain it?"""
    os.chmod(files[0], stat.S_IREAD)
    try:
        freed, failures = delete_files([item(files[0])], permanent=True)
        assert (freed, failures) == (0, 1)
        assert files[0].exists()
    finally:
        os.chmod(files[0], stat.S_IWRITE)


# ---- special names ------------------------------------------------------------
NASTY = ["with space.bin", "amp & ersand.bin", "100% done.bin", "hash #1.bin",
         "brackets [x] (y).bin", "résumé.bin", "日本語.bin"]


@pytest.mark.parametrize("name", NASTY)
def test_DEL_12_special_names_delete_exactly_the_right_file(monkeypatch, workdir, name):
    target = make_file(workdir / name, 500)
    bystander = make_file(workdir / "bystander.bin", 501)
    feed_input(monkeypatch, ["1", "p", "DELETE"])
    offer_deletion([item(target)])
    assert not target.exists() and bystander.exists()


# ---- duplicates + deletion ----------------------------------------------------
def test_DEL_14_selecting_ALL_duplicates_never_removes_the_last_copy(small_mb, monkeypatch, workdir):
    originals = []
    for g in range(4):
        originals.append(make_file(workdir / f"g{g}_orig.bin", 4 * K + g, seed=g, age_days=10))
        make_file(workdir / f"g{g}_copy1.bin", 4 * K + g, seed=g, age_days=5)
        make_file(workdir / f"g{g}_copy2.bin", 4 * K + g, seed=g, age_days=1)
    results = scan_duplicates(workdir)
    assert len(results) == 8
    feed_input(monkeypatch, ["all", "p", "DELETE"])
    offer_deletion(results)
    assert all(o.exists() for o in originals)
    assert len(list(workdir.iterdir())) == 4


def test_DEL_17_rescan_after_deletion_shows_nothing(small_mb, monkeypatch, workdir):
    make_file(workdir / "a.bin", 4 * K, seed=1, age_days=2)
    make_file(workdir / "b.bin", 4 * K, seed=1, age_days=1)
    feed_input(monkeypatch, ["1", "p", "DELETE"])
    offer_deletion(scan_duplicates(workdir))
    assert scan_duplicates(workdir) == []


# ---- the REAL Recycle Bin (Windows) --------------------------------------------
def in_recycle_bin(filename: str) -> bool:
    ps = ("(New-Object -ComObject Shell.Application).Namespace(10).Items() "
          "| ForEach-Object { $_.Name }")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                         capture_output=True, text=True, encoding="utf-8").stdout
    return filename in out.splitlines()


@pytest.mark.windows
def test_DEL_05_real_recycle_bin_receives_the_file(monkeypatch, workdir):
    """Uses the REAL Recycle Bin. Leaves one 300-byte file in it (restore or empty it by hand)."""
    import uuid
    name = f"pccqa_{uuid.uuid4().hex[:10]}.bin"
    target = make_file(workdir / name, 300)
    feed_input(monkeypatch, ["1", "r", "y"])
    offer_deletion([item(target)])
    assert not target.exists()
    assert in_recycle_bin(name), "file vanished but is NOT in the Recycle Bin"


@pytest.mark.windows
def test_DEL_07_real_permanent_delete_bypasses_recycle_bin(monkeypatch, workdir):
    import uuid
    name = f"pccqa_{uuid.uuid4().hex[:10]}.bin"
    target = make_file(workdir / name, 300)
    feed_input(monkeypatch, ["1", "p", "DELETE"])
    offer_deletion([item(target)])
    assert not target.exists()
    assert not in_recycle_bin(name)
