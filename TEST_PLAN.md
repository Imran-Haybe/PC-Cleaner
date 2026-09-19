# PC Cleaner - Test Plan

| | |
|---|---|
| **Application under test** | `pc_cleaner.py` (Python CLI) |
| **Environment** | Windows 10 Home 10.0.19045, Python 3.14.7, NTFS system drive, `send2trash` installed |
| **Author / status** | Draft v0.1 - written from code review, **nothing executed yet** |

## 1. Scope

**In scope:** menu and scan-root input, the four scanners, the selection parser, and the deletion flow (Recycle Bin and permanent).
**Out of scope:** installer/packaging, non-Windows platforms, performance tuning beyond basic sanity checks.

## 2. Approach

- **Never test on real data.** All test data lives in `C:\PCC_QA\` (not a protected folder name) or in clearly marked `pccleaner_qa` subfolders of the real temp locations.
- **One folder per suite, and scan root = that folder.** This keeps the suites from contaminating each other. For example, the large files in `LRG` would show up as "duplicates" if the whole `C:\PCC_QA\` were scanned.
- **Test design techniques used** (tagged in the test name):
  - `[BVA]` boundary value analysis, `[EP]` equivalence partitioning, `[NEG]` negative / invalid input
  - `[ORACLE]` compare the scanner against a slow, trusted brute-force reference
  - `[ERR]` error guessing, from things that commonly break on Windows (locked files, read-only, long paths, junctions, cloud placeholders)
- **Priority:** P1 = data loss / safety promise broken, P2 = wrong results, P3 = cosmetic or edge.
- Results are recorded in `TEST_RESULTS.md` when executed.

## 3. Hypotheses from code review (unconfirmed - verify during execution)

These come from reading the code, not from running it. Each is linked to the test that confirms or refutes it.

| # | Suspected issue | Why it matters | Test |
|---|-----------------|----------------|------|
| H1 | The protected-folder filter only checks *child* folder names, never the scan root. Entering `C:\Windows` or `C:\Program Files` directly probably scans them. | Breaks the "system folders are never scanned" promise | NAV-08, NAV-09 |
| H2 | Protected names match by folder name anywhere in the tree, so a personal folder called `Windows`, `AppData` or `.git` is silently skipped. | Safe direction (missed files), but undocumented | NAV-11 |
| H3 | An invalid folder path silently falls back to scanning the home folder instead of re-prompting. | A typo scans the wrong place | NAV-05 |
| H4 | Option 4 (junk) ignores the folder the user chose. It always scans the home folder plus system temp locations. | Surprising behaviour | JNK-12 |
| H5 | `parse_selection("1,5-3")` probably returns just `[1]`, silently dropping the reversed range. `1-999999999` builds the full range in memory before the bounds check. | Wrong selection accepted / possible memory blow-up | SEL-12, SEL-13 |
| H6 | `group.sort(key=... p.stat())` is not in a try block. A file vanishing between hashing and sorting would crash the app. | Unhandled exception | DUP-15 |
| H7 | Hard links to the same data count as duplicates. Deleting one frees no space, but "Freed X" would still be reported. | Misleading result | DUP-13 |
| H8 | OneDrive "online-only" files report their full size, and hashing one may force a download. | Unexpected bandwidth / disk use | DUP-17 |
| H9 | `.log`, `.bak`, `.old` anywhere under the home folder are flagged as junk, and these can be user backups. | False positives | JNK-09 |
| H10 | `send2trash` on a drive with no Recycle Bin (USB, network) may delete permanently. | "Recoverable" promise broken | DEL-16 (manual) |
| H11 | With stdout piped or redirected, Python 3.14 on Windows encodes output as cp1252; a filename with characters outside it crashes the program. | Crash on legitimate filenames | NAV-16 |
| H12 | Junctions are followed (`is_symlink()` is False for them). One file is reachable by two paths, so the duplicate scanner can flag a file as a duplicate of *itself*. | **Data loss:** deleting the flagged path deletes the only copy | DUP-20, LRG-11 |

**Status (2026-09-19):** first automated run confirmed H1, H5, H6, H7, H11, H12 (14 failing tests). All six are now **fixed and covered by regression tests** (132 passing). H2 confirmed as characterised behaviour. H3 was then hit by accident during a demo run (a stray byte in a piped path silently scanned the whole home folder) and **fixed**: an invalid folder now re-prompts. H4, H8, H9, H10 still need manual execution.

| Defect | Fix |
|--------|-----|
| H1 | `is_protected()` checks the root and all ancestors; guard in `walk_files`, message + re-prompt in `choose_scan_root` |
| H12 | Junctions are never descended; duplicate scanner skips a file it has already seen by `(st_dev, st_ino)` |
| H7 | Fixed by the same identity check as H12 |
| H5 | `parse_selection` validates each range before expanding it; reversed range invalidates the whole input |
| H6 | `.stat()` in the duplicate scanner wrapped; vanished files are dropped from the group |
| H11 | `make_output_crash_proof()` sets `errors="replace"` on stdout/stderr |

## 4. Test cases

### 4.1 Menu and scan-root input (NAV)

| ID | Test | Data / setup | Expected | Pri |
|----|------|--------------|----------|-----|
| NAV-01 | App launches, banner and prompt appear | - | Banner shown, "Folder to scan" prompt | P3 |
| NAV-02 | [EP] Enter accepts default root | Press Enter | Scans `C:\Users\<username>` | P3 |
| NAV-03 | [EP] Valid folder path | `C:\PCC_QA\dup` | "Scanning: C:\PCC_QA\dup" | P2 |
| NAV-04 | [EP] Path wrapped in quotes and with trailing spaces | `"C:\PCC_QA\dup"  ` | Quotes and spaces stripped, valid | P3 |
| NAV-05 | [NEG] Non-existent folder (H3) | `C:\does\not\exist` | Message shown; **record** whether it re-prompts or scans home | P2 |
| NAV-06 | [NEG] Path is a file, not a folder | `C:\PCC_QA\dup\a.bin` | Same as NAV-05 | P3 |
| NAV-07 | [EP] Drive root | `C:\` | `Windows`, `Program Files`, `ProgramData`, `$Recycle.Bin` are skipped; no crash on access-denied folders | P1 |
| NAV-08 | [NEG] Root **is** a protected folder (H1) | `C:\Windows` | Should refuse or scan nothing. **Record** whether system files are listed | P1 |
| NAV-09 | [NEG] Root is inside a protected folder (H1) | `C:\Program Files\Common Files` | Same as NAV-08 | P1 |
| NAV-10 | [EP] UNC / mapped-drive path | `\\localhost\c$\PCC_QA` if available | Works or fails cleanly | P3 |
| NAV-11 | [BVA] Protected name in user folder (H2) | `C:\PCC_QA\nav\windows\big.bin` (150 MB) | Skipped per design; record as known limitation | P3 |
| NAV-12 | Menu: invalid input | `9`, `abc`, empty, `  ` | "Please pick 1-5 or q." and re-prompt | P3 |
| NAV-13 | Menu: `Q` and `q` both quit | `Q` | "Bye!" | P3 |
| NAV-14 | Menu: option 5 runs all four scans in order 1-4 | `5` | Each scan shown, each offers deletion | P2 |
| NAV-15 | Ctrl+C at every prompt (root, menu, selection, confirmation) | Ctrl+C | "Interrupted - nothing further was deleted." No traceback | P1 |
| NAV-16 | [ERR] Non-ASCII filenames print without crashing | `résumé 日本語 🙂.bin` | Name displays or is replaced; no `UnicodeEncodeError` | P2 |

### 4.2 Largest files (LRG) - root `C:\PCC_QA\lrg`

Threshold `>= 100 MB` (104,857,600 bytes), top 25. The docstring says "over 100MB" while the code uses `>=`.

| ID | Test | Data / setup | Expected | Pri |
|----|------|--------------|----------|-----|
| LRG-01 | [BVA] Just below threshold | 104,857,599 B | Not listed | P2 |
| LRG-02 | [BVA] Exactly at threshold | 104,857,600 B | Listed (`>=`); note doc mismatch | P3 |
| LRG-03 | [BVA] Just above threshold | 104,857,601 B | Listed | P2 |
| LRG-04 | Sort order | 101 MB, 300 MB, 200 MB | Order: 300, 200, 101 | P2 |
| LRG-05 | [BVA] Cap of 25 | 30 files, distinct sizes 101-130 MB | Exactly 25 shown, the 25 largest, header says 25 files | P2 |
| LRG-06 | Files in nested subfolders are found | file 3 levels deep | Listed with full path | P2 |
| LRG-07 | Empty folder | empty root | "Nothing found." and no deletion prompt | P3 |
| LRG-08 | Size display | 1.5 GB file | "1.5 GB" | P3 |
| LRG-09 | [ERR] Folder with denied access | `icacls <folder> /deny %USERNAME%:(RX)` | Skipped silently, other files still listed | P2 |
| LRG-10 | [ERR] Symlink to a big file | needs Developer Mode | Symlink not listed | P3 |
| LRG-11 | [ERR] Junction pointing back up the tree | `mklink /J loop ..` | No infinite loop, no double counting | P2 |

### 4.3 Old files (OLD) - root `C:\PCC_QA\old`

Rule: `max(atime, mtime)` older than 730 days **and** size `>= 10 MB`. Test data sets both timestamps with `os.utime`.

| ID | Test | Data / setup | Expected | Pri |
|----|------|--------------|----------|-----|
| OLD-01 | Old and big | 50 MB, both stamps 3 years ago | Listed, "Untouched for 3y ..." | P2 |
| OLD-02 | [BVA] Size just below | 10 MB - 1 B, 3 years old | Not listed | P2 |
| OLD-03 | [BVA] Size at threshold | exactly 10 MB, 3 years old | Listed | P2 |
| OLD-04 | [BVA] Age 729 days | 50 MB | Not listed | P2 |
| OLD-05 | [BVA] Age 731 days | 50 MB | Listed | P2 |
| OLD-06 | Recent | 50 MB, 1 year old | Not listed | P2 |
| OLD-07 | Old mtime, recent atime | mtime 3y ago, atime now | Not listed (max rule) | P2 |
| OLD-08 | Recent mtime, old atime | mtime now, atime 3y ago | Not listed | P2 |
| OLD-09 | Old creation time only | created 3y ago (`(Get-Item).CreationTime`), mtime now | Not listed. Record that creation time is ignored | P3 |
| OLD-10 | Sort and cap of 50 | 60 old files, distinct sizes | 50 shown, largest first | P3 |
| OLD-11 | [ERR] Reading a file bumps atime | Run OLD scan, then DUP scan (hashes files), then OLD again | Same results, or record the difference | P3 |
| OLD-12 | Age text | 3y 4m old | Shows "3y 4m ago" | P3 |

### 4.4 Duplicates (DUP) - root `C:\PCC_QA\dup`

Design: group by size, hash only same-size files, min size `>= 1 MB`. One file per group is kept as the "original" (oldest mtime), the rest are flagged.

| ID | Test | Data / setup | Expected | Pri |
|----|------|--------------|----------|-----|
| DUP-01 | Simple pair | 5 MB file + copy, different names and folders | 1 flagged (the newer one), reason names the original | P2 |
| DUP-02 | Three copies | same content x3 | Exactly 2 flagged; the oldest is never offered | P1 |
| DUP-03 | **Same size, different content** | two 5 MB random files, one differs in the last byte | 0 flagged. Proves the hash step is needed | P1 |
| DUP-04 | All sizes unique | 20 files | "Hashing 0 possible duplicates..." then "Nothing found." | P2 |
| DUP-05 | [BVA] Below min size | identical pair, 1 MB - 1 B | Not flagged | P2 |
| DUP-06 | [BVA] At min size | identical pair, exactly 1 MB | Flagged | P2 |
| DUP-07 | Different name, same content | `a.jpg` and `b.txt` | Flagged (content, not name) | P2 |
| DUP-08 | Near-duplicate (1 byte longer) | 5 MB and 5 MB + 1 B | Not flagged. Known limitation | P3 |
| DUP-09 | Two separate groups | pair of 5 MB + pair of 8 MB | 2 flagged, larger first | P2 |
| DUP-10 | Cap of 50 | 60 identical pairs, distinct sizes | 50 shown | P3 |
| DUP-11 | Copy inside a protected-named folder | pair, one in `node_modules\` | Not flagged (copy invisible) | P3 |
| DUP-12 | Identical mtime tie (`copy2` preserves mtime) | 3 copies, same mtime | Still exactly 2 flagged | P2 |
| DUP-13 | Hard link (H7) | `mklink /H` | Record: flagged? does "Freed" overstate real space? | P3 |
| DUP-14 | [ERR] One file held open exclusively | one of a pair locked by another process | No crash; that file skipped, pair not flagged | P1 |
| DUP-15 | [ERR] File deleted between scan steps (H6) | delete a file while "Hashing..." is running | No traceback. Record the outcome | P2 |
| DUP-16 | [ERR] Long path (>260 chars) and unicode names | pair with deep nesting | Found, or skipped cleanly | P3 |
| DUP-17 | [ERR] OneDrive online-only files (H8) | pair inside OneDrive, files not downloaded | Record: does scanning trigger a download? | P2 |
| DUP-18 | [ORACLE] Compare against brute force | random tree, ~200 files, ~30 planted duplicate sets | Scanner's flagged set == brute-force flagged set (also tests the size-grouping optimization) | P1 |
| DUP-19 | Progress message count | 6 same-size files | "Hashing 6 possible duplicates..." | P3 |

### 4.5 Temp / junk (JNK)

Real system locations are scanned, so **run a baseline first** (JNK-00) and know what is already there. The cap of 50 sorted by size means small test files can be pushed off the list; make test files larger than the real junk, or count relative to the baseline.

| ID | Test | Data / setup | Expected | Pri |
|----|------|--------------|----------|-----|
| JNK-00 | Baseline | Run option 4 before creating any test data | Save the list; nothing deleted | P1 |
| JNK-01 | File in `%TEMP%` | `%TEMP%\pccleaner_qa\t1.dat` | Listed, "In temp/cache folder (Temp)" | P2 |
| JNK-02 | Nested subfolder in `%TEMP%` | 3 levels deep | Listed | P2 |
| JNK-03 | Folder named `windows` inside `%TEMP%` | `%TEMP%\pccleaner_qa\windows\x.dat` | Listed (protected filter is off for known junk folders) | P3 |
| JNK-04 | CrashDumps | `%LOCALAPPDATA%\CrashDumps\pccleaner_qa.dmp` (create folder if missing) | Listed. If folder missing, no crash | P2 |
| JNK-05 | Browser cache path | `%LOCALAPPDATA%\Microsoft\Windows\INetCache\pccleaner_qa.tmp` | Listed | P2 |
| JNK-06 | `C:\Windows\Temp`, run without admin | read-only look | No crash. Unreadable entries skipped | P1 |
| JNK-07 | No duplicate entries | `TEMP` and `TMP` point at the same folder | Each file listed once | P2 |
| JNK-08 | Junk extensions in home | `C:\Users\<username>\PCC_QA_home\` with `.tmp .temp .log .bak .old .dmp .chk .cache` | All 8 listed, "Junk extension (.x)" | P2 |
| JNK-09 | Case and false-positive checks (H9) | `A.TMP`, `b.Log`, `notes.tmp.txt`, `.tmp` (dotfile), `keep.txt` | `A.TMP` and `b.Log` listed; `.txt` files and the bare `.tmp` dotfile not | P2 |
| JNK-10 | Junk-extension file inside `AppData` in home | `...\AppData\Roaming\x.tmp` | Not listed by the extension scan (AppData protected) | P3 |
| JNK-11 | Cap of 50 and sort by size | 60 junk files | 50 shown, largest first | P3 |
| JNK-12 | Scan root ignored (H4) | Choose root `C:\PCC_QA\dup`, run option 4 | Record what gets scanned | P2 |
| JNK-13 | [ERR] Locked file in `%TEMP%` | file held open by a Python process | Listed. Deletion later gives FAILED (see DEL-10) | P1 |
| JNK-14 | [ERR] Read-only file in `%TEMP%` | `attrib +R` | Listed. See DEL-11 | P2 |

### 4.6 Selection parser (SEL) - call `parse_selection(text, max_index)` directly

| ID | Input | max | Expected | Pri |
|----|-------|-----|----------|-----|
| SEL-01 | `1` | 5 | `[0]` | P2 |
| SEL-02 | `1,3,5` | 5 | `[0, 2, 4]` | P2 |
| SEL-03 | `2-4` | 5 | `[1, 2, 3]` | P2 |
| SEL-04 | `1,3,5-8` | 8 | `[0, 2, 4, 5, 6, 7]` | P2 |
| SEL-05 | `all`, `ALL`, `  All  ` | 5 | `[0, 1, 2, 3, 4]` | P2 |
| SEL-06 | `1, 3 - 5` (spaces) | 5 | `[0, 2, 3, 4]` | P3 |
| SEL-07 | `1,1,1` (repeats) | 5 | `[0]` | P3 |
| SEL-08 | [BVA] `0`, `6` | 5 | `[]` (out of range) | P1 |
| SEL-09 | [BVA] `1`, `5` | 5 | `[0]` and `[4]` | P2 |
| SEL-10 | [NEG] `abc`, `1,abc`, `1.5`, `-1`, `-`, `1-`, `1--3`, `1-2-3` | 5 | `[]` for each | P2 |
| SEL-11 | `1,,2` and `,` | 5 | `[0, 1]` and `[]` | P3 |
| SEL-12 | [NEG] Reversed range: `5-3` and `1,5-3` (H5) | 5 | Both should be rejected. Record what `1,5-3` returns | P2 |
| SEL-13 | [NEG] Huge range `1-50000000`, then `1-999999999` (H5) | 5 | `[]` quickly. **Watch memory in Task Manager; run the second only if the first was fine** | P2 |
| SEL-14 | Any selection on a 50-item list | 50 | Indexes map to the correct item | P1 |

### 4.7 Deletion flow (DEL) - root `C:\PCC_QA\del`

The prompts are: selection -> R/P/C -> confirmation (`y`, or `DELETE` for permanent).

| ID | Test | Data / setup | Expected | Pri |
|----|------|--------------|----------|-----|
| DEL-01 | Enter at selection prompt | Enter | Nothing deleted, back to menu | P1 |
| DEL-02 | Invalid selection | `abc` | "Invalid selection - nothing deleted." | P1 |
| DEL-03 | Cancel at mode prompt | `c`, `x`, empty | "Cancelled - nothing deleted." Files still present | P1 |
| DEL-04 | Recycle Bin, decline | `r`, then `n` | Cancelled, files present | P1 |
| DEL-05 | Recycle Bin, confirm | `r`, `y` on 2 files | Files gone from folder, **present in Recycle Bin**, restorable. "Freed" equals the sum of sizes | P1 |
| DEL-06 | Permanent, wrong confirmation | `p`, then `delete` / `yes` / empty | Cancelled, files present | P1 |
| DEL-07 | Permanent, correct confirmation | `p`, `DELETE` | Files gone and **not** in Recycle Bin | P1 |
| DEL-08 | Uppercase mode input | `R`, `P` | Accepted (lowercased) | P3 |
| DEL-09 | File already gone (selected, then deleted by hand before confirming) | delete file in Explorer mid-flow | "FAILED: ..." for that file only; others still deleted; "(1 failed)" shown; failed file's size not counted in Freed | P1 |
| DEL-10 | [ERR] Locked file | file held open | FAILED with reason, rest continue | P1 |
| DEL-11 | [ERR] Read-only file, permanent and Recycle Bin | `attrib +R` | Record behaviour of both modes | P2 |
| DEL-12 | [ERR] Names with spaces, `&`, `%`, `#`, unicode, `[ ]` | files named accordingly | Deleted correctly, no wrong file touched | P2 |
| DEL-13 | [ERR] Path over 260 characters | deep tree | Deleted or fails cleanly | P3 |
| DEL-14 | Duplicates: select every listed item | `all` on the DUP list | The original copy still exists for every group | P1 |
| DEL-15 | `send2trash` not installed | `pip uninstall send2trash` (reinstall afterwards) | Note printed, forced to permanent mode, still requires `DELETE` | P2 |
| DEL-16 | [ERR] Drive with no Recycle Bin (H10) | USB stick or network share | **Record:** does `r` really recycle, or delete permanently without warning? | P1 |
| DEL-17 | After deletion, re-scan | run same scan again | Deleted items no longer listed | P2 |
| DEL-18 | Mixed success and failure summary | 3 selected, 1 locked | "deleted:" x2, "FAILED:" x1, "Done. Freed X (1 failed)." | P2 |
| DEL-19 | Option 5 (run all) with deletion in the first scan | delete a file in scan 1 that would appear in scan 3 | Scan 3 no longer lists it | P2 |

### 4.8 Non-functional (NFR)

| ID | Test | Data / setup | Expected | Pri |
|----|------|--------------|----------|-----|
| NFR-01 | Scan an empty folder with every option | empty folder | "Nothing found." each, no crash | P3 |
| NFR-02 | Duplicate scan on 10,000 small files | `C:\PCC_QA\perf` | Completes, reasonable time. Record it | P3 |
| NFR-03 | Duplicate scan speed vs number of same-size files | 1,000 files all one size vs 1,000 unique sizes | Record the difference. Supports the size-grouping design | P3 |
| NFR-04 | Whole-home scan (option 5) on the real profile | `C:\Users\<username>`, **do not delete anything** | No crash; time recorded | P2 |
| NFR-05 | Files changing while scanning | write to the folder during a scan | No crash | P3 |

## 4b. Automation

Most cases above are automated with pytest in `tests/` (case IDs appear in the test names, so `pytest -k DUP_03` runs one case).

```
pip install -r requirements-dev.txt
python -m pytest                    # everything except real-size files
python -m pytest -m slow            # real 100 MB boundary test
python -m pytest -m "not windows"   # skip locked-file / junction / Recycle Bin tests
```

| Layer | What it does | Files |
|-------|--------------|-------|
| Unit | Calls scanner functions directly on generated data in `C:\PCC_QA\pytest\<test name>\` | `test_scan_*.py`, `test_parse_selection.py` |
| Flow | Scripts the user's typing into `input()`, replaces `send2trash` with a fake so nothing is recycled | `test_deletion.py`, `test_navigation_and_safety.py` |
| Environment | Points `TEMP`, `LOCALAPPDATA`, `USERPROFILE` at a fake profile, so the real temp folders are never scanned or touched | `test_scan_junk.py` |
| Real Windows | Locked files (`CreateFileW` with no sharing), `mklink /J` junctions, `icacls` deny, the real Recycle Bin | tests marked `windows` |
| End-to-end | Runs `pc_cleaner.py` as a subprocess and types into stdin | `test_e2e_cli.py` |
| Oracle | Compares the size-grouped scanner against hash-everything brute force on 5 seeded random trees | `test_DUP_18_*` |

**Design choice:** the `small_mb` fixture shrinks the app's `MB` constant to 1 KiB, so every threshold (100 / 10 / 1 "MB") is exercised at its exact boundary with tiny files. One `slow` test repeats the 100 MB boundary with real sizes to prove the shrink trick did not hide anything.

**Deliberately left manual:** NAV-07, 10 (drive root, UNC), DEL-16 (USB / network drive), DUP-17 (OneDrive placeholders), JNK-12, NFR-02..05 (scale and real-profile runs).

## 5. Entry / exit criteria

- **Entry:** `C:\PCC_QA\` test data generated and verified (file counts and sizes match the data specs above); JNK-00 baseline captured.
- **Exit:** all P1 cases executed and passed, or failures logged with severity; all hypotheses H1-H10 confirmed or refuted; no data outside `C:\PCC_QA\` and the marked `pccleaner_qa` folders was modified.

## 6. Risks

- Junk tests touch real system folders. Use only the `pccleaner_qa` marker subfolders and check them after every deletion test.
- DEL-16 needs a USB drive or network share. Skip if none is available and mark "blocked".
- NFR-04 scans the real profile. Read-only, but never confirm a deletion in that run.
