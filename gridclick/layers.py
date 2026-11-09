"""Layer management: scratch layers, target-layer compatibility, the
one-DGGS-per-layer lock, and feature construction."""
from __future__ import annotations

from typing import Iterable, List, Optional, Tuple

from qgis.core import (
    NULL,
    QgsCategorizedSymbolRenderer,
    QgsCoordinateReferenceSystem,
    QgsExpression,
    QgsFeature,
    QgsFeatureRequest,
    QgsField,
    QgsFields,
    QgsFillSymbol,
    QgsGeometry,
    QgsGeometryGeneratorSymbolLayer,
    QgsMarkerSymbol,
    QgsSimpleFillSymbolLayer,
    QgsSimpleMarkerSymbolLayer,
    QgsSingleSymbolRenderer,
    QgsSymbol,
    QgsGeometryCollection,
    QgsLineString,
    QgsPoint,
    QgsPointXY,
    QgsPolygon,
    QgsProject,
    QgsRendererCategory,
    QgsVectorDataProvider,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtGui import QColor

from . import presets as P
from .backends import LABELS
from .backends.base import CellInfo

# storage modes
ID_ONLY = "id_only"
POINT = "point"
POLYGON = "polygon"
COLLECTION = "collection"
MODES = [ID_ONLY, POINT, POLYGON, COLLECTION]
MODE_LABELS = {
    ID_ONLY: "Cell ID only (no geometry)",
    POINT: "Point (cell centre)",
    POLYGON: "Polygon (cell boundary)",
    COLLECTION: "Point + Polygon (geometry collection)",
}

# what a click does when the cell already has a feature in the layer
ON_ADD = "add"        # append another feature (plain cell picking)
ON_UPDATE = "update"  # rewrite its attributes (labelling: one feature per cell)
ON_SKIP = "skip"      # leave it alone

PROP_DGGS = "gridclick/dggs"
PROP_MODE = "gridclick/mode"

F_DGGS = "dggs"
F_RES = "resolution"
F_ID = "cell_id"
F_ID_INT = "cell_id_int"

_MEMORY_GEOM = {
    ID_ONLY: "None",
    POINT: "Point",
    POLYGON: "Polygon",
    COLLECTION: "GeometryCollection",
}

_WGS84 = QgsCoordinateReferenceSystem("EPSG:4326")
_INT64_MAX = 2 ** 63 - 1
_UINT64 = 2 ** 64


# --------------------------------------------------------------------------- #
# geometry
# --------------------------------------------------------------------------- #
def point_geometry(cell: CellInfo) -> QgsGeometry:
    return QgsGeometry.fromPointXY(QgsPointXY(*cell.centre))


def polygon_geometry(cell: CellInfo) -> QgsGeometry:
    return QgsGeometry.fromPolygonXY([[QgsPointXY(x, y) for x, y in cell.boundary]])


def collection_geometry(cell: CellInfo) -> QgsGeometry:
    coll = QgsGeometryCollection()
    coll.addGeometry(QgsPoint(*cell.centre))
    ring = QgsLineString([QgsPoint(x, y) for x, y in cell.boundary])
    poly = QgsPolygon()
    poly.setExteriorRing(ring)
    coll.addGeometry(poly)
    return QgsGeometry(coll)


def geometry_for(cell: CellInfo, mode: str) -> Optional[QgsGeometry]:
    if mode == POINT:
        return point_geometry(cell)
    if mode == POLYGON:
        return polygon_geometry(cell)
    if mode == COLLECTION:
        return collection_geometry(cell)
    return None


def signed_int64(value: int) -> int:
    """Map an unsigned 64-bit id onto signed int64 (two's complement wrap),
    the convention used by e.g. BigQuery for S2 ids."""
    return value - _UINT64 if value > _INT64_MAX else value


# --------------------------------------------------------------------------- #
# layers
# --------------------------------------------------------------------------- #
def standard_fields() -> QgsFields:
    fields = QgsFields()
    fields.append(QgsField(F_DGGS, QVariant.String, len=16))
    fields.append(QgsField(F_RES, QVariant.Int))
    fields.append(QgsField(F_ID, QVariant.String, len=64))
    fields.append(QgsField(F_ID_INT, QVariant.LongLong))
    return fields


def scratch_layer_name(backend_name: str, mode: str) -> str:
    return f"Gridclick {LABELS.get(backend_name, backend_name)} ({mode})"


def create_scratch_layer(backend_name: str, mode: str, schema=None) -> QgsVectorLayer:
    uri = f"{_MEMORY_GEOM[mode]}?crs=EPSG:4326"
    layer = QgsVectorLayer(uri, scratch_layer_name(backend_name, mode), "memory")
    attrs = list(standard_fields()) + list(P.schema_fields(schema))
    layer.dataProvider().addAttributes(attrs)
    layer.updateFields()
    layer.setCustomProperty(PROP_DGGS, backend_name)
    layer.setCustomProperty(PROP_MODE, mode)
    P.save_schema(layer, schema)
    style_scratch_layer(layer, backend_name, mode, schema)
    QgsProject.instance().addMapLayer(layer)
    return layer


def is_scratch_layer(layer) -> bool:
    """True for layers Gridclick created itself — the only ones whose renderer
    it may replace when the palette changes."""
    return (
        isinstance(layer, QgsVectorLayer)
        and layer.providerType() == "memory"
        and layer.name().startswith("Gridclick ")
    )


# one recognisable hue per DGGS so several scratch layers can coexist
DGGS_COLOURS = {
    "h3": "#1f77b4", "s2": "#2ca02c", "a5": "#9467bd",
    "rhealpix": "#d62728", "geohash": "#ff7f0e",
}
_FILL_ALPHA = 30  # ~12 % — see-through, but the cell still reads as an area


def _centre_marker(colour: QColor, size_mm: float = 2.5) -> QgsMarkerSymbol:
    marker = QgsMarkerSymbol()
    marker.deleteSymbolLayer(0)
    ml = QgsSimpleMarkerSymbolLayer(QgsSimpleMarkerSymbolLayer.Cross, size_mm)
    ml.setStrokeColor(colour)
    ml.setStrokeWidth(0.5)
    marker.appendSymbolLayer(ml)
    return marker


def _outline_fill(colour: QColor) -> QgsFillSymbol:
    fill = QgsFillSymbol()
    fill.deleteSymbolLayer(0)
    faint = QColor(colour)
    faint.setAlpha(_FILL_ALPHA)
    sl = QgsSimpleFillSymbolLayer(faint, strokeColor=colour)
    sl.setStrokeWidth(0.6)
    fill.appendSymbolLayer(sl)
    # a cross at the centroid mirrors the hover preview
    gen = QgsGeometryGeneratorSymbolLayer.create({"geometryModifier": "centroid($geometry)"})
    gen.setSymbolType(QgsSymbol.Marker)
    gen.setSubSymbol(_centre_marker(colour))
    fill.appendSymbolLayer(gen)
    return fill


def _symbol_for(mode: str, colour: QColor):
    if mode == POINT:
        return _centre_marker(colour, 3.0)
    if mode in (POLYGON, COLLECTION):
        return _outline_fill(colour)
    return None


def categorized_renderer(schema, backend_name: str, mode: str):
    """One category per label class, in its palette colour, plus a catch-all
    in the DGGS colour so unlabelled cells still draw."""
    cats = []
    for preset in schema.presets:
        sym = _symbol_for(mode, QColor(preset.colour))
        if sym is None:
            return None
        cats.append(QgsRendererCategory(preset.name, sym, preset.name))
    other = _symbol_for(mode, QColor(DGGS_COLOURS.get(backend_name, "#e65100")))
    if other is None:
        return None
    # an invalid QVariant (NULL) is QGIS's "all other values" category
    cats.append(QgsRendererCategory(NULL, other, "unlabelled"))
    return QgsCategorizedSymbolRenderer(schema.label_field, cats)


def style_scratch_layer(layer: QgsVectorLayer, backend_name: str, mode: str, schema=None) -> None:
    """See-through default style: coloured outline + centre cross (polygon /
    collection), coloured cross (point). ID-only layers have no geometry.
    With a label schema the layer is categorised by class instead, so labels
    are visible as they are laid down."""
    if layer.renderer() is None:
        # GeometryCollection layers have no renderer: QGIS cannot draw mixed
        # collections, so they are data-only (see README "Limitations").
        return
    if schema is not None and not schema.is_empty():
        renderer = categorized_renderer(schema, backend_name, mode)
        if renderer is not None:
            layer.setRenderer(renderer)
            layer.triggerRepaint()
            return
    symbol = _symbol_for(mode, QColor(DGGS_COLOURS.get(backend_name, "#e65100")))
    if symbol is None:
        return
    layer.setRenderer(QgsSingleSymbolRenderer(symbol))
    layer.triggerRepaint()


def find_scratch_layer(backend_name: str, mode: str) -> Optional[QgsVectorLayer]:
    """Locate an existing scratch layer for (backend, mode) in the project."""
    for layer in QgsProject.instance().mapLayers().values():
        if (
            isinstance(layer, QgsVectorLayer)
            and layer.providerType() == "memory"
            and layer.customProperty(PROP_DGGS) == backend_name
            and layer.customProperty(PROP_MODE) == mode
            and layer.name().startswith("Gridclick ")
        ):
            return layer
    return None


def mode_geometry_ok(layer: QgsVectorLayer, mode: str) -> bool:
    gt = layer.geometryType()
    wkb = QgsWkbTypes.flatType(layer.wkbType())
    if mode == ID_ONLY:
        return True  # geometry (if any) is left NULL
    if mode == POINT:
        return gt == QgsWkbTypes.PointGeometry
    if mode == POLYGON:
        return gt == QgsWkbTypes.PolygonGeometry
    if mode == COLLECTION:
        return wkb == QgsWkbTypes.GeometryCollection
    return False


def layer_writable(layer) -> bool:
    if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
        return False
    caps = layer.dataProvider().capabilities()
    return bool(caps & QgsVectorDataProvider.AddFeatures)


def compatible_layers(mode: str) -> List[QgsVectorLayer]:
    out = []
    for layer in QgsProject.instance().mapLayers().values():
        if layer_writable(layer) and mode_geometry_ok(layer, mode):
            out.append(layer)
    out.sort(key=lambda lyr: lyr.name().lower())
    return out


# --------------------------------------------------------------------------- #
# the DGGS lock
# --------------------------------------------------------------------------- #
def layer_dggs(layer: QgsVectorLayer) -> Optional[str]:
    """Return the DGGS a layer is bound to: the custom property if set,
    otherwise inferred from a non-null `dggs` field value, else None."""
    if layer is None:
        return None
    tagged = layer.customProperty(PROP_DGGS)
    if tagged:
        return str(tagged)
    idx = layer.fields().indexOf(F_DGGS)
    if idx < 0:
        return None
    for feat in layer.getFeatures():
        val = feat.attribute(idx)
        if val not in (None, NULL) and str(val):
            return str(val)
    return None


def layer_mode(layer: QgsVectorLayer) -> Optional[str]:
    tagged = layer.customProperty(PROP_MODE)
    return str(tagged) if tagged else None


def check_lock(layer: QgsVectorLayer, backend_name: str, mode: str, schema=None) -> Tuple[bool, str]:
    """(ok, reason). Refuses a write that would mix DGGSs or storage modes, or
    that would silently drop label values the layer has no field for."""
    bound = layer_dggs(layer)
    if bound and bound != backend_name:
        return False, (
            f"Layer '{layer.name()}' holds {LABELS.get(bound, bound)} cells; "
            f"refusing to add {LABELS.get(backend_name, backend_name)} cells."
        )
    bound_mode = layer_mode(layer)
    if bound_mode and bound_mode != mode:
        return False, (
            f"Layer '{layer.name()}' stores '{MODE_LABELS.get(bound_mode, bound_mode)}'; "
            f"refusing to add '{MODE_LABELS.get(mode, mode)}' features."
        )
    if not mode_geometry_ok(layer, mode):
        return False, f"Layer '{layer.name()}' geometry type does not match '{mode}'."
    if not layer_writable(layer):
        return False, f"Layer '{layer.name()}' does not accept new features."
    missing = P.missing_fields(layer, schema)
    if missing:
        return False, (
            f"Layer '{layer.name()}' has no field for {', '.join(missing)}; "
            f"labels would be dropped."
        )
    return True, ""


def bind_layer(layer: QgsVectorLayer, backend_name: str, mode: str) -> None:
    if not layer.customProperty(PROP_DGGS):
        layer.setCustomProperty(PROP_DGGS, backend_name)
    if not layer.customProperty(PROP_MODE):
        layer.setCustomProperty(PROP_MODE, mode)


# --------------------------------------------------------------------------- #
# features
# --------------------------------------------------------------------------- #
def _first_field_of_type(fields: QgsFields, types: Iterable[int], exclude=()) -> int:
    for i, f in enumerate(fields):
        if f.type() in types and f.name() not in exclude:
            return i
    return -1


def _label_fields(layer: QgsVectorLayer, schema=None) -> set:
    """Names a label schema writes. The cell-id fallback below must not land
    on one of these, or a click would overwrite its own label."""
    schema = schema if schema is not None else P.load_schema(layer)
    return set(schema.field_names()) if schema is not None else set()


def _id_field_indexes(layer: QgsVectorLayer, schema=None):
    """(string index, int index) for the cell id. Layers Gridclick made have
    the standard fields; for a layer the user brought, fall back to its first
    field of a usable type."""
    fields = layer.fields()
    i_str = fields.indexOf(F_ID)
    i_int = fields.indexOf(F_ID_INT)
    if i_str < 0 and i_int < 0:
        i_str = _first_field_of_type(fields, (QVariant.String,), _label_fields(layer, schema))
    return i_str, i_int


def build_feature(layer: QgsVectorLayer, cell: CellInfo, mode: str,
                  attrs=None) -> QgsFeature:
    fields = layer.fields()
    feat = QgsFeature(fields)
    geom = geometry_for(cell, mode)
    if geom is not None and layer.geometryType() != QgsWkbTypes.NullGeometry:
        # promote to multi if the layer is multi-type
        if QgsWkbTypes.isMultiType(layer.wkbType()) and not geom.isMultipart():
            geom.convertToMultiType()
        feat.setGeometry(geom)

    def setf(name, value):
        idx = fields.indexOf(name)
        if idx >= 0:
            feat.setAttribute(idx, value)
            return True
        return False

    setf(F_DGGS, cell.dggs)
    setf(F_RES, cell.resolution)

    # Both spellings of the id are written. They are the same cell, the layer
    # carries both columns anyway, and the string form stays authoritative for
    # the DGGSs whose ids overflow int64.
    reserved = set(attrs or {}) | _label_fields(layer)
    if not setf(F_ID, cell.id_str):
        # a layer of the user's own with no cell_id: fall back to a spare
        # string field so the click still records something
        idx = _first_field_of_type(fields, (QVariant.String,), reserved)
        if idx >= 0:
            feat.setAttribute(idx, cell.id_str)
    if cell.id_int is not None:
        # no fallback for the integer: writing it into whatever numeric column
        # happened to be first would clobber unrelated data
        setf(F_ID_INT, signed_int64(cell.id_int))

    for name, value in (attrs or {}).items():
        idx = fields.indexOf(name)
        if idx >= 0:
            feat.setAttribute(idx, P.coerce(value, fields[idx].type()))
    return feat


def add_cell(layer: QgsVectorLayer, cell: CellInfo, mode: str,
             attrs=None, schema=None, on_existing: str = ON_ADD) -> Tuple[bool, str, str]:
    """Write `cell` into `layer`, honouring the DGGS lock. Returns
    (ok, reason, action) where action is "added", "updated" or "skipped".

    `on_existing` decides what a repeat click does. Labelling uses ON_UPDATE so
    a layer stays a clean cell -> class mapping and a misclick is corrected by
    clicking again; plain cell picking uses ON_ADD.
    Starts an edit session if needed (memory layers are committed immediately)."""
    ok, reason = check_lock(layer, cell.dggs, mode, schema)
    if not ok:
        return False, reason, ""
    bind_layer(layer, cell.dggs, mode)

    if on_existing in (ON_UPDATE, ON_SKIP):
        fids = find_cell_features(layer, cell)
        if fids:
            if on_existing == ON_SKIP:
                return True, "", "skipped"
            n, err = update_cell_attributes(layer, fids, attrs)
            if err:
                return False, err, ""
            return True, "", "updated"

    feat = build_feature(layer, cell, mode, attrs)
    if layer.isEditable():
        ok = layer.addFeature(feat)
    elif layer.providerType() == "memory":
        ok, _ = layer.dataProvider().addFeatures([feat])
        layer.updateExtents()
    else:
        if not layer.startEditing():
            return False, f"Could not start editing '{layer.name()}'.", ""
        ok = layer.addFeature(feat)
    if not ok:
        return False, f"Failed to add feature to '{layer.name()}'.", ""
    layer.triggerRepaint()
    return True, "", "added"


def update_cell_attributes(layer: QgsVectorLayer, fids: List[int], attrs) -> Tuple[int, str]:
    """Rewrite `attrs` on the given features. Returns (count, error)."""
    if not attrs or not fids:
        return 0, ""
    if not layer.dataProvider().capabilities() & QgsVectorDataProvider.ChangeAttributeValues:
        return 0, f"Layer '{layer.name()}' does not accept attribute changes."
    fields = layer.fields()
    changes = {}
    for name, value in attrs.items():
        idx = fields.indexOf(name)
        if idx >= 0:
            changes[idx] = P.coerce(value, fields[idx].type())
    if not changes:
        return 0, ""
    if layer.providerType() == "memory" and not layer.isEditable():
        ok = layer.dataProvider().changeAttributeValues({fid: dict(changes) for fid in fids})
    else:
        if not layer.isEditable() and not layer.startEditing():
            return 0, f"Could not start editing '{layer.name()}'."
        ok = all(
            layer.changeAttributeValue(fid, idx, value)
            for fid in fids
            for idx, value in changes.items()
        )
    if not ok:
        return 0, f"Failed to update features in '{layer.name()}'."
    layer.triggerRepaint()
    return len(fids), ""


def find_cell_features(layer: QgsVectorLayer, cell: CellInfo) -> List[int]:
    """Feature ids in `layer` that represent `cell` (by string or int id).

    Expressed as a provider filter rather than a Python scan: relabelling looks
    the cell up on every click, and a labelling layer runs to many thousands
    of cells."""
    fields = layer.fields()
    i_str, i_int = _id_field_indexes(layer)
    clauses, wanted = [], []
    if i_str >= 0:
        clauses.append(
            f"{QgsExpression.quotedColumnRef(fields[i_str].name())} = "
            f"{QgsExpression.quotedValue(cell.id_str)}"
        )
        wanted.append(i_str)
    if i_int >= 0 and cell.id_int is not None:
        # compared as text on purpose: QGIS evaluates a numeric comparison in
        # an expression as a double, and S2/A5 ids are large enough that
        # adjacent cells collapse onto the same double — which would delete or
        # re-label the wrong cell. to_string() compares the int64 exactly.
        clauses.append(
            f"to_string({QgsExpression.quotedColumnRef(fields[i_int].name())}) = "
            f"{QgsExpression.quotedValue(str(signed_int64(cell.id_int)))}"
        )
        wanted.append(i_int)
    if not clauses:
        return []
    req = QgsFeatureRequest().setFilterExpression(" OR ".join(clauses))
    req.setFlags(QgsFeatureRequest.NoGeometry)
    req.setSubsetOfAttributes(wanted)
    return [feat.id() for feat in layer.getFeatures(req)]


def remove_cell(layer: QgsVectorLayer, cell: CellInfo) -> Tuple[int, str]:
    """Delete every feature representing `cell` from `layer`.
    Returns (count_removed, error_message)."""
    bound = layer_dggs(layer)
    if bound and bound != cell.dggs:
        return 0, f"Layer '{layer.name()}' holds {LABELS.get(bound, bound)} cells, not {LABELS.get(cell.dggs, cell.dggs)}."
    fids = find_cell_features(layer, cell)
    if not fids:
        return 0, ""
    if layer.isEditable():
        ok = layer.deleteFeatures(fids)
    elif layer.providerType() == "memory":
        ok = layer.dataProvider().deleteFeatures(fids)
        layer.updateExtents()
    else:
        if not layer.startEditing():
            return 0, f"Could not start editing '{layer.name()}'."
        ok = layer.deleteFeatures(fids)
    if not ok:
        return 0, f"Could not remove the cell's features from '{layer.name()}'."
    layer.triggerRepaint()
    return len(fids), ""
