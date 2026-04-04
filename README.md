# Lightroom Deduplicator

A pair of Python scripts designed to clean up your photography directories. They are specifically tailored for Adobe Lightroom workflows, aggressively recovering wasted disk space while ensuring completely safe, automated culling of both **exact duplicate clones** and **lower-quality derivatives**.

## How it Works

The pipeline is split into two scripts to ensure safety. 

### Phase 1: `strict_deduplicator.py`
Instead of naively relying on filenames or EXIF metadata, this script eliminates files only if they are **100% bit-for-bit identical**. To overcome the typical slowness of hashing gigabytes of large photos, it leverages a parallelized, multi-threaded process to fully saturate your SSD's read speeds alongside a multi-stage elimination pipeline (Size Grouping → Concurrent Partial Hashing → Concurrent Full-Hash).

### Phase 2: `derivative_deduplicator.py`
Once the exact clones are gone, this script hunts for lower-quality exported derivatives (like a `.JPG` generated from a `.CR3`) across all your folders, even if you renamed them. It does this instantly by grouping your library by embedded EXIF `DateTimeOriginal` timestamps. If it finds two photos taken at the exact same millisecond, it enforces a preservation hierarchy (`RAW` > `Lossless` > `HEIC` > `Lossy Compressed`) and deletes the lower-tier file. It intelligently preserves multiple files within the same tier to protect edited variants (e.g., Apple's `E` prefix edited photos).

## Usage

Before running, ensure you have correctly configured the `FOLDERS` array at the top of both scripts with all the absolute or `~` based directory paths you wish to traverse.

### 1. Execute the Strict Pass
First, clear out the exact clones to remove the dead weight:

```bash
uv run strict_deduplicator.py
uv run strict_deduplicator.py --delete
```
*(Review `strict.csv` before running with `--delete`)*

### 2. Execute the Derivative Pass
Second, sweep for multi-format derivatives (like orphaned JPGs):

```bash
uv run derivative_deduplicator.py
uv run derivative_deduplicator.py --delete
```
*(Review `derivatives.csv` before running with `--delete`)*

### 3. Lightroom Catalog Cleanup
Because these scripts eliminate duplicates directly from the filesystem, Lightroom will still retain ghost references to the deleted copies in its active catalog. You must scrub the catalog to align it with your filesystem:

1. Open Lightroom Classic.
2. In the top toolbar, go to **Library** → **Find All Missing Photos**
3. Select all the photos in the resulting grid view (e.g. `Cmd + A` on Mac).
4. Hit the `Delete` key (or `Right Click` → **Remove from Catalog**) to purge the ghosts.

You should perform this "Find All Missing Photos" check *before* you run the scripts. This allows you to identify and deal with any photos that were already missing from your filesystem.
