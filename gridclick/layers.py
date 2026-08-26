"""Layer management: scratch layers, target-layer compatibility, the
one-DGGS-per-layer lock, and feature construction."""
from __future__ import annotations

from typing import Iterable, List, Optional, Tuple

from qgis.core import (
    NULL,
    QgsCoordinateReferenceSystem,
    QgsFeature,
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
    QgsVectorDataProvider,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtGui import QColor

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

# id formats
ID_STR = "str"
ID_INT = "int"

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


def create_scratch_layer(backend_name: str, mode: str) -> QgsVectorLayer:
    uri = f"{_MEMORY_GEOM[mode]}?crs=EPSG:4326"
    layer = QgsVectorLayer(uri, scratch_layer_name(backend_name, mode), "memory")
    layer.dataProvider().addAttributes(list(standard_fields()))
    layer.updateFields()
    layer.setCustomProperty(PROP_DGGS, backend_name)
    layer.setCustomProperty(PROP_MODE, mode)
    style_scratch_layer(layer, backend_name, mode)
    QgsProject.instance().addMapLayer(layer)
    return layer


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


def style_scratch_layer(layer: QgsVectorLayer, backend_name: str, mode: str) -> None:
    """See-through default style: coloured outline + centre cross (polygon /
    collection), coloured cross (point). ID-only layers have no geometry."""
    colour = QColor(DGGS_COLOURS.get(backend_name, "#e65100"))
    if mode == POINT:
        symbol = _centre_marker(colour, 3.0)
    elif mode in (POLYGON, COLLECTION):
        symbol = _outline_fill(colour)
    else:
        return
    if layer.renderer() is None:
        # GeometryCollection layers have no renderer: QGIS cannot draw mixed
        # collections, so they are data-only (see README "Limitations").
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
    out.sort(key=lambda l: l.name().lower())
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


def check_lock(layer: QgsVectorLayer, backend_name: str, mode: str) -> Tuple[bool, str]:
    """(ok, reason). Refuses a write that would mix DGGSs or storage modes."""
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
    return True, ""


def bind_layer(layer: QgsVectorLayer, backend_name: str, mode: str) -> None:
    if not layer.customProperty(PROP_DGGS):
        layer.setCustomProperty(PROP_DGGS, backend_name)
    if not layer.customProperty(PROP_MODE):
        layer.setCustomProperty(PROP_MODE, mode)


# --------------------------------------------------------------------------- #
# features
# --------------------------------------------------------------------------- #
def _first_field_of_type(fields: QgsFields, types: Iterable[int]) -> int:
    for i, f in enumerate(fields):
        if f.type() in types:
            return i
    return -1


def build_feature(layer: QgsVectorLayer, cell: CellInfo, mode: str, id_format: str) -> QgsFeature:
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

    use_int = id_format == ID_INT and cell.id_int is not None
    if use_int:
        wrote = setf(F_ID_INT, signed_int64(cell.id_int))
        if not wrote:
            idx = _first_field_of_type(fields, (QVariant.LongLong, QVariant.ULongLong))
            if idx >= 0:
                feat.setAttribute(idx, signed_int64(cell.id_int))
            else:
                setf(F_ID, str(cell.id_int))
    else:
        wrote = setf(F_ID, cell.id_str)
        if not wrote:
            idx = _first_field_of_type(fields, (QVariant.String,))
            if idx >= 0:
                feat.setAttribute(idx, cell.id_str)
    return feat


def add_cell(layer: QgsVectorLayer, cell: CellInfo, mode: str, id_format: str) -> Tuple[bool, str]:
    """Add a feature for `cell` to `layer`, honouring the DGGS lock.
    Starts an edit session if needed (memory layers are committed immediately)."""
    ok, reason = check_lock(layer, cell.dggs, mode)
    if not ok:
        return False, reason
    bind_layer(layer, cell.dggs, mode)
    feat = build_feature(layer, cell, mode, id_format)
    if layer.isEditable():
        ok = layer.addFeature(feat)
    elif layer.providerType() == "memory":
        ok, _ = layer.dataProvider().addFeatures([feat])
        layer.updateExtents()
    else:
        if not layer.startEditing():
            return False, f"Could not start editing '{layer.name()}'."
        ok = layer.addFeature(feat)
    if not ok:
        return False, f"Failed to add feature to '{layer.name()}'."
    layer.triggerRepaint()
    return True, ""


def find_cell_features(layer: QgsVectorLayer, cell: CellInfo) -> List[int]:
    """Feature ids in `layer` that represent `cell` (by string or int id)."""
    fields = layer.fields()
    ids = []
    i_str = fields.indexOf(F_ID)
    i_int = fields.indexOf(F_ID_INT)
    if i_str < 0 and i_int < 0:
        i_str = _first_field_of_type(fields, (QVariant.String,))
    sid = cell.id_str
    iid = signed_int64(cell.id_int) if cell.id_int is not None else None
    for feat in layer.getFeatures():
        if i_str >= 0 and feat.attribute(i_str) not in (None, NULL) and str(feat.attribute(i_str)) == sid:
            ids.append(feat.id())
        elif i_int >= 0 and iid is not None and feat.attribute(i_int) not in (None, NULL) and int(feat.attribute(i_int)) == iid:
            ids.append(feat.id())
    return ids


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
        return 0, f"Failed to delete from '{layer.name()}'."
    layer.triggerRepaint()
    return len(fids), ""
