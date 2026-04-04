# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "tqdm",
#     "exifread",
# ]
# ///
import argparse
import csv
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import exifread
from tqdm import tqdm

from utils import FOLDERS, collect_files, fmt_bytes, delete_files

CSV_PATH = "derivatives.csv"

# Pre-computation mapping for Tiers. Lower is better.
def get_tier(suffix: str) -> int:
    s = suffix.lower()
    if s in {'.cr3', '.cr2', '.nef', '.arw', '.orf', '.rw2', '.raf', '.dng'}:
        return 1
    if s in {'.tif', '.tiff', '.png'}:
        return 2
    if s in {'.heic', '.heif'}:
        return 3
    if s in {'.jpg', '.jpeg'}:
        return 4
    if s in {'.mov', '.mp4'}:
        return 1  # Original video formats treated as high tier
    return 99


def extract_exif(path: Path):
    try:
        with open(path, 'rb') as f:
            tags = exifread.process_file(f, details=False, stop_tag='EXIF DateTimeOriginal')
            # Look for timestamp
            dt = tags.get('EXIF DateTimeOriginal') or tags.get('Image DateTime')
            
            # Look for sub-second precise time to limit false positives
            subsec = tags.get('EXIF SubSecTimeOriginal', '')
            
            # Camera model
            model = tags.get('Image Model', 'Unknown')
            
            if dt:
                # Add subseconds to the string if they exist to separate bursts
                timestamp = f"{dt.values}.{subsec.values if subsec else ''}"
                return timestamp, str(model).strip()
            
            # If exifread finds no EXIF (e.g. video files / heavily edited JPGs)
            return None, None
    except Exception:
        return None, None

def process_file_metadata(f: Path):
    try:
        size = f.stat().st_size
    except OSError:
        return None
        
    dt, model = extract_exif(f)
    return f, size, dt, model


def map_derivatives(files: list):
    print(f"\nExtracting EXIF data from {len(files)} files...")
    
    # Store EXIF groups
    exif_map = defaultdict(list)
    no_exif_count = 0
    
    with ThreadPoolExecutor() as executor:
        futures = {executor.submit(process_file_metadata, f): f for f in files}
        for future in tqdm(as_completed(futures), total=len(futures), desc="Reading EXIF", unit="file", dynamic_ncols=True):
            res = future.result()
            if not res:
                continue
                
            f, size, dt, model = res
            
            if dt:
                # Group strictly by Time AND Model to prevent coincidences
                exif_map[(dt, model)].append({
                    'path': f,
                    'size': size,
                    'tier': get_tier(f.suffix)
                })
            else:
                no_exif_count += 1

    print(f"\nGrouped {len(files) - no_exif_count} files via EXIF. Skipped {no_exif_count} without timestamps.")
    
    records = []
    
    # Analyze the groups
    for (dt, model), group in exif_map.items():
        if len(group) < 2:
            continue
            
        # Sort group by: 1. Tier (lowest number is best), 2. File size (largest is best) 
        group.sort(key=lambda r: (r['tier'], -r['size']))
        
        keeper = group[0]
        best_tier = keeper['tier']
        
        for r in group:
            # Protect all files that are in the highest discovered tier.
            # This ensures we don't accidentally delete "Original" vs "Edited" JPGs that share an EXIF time.
            if r['tier'] == best_tier:
                r['to_delete'] = False
                r['keeper_path'] = keeper['path']
            else:
                # Only cull if it's explicitly a lower-quality derivative format
                r['to_delete'] = True
                r['keeper_path'] = keeper['path']
                
            r['exif_time'] = dt
            r['model'] = model
            records.append(r)
            
    return records


def write_csv(records: list, csv_path: Path) -> None:
    with open(csv_path, 'w', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh)
        w.writerow(['path', 'tier', 'size_bytes', 'exif_timestamp', 'camera_model', 'to_delete', 'keeper_path'])
        for r in records:
            w.writerow([
                str(r['path']), r['tier'], r['size'], r['exif_time'], r['model'],
                r['to_delete'], str(r['keeper_path'])
            ])
    print(f"CSV written → {csv_path}\n")


def print_report(records: list) -> list:
    to_delete = [r for r in records if r.get('to_delete')]
    if not to_delete:
        print("No derivatives found. Library looks tight!")
        return to_delete

    # Group the deletions by their keeper for pretty printing
    by_keeper = defaultdict(list)
    for r in to_delete:
        by_keeper[r['keeper_path']].append(r)

    running = 0
    for keeper_path, dupes in sorted(by_keeper.items(), key=lambda i: str(i[0])):
        group_size = sum(d['size'] for d in dupes)
        running += group_size
        print(f"  KEEP   {keeper_path}")
        for d in dupes:
            print(f"  DELETE {d['path']}  ({fmt_bytes(d['size'])})")
        print(f"  → saves {fmt_bytes(group_size)}  |  running total: {fmt_bytes(running)}\n")

    total_size = sum(r['size'] for r in to_delete)
    print(f"{'='*70}")
    print(f"  {len(to_delete)} derivative(s) flagged for deletion  ({fmt_bytes(total_size)} recoverable)")
    print(f"{'='*70}")

    return to_delete


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

    records = map_derivatives(files)
    
    if not records:
        print("\nNo overlapping EXIF sequences found.")
        sys.exit(0)
        
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
