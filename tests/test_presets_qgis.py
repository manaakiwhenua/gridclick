"""Headless QGIS tests for the label palette (gridclick.presets + the
labelling paths in gridclick.layers).
Run:  QT_QPA_PLATFORM=offscreen python -m pytest tests/test_presets_qgis.py
"""
import os, sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
pytest.importorskip("qgis.core")
from qgis.core import (  # noqa: E402
    NULL,
    QgsCategorizedSymbolRenderer,
    QgsProject,
    QgsVectorLayer,
)

from gridclick import layers as L  # noqa: E402
from gridclick import presets as P  # noqa: E402
from gridclick.backends.base import CellInfo  # noqa: E402


@pytest.fixture(autouse=True)
def _app(qgis_app):
    QgsProject.instance().removeAllMapLayers()
    yield


def cell(dggs="h3", i=0):
    return CellInfo(dggs=dggs, id_str=f"85bd7{i}fffffffff", id_int=2 ** 63 + i, resolution=5,
                    centre=(174.0 + i, -41.0),
                    boundary=[(173.5 + i, -41.5), (174.5 + i, -41.5), (174.5 + i, -40.5),
                              (173.5 + i, -40.5), (173.5 + i, -41.5)])


def schema():
    return P.PresetSchema(
        label_field="class",
        fields=["confidence", "source"],
        presets=[
            P.Preset("schools", "#E69F00", {"confidence": "high", "source": "imagery"}),
            P.Preset("absent", "#56B4E9", {"confidence": "high"}),
        ],
    )


# --------------------------------------------------------------------------- #
# the schema itself
# --------------------------------------------------------------------------- #
def test_schema_roundtrip():
    s = schema()
    back = P.PresetSchema.from_json(s.to_json())
    assert back.label_field == "class"
    assert [p.name for p in back.presets] == ["schools", "absent"]
    assert back.fields == ["confidence", "source"]
    assert back.presets[0].values == {"confidence": "high", "source": "imagery"}
    assert back.presets[0].colour == "#E69F00"


def test_field_names_are_ordered_and_deduplicated():
    # "confidence" is set by both classes but must appear once, after the label
    assert schema().field_names() == [
        "class", "confidence", "source", P.F_CREATED, P.F_AUTHOR]


def test_a_v1_palette_still_loads():
    """v1 declared fields per class; the columns are the union of those."""
    v1 = ('{"version": 1, "label_field": "class", "presets": ['
          '{"name": "schools", "extra": {"confidence": "high", "source": "imagery"}},'
          '{"name": "absent", "extra": {"confidence": "low"}}]}')
    back = P.PresetSchema.from_json(v1)
    assert back.fields == ["confidence", "source"]
    assert back.presets[0].values["source"] == "imagery"
    assert back.presets[1].values == {"confidence": "low"}


def test_a_field_is_shared_by_every_class():
    s = schema()
    assert s.add_field("name")
    assert s.fields == ["confidence", "source", "name"]
    # no class has a value for it yet, so every one of them writes NULL
    for preset in s.presets:
        assert preset.value("name") == ""
        assert P.attributes_for(s, preset)["name"] is None
    assert not s.add_field("name")          # already there
    assert not s.add_field("class")         # that is the label field
    assert s.remove_field("confidence")
    assert s.fields == ["source", "name"]
    assert all("confidence" not in p.values for p in s.presets)


def test_provenance_can_be_turned_off():
    s = schema()
    s.provenance = False
    assert s.field_names() == ["class", "confidence", "source"]


def test_unreadable_schema_is_ignored_not_raised():
    assert P.PresetSchema.from_json("{not json") is None
    assert P.PresetSchema.from_json("") is None
    assert P.PresetSchema.from_json("[]") is None


def test_attributes_for_covers_every_field():
    s = schema()
    attrs = P.attributes_for(s, s.presets[0])
    assert attrs["class"] == "schools" and attrs["source"] == "imagery"
    # "absent" leaves source blank, so it is written as NULL rather than omitted
    assert P.attributes_for(s, s.presets[1])["source"] is None
    assert attrs[P.F_CREATED].startswith("20") and attrs[P.F_CREATED].endswith("+00:00")
    assert P.F_AUTHOR in attrs
    assert P.attributes_for(None, None) == {}


# --------------------------------------------------------------------------- #
# schema on a layer
# --------------------------------------------------------------------------- #
def test_scratch_layer_carries_schema_and_fields():
    s = schema()
    lyr = L.create_scratch_layer("h3", L.POLYGON, s)
    names = [f.name() for f in lyr.fields()]
    for want in ["dggs", "resolution", "cell_id", "class", "confidence", "source",
                 P.F_CREATED, P.F_AUTHOR]:
        assert want in names
    stored = P.load_schema(lyr)
    assert stored is not None and [p.name for p in stored.presets] == ["schools", "absent"]
    assert P.missing_fields(lyr, s) == []


def test_click_writes_the_preset_attributes():
    s = schema()
    lyr = L.create_scratch_layer("h3", L.POLYGON, s)
    attrs = P.attributes_for(s, s.presets[0])
    ok, reason, action = L.add_cell(lyr, cell(), L.POLYGON, attrs, s, L.ON_UPDATE)
    assert ok, reason
    assert action == "added"
    f = next(lyr.getFeatures())
    assert f["cell_id"] == "85bd70fffffffff"
    assert f["class"] == "schools" and f["confidence"] == "high" and f["source"] == "imagery"
    assert f[P.F_CREATED]


def test_reclick_relabels_in_place():
    s = schema()
    lyr = L.create_scratch_layer("h3", L.POLYGON, s)
    L.add_cell(lyr, cell(), L.POLYGON, P.attributes_for(s, s.presets[0]), s, L.ON_UPDATE)
    ok, reason, action = L.add_cell(
        lyr, cell(), L.POLYGON, P.attributes_for(s, s.presets[1]), s, L.ON_UPDATE)
    assert ok, reason
    assert action == "updated"
    assert lyr.featureCount() == 1                     # no contradictory second label
    f = next(lyr.getFeatures())
    assert f["class"] == "absent"
    # the class defines the whole attribute row, so a blank cell clears the
    # value rather than leaving "imagery" behind from when it was "schools"
    assert f["source"] == NULL


def test_reclick_appends_when_not_labelling():
    lyr = L.create_scratch_layer("h3", L.POLYGON)
    L.add_cell(lyr, cell(), L.POLYGON)
    ok, _, action = L.add_cell(lyr, cell(), L.POLYGON)
    assert ok and action == "added" and lyr.featureCount() == 2


def test_skip_leaves_the_existing_label():
    s = schema()
    lyr = L.create_scratch_layer("h3", L.POLYGON, s)
    L.add_cell(lyr, cell(), L.POLYGON, P.attributes_for(s, s.presets[0]), s, L.ON_SKIP)
    ok, _, action = L.add_cell(
        lyr, cell(), L.POLYGON, P.attributes_for(s, s.presets[1]), s, L.ON_SKIP)
    assert ok and action == "skipped"
    assert lyr.featureCount() == 1
    assert next(lyr.getFeatures())["class"] == "schools"


# --------------------------------------------------------------------------- #
# refusing to drop labels
# --------------------------------------------------------------------------- #
def test_write_refused_when_the_layer_has_no_label_field():
    s = schema()
    lyr = QgsVectorLayer("Polygon?crs=EPSG:4326&field=cell_id:string", "plain", "memory")
    QgsProject.instance().addMapLayer(lyr)
    ok, reason, _ = L.add_cell(
        lyr, cell(), L.POLYGON, P.attributes_for(s, s.presets[0]), s, L.ON_UPDATE)
    assert not ok
    assert "class" in reason and "confidence" in reason
    assert lyr.featureCount() == 0


def test_add_missing_fields_unblocks_the_write():
    s = schema()
    lyr = QgsVectorLayer("Polygon?crs=EPSG:4326&field=cell_id:string", "plain", "memory")
    QgsProject.instance().addMapLayer(lyr)
    added, err = P.add_missing_fields(lyr, s)
    assert not err
    assert added == ["class", "confidence", "source", P.F_CREATED, P.F_AUTHOR]
    assert P.missing_fields(lyr, s) == []
    ok, reason, _ = L.add_cell(
        lyr, cell(), L.POLYGON, P.attributes_for(s, s.presets[0]), s, L.ON_UPDATE)
    assert ok, reason
    assert next(lyr.getFeatures())["class"] == "schools"


def test_cell_id_fallback_never_lands_on_a_label_field():
    """A layer with no cell_id field: the id goes to a spare string field, not
    to the column the label is about to be written to."""
    s = P.PresetSchema(label_field="class", presets=[P.Preset("schools")], provenance=False)
    lyr = QgsVectorLayer("Polygon?crs=EPSG:4326&field=class:string&field=note:string",
                         "plain", "memory")
    QgsProject.instance().addMapLayer(lyr)
    ok, reason, _ = L.add_cell(
        lyr, cell(), L.POLYGON, P.attributes_for(s, s.presets[0]), s, L.ON_UPDATE)
    assert ok, reason
    f = next(lyr.getFeatures())
    assert f["class"] == "schools"
    assert f["note"] == "85bd70fffffffff"


def test_values_are_coerced_to_the_field_type():
    s = P.PresetSchema(label_field="class", fields=["count"],
                       presets=[P.Preset("schools", values={"count": "3"})],
                       provenance=False)
    lyr = QgsVectorLayer("Polygon?crs=EPSG:4326&field=cell_id:string&field=class:string"
                         "&field=count:integer", "typed", "memory")
    QgsProject.instance().addMapLayer(lyr)
    ok, reason, _ = L.add_cell(
        lyr, cell(), L.POLYGON, P.attributes_for(s, s.presets[0]), s, L.ON_UPDATE)
    assert ok, reason
    assert next(lyr.getFeatures())["count"] == 3       # int, not "3"


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #
def test_labelled_layer_is_categorised_by_class():
    s = schema()
    lyr = L.create_scratch_layer("h3", L.POLYGON, s)
    renderer = lyr.renderer()
    assert isinstance(renderer, QgsCategorizedSymbolRenderer)
    assert renderer.classAttribute() == "class"
    cats = renderer.categories()
    assert [c.value() for c in cats[:2]] == ["schools", "absent"]
    assert cats[0].symbol().symbolLayer(0).strokeColor().name() == "#e69f00"
    # a catch-all so unlabelled cells still draw
    assert cats[-1].value() == NULL and cats[-1].label() == "unlabelled"


def test_unlabelled_layer_keeps_the_plain_style():
    from qgis.core import QgsSingleSymbolRenderer
    lyr = L.create_scratch_layer("h3", L.POLYGON)
    assert isinstance(lyr.renderer(), QgsSingleSymbolRenderer)
