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

## Usage

Before running, ensure you have correctly configured the `FOLDERS` array at the top of `utils.py` with all absolute or `~` based directory paths you wish to traverse.

There are two deletion workflows. Choose one:

### Option A: Delete via Lightroom Plugin (recommended)

This approach uses a bundled Lightroom plugin to remove duplicates from both the catalog and the filesystem in one step. No ghost references to clean up.

**One-time setup:** In Lightroom Classic, go to **File** → **Plug-in Manager** → **Add** and select the `RemoveFromCatalog.lrplugin` folder.

**Step 1 — Scan and review:**
```bash
uv run strict_deduplicator.py          # dry run — review strict.csv
uv run derivative_deduplicator.py      # dry run — review derivatives.csv
```

**Step 2 — Mark for deletion:**
```bash
uv run strict_deduplicator.py --delete_in_lightroom
uv run derivative_deduplicator.py --delete_in_lightroom
```
Both scripts append to the same `deleted_paths.txt`, so you can run both before opening Lightroom.

**Step 3 — Remove in Lightroom:**
1. In Lightroom, go to **Library** → **Plug-in Extras** → **Remove Deleted Duplicates from Catalog**.
2. Confirm the removal when prompted. The plugin clears `deleted_paths.txt` after a successful run.

### Option B: Delete from filesystem only

This deletes duplicate files directly from disk. Lightroom will still show ghost references to the deleted files, which you must clean up manually.

**Step 1 — Scan and review:**
```bash
uv run strict_deduplicator.py          # dry run — review strict.csv
uv run derivative_deduplicator.py      # dry run — review derivatives.csv
```

**Step 2 — Delete:**
```bash
uv run strict_deduplicator.py --delete_from_filesystem
uv run derivative_deduplicator.py --delete_from_filesystem
```

**Step 3 — Clean up Lightroom catalog:**
1. Open Lightroom Classic.
2. Go to **Library** → **Find All Missing Photos**.
3. Select all (`Cmd + A`) → **Delete** → **Remove from Catalog**.

Tip: Run "Find All Missing Photos" *before* the scripts too, to deal with any pre-existing missing photos first.
