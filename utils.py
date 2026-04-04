# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "send2trash",
# ]
# ///
import atexit
import csv
import os
import sqlite3
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from pathlib import Path

# ---------------------------------------------------------------------------
# Path to your Lightroom Classic catalog (.lrcat file).
# The scripts read folder paths directly from the catalog.
# ---------------------------------------------------------------------------
CATALOG_PATH = "~/Pictures/Lightroom Catalog-v13-3.lrcat"


def get_folders_from_catalog(catalog_path: str) -> list[str]:
    """Query the Lightroom catalog for all root folder paths."""
    p = Path(catalog_path).expanduser().resolve()
    if not p.exists():
        print(f"[ERROR] Catalog not found at {p}", file=sys.stderr)
        print("        Update CATALOG_PATH in utils.py to point to your .lrcat file.", file=sys.stderr)
        sys.exit(1)
    print(f"Reading folders from catalog: {p.name}")
    conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    try:
        rows = conn.execute("SELECT absolutePath FROM AgLibraryRootFolder").fetchall()
    finally:
        conn.close()
    folders = [row[0].rstrip("/") for row in rows]
    if not folders:
        print("[ERROR] No folders found in the Lightroom catalog.", file=sys.stderr)
        sys.exit(1)
    return folders


def get_catalog_path() -> str:
    """Return catalog path from --catalog CLI arg, or fall back to CATALOG_PATH."""
    for i, arg in enumerate(sys.argv):
        if arg == "--catalog" and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return CATALOG_PATH


FOLDERS = get_folders_from_catalog(get_catalog_path())
FOLDERS.remove("/Volumes/FILES/Photos")
print(FOLDERS)

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

# Progress file for the Lightroom plugin to poll
PROGRESS_FILE = Path(__file__).parent / ".dedup_progress.txt"


def update_progress(message: str) -> None:
    """Write a status line for the Lightroom plugin's progress bar."""
    with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
        f.write(message)


def clear_progress() -> None:
    """Remove the progress file on exit."""
    try:
        PROGRESS_FILE.unlink(missing_ok=True)
    except OSError:
        pass


atexit.register(clear_progress)


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

    for fi, folder in enumerate(FOLDERS, 1):
        p = Path(folder).expanduser().resolve()
        if not p.is_dir():
            print(f"[WARN] Not a directory, skipping: {p}", file=sys.stderr)
            continue

        print(f"  --> {p}")
        update_progress(f"Scanning folder {fi}/{len(FOLDERS)}: {p.name}")
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
                        update_progress(f"Scanning folder {fi}/{len(FOLDERS)}: {p.name} — {scanned_items:,} items")
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
    # Write a short summary for the Lightroom plugin dialog
    with open(SUMMARY_FILE, 'w', encoding='utf-8') as f:
        f.write(f"{count:,} {label} flagged for deletion\n")
        f.write(f"{fmt_bytes(recoverable)} recoverable\n")
        f.write(f"Scanned {fmt_bytes(scanned)} in {elapsed:,.1f}s\n")


CATALOG_DELETE_FILE = Path(__file__).parent / "to_delete_in_catalog.txt"
IMPORT_PATHS_FILE = Path(__file__).parent / "needs_import.txt"
SUMMARY_FILE = Path(__file__).parent / ".dedup_summary.txt"


def get_catalog_paths() -> set[str]:
    """Return the set of all file paths tracked by the Lightroom catalog."""
    p = Path(get_catalog_path()).expanduser().resolve()
    if not p.exists():
        return set()
    conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    try:
        rows = conn.execute("""
            SELECT rf.absolutePath || f.pathFromRoot || lf.baseName || '.' || lf.extension
            FROM AgLibraryFile lf
            JOIN AgLibraryFolder f ON lf.folder = f.id_local
            JOIN AgLibraryRootFolder rf ON f.rootFolder = rf.id_local
        """).fetchall()
    finally:
        conn.close()
    return {row[0] for row in rows}


def write_import_paths(paths: list[str]) -> None:
    """Write paths that need to be imported into Lightroom."""
    if not paths:
        return
    with open(IMPORT_PATHS_FILE, 'a', encoding='utf-8') as f:
        f.write('\n'.join(paths) + '\n')
    print(f"\n{len(paths):,} keeper(s) not in the Lightroom catalog — listed in {IMPORT_PATHS_FILE}")
    print("Import these into Lightroom so they aren't missing from your library.")


DISK_DELETE_FILE = Path(__file__).parent / "to_delete_from_disk.txt"


def write_paths_for_lightroom(to_delete: list, catalog_paths: set[str]) -> None:
    """Write paths for the Lightroom plugin.
    - In-catalog files  → deleted_paths.txt  (plugin flags as Rejected)
    - Not-in-catalog    → delete_from_disk.txt (plugin deletes from disk directly)
    """
    in_catalog = [r for r in to_delete if str(r['path']) in catalog_paths]
    not_in_catalog = [r for r in to_delete if str(r['path']) not in catalog_paths]

    if in_catalog:
        paths = [str(r['path']) for r in in_catalog]
        with open(CATALOG_DELETE_FILE, 'a', encoding='utf-8') as f:
            f.write('\n'.join(paths) + '\n')
        print(f"\n{len(paths):,} in-catalog path(s) appended to {CATALOG_DELETE_FILE}")

    if not_in_catalog:
        paths = [str(r['path']) for r in not_in_catalog]
        with open(DISK_DELETE_FILE, 'a', encoding='utf-8') as f:
            f.write('\n'.join(paths) + '\n')
        print(f"{len(paths):,} not-in-catalog path(s) appended to {DISK_DELETE_FILE}")

    print("In Lightroom: Library → Plug-in Extras → Remove Deleted Duplicates from Catalog")


def delete_from_disk_file() -> None:
    """Move all files listed in to_delete_from_disk.txt to Trash, then clear it."""
    from send2trash import send2trash

    if not DISK_DELETE_FILE.exists():
        print("Nothing to delete.")
        return

    paths = [
        line.strip() for line in DISK_DELETE_FILE.read_text(encoding='utf-8').splitlines()
        if line.strip()
    ]
    if not paths:
        print("Nothing to delete.")
        return

    trashed = failed = 0
    for p in paths:
        try:
            send2trash(p)
            trashed += 1
        except Exception as e:
            print(f"  ERR {p}  ({e})", file=sys.stderr)
            failed += 1

    DISK_DELETE_FILE.write_text('', encoding='utf-8')
    print(f"Moved {trashed:,} to Trash  |  Failed {failed:,}")


TO_IMPORT_DIR = Path(__file__).parent / "to_import"


def move_needs_import() -> None:
    """Move files listed in needs_import.txt into the to_import/ folder."""
    if not IMPORT_PATHS_FILE.exists():
        return

    paths = [
        line.strip() for line in IMPORT_PATHS_FILE.read_text(encoding='utf-8').splitlines()
        if line.strip()
    ]
    if not paths:
        return

    TO_IMPORT_DIR.mkdir(exist_ok=True)
    moved = failed = 0
    for p in paths:
        src = Path(p)
        dst = TO_IMPORT_DIR / src.name
        # Avoid name collisions
        if dst.exists():
            stem, suffix = dst.stem, dst.suffix
            n = 1
            while dst.exists():
                dst = TO_IMPORT_DIR / f"{stem}-{n}{suffix}"
                n += 1
        try:
            src.rename(dst)
            moved += 1
        except OSError as e:
            print(f"  ERR {p}  ({e})", file=sys.stderr)
            failed += 1

    IMPORT_PATHS_FILE.write_text('', encoding='utf-8')
    print(f"Moved {moved:,} file(s) to {TO_IMPORT_DIR}  |  Failed {failed:,}")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--delete-from-disk', action='store_true')
    parser.add_argument('--move-needs-import', action='store_true')
    args = parser.parse_args()

    if args.delete_from_disk:
        delete_from_disk_file()
    if args.move_needs_import:
        move_needs_import()
