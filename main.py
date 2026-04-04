# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "tqdm",
# ]
# ///
"""
lr_dedup.py  —  Lightroom Deduplicator
----------------------------------------------------------------------
Edit FOLDERS below, then run with:

    uv run lr_dedup.py              # dry run — reports what would be deleted
    uv run lr_dedup.py --delete     # actually deletes after confirmation

After deletion, in Lightroom:
  Library menu → Find All Missing Photos → select all → Remove from Catalog
"""

# ---------------------------------------------------------------------------
# CONFIG — edit these before running
# ---------------------------------------------------------------------------

FOLDERS = [
    "~/Pictures/2026",
    "~/Pictures/2",
    "~/Pictures/3",
    "~/Pictures/1904",
    "~/Pictures/2023",
    "~/Pictures/2025",
    "~/FILES/Photos"
]

# Only match numeric suffixes up to this value as "duplicate imports".
# Keeps 99 so IMG_1234-2.JPG is caught but holiday-2024.jpg is not.
MAX_SUFFIX = 99

# Where to write the audit CSV.
CSV_PATH = "lr_dedup.csv"

# ---------------------------------------------------------------------------
# (no edits needed below this line)
# ---------------------------------------------------------------------------

import argparse
import csv
import hashlib
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from tqdm import tqdm


PHOTO_EXTENSIONS = {
    '.jpg', '.jpeg',
    '.heic', '.heif',
    '.cr3', '.cr2',
    '.nef', '.arw', '.orf', '.rw2', '.raf', '.dng',
    '.png', '.tif', '.tiff',
    '.mov', '.mp4',
}

_DUP_RE = re.compile(r'^(?P<stem>.+)-(?P<n>\d+)(?P<ext>\.[^.]+)$', re.IGNORECASE)


def is_dup_pattern(name: str) -> bool:
    m = _DUP_RE.match(name)
    return bool(m) and int(m.group('n')) <= MAX_SUFFIX


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


def fmt_bytes(n: float) -> str:
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def fmt_time(t: float) -> str:
    return datetime.fromtimestamp(t).strftime('%Y-%m-%d %H:%M:%S')


def collect_files() -> list:
    files = []
    for folder in FOLDERS:
        p = Path(folder).expanduser().resolve()
        if not p.is_dir():
            print(f"[WARN] Not a directory, skipping: {p}", file=sys.stderr)
            continue
        for f in sorted(p.rglob('*')):
            if f.is_file() and f.suffix.lower() in PHOTO_EXTENSIONS:
                files.append(f)
    return files


def hash_all(files: list) -> list:
    total = len(files)
    print(f"\nProcessing {total} file(s) for potential duplicates ...")
    
    # Step 1: Group by file size
    size_groups = defaultdict(list)
    for f in tqdm(files, desc="Grouping by size", unit="file", dynamic_ncols=True):
        try:
            size_groups[f.stat().st_size].append(f)
        except OSError as e:
            tqdm.write(f"[WARN] Skipping {f}: {e}", file=sys.stderr)

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
    print(f"\nFound {len(files_to_phash)} files with duplicate sizes. Checking headers (1MB)...")
    phash_groups = defaultdict(list)
    for f in tqdm(files_to_phash, desc="Partial hashing", unit="file", dynamic_ncols=True):
        try:
            size = f.stat().st_size
            phash_groups[(size, sha256_partial(f))].append(f)
        except OSError as e:
            tqdm.write(f"[WARN] Skipping {f}: {e}", file=sys.stderr)

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
        print(f"\nFound {len(files_to_full_hash)} strictly similar files. Performing full hash...")
        for f in tqdm(files_to_full_hash, desc="Rigorous full-hash", unit="file", dynamic_ncols=True):
            try:
                records.append({
                    'path': f,
                    'sha256': sha256_full(f),
                    'birthtime': birthtime(f),
                    'size': f.stat().st_size,
                })
            except OSError as e:
                tqdm.write(f"[WARN] Skipping {f}: {e}", file=sys.stderr)
    else:
        print("\nAll remaining files were unique after header check!")
        
    print()
    return records


def select_keepers(records: list) -> list:
    """
    Within each hash group, pick the keeper:
      1. Prefer non-dup-pattern names over dup-pattern names.
      2. Tiebreak: oldest birthtime (first imported).
    """
    for r in records:
        r['is_dup_pattern'] = is_dup_pattern(r['path'].name)

    by_hash = defaultdict(list)
    for r in records:
        by_hash[r['sha256']].append(r)

    for group in by_hash.values():
        if len(group) == 1:
            group[0].update(to_delete=False, keeper_path=group[0]['path'])
            continue
        ranked = sorted(group, key=lambda r: (r['is_dup_pattern'], r['birthtime']))
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


def print_report(records: list) -> list:
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
    print(f"{'='*70}")
    print(f"  {len(to_delete)} file(s) flagged for deletion  ({fmt_bytes(total_size)} recoverable)")
    print(f"{'='*70}")

    return to_delete


def delete_files(to_delete: list) -> None:
    print(f"{'!'*70}")
    print(f"  About to permanently delete {len(to_delete)} file(s).")
    print(f"  Review the CSV and the report above before continuing.")
    print(f"{'!'*70}")
    if input("\n  Type  YES  to proceed: ").strip() != 'YES':
        print("Aborted. Nothing deleted.")
        sys.exit(0)

    deleted = failed = 0
    for r in to_delete:
        try:
            r['path'].unlink()
            print(f"  OK  {r['path']}")
            deleted += 1
        except OSError as e:
            print(f"  ERR {r['path']}  ({e})", file=sys.stderr)
            failed += 1

    print(f"\nDeleted {deleted}  |  Failed {failed}")
    if deleted:
        print("\nIn Lightroom: Library → Find All Missing Photos → select all → Remove from Catalog")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--delete', action='store_true', help='Actually delete (default: dry run)')
    args = parser.parse_args()

    csv_path = (Path(__file__).parent / CSV_PATH).resolve()

    files = collect_files()
    if not files:
        print("No photo files found. Check FOLDERS in the script.")
        sys.exit(0)
    print(f"Found {len(files)} photo file(s) across {len(FOLDERS)} folder(s).")

    records = hash_all(files)
    records = select_keepers(records)
    write_csv(records, csv_path)
    to_delete = print_report(records)

    if not to_delete:
        sys.exit(0)

    if not args.delete:
        print("[DRY RUN] Re-run with --delete to remove the files listed above.")
        sys.exit(0)

    delete_files(to_delete)


if __name__ == '__main__':
    main()