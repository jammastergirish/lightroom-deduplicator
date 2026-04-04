# Lightroom Deduplicator

A pair of **blazing-fast, multi-threaded** Python scripts engineered to clean up your photography directories. Specifically tailored for Adobe Lightroom workflows, they leverage parallel crawlers and asynchronous thread-pools to blast through local and remote drives (SMB/NAS), recovering wasted disk space while ensuring completely safe, automated culling of both **exact duplicate clones** and **lower-quality derivatives**.

## How it Works

The pipeline is split into two scripts to ensure safety. 

### Phase 0: Parallel Network Crawling
To prevent the script from silently hanging when exploring high-latency Network Attached Storage (like an SMB or NAS drive), both scripts share a specialized file collector. It unleashes dozens of concurrent threads to explore subdirectories in parallel, aggressively bypassing network lockstep latency. It also provides a live-streaming terminal readout so you aren't left waiting blindly. *(Note: The thread count is configurable via `SMB_WORKERS` in `utils.py`)*

### Phase 1: `strict_deduplicator.py`
Instead of naively relying on filenames or EXIF metadata, this script eliminates files only if they are **100% bit-for-bit identical**. To overcome the typical slowness of hashing gigabytes of large photos, it leverages a parallelized, multi-threaded process to fully saturate your disks' read speeds alongside a multi-stage elimination pipeline (Size Grouping → Concurrent Partial Hashing → Concurrent Full-Hash).

### Phase 2: `derivative_deduplicator.py`
Once the exact clones are gone, this script hunts for lower-quality exported derivatives (like a `.JPG` generated from a `.CR3`) across all your folders, even if you renamed them. It does this instantly by grouping your library by embedded EXIF `DateTimeOriginal` timestamps. If it finds two photos taken at the exact same millisecond, it enforces a preservation hierarchy (`RAW` > `Lossless` > `HEIC` > `Lossy Compressed`) and deletes the lower-tier file. It intelligently preserves multiple files within the same tier to protect edited variants (e.g., Apple's `E` prefix edited photos).

## Setup

The scripts read your folder paths directly from the Lightroom catalog (`.lrcat` file). If using the Lightroom plugin (Option A), this is automatic. If using the terminal (Option B), set `CATALOG_PATH` at the top of `utils.py` to point to your catalog.

## Usage

There are two ways to use the deduplicator. Choose one:

### Option A: From inside Lightroom (recommended)

Everything happens from within Lightroom. The bundled plugin scans your library, deletes duplicate files from disk, and flags them as Rejected in the catalog. One final step removes them from the catalog entirely.

**One-time setup:** In Lightroom Classic, go to **File** → **Plug-in Manager** → **Add** and select the `Deduplicator.lrplugin` folder.

**Then, whenever you want to deduplicate:**
1. Go to **Library** → **Plug-in Extras** → **Remove Strict Duplicates**.
2. The plugin scans your library and shows a summary (e.g. "42 files, 1.2 GB recoverable"). Click OK.
3. A confirmation dialog asks if you want to proceed. Click **Flag as Rejected** to mark the duplicates, or **Cancel** to abort.
4. In Lightroom, go to **Photo** → **Delete Rejected Photos** to remove them from the catalog.
5. Repeat with **Library** → **Plug-in Extras** → **Remove Derivative Duplicates**.

A detailed CSV (`strict.csv` / `derivatives.csv`) is always written alongside the plugin for manual review.

### Option B: From the terminal

Run the Python scripts directly from the command line. This deletes files from disk only — Lightroom will still show ghost references that you need to clean up manually.

**Step 1 — Scan.** Review the CSVs before proceeding:
```bash
uv run strict_deduplicator.py
uv run derivative_deduplicator.py
```

**Step 2 — Delete.** Each script asks you to type `YES` to confirm:
```bash
uv run strict_deduplicator.py --delete_from_filesystem
uv run derivative_deduplicator.py --delete_from_filesystem
```

**Step 3 — Clean up Lightroom.** The deleted files will appear as "missing" in Lightroom:
1. Open Lightroom Classic.
2. Go to **Library** → **Find All Missing Photos**.
3. Select all (`Cmd + A`) → **Delete** → **Remove from Catalog**.

> **Tip:** Run "Find All Missing Photos" *before* the scripts too, to deal with any pre-existing missing photos first.
