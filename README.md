# Lightroom Deduplicator

A pair of **blazing-fast, multi-threaded** Python scripts engineered to clean up your photography directories. Specifically tailored for Adobe Lightroom workflows, they leverage parallel crawlers and asynchronous thread-pools to blast through local and remote drives (SMB/NAS), recovering wasted disk space while ensuring completely safe, automated culling of both **exact duplicate clones** and **lower-quality derivatives**.

## How it Works

The pipeline is split into two scripts to ensure safety. Both scripts query your Lightroom catalog (read-only, via SQLite `?mode=ro`) to determine which files are tracked. This is used in two ways:

1. **Smarter keeper selection** — when choosing which copy to keep from a duplicate group, the scripts prefer files that are already in the Lightroom catalog. This prevents the scenario where the "keeper" is a file Lightroom doesn't know about, leaving a gap in your library.
2. **`to_import/` folder** — if a keeper isn't in the catalog (because *none* of the copies in that group were imported), it is moved to the `to_import/` folder next to the plugin so you can easily import it into Lightroom after cleanup.

The catalog is never modified by the Python scripts. Only the Lightroom plugin writes to the catalog (by flagging photos as Rejected).

### Safety guarantees

- **No unique file is ever deleted.** The strict deduplicator only flags files that have a bit-for-bit identical copy elsewhere. The derivative deduplicator only flags files that have a higher-quality version with the same EXIF timestamp and camera model.
- **The catalog is read-only.** Python reads the catalog via SQLite `?mode=ro` to inform keeper selection. It cannot modify the catalog file.
- **Nothing happens without confirmation.** The plugin always shows a summary and asks you to confirm before any files are flagged or deleted.
- **A CSV is always written first.** Review `strict.csv` or `derivatives.csv` before confirming to see exactly what will be kept and what will be deleted.

### Phase 0: Parallel Network Crawling
To prevent the script from silently hanging when exploring high-latency Network Attached Storage (like an SMB or NAS drive), both scripts share a specialized file collector. It unleashes dozens of concurrent threads to explore subdirectories in parallel, aggressively bypassing network lockstep latency. It also provides a live-streaming terminal readout so you aren't left waiting blindly. *(Note: The thread count is configurable via `SMB_WORKERS` in `utils.py`)*

### Phase 1: `strict_deduplicator.py`
Instead of naively relying on filenames or EXIF metadata, this script eliminates files only if they are **100% bit-for-bit identical**. To overcome the typical slowness of hashing gigabytes of large photos, it leverages a parallelized, multi-threaded process to fully saturate your disks' read speeds alongside a multi-stage elimination pipeline (Size Grouping → Concurrent Partial Hashing → Concurrent Full-Hash).

### Phase 2: `derivative_deduplicator.py`
Once the exact clones are gone, this script hunts for lower-quality exported derivatives (like a `.JPG` generated from a `.CR3`) across all your folders, even if you renamed them. It does this instantly by grouping your library by embedded EXIF `DateTimeOriginal` timestamps. If it finds two photos taken at the exact same millisecond, it enforces a preservation hierarchy (`RAW` > `Lossless` > `HEIC` > `Lossy Compressed`) and deletes the lower-tier file. It intelligently preserves multiple files within the same tier to protect edited variants (e.g., Apple's `E` prefix edited photos).

## Setup

1. Install [uv](https://docs.astral.sh/uv/) (the Python package runner): `curl -LsSf https://astral.sh/uv/install.sh | sh`
2. Set `CATALOG_PATH` at the top of `utils.py` to point to your Lightroom catalog (`.lrcat` file).
3. In Lightroom Classic, go to **File** → **Plug-in Manager** → **Add** and select the `Deduplicator.lrplugin` folder.

## Usage

Everything happens from within Lightroom. The plugin scans your library, shows a confirmation dialog, and then:
- **In-catalog duplicates** are flagged as Rejected — you finish by using Photo → Delete Rejected Photos.
- **Not-in-catalog duplicates** (files on disk that were never imported) are moved to Trash after you confirm.

**Whenever you want to deduplicate:**
1. Go to **Library** → **Plug-in Extras** → **Remove Strict Duplicates**.
2. The plugin scans your library and shows a summary (e.g. "42 files, 1.2 GB recoverable"). Click OK.
3. A confirmation dialog shows how many photos will be flagged as Rejected and how many files will be deleted from disk. Click **Proceed** or **Cancel**.
4. In Lightroom, go to **Photo** → **Delete Rejected Photos** to remove the flagged photos from the catalog.
5. If any keepers weren't already in the catalog, they are moved to the `to_import/` folder next to the plugin. Import this folder into Lightroom so your library stays complete.
6. Repeat with **Library** → **Plug-in Extras** → **Remove Derivative Duplicates**.

A detailed CSV (`strict.csv` / `derivatives.csv`) is always written alongside the plugin for manual review.
