# Lightroom Deduplicator

A Python script designed to find and delete bit-for-bit exact duplicate photos and videos across your directories. It is specifically tailored to complement Adobe Lightroom workflows, aggressively recovering wasted disk space while ensuring completely safe, automated culling of duplicate imports.

## How it Works

Instead of naively relying on filenames or EXIF metadata, this script guarantees safety by verifying exact file matches with hashes. To overcome the slowness of hashing large files, it utilizes a multi-stage pipeline:

1. **Size Grouping:** It rapidly scans all target files and groups them by exact byte-ratio. Any file with a completely unique size is instantly bypassed (as it cannot therefore be an exact duplicate).
2. **Partial Hashing:** For files that happen to share an exact size, it generates a quick SHA-256 hash of *just* the first 1MB.
3. **Full-Hash:** Only files that perfectly match both their byte size *and* their first-megabyte signature undergo a rigorous full-file SHA-256 hash check.
4. **Keeper Selection:** When a true bit-for-bit duplicate cluster is confirmed, the script protects the oldest file (based on birthtime). It also inherently prefers clean, base filenames, actively targeting Lightroom-generated duplicate patterns like `IMG_1234-2.JPG` or `FILE_NAME 1.MOV`.

## Usage

Before running, ensure you have correctly configured the `FOLDERS` array at the top of `main.py` with all the absolute or `~` based directory paths you wish to traverse.

### 1. Execute a Dry Run (Baseline)
This will scan your library, highlight duplicates, show exactly what would be removed, estimate total disk space savings, and output a detailed audit map (`lr_dedup.csv`) without deleting a single thing.

```bash
uv run main.py
```

### 2. Confirm and Delete
Once you've reviewed the dry-run output and are ready to reclaim your disk space, invoke the script with the `--delete` flag.

```bash
uv run main.py --delete
```
*(The script will present a final confirmation prompt demanding you type `YES` before it permanently unlinks any files).*

### 3. Lightroom Catalog Cleanup
Because this script eliminates duplicates directly from the filesystem, Lightroom will still retain ghost references to the deleted copies in its active catalog. You must scrub the catalog to align it with your filesystem:

1. Open Lightroom Classic.
2. In the top toolbar, go to **Library** → **Find All Missing Photos**
3. Select all the photos in the resulting grid view (e.g. `Cmd + A` on Mac).
4. Hit the `Delete` key (or `Right Click` → **Remove from Catalog**) to purge the ghosts.
