[![manaakiwhenua-standards](https://github.com/manaakiwhenua/gridclick/workflows/manaakiwhenua-standards/badge.svg)](https://github.com/manaakiwhenua/manaakiwhenua-standards)

# <img src="gridclick/icon.svg" width="32" height="32" alt="Gridclick icon" align="top"> Gridclick — QGIS DGGS cell picker

Left-click the map to create a feature representing the DGGS cell under the
cursor; right-click a cell to remove its feature from the target layer.
Hovering previews the cell outline and centre; `+` / `-` (or Ctrl+wheel, or the
dock buttons) move up and down the DGGS hierarchy. Turn on the **class palette**
and the same click also writes label attributes, so the plugin doubles as a
cell-based labelling tool.

Supported DGGSs: **H3, S2, A5, rHEALPix (WGS84, N_side 3), Geohash**.

## Applications

- **Areas of interest** — sketch an AOI as a set of cells rather than a
  free-hand polygon: the cell IDs are compact, unambiguous, resolution-aware
  and directly usable as a filter or spatial join key in DGGS-indexed datasets.
- **Training / labelling data** — define a palette of classes (land cover,
  presence/absence, damage class…) and lay them down with keys `1`–`9` and the
  mouse; see [Labelling](#labelling-cells) below. Cell-based labels line up
  exactly with cell-based features and rasters aggregated to the same grid, so
  no polygon clipping is needed; the `cell_id` is a stable sample key across
  resolutions (parents/children are derivable from it).
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
| Target layer | a Gridclick scratch layer (default) or any compatible editable layer |
| Labels | off by default; see below |

Features carry fields `dggs`, `resolution`, `cell_id` (string) and
`cell_id_int` (int64). **Both** are filled — they are two spellings of the same
cell, so there is nothing to choose between. `cell_id_int` is left NULL for the
DGGSs that have no integer form (rHEALPix, Geohash). Unsigned 64-bit ids (S2,
A5) that exceed int64 are stored as their two's-complement signed value, the
same convention BigQuery uses for S2; the string stays authoritative.

Writing into a layer of your own that has no `cell_id`, the string id falls
back to the first spare text field. The integer has no such fallback — putting
it in whatever numeric column came first would overwrite unrelated data.

### Labelling cells

Tick **Label cells on click** in the dock's *Labels* box to attribute cells as
you pick them.

The palette is a table: one row per class, one column per attribute. A *class*
is a named label — `schools`, `pasture`, `absent` — whose name goes into the
**label field** (`label` by default); the other columns are the attributes each
click writes, so one click can record
`class=schools, confidence=high, source=imagery`. Each class has a colour, and
the scratch layer is drawn categorised by class, so labels are visible as they
are laid down.

**Attributes belong to the palette, not to one class.** Adding a column adds
the field for every class at once and to the layer, where the rows already
written get NULL for it. A class that leaves a cell blank writes NULL there.
That is what the data looks like on disk, and it is the only way to keep the
field names consistent — a per-class editor lets one typo invent a whole extra
column.

**Sorting reorders the palette, and so the hotkeys.** Click a column heading to
sort the classes by it, again to reverse. This is not a view sort: the row
order *is* the palette order, which is what the `1`–`9` keys address, so
sorting is how you bring the classes you are about to use onto the first nine
keys. Classes with no value for that column sort last either way, since they
are the NULLs. The class you had selected stays selected — only its hotkey
moves. Sorting is a change to the palette, so it is saved with the layer.

The class colour is also used for the hover preview, so the cell under the
cursor already looks like the class a click would give it. The colour is shown
exactly, with a contrasting halo under the outline so that a pale class stays
readable on a light basemap. With labelling off the preview returns to its
neutral orange.

| Control | Effect |
|---|---|
| Keys `1`–`9` | select a class while the pick tool is active |
| Key `0` | with more than nine classes, move the keys to the next nine |
| Left-click | label the cell with the selected class |
| Right-click | delete the cell's feature |
| Add / Remove class | add or drop a row; ↑ ↓ reorder them (and so the hotkeys) |
| Add / Remove attribute | add or drop a column, for every class at once |
| Rename attribute | rename the selected column, keeping its values |
| Colour… | recolour the selected class |
| Click a column heading | sort the classes by it; click again to reverse |
| Drag a column edge | set its width; widths are kept as you edit |
| Record author and time | add `created_at` (ISO-8601 UTC) and `author`, stamped on every label |

The hotkeys work as soon as the tool is active — you do not have to click the
map first to give the canvas keyboard focus, and they take precedence over any
QGIS action bound to a bare digit for as long as labelling is on. A digit typed
into a text box, spin box or dialog is left alone, as is any digit with
Ctrl/Alt/Shift held; those still reach QGIS, as do all digits once labelling is
switched off. A key with no class behind it says so in the message bar rather
than doing nothing.

**More than nine classes.** The hotkeys address nine classes at a time. `0`
steps to the next nine (wrapping at the end) and selects the first of them; the
list numbers only the classes the keys currently reach and says which page you
are on. Picking a class from the list also moves the keys to it, so after
clicking class 21 the keys address 19–27. There is no limit on how many classes
a palette may hold.

**One feature per cell.** With labelling on, clicking a cell that is already
labelled *re-labels it in place* rather than appending a second feature — a
misclick is corrected by picking the right class and clicking again. Without
labelling, clicks append as before. A class defines the whole attribute row, so
re-labelling replaces every column: a blank cell clears the old value rather
than leaving it behind from the class the cell used to be.

**The palette belongs to the layer.** It is stored as JSON in the layer's
`gridclick/presets` custom property, so it is saved in the `.qgz` and comes
back with the dataset; targeting a layer that carries a palette loads it into
the dock. The last palette used is also remembered across projects, so a new
scratch layer inherits it.

**Labelling an existing layer.** Gridclick refuses to write a label the target
layer has no field for, rather than silently dropping it; the dock names the
missing fields and offers to add them. Values are converted to whatever type
the field actually has, so a class that sets `count=3` lands as an integer in
an integer column.

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
python -m pytest tests/                             # backends only, no QGIS
QT_QPA_PLATFORM=offscreen python -m pytest tests/   # plus the QGIS ones
```

The QGIS tests must run under the interpreter that carries the QGIS bindings
(on Ubuntu, `/usr/bin/python3`). They run against a throwaway QGIS profile, so
they cannot disturb your real settings.

## License

GPL-2.0-or-later — see [LICENSE](LICENSE). QGIS plugins must be released under
a GPL-compatible license.
