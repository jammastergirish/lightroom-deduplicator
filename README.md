# Lightroom Deduplicator

Blazing-fast, multi-threaded Python scripts that clean up your Lightroom photo library. They blast through local and network drives (SMB/NAS) in parallel, safely culling both **exact duplicate clones** and **lower-quality derivatives**.

## How it Works

### Phase 0: Parallel Network Crawling
Both scripts share a multi-threaded file collector that explores subdirectories concurrently, bypassing network latency on SMB/NAS drives. *(Configurable via `SMB_WORKERS` in `utils.py`)*

### Phase 1: `strict_deduplicator.py`
Eliminates files that are **100% bit-for-bit identical** using a multi-stage pipeline: Size Grouping → Concurrent Partial Hashing (first 1 MB) → Concurrent Full-Hash. Fully saturates disk read speeds.

### Phase 2: `derivative_deduplicator.py`
Hunts for lower-quality exports (e.g. a `.JPG` from a `.CR3`) by grouping files with matching EXIF `DateTimeOriginal` timestamps and camera model. Enforces a preservation hierarchy (`RAW` > `Lossless` > `HEIC` > `JPEG`) and flags the lower-tier file. Multiple files within the same tier are protected to preserve edited variants.

### Keeper selection

When multiple files are candidates for deletion, each script picks the **keeper** using a strict priority order (first criterion wins):

**Strict deduplicator** (bit-identical groups):
1. In the Lightroom catalog (preferred over not-in-catalog)
2. Non-duplicate-pattern filename (`IMG_1234.JPG` over `IMG_1234-2.JPG`)
3. Descriptive filename (`Screenshot …`, `Screen Recording …`) over generic names
4. Oldest creation date (earliest imported/created file wins the tie)

**Derivative deduplicator** (same EXIF timestamp + camera model):
1. Best format tier: RAW (.CR3, .DNG, …) > Lossless (.TIFF, .PNG) > HEIC > JPEG
2. In the Lightroom catalog (preferred over not-in-catalog)
3. Largest file size

All files sharing the best tier are always protected — so an original and edited JPEG from the same burst are never both flagged.

### Lightroom catalog awareness
Both scripts query the catalog (read-only, via SQLite `?mode=ro` — never modified) to decide what to keep. In-catalog files are always preferred as keepers. For files found on the filesystem but **not** in the catalog:

- **Has a matching duplicate already in the catalog** → safely trashed (the catalog copy is the keeper).
- **No matching duplicate in the catalog** (i.e. it's unique/the keeper) → moved to `to_import/` so you can import it into Lightroom after cleanup.

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

<img width="267" height="376" alt="Untitled 3" src="https://github.com/user-attachments/assets/04dcd546-73a2-4c03-9001-9970ac11a3a9" />

<img width="270" height="348" alt="Untitled 2" src="https://github.com/user-attachments/assets/750aa613-c218-47b8-b15e-bc0b7d4122b3" />

<img width="274" height="265" alt="Untitled" src="https://github.com/user-attachments/assets/49bdac91-c101-4790-ac11-3275bf0b778f" />
