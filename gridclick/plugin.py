"""Plugin glue: toolbar action, dock, map tool and their wiring."""
from __future__ import annotations

import os

from qgis.core import Qgis, QgsProject
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction

from . import layers as L
from .dock import GridclickDock
from .maptool import GridclickTool


class GridclickPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.action = None
        self.dock = None
        self.tool = None

    # ------------------------------------------------------------------ #
    def initGui(self):  # noqa: N802
        icon_path = os.path.join(os.path.dirname(__file__), "icon.svg")
        icon = QIcon(icon_path) if os.path.exists(icon_path) else QIcon()
        self.action = QAction(icon, "Gridclick (DGGS cell picker)", self.iface.mainWindow())
        self.action.setCheckable(True)
        self.action.setToolTip("Left-click: add DGGS cell feature; right-click: remove it; +/- change resolution")
        self.action.triggered.connect(self._on_action)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu("&Gridclick", self.action)

        self.dock = GridclickDock(self.iface, self.iface.mainWindow())
        self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dock)

        self.tool = GridclickTool(self.canvas, self.dock.resolution)
        self.tool.setAction(self.action)
        self.tool.set_backend(self.dock.backend())

        # dock -> tool
        self.dock.backendChanged.connect(lambda _n: self.tool.set_backend(self.dock.backend()))
        self.dock.resolutionChanged.connect(lambda _v: self.tool.refresh())
        self.dock.activateToggled.connect(self._set_tool_active)
        # tool -> dock / layers
        self.tool.cellHovered.connect(self.dock.show_cell)
        self.tool.cellClicked.connect(self._on_cell_clicked)
        self.tool.cellRightClicked.connect(self._on_cell_right_clicked)
        self.tool.resolutionStep.connect(self.dock.step_resolution)
        self.tool.deactivated.connect(lambda: self.dock.set_active(False))
        self.canvas.mapToolSet.connect(self._on_map_tool_set)

    def unload(self):
        if self.tool is not None:
            if self.canvas.mapTool() is self.tool:
                self.canvas.unsetMapTool(self.tool)
            self.tool.cleanup()
            self.tool = None
        if self.dock is not None:
            self.dock.cleanup()
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None
        if self.action is not None:
            self.iface.removePluginMenu("&Gridclick", self.action)
            self.iface.removeToolBarIcon(self.action)
            self.action = None

    # ------------------------------------------------------------------ #
    def _on_action(self, checked):
        self._set_tool_active(checked)

    def _set_tool_active(self, active: bool):
        if active:
            if self.dock.backend() is None:
                self.iface.messageBar().pushWarning("Gridclick", "Selected DGGS library is not installed.")
                self.dock.set_active(False)
                self.action.setChecked(False)
                return
            self.dock.show()
            self.canvas.setMapTool(self.tool)
            self.dock.set_active(True)
        elif self.canvas.mapTool() is self.tool:
            self.canvas.unsetMapTool(self.tool)

    def _on_map_tool_set(self, new_tool, _old_tool=None):
        self.dock.set_active(new_tool is self.tool)
        if self.action is not None:
            self.action.setChecked(new_tool is self.tool)

    def _on_cell_clicked(self, cell):
        mode = self.dock.mode()
        id_format = self.dock.id_format()
        layer = self.dock.target_layer()
        if layer is None:
            layer = L.find_scratch_layer(cell.dggs, mode) or L.create_scratch_layer(cell.dggs, mode)
        ok, reason = L.add_cell(layer, cell, mode, id_format)
        if not ok:
            self.iface.messageBar().pushWarning("Gridclick", reason)
            return
        self.iface.messageBar().pushMessage(
            "Gridclick", f"Added {cell.id_str} → {layer.name()}", level=Qgis.Info, duration=2
        )

    def _on_cell_right_clicked(self, cell):
        mode = self.dock.mode()
        layer = self.dock.target_layer() or L.find_scratch_layer(cell.dggs, mode)
        if layer is None:
            return
        n, err = L.remove_cell(layer, cell)
        if err:
            self.iface.messageBar().pushWarning("Gridclick", err)
        elif n:
            self.iface.messageBar().pushMessage(
                "Gridclick", f"Removed {cell.id_str} from {layer.name()}", level=Qgis.Info, duration=2
            )
