# PC Cleaner

A Python command-line tool that scans a Windows PC for clutter and lets you delete it **safely**.

It finds four kinds of clutter, shows you exactly what it found and how much space you'd get back, and never deletes anything until you have chosen the files *and* confirmed.

```
  Duplicate files  -  1 files, 3.0 MB reclaimable
  [ 1]     3.0 MB  C:\PCC_QA\demo\backup\beach copy.mp4
       Duplicate of C:\PCC_QA\demo\holiday\beach.mp4
```

> **Use at your own risk.** This tool deletes files. Start with the Recycle Bin mode (the default), try it on a small folder first, and read the list before you confirm. See the [licence](LICENSE).

## What it scans for

| # | Scan | What counts |
|---|------|-------------|
| 1 | **Largest files** | Files of 100 MB or more, top 25 |
| 2 | **Old files** | 10 MB or more and not accessed **or** modified for 2+ years |
| 3 | **Duplicate files** | 1 MB or more with byte-identical content (size grouping, then SHA-256) |
| 4 | **Temp / junk** | Windows temp folders, crash dumps, browser cache, plus `.tmp .temp .log .bak .old .dmp .chk .cache` files in your user folder |

All thresholds are constants at the top of [`pc_cleaner.py`](pc_cleaner.py).

## Safety design

- **Nothing is deleted without two steps:** you select files by number (`1,3,5-8` or `all`), then confirm.
- **Recycle Bin by default** (via [`send2trash`](https://pypi.org/project/Send2Trash/)), so mistakes are recoverable.
- **Permanent deletion is separate** and requires typing `DELETE` exactly.
- **System folders are never scanned:** `Windows`, `Program Files`, `Program Files (x86)`, `ProgramData`, `AppData`, `$Recycle.Bin`, `System Volume Information`, `node_modules`, `.git`. This applies to the folder you choose *and every folder above it*, so pointing the tool at `C:\Windows` is refused.
- **The original of a duplicate set is never offered for deletion.** The oldest copy is kept; only the others are listed.
- **Shortcuts that could make one file look like two are ignored:** junctions are not followed, and hard links to the same physical file are not counted as duplicates.
- **A bad folder path re-prompts.** It never silently scans somewhere else.
- **Failures are contained.** A locked or already-deleted file is reported as `FAILED` and the rest carry on.

## Install and run

Requires **Windows** and **Python 3.12 or newer**.

```
pip install -r requirements.txt
python pc_cleaner.py
```

You'll be asked for a folder (Enter = your user folder), then pick a scan from the menu. Option `4` scans your system temp locations and your user folder regardless of the folder you entered.

If your filenames contain characters your console can't display and you redirect the output to a file, they show as `?`. Set `PYTHONUTF8=1` for full-fidelity output.

## How the duplicate scanner works

Hashing every file would mean reading every byte on the disk. Instead:

1. **Group files by size** (free: the size is already known from the file listing).
2. **Hash only files that share a size with another file.**

This is a pure performance optimisation. Two files with different sizes can never have identical content, so the results are the same as hashing everything. On my machine, reading a 4.5 GB file's size took 0.000093 s while its SHA-256 took 4.2 s, about 45,000 times slower, and in a typical folder the vast majority of files have a unique size and never get hashed.

Because it is "only" an optimisation, the test suite checks it against a slow brute-force version that hashes everything (see below).

## Tests

The repository ships with a written [test plan](TEST_PLAN.md) (about 95 cases) and an automated pytest suite of 132 tests.

```
pip install -r requirements-dev.txt
python -m pytest                    # everything except the real-size test
python -m pytest -m slow            # real 100 MB boundary test
python -m pytest -m "not windows"   # skip locked-file / junction / Recycle Bin tests
```

Test case IDs are in the test names, so `python -m pytest -k DUP_03` runs one case. Tests create all their data under `C:\PCC_QA\pytest\` (override with `PCC_QA_ROOT`) and delete it afterwards. They never touch your real folders: the junk scanner tests run against a fake user profile, and the deletion flow tests use a fake Recycle Bin. One test uses the real Recycle Bin and leaves a 300-byte file in it; another confirms that permanent deletion bypasses it.

What the suite covers:

- **Boundaries:** exactly at, just below and just above every size and age threshold.
- **Oracle testing:** the size-grouped duplicate scanner is compared with a hash-everything reference on five randomised folder trees.
- **Real Windows behaviour:** exclusively locked files, directory junctions, hard links, denied folder access, read-only files, unicode and special characters in names, and the real Recycle Bin.
- **The typed-input flow:** every prompt is scripted, including cancelling, wrong confirmations and Ctrl+C.
- **End to end:** the real program run as a subprocess.

### Bugs the tests found

The first automated run failed 14 tests and exposed real defects, all now fixed and covered by regression tests:

| Defect | What went wrong |
|--------|-----------------|
| Protected-folder check ignored the folder you typed | Entering `C:\Windows` scanned it |
| Junctions were followed | One file was reachable by two paths, so the duplicate scanner could flag a file as a duplicate of *itself* (deleting it would delete the only copy) |
| Hard links counted as duplicates | Deleting one frees no space |
| `1,5-3` silently selected only item 1 | Wrong selection accepted without warning |
| `1-999999999` built a huge range in memory before validating | Memory blow-up on invalid input |
| A file vanishing mid-scan | Unhandled exception |
| Filenames with non-Latin characters when output is piped | Crash with `UnicodeEncodeError` |
| A mistyped folder path | Silently scanned the whole user folder instead |

## Known limitations

- **Files behind a junction are not scanned** (a deliberate trade-off, see above).
- **Near-duplicates are not detected.** A copy that differs by one byte is a different file.
- **A folder *named* `windows`, `appdata` or `.git` anywhere in a tree is skipped**, even if it is your own.
- **Old files** use the newer of last-access and last-modified time, because Windows may not update access times. Creation time is ignored.
- **Not yet verified on real hardware:** whether Recycle Bin deletion is really recoverable on a USB stick or network drive, and whether scanning OneDrive "online-only" files triggers a download. Treat both with care until they are covered by the [test plan](TEST_PLAN.md).
- `.log`, `.bak` and `.old` files anywhere in your user folder are listed as junk. Some of those may be backups you want. Read the list.

## Licence

[MIT](LICENSE)
