import csv
import sys
from collections import defaultdict
from pathlib import Path

FOLDERS = [
    "~/Pictures/2026",
    "~/Pictures/2",
    "~/Pictures/3",
    "~/Pictures/1904",
    "~/Pictures/2023",
    "~/Pictures/2025",
    "/Volumes/FILES/Photos"
]

PHOTO_EXTENSIONS = {
    '.jpg', '.jpeg',
    '.heic', '.heif',
    '.cr3', '.cr2',
    '.nef', '.arw', '.orf', '.rw2', '.raf', '.dng',
    '.png', '.tif', '.tiff',
    '.mov', '.mp4',
}


def collect_files() -> list:
    files = []
    print("Scanning directories for photos...")
    for folder in FOLDERS:
        p = Path(folder).expanduser().resolve()
        if not p.is_dir():
            print(f"[WARN] Not a directory, skipping: {p}", file=sys.stderr)
            continue
            
        print(f"  --> {p}")
        scanned_items = 0
        
        # rglob yields continuously. By removing sorted(), we unblock the scan!
        for f in p.rglob('*'):
            scanned_items += 1
            if scanned_items % 100 == 0:
                # Carriage return (\r) overwrites the same line for a clean animation
                print(f"      Scanned {scanned_items:,} items...", end="\r", flush=True)
                
            if f.is_file() and f.suffix.lower() in PHOTO_EXTENSIONS:
                files.append(f)
                
        # Clear the terminal line and report final count for this folder
        print(f"      Completed: {scanned_items:,} items scanned.                           ")
        
    return files


def fmt_bytes(n: float) -> str:
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def print_summary(count: int, label: str, recoverable: int, scanned: int, elapsed: float) -> None:
    print(f"{'='*70}")
    print(f"  {count:,} {label} flagged for deletion  ({fmt_bytes(recoverable)} recoverable)")
    print(f"  Scanned {fmt_bytes(scanned)} in {elapsed:,.1f} seconds")
    print(f"{'='*70}")


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
        print("\nIn Lightroom: Library -> Find All Missing Photos -> select all -> Remove from Catalog")
