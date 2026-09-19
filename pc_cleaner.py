#!/usr/bin/env python3
"""
PC Cleaner - find what's clogging up your PC and (optionally) delete it.

Scans for four kinds of clutter:
  1. Largest files
  2. Old files (not accessed in a long time)
  3. Duplicate files (identical content)
  4. Temp / cache / junk files

SAFETY:
  * Nothing is ever deleted without you selecting it AND confirming.
  * Default deletion sends files to the Recycle Bin (recoverable).
  * Permanent deletion is a separate option with an extra confirmation.
  * System folders (C:\\Windows, Program Files, etc.) are never scanned.

Setup:
    pip install send2trash
Run:
    python pc_cleaner.py
"""

import hashlib
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

try:
    from send2trash import send2trash
except ImportError:
    send2trash = None

# ----------------------------------------------------------------------------
# Configuration - tweak these to taste
# ----------------------------------------------------------------------------
TOP_N_LARGEST = 25            # how many big files to show
LARGE_FILE_MIN_MB = 100       # ignore files smaller than this in the "largest" list
OLD_FILE_YEARS = 2            # "old" = not accessed in this many years
OLD_FILE_MIN_MB = 10          # only flag old files bigger than this (avoids tiny noise)
DUPLICATE_MIN_MB = 1          # only look for duplicates bigger than this
MAX_RESULTS_PER_CATEGORY = 50 # cap the list length so it stays readable

# Folders we never scan (safety). Compared case-insensitively.
PROTECTED_DIR_NAMES = {
    "windows", "program files", "program files (x86)", "programdata",
    "$recycle.bin", "system volume information", "appdata",
    "node_modules", ".git",
}

# File extensions that usually indicate junk
JUNK_EXTENSIONS = {".tmp", ".temp", ".log", ".bak", ".old", ".dmp", ".chk", ".cache"}

MB = 1024 * 1024


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def human_size(num_bytes: float) -> str:
    """Turn a byte count into something readable like '1.4 GB'."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num_bytes < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} PB"


def human_age(timestamp: float) -> str:
    days = int((time.time() - timestamp) / 86400)
    if days >= 365:
        return f"{days // 365}y {(days % 365) // 30}m ago"
    if days >= 30:
        return f"{days // 30}m ago"
    return f"{days}d ago"


def get_junk_locations() -> list[Path]:
    """Windows temp/cache folders that are safe to clean."""
    candidates = [
        os.environ.get("TEMP"),
        os.environ.get("TMP"),
        r"C:\Windows\Temp",
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Temp"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "CrashDumps"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""),
                     r"Microsoft\Windows\INetCache"),
    ]
    seen, result = set(), []
    for c in candidates:
        if c and Path(c).is_dir() and c.lower() not in seen:
            seen.add(c.lower())
            result.append(Path(c))
    return result


def is_protected(path: Path) -> bool:
    """
    True if `path` is a protected folder, or sits anywhere inside one.
    Checks every folder name in the full path, so 'C:\\Windows' and
    'C:\\Program Files\\Common Files' are both caught. resolve() makes '..' and
    junctions/symlinks show their real location first.
    """
    return any(part.lower() in PROTECTED_DIR_NAMES for part in path.resolve().parts)


def walk_files(root: Path, skip_protected: bool = True):
    """
    Yield (path, stat_result) for every readable file under root.
    Skips protected folders and swallows permission errors.
    """
    if skip_protected and is_protected(root):
        return
    for dirpath, dirnames, filenames in os.walk(root, onerror=lambda e: None):
        # Windows junctions look like normal folders but point somewhere else
        # (possibly back up the tree). Following them makes one file appear at
        # several paths, so never descend into them.
        dirnames[:] = [d for d in dirnames
                       if not os.path.isjunction(os.path.join(dirpath, d))]
        if skip_protected:
            # Editing dirnames in place stops os.walk descending into them
            dirnames[:] = [d for d in dirnames
                           if d.lower() not in PROTECTED_DIR_NAMES]
        for name in filenames:
            path = Path(dirpath) / name
            try:
                if path.is_symlink():
                    continue
                yield path, path.stat()
            except (OSError, PermissionError):
                continue


def file_hash(path: Path, chunk_size: int = 1024 * 1024) -> str | None:
    """SHA-256 of a file's contents, read in chunks so big files don't eat RAM."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            while chunk := f.read(chunk_size):
                h.update(chunk)
    except (OSError, PermissionError):
        return None
    return h.hexdigest()


# ----------------------------------------------------------------------------
# Scanners - each returns a list of dicts: {path, size, reason, ...}
# ----------------------------------------------------------------------------
def scan_largest(root: Path) -> list[dict]:
    results = []
    for path, st in walk_files(root):
        if st.st_size >= LARGE_FILE_MIN_MB * MB:
            results.append({"path": path, "size": st.st_size,
                            "reason": f"Large file (modified {human_age(st.st_mtime)})"})
    results.sort(key=lambda r: r["size"], reverse=True)
    return results[:TOP_N_LARGEST]


def scan_old(root: Path) -> list[dict]:
    cutoff = time.time() - OLD_FILE_YEARS * 365 * 86400
    results = []
    for path, st in walk_files(root):
        # st_atime = last accessed. Windows sometimes disables atime updates,
        # so we use the NEWER of atime/mtime to avoid false positives.
        last_used = max(st.st_atime, st.st_mtime)
        if last_used < cutoff and st.st_size >= OLD_FILE_MIN_MB * MB:
            results.append({"path": path, "size": st.st_size,
                            "reason": f"Untouched for {human_age(last_used)}"})
    results.sort(key=lambda r: r["size"], reverse=True)
    return results[:MAX_RESULTS_PER_CATEGORY]


def scan_duplicates(root: Path) -> list[dict]:
    """
    Efficient duplicate detection:
      1. Group files by size (cheap - no reading needed).
      2. Only hash files that share a size with another file.
    Files with a unique size can't possibly be duplicates.
    """
    by_size: dict[int, list[Path]] = defaultdict(list)
    seen_ids: set[tuple[int, int]] = set()
    for path, st in walk_files(root):
        if st.st_size >= DUPLICATE_MIN_MB * MB:
            # (device, file index) identifies the physical file. If we meet it
            # again under another path (hard link, alias) it is the SAME file,
            # not a duplicate - deleting it would delete the only copy.
            file_id = (st.st_dev, st.st_ino)
            if st.st_ino and file_id in seen_ids:
                continue
            seen_ids.add(file_id)
            by_size[st.st_size].append(path)

    candidates = [(size, paths) for size, paths in by_size.items() if len(paths) > 1]
    total = sum(len(p) for _, p in candidates)
    print(f"    Hashing {total} possible duplicates...")

    results = []
    for size, paths in candidates:
        by_hash: dict[str, list[Path]] = defaultdict(list)
        for p in paths:
            digest = file_hash(p)
            if digest:
                by_hash[digest].append(p)
        for group in by_hash.values():
            if len(group) < 2:
                continue
            # Keep the oldest-modified copy as the "original"; flag the rest.
            dated = []
            for p in group:
                try:
                    dated.append((p.stat().st_mtime, p))
                except OSError:
                    continue  # vanished since hashing; can't be offered for deletion
            if len(dated) < 2:
                continue
            dated.sort(key=lambda item: item[0])
            original = dated[0][1]
            for _, dup in dated[1:]:
                results.append({"path": dup, "size": size,
                                "reason": f"Duplicate of {original}"})
    results.sort(key=lambda r: r["size"], reverse=True)
    return results[:MAX_RESULTS_PER_CATEGORY]


def scan_junk() -> list[dict]:
    """Scan known temp/cache folders, plus junk-extension files in the home dir."""
    results, seen = [], set()

    for loc in get_junk_locations():
        for path, st in walk_files(loc, skip_protected=False):
            key = str(path).lower()
            if key not in seen:
                seen.add(key)
                results.append({"path": path, "size": st.st_size,
                                "reason": f"In temp/cache folder ({loc.name})"})

    for path, st in walk_files(Path.home()):
        if path.suffix.lower() in JUNK_EXTENSIONS:
            key = str(path).lower()
            if key not in seen:
                seen.add(key)
                results.append({"path": path, "size": st.st_size,
                                "reason": f"Junk extension ({path.suffix})"})

    results.sort(key=lambda r: r["size"], reverse=True)
    return results[:MAX_RESULTS_PER_CATEGORY]


# ----------------------------------------------------------------------------
# Display + deletion
# ----------------------------------------------------------------------------
def show_results(title: str, results: list[dict]) -> None:
    total = sum(r["size"] for r in results)
    print(f"\n{'=' * 78}")
    print(f"  {title}  -  {len(results)} files, {human_size(total)} reclaimable")
    print("=" * 78)
    if not results:
        print("  Nothing found.")
        return
    for i, r in enumerate(results, 1):
        print(f"  [{i:>2}] {human_size(r['size']):>10}  {r['path']}")
        print(f"       {r['reason']}")


def parse_selection(text: str, max_index: int) -> list[int]:
    """
    Turn '1,3,5-8' or 'all' into a sorted list of 0-based indexes.
    Returns [] on anything invalid rather than guessing.
    """
    text = text.strip().lower()
    if text == "all":
        return list(range(max_index))
    chosen: set[int] = set()
    try:
        for part in text.split(","):
            part = part.strip()
            if "-" in part:
                first, last = (int(x) for x in part.split("-"))
            elif part:
                first = last = int(part)
            else:
                continue
            # Validate BEFORE expanding, so '1-999999999' is rejected instantly
            # instead of building a huge set, and a reversed range like '5-3'
            # invalidates the whole input instead of being silently dropped.
            if first < 1 or last > max_index or first > last:
                return []
            chosen.update(range(first, last + 1))
    except ValueError:
        return []
    return sorted(n - 1 for n in chosen)


def delete_files(items: list[dict], permanent: bool) -> tuple[int, int]:
    """Delete the given items. Returns (bytes_freed, failures)."""
    freed, failures = 0, 0
    for item in items:
        path = item["path"]
        try:
            if permanent:
                os.remove(path)
            else:
                send2trash(str(path))
            freed += item["size"]
            print(f"    deleted: {path}")
        except Exception as e:  # noqa: BLE001 - show any failure, keep going
            failures += 1
            print(f"    FAILED:  {path}  ({e})")
    return freed, failures


def offer_deletion(results: list[dict]) -> None:
    if not results:
        return
    print("\n  Choose files to delete: e.g. '1,3,5-8', 'all', or Enter to skip.")
    choice = input("  > ").strip()
    if not choice:
        return

    indexes = parse_selection(choice, len(results))
    if not indexes:
        print("  Invalid selection - nothing deleted.")
        return

    selected = [results[i] for i in indexes]
    size = sum(s["size"] for s in selected)
    print(f"\n  You selected {len(selected)} files ({human_size(size)}).")

    if send2trash is None:
        print("  NOTE: 'send2trash' isn't installed, so Recycle Bin deletion is "
              "unavailable.\n  Run: pip install send2trash")
        mode = "p"
    else:
        mode = input("  [R]ecycle Bin (recoverable) / [P]ermanent / [C]ancel? "
                     "(r/p/c): ").strip().lower()

    if mode == "c" or mode not in ("r", "p"):
        print("  Cancelled - nothing deleted.")
        return

    if mode == "p":
        print("\n  WARNING: permanent deletion CANNOT be undone.")
        if input("  Type DELETE to confirm: ").strip() != "DELETE":
            print("  Cancelled - nothing deleted.")
            return
    else:
        if input("  Confirm move to Recycle Bin? (y/n): ").strip().lower() != "y":
            print("  Cancelled - nothing deleted.")
            return

    freed, failures = delete_files(selected, permanent=(mode == "p"))
    print(f"\n  Done. Freed {human_size(freed)}"
          + (f" ({failures} failed)" if failures else "") + ".")


# ----------------------------------------------------------------------------
# Main menu
# ----------------------------------------------------------------------------
def choose_scan_root() -> Path:
    default = Path.home()
    while True:
        raw = input(f"Folder to scan [Enter = {default}]: ").strip().strip('"')
        root = Path(raw) if raw else default
        if not root.is_dir():
            # Never guess: silently scanning some OTHER folder after a typo is
            # dangerous in a tool that deletes files.
            print(f"'{root}' isn't a valid folder. Please try again.")
            continue
        if is_protected(root):
            print(f"'{root}' is (or is inside) a protected system folder and is "
                  "never scanned. Please choose another folder.")
            continue
        return root


def make_output_crash_proof() -> None:
    """
    When output is piped or redirected, Python uses the system code page
    (cp1252 on many Windows PCs), which can't encode every filename. Replace
    what can't be shown with '?' instead of crashing. Set PYTHONUTF8=1 for
    full-fidelity output.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass


def main() -> None:
    make_output_crash_proof()
    print("=" * 78)
    print("  PC CLEANER - find and remove what's clunking up your PC")
    print("=" * 78)
    if not sys.platform.startswith("win"):
        print("  (Note: junk-folder detection is tuned for Windows.)")

    root = choose_scan_root()
    print(f"\nScanning: {root}\n(This can take a few minutes on big drives.)")

    menu = {
        "1": ("Largest files", lambda: scan_largest(root)),
        "2": ("Old, unused files", lambda: scan_old(root)),
        "3": ("Duplicate files", lambda: scan_duplicates(root)),
        "4": ("Temp / cache / junk", scan_junk),
    }

    while True:
        print("\nWhat would you like to scan for?")
        for key, (label, _) in menu.items():
            print(f"  {key}. {label}")
        print("  5. Run ALL scans")
        print("  q. Quit")
        choice = input("> ").strip().lower()

        if choice == "q":
            print("Bye!")
            return

        keys = list(menu) if choice == "5" else [choice] if choice in menu else []
        if not keys:
            print("Please pick 1-5 or q.")
            continue

        for key in keys:
            label, scanner = menu[key]
            print(f"\n  Scanning: {label}...")
            results = scanner()
            show_results(label, results)
            offer_deletion(results)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted - nothing further was deleted.")
