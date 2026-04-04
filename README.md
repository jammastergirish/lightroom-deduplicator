# Lightroom Deduplicator

Blazing-fast, multi-threaded Python scripts that clean up your Lightroom photo library. They blast through local and network drives (SMB/NAS) in parallel, safely culling both **exact duplicate clones** and **lower-quality derivatives**.

## How it Works

### Phase 0: Parallel Network Crawling
Both scripts share a multi-threaded file collector that explores subdirectories concurrently, bypassing network latency on SMB/NAS drives. *(Configurable via `SMB_WORKERS` in `utils.py`)*

### Phase 1: `strict_deduplicator.py`
Eliminates files that are **100% bit-for-bit identical** using a multi-stage pipeline: Size Grouping → Concurrent Partial Hashing (first 1 MB) → Concurrent Full-Hash. Fully saturates disk read speeds.

### Phase 2: `derivative_deduplicator.py`
Hunts for lower-quality exports (e.g. a `.JPG` from a `.CR3`) by grouping files with matching EXIF `DateTimeOriginal` timestamps and camera model. Enforces a preservation hierarchy (`RAW` > `Lossless` > `HEIC` > `JPEG`) and flags the lower-tier file. Multiple files within the same tier are protected to preserve edited variants.

### Lightroom catalog awareness
Both scripts query the catalog (read-only, via SQLite `?mode=ro` — never modified) to prefer in-catalog files as keepers. If a keeper isn't in the catalog, it's moved to `to_import/` for easy import after cleanup.

## Safety

- **No unique file is ever touched.** Only proven duplicates or lower-tier derivatives are flagged.
- **Nothing is permanently deleted.** In-catalog duplicates are flagged as Rejected for you to review. Not-in-catalog duplicates are moved to Trash.
- **Nothing happens without confirmation.** A summary and confirmation dialog are shown before any action.
- **A CSV is always written first** (`strict.csv` / `derivatives.csv`) for manual review.

## Setup

1. Install [uv](https://docs.astral.sh/uv/): `curl -LsSf https://astral.sh/uv/install.sh | sh`
2. Set `CATALOG_PATH` at the top of `utils.py` to point to your `.lrcat` file.
3. In Lightroom Classic: **File** → **Plug-in Manager** → **Add** → select `Deduplicator.lrplugin`.

## Usage

1. **Library** → **Plug-in Extras** → **Remove Strict Duplicates**.
2. Review the summary, then click **Proceed** or **Cancel**.
3. **Photo** → **Delete Rejected Photos** to finish removing flagged photos.
4. Import the `to_import/` folder if any keepers weren't already in the catalog.
5. Repeat with **Library** → **Plug-in Extras** → **Remove Derivative Duplicates**.
