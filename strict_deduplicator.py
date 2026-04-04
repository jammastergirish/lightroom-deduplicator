# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "tqdm",
#     "send2trash",
# ]
# ///
"""
strict_deduplicator.py  —  Lightroom Strict Bit-for-Bit Deduplicator
----------------------------------------------------------------------
Typically invoked by the Lightroom plugin. Can also be run directly:

    uv run strict_deduplicator.py           # dry run — reports what would be deleted
    uv run strict_deduplicator.py --delete  # write paths for the Lightroom plugin to act on
"""

# ---------------------------------------------------------------------------
# CONFIG — edit these before running
# ---------------------------------------------------------------------------

# Only match numeric suffixes up to this value as "duplicate imports".
# Keeps 10 so IMG_1234-2.JPG is caught but holiday-2024.jpg is not.
MAX_SUFFIX = 10

# Where to write the audit CSV.
CSV_PATH = "strict.csv"

# ---------------------------------------------------------------------------
# (no edits needed below this line)
# ---------------------------------------------------------------------------

import argparse
import csv
import hashlib
import re
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from tqdm import tqdm

from utils import FOLDERS, collect_files, fmt_bytes, print_summary, write_paths_for_lightroom, update_progress, SMB_WORKERS, get_catalog_paths, write_import_paths

_DUP_RE = re.compile(r'^(?P<stem>.+)[- ](?P<n>\d+)(?P<ext>\.[^.]+)$', re.IGNORECASE)
_DESCRIPTIVE_RE = re.compile(r'^(Screenshot|Screen Recording|Screencast)', re.IGNORECASE)


def is_dup_pattern(name: str) -> bool:
    m = _DUP_RE.match(name)
    return bool(m) and int(m.group('n')) <= MAX_SUFFIX


def is_descriptive_name(name: str) -> bool:
    """Return True for human-readable names like 'Screenshot 2024-...'."""
    return bool(_DESCRIPTIVE_RE.match(name))


def birthtime(path: Path) -> float:
    st = path.stat()
    return getattr(st, 'st_birthtime', st.st_mtime)


def sha256_full(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while buf := f.read(chunk):
            h.update(buf)
    return h.hexdigest()


def sha256_partial(path: Path, chunk: int = 1 << 20) -> str:
    """Hash only the first 1MB to quickly rule out false positives."""
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        buf = f.read(chunk)
        h.update(buf)
    return h.hexdigest()


def fmt_time(t: float) -> str:
    return datetime.fromtimestamp(t).strftime('%Y-%m-%d %H:%M:%S')


def hash_all(files: list) -> list:
    total = len(files)
    print(f"\nProcessing {total:,} file(s) for potential duplicates ...")
    update_progress(f"Step 1/3: Grouping {total:,} files by size")

    # Step 1: Group by file size
    size_groups = defaultdict(list)
    
    def _get_size(f: Path):
        try:
            return f, f.stat().st_size, None
        except OSError as e:
            return f, None, e

    with ThreadPoolExecutor(max_workers=SMB_WORKERS) as executor:
        futures = {executor.submit(_get_size, f): f for f in files}
        for future in tqdm(as_completed(futures), total=len(futures), desc="Grouping by size", unit="file", dynamic_ncols=True):
            f, size, err = future.result()
            if err:
                tqdm.write(f"[WARN] Skipping {f}: {err}", file=sys.stderr)
            else:
                size_groups[size].append(f)

    records = []
    files_to_phash = []
    
    for size, group in size_groups.items():
        if len(group) > 1:
            files_to_phash.extend(group)
        else:
            f = group[0]
            try:
                records.append({
                    'path': f,
                    'sha256': f"<unique:{f}>",
                    'birthtime': birthtime(f),
                    'size': size,
                })
            except OSError as e:
                tqdm.write(f"[WARN] Skipping {f}: {e}", file=sys.stderr)

    if not files_to_phash:
        print("\nAll files have unique sizes. No hashing needed!")
        print()
        return records

    # Step 2: Partial hash (first 1MB) for files sharing a size
    print(f"\nFound {len(files_to_phash):,} files with duplicate sizes. Checking headers (1MB)...")
    update_progress(f"Step 2/3: Partial-hashing {len(files_to_phash):,} size-matched files")
    phash_groups = defaultdict(list)
    
    def _do_phash(f):
        try:
            return f, f.stat().st_size, sha256_partial(f), None
        except OSError as e:
            return f, None, None, e

    with ThreadPoolExecutor(max_workers=SMB_WORKERS) as executor:
        futures = {executor.submit(_do_phash, f): f for f in files_to_phash}
        for future in tqdm(as_completed(futures), total=len(futures), desc="Partial hashing", unit="file", dynamic_ncols=True):
            f, size, phash, err = future.result()
            if err:
                tqdm.write(f"[WARN] Skipping {f}: {err}", file=sys.stderr)
            else:
                phash_groups[(size, phash)].append(f)

    files_to_full_hash = []
    for (size, phash), group in phash_groups.items():
        if len(group) > 1:
            files_to_full_hash.extend(group)
        else:
            f = group[0]
            try:
                records.append({
                    'path': f,
                    'sha256': f"<unique:{f}>",
                    'birthtime': birthtime(f),
                    'size': size,
                })
            except OSError as e:
                tqdm.write(f"[WARN] Skipping {f}: {e}", file=sys.stderr)

    # Step 3: Full hash only for files with identical sizes AND headers
    if files_to_full_hash:
        print(f"\nFound {len(files_to_full_hash):,} strictly similar files. Performing full hash...")
        update_progress(f"Step 3/3: Full-hashing {len(files_to_full_hash):,} header-matched files")
        
        def _do_fhash(f):
            try:
                return f, f.stat().st_size, sha256_full(f), birthtime(f), None
            except OSError as e:
                return f, None, None, None, e

        with ThreadPoolExecutor(max_workers=SMB_WORKERS) as executor:
            futures = {executor.submit(_do_fhash, f): f for f in files_to_full_hash}
            for future in tqdm(as_completed(futures), total=len(futures), desc="Rigorous full-hash", unit="file", dynamic_ncols=True):
                f, size, fhash, btime, err = future.result()
                if err:
                    tqdm.write(f"[WARN] Skipping {f}: {err}", file=sys.stderr)
                else:
                    records.append({
                        'path': f,
                        'sha256': fhash,
                        'birthtime': btime,
                        'size': size,
                    })
    else:
        print("\nAll remaining files were unique after header check!")
        
    print()
    return records


def select_keepers(records: list, catalog_paths: set[str]) -> list:
    """
    Within each hash group, pick the keeper:
      1. Prefer files that are in the Lightroom catalog.
      2. Prefer descriptive names (Screenshot, etc.) over generic ones.
      3. Prefer non-dup-pattern names over dup-pattern names.
      4. Tiebreak: oldest birthtime (first imported).
    """
    for r in records:
        r['is_dup_pattern'] = is_dup_pattern(r['path'].name)
        r['in_catalog'] = str(r['path']) in catalog_paths

    by_hash = defaultdict(list)
    for r in records:
        by_hash[r['sha256']].append(r)

    for group in by_hash.values():
        if len(group) == 1:
            group[0].update(to_delete=False, keeper_path=group[0]['path'])
            continue
        ranked = sorted(group, key=lambda r: (
            not r['in_catalog'],
            r['is_dup_pattern'],
            not is_descriptive_name(r['path'].name),
            r['birthtime'],
        ))
        keeper = ranked[0]
        for r in group:
            r['to_delete'] = (r is not keeper)
            r['keeper_path'] = keeper['path']

    return records


def write_csv(records: list, csv_path: Path) -> None:
    with open(csv_path, 'w', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh)
        w.writerow(['path', 'sha256', 'birthtime_iso', 'size_bytes', 'is_dup_pattern', 'to_delete', 'keeper_path'])
        for r in records:
            w.writerow([
                str(r['path']), r['sha256'], fmt_time(r['birthtime']),
                r.get('size', ''), r['is_dup_pattern'],
                r.get('to_delete', False), str(r.get('keeper_path', '')),
            ])
    print(f"CSV written → {csv_path}\n")


def print_report(records: list, scanned_size: int, elapsed: float) -> list:
    to_delete = [r for r in records if r.get('to_delete')]
    if not to_delete:
        print("No duplicates found. Library is clean!")
        return to_delete

    by_hash = defaultdict(list)
    for r in to_delete:
        by_hash[r['sha256']].append(r)

    running = 0
    for dupes in sorted(by_hash.values(), key=lambda g: str(g[0]['keeper_path'])):
        group_size = sum(d['size'] for d in dupes)
        running += group_size
        print(f"  KEEP   {dupes[0]['keeper_path']}")
        for d in dupes:
            tag = " [dup-pattern]" if d['is_dup_pattern'] else ""
            print(f"  DELETE {d['path']}  ({fmt_bytes(d['size'])}  imported {fmt_time(d['birthtime'])}){tag}")
        print(f"  → saves {fmt_bytes(group_size)}  |  running total: {fmt_bytes(running)}\n")

    total_size = sum(r['size'] for r in to_delete)
    print_summary(len(to_delete), "file(s)", total_size, scanned_size, elapsed)

    return to_delete


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--catalog', help=argparse.SUPPRESS)  # handled by utils.py
    parser.add_argument('--delete', action='store_true', help='Write paths for the Lightroom plugin to act on')
    args = parser.parse_args()

    t0 = time.time()
    csv_path = (Path(__file__).parent / CSV_PATH).resolve()

    files = collect_files()
    if not files:
        print("No photo files found. Check FOLDERS in the script.")
        sys.exit(0)
    print(f"Found {len(files):,} photo file(s) across {len(FOLDERS):,} folder(s).")

    print("Loading Lightroom catalog for keeper selection...")
    catalog_paths = get_catalog_paths()
    print(f"  {len(catalog_paths):,} file(s) tracked in catalog.")

    records = hash_all(files)
    records = select_keepers(records, catalog_paths)
    write_csv(records, csv_path)
    scanned_size = sum(r.get('size', 0) for r in records)
    elapsed = time.time() - t0
    to_delete = print_report(records, scanned_size, elapsed)

    if not to_delete:
        sys.exit(0)

    # Keepers that aren't in the catalog need to be imported
    keeper_paths = {str(r['keeper_path']) for r in to_delete}
    needs_import = sorted(p for p in keeper_paths if p not in catalog_paths)
    if needs_import:
        write_import_paths(needs_import)

    if args.delete:
        write_paths_for_lightroom(to_delete, catalog_paths)
    else:
        print("[DRY RUN] Re-run with --delete to act on the files listed above.")
        sys.exit(0)


if __name__ == '__main__':
    main()