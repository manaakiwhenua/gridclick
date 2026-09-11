"""Headless QGIS tests for gridclick.layers (needs qgis.core importable).
Run:  QT_QPA_PLATFORM=offscreen python -m pytest tests/test_layers_qgis.py
"""
import os, sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
qgis = pytest.importorskip("qgis.core")
from qgis.core import NULL, QgsApplication, QgsProject, QgsWkbTypes, QgsVectorLayer  # noqa: E402

from gridclick import layers as L  # noqa: E402
from gridclick.backends.base import CellInfo  # noqa: E402


@pytest.fixture(autouse=True)
def _app(qgis_app):
    QgsProject.instance().removeAllMapLayers()  # isolate from other test modules
    yield


def cell(dggs="h3", i=0):
    return CellInfo(dggs=dggs, id_str=f"85bd7{i}fffffffff", id_int=2 ** 63 + i, resolution=5,
                    centre=(174.0 + i, -41.0),
                    boundary=[(173.5 + i, -41.5), (174.5 + i, -41.5), (174.5 + i, -40.5), (173.5 + i, -40.5), (173.5 + i, -41.5)])


@pytest.mark.parametrize("mode,wkb", [
    (L.ID_ONLY, QgsWkbTypes.NoGeometry), (L.POINT, QgsWkbTypes.Point),
    (L.POLYGON, QgsWkbTypes.Polygon), (L.COLLECTION, QgsWkbTypes.GeometryCollection)])
def test_scratch_layer_and_add(mode, wkb):
    lyr = L.create_scratch_layer("h3", mode)
    assert lyr.isValid() and lyr.wkbType() == wkb
    assert L.find_scratch_layer("h3", mode) is lyr
    ok, reason, _ = L.add_cell(lyr, cell(), mode)
    assert ok, reason
    ok, reason, _ = L.add_cell(lyr, cell(i=1), mode)
    assert ok, reason
    feats = list(lyr.getFeatures())
    assert len(feats) == 2
    f0, f1 = feats
    assert f0["cell_id"] == "85bd70fffffffff" and f0["dggs"] == "h3" and f0["resolution"] == 5
    # both spellings of the id are recorded, not one or the other
    assert f0["cell_id_int"] == L.signed_int64(2 ** 63) < 0
    assert f1["cell_id"] == "85bd71fffffffff"
    assert f1["cell_id_int"] == L.signed_int64(2 ** 63 + 1) < 0
    if mode != L.ID_ONLY:
        assert not f0.geometry().isNull()
        if mode == L.COLLECTION:
            assert f0.geometry().wkbType() == QgsWkbTypes.GeometryCollection
            assert f0.geometry().constGet().numGeometries() == 2


def test_lock_blocks_other_dggs():
    lyr = L.create_scratch_layer("s2", L.POLYGON)
    ok, reason, _ = L.add_cell(lyr, cell(dggs="h3"), L.POLYGON)
    assert not ok and "S2" in reason


def test_lock_inferred_from_field_when_untagged():
    lyr = QgsVectorLayer("Polygon?crs=EPSG:4326&field=dggs:string&field=cell_id:string", "plain", "memory")
    QgsProject.instance().addMapLayer(lyr)
    assert L.layer_dggs(lyr) is None
    ok, _, _ = L.add_cell(lyr, cell(dggs="a5"), L.POLYGON)
    assert ok
    assert lyr.customProperty(L.PROP_DGGS) == "a5"
    lyr.removeCustomProperty(L.PROP_DGGS)
    assert L.layer_dggs(lyr) == "a5"          # inferred from data
    ok, reason, _ = L.add_cell(lyr, cell(dggs="h3"), L.POLYGON)
    assert not ok


def test_mode_lock_and_geometry_compat():
    pts = L.create_scratch_layer("geohash", L.POINT)
    ok, reason, _ = L.add_cell(pts, cell(dggs="geohash"), L.POLYGON)
    assert not ok
    assert pts in L.compatible_layers(L.POINT)
    assert pts not in L.compatible_layers(L.POLYGON)
    assert pts in L.compatible_layers(L.ID_ONLY)


def test_existing_layer_without_standard_fields():
    lyr = QgsVectorLayer("Point?crs=EPSG:4326&field=name:string", "names", "memory")
    ok, reason, _ = L.add_cell(lyr, cell(), L.POINT)
    assert ok, reason
    assert next(lyr.getFeatures())["name"] == "85bd70fffffffff"


def test_remove_cell():
    lyr = L.create_scratch_layer("h3", L.POLYGON)
    L.add_cell(lyr, cell(i=0), L.POLYGON)
    L.add_cell(lyr, cell(i=1), L.POLYGON)
    L.add_cell(lyr, cell(i=2), L.POLYGON)
    assert lyr.featureCount() == 3
    assert L.remove_cell(lyr, cell(i=1)) == (1, "")
    assert L.remove_cell(lyr, cell(i=0)) == (1, "")
    assert L.remove_cell(lyr, cell(i=0)) == (0, "")      # nothing left to remove
    assert lyr.featureCount() == 1
    n, err = L.remove_cell(lyr, cell(dggs="s2"))
    assert n == 0 and "H3" in err


def test_scratch_style_is_see_through():
    from qgis.core import QgsFillSymbol, QgsMarkerSymbol
    poly = L.create_scratch_layer("h3", L.POLYGON)
    sym = poly.renderer().symbol()
    assert isinstance(sym, QgsFillSymbol) and sym.symbolLayerCount() == 2
    fill_layer = sym.symbolLayer(0)
    assert fill_layer.fillColor().alpha() < 64            # faint, not solid
    assert fill_layer.strokeColor().alpha() == 255
    assert sym.symbolLayer(1).layerType() == "GeometryGenerator"
    pts = L.create_scratch_layer("s2", L.POINT)
    assert isinstance(pts.renderer().symbol(), QgsMarkerSymbol)
    coll = L.create_scratch_layer("a5", L.COLLECTION)   # QGIS gives these no renderer
    assert coll.renderer() is None
    L.create_scratch_layer("geohash", L.ID_ONLY)            # must not raise


def test_a_backend_without_integer_ids_leaves_that_column_null():
    lyr = L.create_scratch_layer("geohash", L.POLYGON)
    plain = CellInfo(dggs="geohash", id_str="rbsm4", id_int=None, resolution=5,
                     centre=(174.0, -41.0),
                     boundary=[(173.5, -41.5), (174.5, -41.5), (174.5, -40.5),
                               (173.5, -40.5), (173.5, -41.5)])
    ok, reason, _ = L.add_cell(lyr, plain, L.POLYGON)
    assert ok, reason
    f = next(lyr.getFeatures())
    assert f["cell_id"] == "rbsm4"
    assert f["cell_id_int"] == NULL


def test_the_integer_id_never_falls_back_onto_another_numeric_column():
    """A layer of the user's own with a numeric column of its own must not
    have the cell id written into it."""
    lyr = QgsVectorLayer("Polygon?crs=EPSG:4326&field=name:string&field=count:integer",
                         "theirs", "memory")
    QgsProject.instance().addMapLayer(lyr)
    ok, reason, _ = L.add_cell(lyr, cell(), L.POLYGON)
    assert ok, reason
    f = next(lyr.getFeatures())
    assert f["name"] == "85bd70fffffffff"      # the string still falls back
    assert f["count"] == NULL                  # the integer does not


def test_neighbouring_large_ids_are_told_apart():
    """S2 and A5 ids are big enough that adjacent ones round to the same
    double. Matching a cell must be exact, or a right-click would delete a
    neighbouring cell instead."""
    lyr = L.create_scratch_layer("s2", L.POLYGON)
    for i in (0, 1, 2):
        L.add_cell(lyr, cell(dggs="s2", i=i), L.POLYGON)
    assert lyr.featureCount() == 3
    # the three ids differ by 1 either side of -2**63
    assert len({L.signed_int64(2 ** 63 + i) for i in (0, 1, 2)}) == 3
    for i in (0, 1, 2):
        assert L.find_cell_features(lyr, cell(dggs="s2", i=i)) == [i + 1]

    # and matching still works when only the integer column is populated,
    # as layers written by earlier versions may be
    lyr.startEditing()
    idx = lyr.fields().indexOf(L.F_ID)
    for feat in lyr.getFeatures():
        lyr.changeAttributeValue(feat.id(), idx, None)
    lyr.commitChanges()
    for i in (0, 1, 2):
        assert L.find_cell_features(lyr, cell(dggs="s2", i=i)) == [i + 1]
    assert L.remove_cell(lyr, cell(dggs="s2", i=1)) == (1, "")
    assert lyr.featureCount() == 2
