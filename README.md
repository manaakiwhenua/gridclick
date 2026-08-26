[![manaakiwhenua-standards](https://github.com/manaakiwhenua/gridclick/workflows/manaakiwhenua-standards/badge.svg)](https://github.com/manaakiwhenua/manaakiwhenua-standards)

# <img src="gridclick/icon.svg" width="32" height="32" alt="Gridclick icon" align="top"> Gridclick — QGIS DGGS cell picker

Left-click the map to create a feature representing the DGGS cell under the
cursor; right-click a cell to remove its feature from the target layer.
Hovering previews the cell outline and centre; `+` / `-` (or Ctrl+wheel, or the
dock buttons) move up and down the DGGS hierarchy.

Supported DGGSs: **H3, S2, A5, rHEALPix (WGS84, N_side 3), Geohash**.

## Applications

- **Areas of interest** — sketch an AOI as a set of cells rather than a
  free-hand polygon: the cell IDs are compact, unambiguous, resolution-aware
  and directly usable as a filter or spatial join key in DGGS-indexed datasets.
- **Training / labelling data** — click cells to label them (land cover,
  presence/absence, damage class…). Cell-based labels line up exactly with
  cell-based features and rasters aggregated to the same grid, so no polygon
  clipping is needed; the `cell_id` is a stable sample key across resolutions
  (parents/children are derivable from it).
- **Sampling designs and field plans** — pick survey cells at a chosen
  resolution, then step to a finer level to designate sub-plots within them.
- **Tasking & QA** — mark cells to revisit, re-process or exclude; hand the
  ID list to a pipeline or colleague instead of a shapefile.
- **Aggregation targets** — choose cells whose statistics you want (zonal
  stats, hex-binned counts) in analytics systems that already speak H3 / S2 /
  A5 / rHEALPix / Geohash.
- **Location references** — a short Geohash or H3 index is easy to quote in a
  report, ticket or message and reproduces the exact cell anywhere.
- **Coarse, privacy-preserving locations** — record where something is at a
  deliberately coarse resolution without storing a precise coordinate.
- **Cross-DGGS comparison** — pick the same spot in several DGGSs (each in its
  own scratch layer) to compare cell shapes, sizes and hierarchies, or to build
  test fixtures for DGGS tooling.

## Install

1. Install the DGGS libraries into QGIS's Python (each is optional):
   ```sh
   /usr/bin/python3 -m pip install --user -r requirements.txt
   ```
2. Link the plugin into your profile:
   ```sh
   ln -s "$PWD/gridclick" ~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/gridclick
   ```
3. Plugins ▸ Manage and Install ▸ enable **Gridclick**.

## Use

Open the *Gridclick* dock (right side) and press **Activate pick tool** (or the
toolbar button).

| Control | Effect |
|---|---|
| DGGS | which grid; greyed entries name the missing pip package |
| Resolution `−` / `+` | coarser / finer; also keys `-`/`+`, `↓`/`↑`, Ctrl+wheel |
| Store as | Cell ID only · Point · Polygon · Point + Polygon (GeometryCollection) |
| Cell ID as | String, or Integer (int64) where the DGGS has one (H3, S2, A5) |
| Target layer | a Gridclick scratch layer (default) or any compatible editable layer |

Features carry fields `dggs`, `resolution`, `cell_id` (string), `cell_id_int`
(int64). Only the chosen ID column is filled. Unsigned 64-bit ids (S2, A5) that
exceed int64 are stored as their two's-complement signed value, the same
convention BigQuery uses for S2.

### One DGGS per layer

A layer may only ever hold cells from a single DGGS. Gridclick tags every layer it
writes to (`gridclick/dggs`, `gridclick/mode` custom properties). Changing the
DGGS while an existing layer is targeted asks you to switch to a fresh scratch
layer; choosing a layer bound to another DGGS switches the DGGS to match; and
every click re-checks the lock before writing.

## Limitations

QGIS does not render layers whose geometry type is GeometryCollection, so the
*Point + Polygon* mode produces a data-only scratch layer: the features (and
their point+polygon geometries) are stored and exportable, but the layer draws
nothing on the canvas. Use *Polygon* mode when you want to see the cells, or
render the collection layer via a virtual layer / geometry generator.

Scratch layers default to a see-through style: a coloured outline (one colour
per DGGS) with a faint fill and a cross at each cell centre.

Cells straddling the antimeridian are stored with continuous ("unwrapped")
longitudes rather than split. Polar rHEALPix/S2 cells are densified but not
split either.

## Development

```sh
python -m pip install -r requirements.txt pytest
python -m pytest tests/         # backend tests, no QGIS needed
```

## License

GPL-2.0-or-later — see [LICENSE](LICENSE). QGIS plugins must be released under
a GPL-compatible license.
