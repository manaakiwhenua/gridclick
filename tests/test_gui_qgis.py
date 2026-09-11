"""Headless end-to-end test: real GridclickPlugin on an offscreen QgsMapCanvas
with a fake iface. Needs qgis + at least h3 importable.
Run:  QT_QPA_PLATFORM=offscreen python -m pytest tests/test_gui_qgis.py
"""
import os, sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
pytest.importorskip("qgis.gui")
pytest.importorskip("h3")
from qgis.core import (NULL, QgsApplication, QgsCategorizedSymbolRenderer, QgsCoordinateReferenceSystem, QgsPointXY, QgsProject, QgsRectangle, QgsVectorLayer)  # noqa
from qgis.gui import QgsMapCanvas, QgsMessageBar  # noqa
from qgis.PyQt.QtWidgets import QMainWindow  # noqa

from gridclick.plugin import GridclickPlugin  # noqa
from gridclick import layers as L  # noqa
from gridclick import presets as P  # noqa


class FakeIface:
    def __init__(self):
        self.win = QMainWindow()
        self.canvas = QgsMapCanvas(self.win)
        self.canvas.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
        self.canvas.setExtent(QgsRectangle(19000000, -5100000, 19600000, -4900000))
        self.canvas.resize(800, 600)
        self.bar = QgsMessageBar(self.win)
        self.actions, self.docks = [], []
    def mainWindow(self): return self.win
    def mapCanvas(self): return self.canvas
    def messageBar(self): return self.bar
    def addToolBarIcon(self, a): self.actions.append(a)
    def removeToolBarIcon(self, a): self.actions.remove(a)
    def addPluginToMenu(self, n, a): pass
    def removePluginMenu(self, n, a): pass
    def addDockWidget(self, area, d): self.docks.append(d)
    def removeDockWidget(self, d): self.docks.remove(d)




@pytest.fixture
def gridclick(qgis_app):
    """A loaded plugin on a throwaway canvas, always unloaded afterwards. The
    hotkey filter lives on the QApplication, so a test that fails before its
    own unload would otherwise leave it swallowing digits in later tests."""
    QgsProject.instance().removeAllMapLayers()
    iface = FakeIface()
    plugin = GridclickPlugin(iface)
    plugin.initGui()
    try:
        yield plugin, iface
    finally:
        plugin.unload()


def test_plugin_end_to_end(gridclick):
    plugin, iface = gridclick
    dock, tool = plugin.dock, plugin.tool
    assert dock is not None and tool is not None

    # plain cell picking: no labels (the dock may have restored them from settings)
    dock.palette.set_schema(None, enable=False)
    assert dock.schema() is None and dock.on_existing() == L.ON_ADD

    # choose H3 / polygon / string, scratch target
    dock._set_combo_data(dock.dggs_combo, "h3"); dock._on_dggs_changed(0)
    dock._mode_buttons[L.POLYGON].setChecked(True); dock._on_mode_changed(None)
    dock.res_spin.setValue(5)
    plugin._set_tool_active(True)
    assert iface.canvas.mapTool() is tool

    # hover: Wellington in EPSG:3857
    wgs_pt = QgsPointXY(174.77, -41.29)
    from qgis.core import QgsCoordinateTransform
    xf = QgsCoordinateTransform(QgsCoordinateReferenceSystem("EPSG:4326"), iface.canvas.mapSettings().destinationCrs(), QgsProject.instance())
    map_pt = xf.transform(wgs_pt)
    tool._update(map_pt)
    assert tool._cell is not None and tool._cell.dggs == "h3" and tool._cell.resolution == 5
    assert tool.band.numberOfVertices() > 4
    assert "res 5" in dock.readout.text()
    first_id = tool._cell.id_str

    # +/- via the tool signal changes the spinbox and the preview
    tool.resolutionStep.emit(+1)
    assert dock.resolution() == 6 and tool._cell.resolution == 6 and tool._cell.id_str != first_id
    tool.resolutionStep.emit(-1)
    assert dock.resolution() == 5 and tool._cell.id_str == first_id

    # click -> scratch layer created with one feature
    tool.cellClicked.emit(tool._cell)
    lyr = L.find_scratch_layer("h3", L.POLYGON)
    assert lyr is not None and lyr.featureCount() == 1
    f = next(lyr.getFeatures())
    assert f["cell_id"] == first_id and f["dggs"] == "h3"
    assert f.geometry().contains(wgs_pt)

    # right-click removes it again, then re-add for the rest of the test
    tool.cellRightClicked.emit(tool._cell)
    assert lyr.featureCount() == 0
    tool.cellClicked.emit(tool._cell)
    assert lyr.featureCount() == 1

    # switch DGGS while targeting scratch: silent retarget, own layer
    dock._set_combo_data(dock.dggs_combo, "s2"); dock._on_dggs_changed(0)
    assert tool.backend.name == "s2"
    tool.refresh()
    tool.cellClicked.emit(tool._cell)
    assert L.find_scratch_layer("h3", L.POLYGON).featureCount() == 1   # untouched
    assert L.find_scratch_layer("s2", L.POLYGON).featureCount() == 1

    # click-time guard: target the H3 layer explicitly while S2 is selected
    dock._refresh_layers()
    idx = dock.layer_combo.findData(L.find_scratch_layer("h3", L.POLYGON).id())
    assert idx > 0
    dock.layer_combo.blockSignals(True); dock.layer_combo.setCurrentIndex(idx); dock.layer_combo.blockSignals(False)
    tool.cellClicked.emit(tool._cell)                                 # must be refused
    assert L.find_scratch_layer("h3", L.POLYGON).featureCount() == 1
    # ...and the layer-combo handler makes the DGGS follow the layer
    dock._on_layer_changed(idx)
    assert dock.backend_name() == "h3" and tool.backend.name == "h3"

    # geometry collection + int id
    dock._set_combo_data(dock.layer_combo, "__scratch__")
    dock._mode_buttons[L.COLLECTION].setChecked(True); dock._on_mode_changed(None)
    tool.refresh(); tool.cellClicked.emit(tool._cell)
    gc = L.find_scratch_layer("h3", L.COLLECTION)
    g = next(gc.getFeatures())
    assert g.geometry().constGet().numGeometries() == 2 and g["cell_id_int"] is not None

    plugin.unload()
    assert iface.canvas.mapTool() is not tool and not iface.docks and not iface.actions
    # project signals must no longer reach the unloaded dock
    L.create_scratch_layer("geohash", L.POINT)


def _hover(iface, tool, lon=174.77, lat=-41.29):
    from qgis.core import QgsCoordinateTransform
    xf = QgsCoordinateTransform(QgsCoordinateReferenceSystem("EPSG:4326"),
                                iface.canvas.mapSettings().destinationCrs(), QgsProject.instance())
    tool._update(xf.transform(QgsPointXY(lon, lat)))
    return tool._cell


def test_labelling_end_to_end(gridclick):
    """Pick a class, click a cell, re-classify it with a hotkey, then move to a
    layer that has no label fields."""
    plugin, iface = gridclick
    dock, tool = plugin.dock, plugin.tool

    dock._set_combo_data(dock.dggs_combo, "h3"); dock._on_dggs_changed(0)
    dock._mode_buttons[L.POLYGON].setChecked(True); dock._on_mode_changed(None)
    dock.res_spin.setValue(6)
    dock.palette.set_schema(P.PresetSchema(
        label_field="class", fields=["confidence"], presets=[
            P.Preset("schools", "#E69F00", {"confidence": "high"}),
            P.Preset("absent", "#56B4E9"),
        ]), enable=True)
    dock.palette.select_index(0)
    assert dock.schema() is not None and dock.on_existing() == L.ON_UPDATE
    plugin._set_tool_active(True)

    cell = _hover(iface, tool)
    assert cell is not None
    assert "label: schools" in dock.readout.text()

    # click: scratch layer is built with the schema's fields and categorised
    tool.cellClicked.emit(cell)
    lyr = L.find_scratch_layer("h3", L.POLYGON)
    assert lyr is not None and lyr.featureCount() == 1
    f = next(lyr.getFeatures())
    assert f["cell_id"] == cell.id_str
    assert f["class"] == "schools" and f["confidence"] == "high"
    assert f[P.F_CREATED]
    assert isinstance(lyr.renderer(), QgsCategorizedSymbolRenderer)
    assert lyr.renderer().classAttribute() == "class"
    assert P.load_schema(lyr) is not None

    # hotkey "2" switches class; clicking the same cell re-labels it
    tool.presetSelected.emit(1)
    assert dock.active_preset().name == "absent"
    tool.cellClicked.emit(cell)
    assert lyr.featureCount() == 1                       # no contradictory duplicate
    f = next(lyr.getFeatures())
    assert f["class"] == "absent"
    # "absent" leaves confidence blank, so re-labelling clears it rather than
    # leaving "high" behind from when the cell was "schools"
    assert f["confidence"] == NULL

    # a hotkey with no class behind it is ignored
    tool.presetSelected.emit(8)
    assert dock.active_preset().name == "absent"

    # a layer of the user's own without the label fields is refused, not filled
    plain = QgsVectorLayer("Polygon?crs=EPSG:4326&field=cell_id:string", "plain", "memory")
    QgsProject.instance().addMapLayer(plain)
    dock._refresh_layers()
    idx = dock.layer_combo.findData(plain.id())
    assert idx > 0
    dock.layer_combo.setCurrentIndex(idx)
    assert dock.target_layer() is plain
    assert not dock.fixfields_btn.isHidden()             # the offer to fix it
    tool.cellClicked.emit(cell)
    assert plain.featureCount() == 0

    # ...and once the fields are added the same click lands
    P.add_missing_fields(plain, dock.schema())
    dock._update_binding_label()
    assert dock.fixfields_btn.isHidden()
    tool.cellClicked.emit(cell)
    assert plain.featureCount() == 1
    assert next(plain.getFeatures())["class"] == "absent"

    plugin.unload()


def test_hotkey_paging_end_to_end(gridclick):
    """With more classes than hotkeys, key 0 moves the keys to the next nine."""
    plugin, iface = gridclick
    dock, tool = plugin.dock, plugin.tool

    dock._set_combo_data(dock.dggs_combo, "h3"); dock._on_dggs_changed(0)
    dock._mode_buttons[L.POLYGON].setChecked(True); dock._on_mode_changed(None)
    dock.res_spin.setValue(6)
    dock.palette.set_schema(P.PresetSchema(
        label_field="class",
        presets=[P.Preset(f"c{i:02d}") for i in range(1, 13)]), enable=True)
    plugin._set_tool_active(True)
    cell = _hover(iface, tool)
    assert cell is not None

    tool.presetSelected.emit(2)                      # key "3"
    assert dock.active_preset().name == "c03"

    tool.presetPageNext.emit()                       # key "0" -> classes 10-12
    assert dock.active_preset().name == "c10"
    tool.presetSelected.emit(2)                      # key "3" now means c12
    assert dock.active_preset().name == "c12"

    tool.cellClicked.emit(cell)
    lyr = L.find_scratch_layer("h3", L.POLYGON)
    assert next(lyr.getFeatures())["class"] == "c12"

    tool.presetSelected.emit(5)                      # key "6": past the last class
    assert dock.active_preset().name == "c12"

    tool.presetPageNext.emit()                       # wraps to the first nine
    assert dock.active_preset().name == "c01"
    tool.cellClicked.emit(cell)
    assert lyr.featureCount() == 1                   # same cell, re-labelled
    assert next(lyr.getFeatures())["class"] == "c01"

    plugin.unload()


def test_hotkeys_reach_the_palette_without_canvas_focus(gridclick):
    """Regression: choosing a class is the first thing you do, before any
    click, so the map canvas does not have keyboard focus and never sees the
    digit. The keys must work anyway — and must not eat digits typed
    elsewhere."""
    from qgis.PyQt.QtCore import QEvent, Qt
    from qgis.PyQt.QtGui import QKeyEvent
    from qgis.PyQt.QtWidgets import QApplication

    plugin, iface = gridclick
    dock, tool = plugin.dock, plugin.tool
    dock._set_combo_data(dock.dggs_combo, "h3"); dock._on_dggs_changed(0)
    dock._mode_buttons[L.POLYGON].setChecked(True); dock._on_mode_changed(None)
    dock.palette.set_schema(P.PresetSchema(
        label_field="class",
        presets=[P.Preset(f"c{i:02d}") for i in range(1, 13)]), enable=True)
    plugin._set_tool_active(True)

    def send(widget, key, mods=Qt.NoModifier):
        event = QKeyEvent(QEvent.KeyPress, key, mods)
        QApplication.sendEvent(widget, event)
        return event.isAccepted()

    # focus is in the dock, not on the canvas — this is the case that failed
    assert send(dock.activate_btn, Qt.Key_3)
    assert dock.active_preset().name == "c03"
    assert send(dock.palette.table, Qt.Key_5)
    assert dock.active_preset().name == "c05"

    # "0" pages, and the digits then address the new nine
    assert send(dock.activate_btn, Qt.Key_0)
    assert dock.active_preset().name == "c10"
    assert send(dock.activate_btn, Qt.Key_2)
    assert dock.active_preset().name == "c11"

    # ...but a digit being typed is never stolen
    assert not send(dock.palette.field_edit, Qt.Key_7)
    assert not send(dock.res_spin, Qt.Key_4)
    assert not send(dock.activate_btn, Qt.Key_2, Qt.ControlModifier)
    assert dock.active_preset().name == "c11"

    # a digit past the end of the palette falls through to QGIS
    assert not send(dock.activate_btn, Qt.Key_9)

    # with labelling off the digits are QGIS's again
    dock.palette.set_schema(None, enable=False)
    assert not send(dock.activate_btn, Qt.Key_3)

    # and the filter goes away with the tool
    dock.palette.set_schema(P.PresetSchema(
        label_field="class", presets=[P.Preset("a"), P.Preset("b")]), enable=True)
    plugin._set_tool_active(False)
    assert not send(dock.activate_btn, Qt.Key_2)

    plugin.unload()
    assert not send(dock.activate_btn, Qt.Key_1)


def test_the_hover_preview_takes_the_class_colour(gridclick):
    from qgis.PyQt.QtGui import QColor
    from gridclick.maptool import PREVIEW_DEFAULT

    plugin, iface = gridclick
    dock, tool = plugin.dock, plugin.tool
    dock._set_combo_data(dock.dggs_combo, "h3"); dock._on_dggs_changed(0)
    dock._mode_buttons[L.POLYGON].setChecked(True); dock._on_mode_changed(None)
    dock.palette.enable_cb.setChecked(False)
    plugin._set_tool_active(True)

    # not labelling: the neutral hover colour
    assert tool.band.strokeColor().rgb() == QColor(PREVIEW_DEFAULT).rgb()

    dock.palette.set_schema(P.PresetSchema(label_field="class", presets=[
        P.Preset("schools", "#E69F00"), P.Preset("absent", "#56B4E9")]), enable=True)

    # choosing a class re-tints the cell under the cursor
    tool.presetSelected.emit(0)
    assert tool.band.strokeColor().name() == "#e69f00"
    assert tool.marker.color().name() == "#e69f00"
    tool.presetSelected.emit(1)
    assert tool.band.strokeColor().name() == "#56b4e9"
    assert tool.band.fillColor().name() == "#56b4e9"
    assert tool.band.fillColor().alpha() < tool.band.strokeColor().alpha()

    # the preview matches what actually lands in the layer
    cell = _hover(iface, tool)
    tool.cellClicked.emit(cell)
    lyr = L.find_scratch_layer("h3", L.POLYGON)
    assert next(lyr.getFeatures())["class"] == "absent"
    assert dock.palette.raw_schema().get("absent").colour.lower() == \
        tool.band.strokeColor().name()

    # switching labelling off restores the neutral colour
    dock.palette.enable_cb.setChecked(False)
    assert tool.band.strokeColor().rgb() == QColor(PREVIEW_DEFAULT).rgb()

    plugin.unload()


def test_key_0_says_why_it_did_nothing(gridclick):
    """With one page there is nothing to page to; saying so beats a dead key."""
    plugin, iface = gridclick
    dock = plugin.dock
    said = []
    iface.bar.pushMessage = lambda *a, **k: said.append(" ".join(str(x) for x in a))

    dock.palette.set_schema(P.PresetSchema(
        label_field="class",
        presets=[P.Preset(f"c{i}") for i in range(1, 5)]), enable=True)
    assert plugin._next_preset_page() is False        # key falls through to QGIS
    assert said and "all 4 classes" in said[0]

    # ...and with two pages it pages, and says where it landed
    said.clear()
    dock.palette.set_schema(P.PresetSchema(
        label_field="class",
        presets=[P.Preset(f"c{i:02d}") for i in range(1, 13)]), enable=True)
    assert plugin._next_preset_page() is True
    assert dock.active_preset().name == "c10"
    assert said and "c10" in said[0]


def test_the_label_table_grows_with_the_dock(gridclick):
    """The palette takes the slack: a taller dock is a taller table, not a
    band of empty space under it. The dock has to be in a real QMainWindow —
    a free-floating QDockWidget never resizes its own child."""
    from qgis.PyQt.QtCore import Qt
    from qgis.PyQt.QtWidgets import QApplication

    plugin, iface = gridclick
    dock = plugin.dock
    dock.palette.enable_cb.setChecked(True)
    iface.win.addDockWidget(Qt.RightDockWidgetArea, dock)
    iface.win.show()
    try:
        iface.win.resize(900, 500)
        QApplication.processEvents()
        short = dock.palette.table.height()
        iface.win.resize(900, 1100)
        QApplication.processEvents()
        tall = dock.palette.table.height()
        readout = dock.readout.height()
    finally:
        iface.win.removeDockWidget(dock)
        iface.win.hide()

    assert short >= 140                  # never collapses to nothing
    assert tall - short > 300            # the extra height goes to the table
    assert readout < 100                 # ...not to the readout below it
