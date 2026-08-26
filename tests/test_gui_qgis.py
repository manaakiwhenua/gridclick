"""Headless end-to-end test: real GridclickPlugin on an offscreen QgsMapCanvas
with a fake iface. Needs qgis + at least h3 importable.
Run:  QT_QPA_PLATFORM=offscreen python -m pytest tests/test_gui_qgis.py
"""
import os, sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
pytest.importorskip("qgis.gui")
pytest.importorskip("h3")
from qgis.core import QgsApplication, QgsCoordinateReferenceSystem, QgsPointXY, QgsProject, QgsRectangle  # noqa
from qgis.gui import QgsMapCanvas, QgsMessageBar  # noqa
from qgis.PyQt.QtWidgets import QMainWindow  # noqa

from gridclick.plugin import GridclickPlugin  # noqa
from gridclick import layers as L  # noqa


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




def test_plugin_end_to_end(qgis_app):
    iface = FakeIface()
    plugin = GridclickPlugin(iface)
    plugin.initGui()
    dock, tool = plugin.dock, plugin.tool
    assert dock is not None and tool is not None

    # choose H3 / polygon / string, scratch target
    dock._set_combo_data(dock.dggs_combo, "h3"); dock._on_dggs_changed(0)
    dock._mode_buttons[L.POLYGON].setChecked(True); dock._on_mode_changed(None)
    dock.id_str_rb.setChecked(True)
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
    dock.id_int_rb.setChecked(True)
    tool.refresh(); tool.cellClicked.emit(tool._cell)
    gc = L.find_scratch_layer("h3", L.COLLECTION)
    g = next(gc.getFeatures())
    assert g.geometry().constGet().numGeometries() == 2 and g["cell_id_int"] is not None

    plugin.unload()
    assert iface.canvas.mapTool() is not tool and not iface.docks and not iface.actions
    # project signals must no longer reach the unloaded dock
    L.create_scratch_layer("geohash", L.POINT)
