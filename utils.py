import csv
import os
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
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

# Number of concurrent network requests to make when scanning folders.
# If your SMB server can handle it, crank this to 64 or 128 for blistering scan speeds.
SMB_WORKERS = 64


def collect_files() -> list:
    files = []
    print("Scanning directories for photos (multithreaded)...")
    
    # Worker function to scan a single directory using the fast os.scandir
    def scan_dir(target_dir: str):
        local_files = []
        local_dirs = []
        items_count = 0
        try:
            with os.scandir(target_dir) as it:
                for entry in it:
                    items_count += 1
                    if entry.is_dir(follow_symlinks=False):
                        # Skip hidden directories like .Trash to save time
                        if not entry.name.startswith('.'):
                            local_dirs.append(entry.path)
                    elif entry.is_file(follow_symlinks=False):
                        ext = os.path.splitext(entry.name)[1].lower()
                        if ext in PHOTO_EXTENSIONS:
                            local_files.append(Path(entry.path))
        except OSError:
            pass  # e.g., permission denied
        return local_files, local_dirs, items_count

    for folder in FOLDERS:
        p = Path(folder).expanduser().resolve()
        if not p.is_dir():
            print(f"[WARN] Not a directory, skipping: {p}", file=sys.stderr)
            continue
            
        print(f"  --> {p}")
        folder_files = []
        scanned_items = 0
        last_print_count = 0
        
        # Spawn concurrent workers to blast through network latency sequentially
        with ThreadPoolExecutor(max_workers=SMB_WORKERS) as executor:
            futures = {executor.submit(scan_dir, str(p))}
            
            while futures:
                # Wait for at least one directory to finish scanning
                done, futures = wait(futures, return_when=FIRST_COMPLETED)
                
                for fut in done:
                    loc_files, loc_dirs, count = fut.result()
                    scanned_items += count
                    folder_files.extend(loc_files)
                    
                    # Submit all newly discovered subdirectories as independent async jobs
                    for d in loc_dirs:
                        futures.add(executor.submit(scan_dir, d))
                        
                    # Update progress occasionally to avoid terminal stutter
                    if scanned_items - last_print_count >= 100:
                        print(f"      Scanned {scanned_items:,} items...", end="\r", flush=True)
                        last_print_count = scanned_items
                
        # Clear the terminal line and report final count for this folder
        print(f"      Completed: {scanned_items:,} items scanned.                           ")
        files.extend(folder_files)
        
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
