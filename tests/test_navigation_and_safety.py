"""NAV-xx: scan-root input, the protected-folder promise, and Ctrl+C handling."""

import runpy
from pathlib import Path

import pytest

from conftest import feed_input
from pc_cleaner import choose_scan_root, walk_files


# ---- choose_scan_root ------------------------------------------------------
def test_NAV_02_enter_accepts_home_by_default(monkeypatch):
    feed_input(monkeypatch, [""])
    assert choose_scan_root() == Path.home()


def test_NAV_03_valid_folder(monkeypatch, workdir):
    feed_input(monkeypatch, [str(workdir)])
    assert choose_scan_root() == workdir


def test_NAV_04_quotes_and_trailing_spaces_are_stripped(monkeypatch, workdir):
    feed_input(monkeypatch, [f'"{workdir}"  '])
    assert choose_scan_root() == workdir


def test_NAV_05_nonexistent_folder_asks_again_instead_of_scanning_home(monkeypatch, workdir, capsys):
    """H3: a typo must never silently redirect the scan to another folder."""
    feed_input(monkeypatch, [r"C:\does\not\exist", str(workdir)])
    assert choose_scan_root() == workdir
    assert "isn't a valid folder" in capsys.readouterr().out


def test_NAV_06_a_file_path_is_not_a_folder(monkeypatch, workdir):
    f = workdir / "a.bin"
    f.write_bytes(b"x")
    feed_input(monkeypatch, [str(f), str(workdir)])
    assert choose_scan_root() == workdir


# ---- H1: the "system folders are never scanned" promise ---------------------
@pytest.mark.parametrize("protected", [
    "Windows", "Program Files", "Program Files (x86)", "ProgramData", "AppData",
])
def test_NAV_08_root_that_IS_a_protected_folder_yields_nothing(workdir, protected):
    """H1: only CHILD folder names are filtered, so pointing the scanner
    straight at a protected folder walks all of it."""
    root = workdir / protected
    (root / "sub").mkdir(parents=True)
    (root / "top.bin").write_bytes(b"x")
    (root / "sub" / "deep.bin").write_bytes(b"x")
    assert list(walk_files(root)) == []


def test_NAV_09_root_INSIDE_a_protected_folder_yields_nothing(workdir):
    """H1: e.g. C:\\Program Files\\Common Files - name is not protected,
    but an ancestor is. Checking only the root's own name would miss this."""
    root = workdir / "Program Files" / "Common Files"
    root.mkdir(parents=True)
    (root / "x.bin").write_bytes(b"x")
    assert list(walk_files(root)) == []


@pytest.mark.windows
@pytest.mark.parametrize("real", [r"C:\Windows", r"C:\Windows\System32", r"C:\Program Files"])
def test_NAV_08_real_system_folder_is_never_walked(real):
    """Read-only against the real system: does the generator yield even ONE file?"""
    if not Path(real).is_dir():
        pytest.skip(f"{real} not present")
    assert next(walk_files(Path(real)), None) is None


def test_NAV_08b_choose_scan_root_refuses_a_protected_folder_and_asks_again(monkeypatch, workdir, capsys):
    """The user-facing stop: a clear message, then a new prompt (not a silent empty scan)."""
    (workdir / "Windows").mkdir()
    feed_input(monkeypatch, [str(workdir / "Windows"), str(workdir)])
    assert choose_scan_root() == workdir
    assert "protected system folder" in capsys.readouterr().out


def test_NAV_08c_dotdot_cannot_sneak_into_a_protected_folder(workdir):
    (workdir / "Windows").mkdir()
    (workdir / "Windows" / "x.bin").write_bytes(b"x")
    (workdir / "other").mkdir()
    sneaky = workdir / "other" / ".." / "Windows"
    assert list(walk_files(sneaky)) == []


def test_NAV_11_protected_name_deep_in_tree_is_skipped_by_design(workdir):
    """H2 (characterisation): a personal folder called 'windows' is skipped."""
    (workdir / "windows").mkdir()
    (workdir / "windows" / "mine.bin").write_bytes(b"x")
    (workdir / "ok.bin").write_bytes(b"x")
    assert [p.name for p, _ in walk_files(workdir)] == ["ok.bin"]


def test_NAV_11b_protected_folder_match_is_case_insensitive(workdir):
    (workdir / "PROGRAM FILES").mkdir()
    (workdir / "PROGRAM FILES" / "x.bin").write_bytes(b"x")
    assert list(walk_files(workdir)) == []


# ---- Ctrl+C -----------------------------------------------------------------
def test_NAV_15_ctrl_c_prints_message_and_exits_cleanly(monkeypatch, capsys):
    def interrupt(prompt=""):
        raise KeyboardInterrupt
    monkeypatch.setattr("builtins.input", interrupt)
    runpy.run_module("pc_cleaner", run_name="__main__")      # must not raise
    assert "Interrupted - nothing further was deleted." in capsys.readouterr().out


# ---- menu -------------------------------------------------------------------
def test_NAV_12_invalid_menu_choice_reprompts_then_quit_is_case_insensitive(monkeypatch, workdir, capsys):
    from pc_cleaner import main
    feed_input(monkeypatch, [str(workdir), "9", "abc", "", "Q"])
    main()
    out = capsys.readouterr().out
    assert out.count("Please pick 1-5 or q.") == 3
    assert "Bye!" in out
