"""Plugin glue: toolbar action, dock, map tool and their wiring."""
from __future__ import annotations

import os

from qgis.core import Qgis, QgsProject
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction

from . import layers as L
from . import presets as P
from .dock import GridclickDock
from .hotkeys import HotkeyFilter
from .maptool import GridclickTool


class GridclickPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.action = None
        self.dock = None
        self.tool = None
        self.hotkeys = None

    # ------------------------------------------------------------------ #
    def initGui(self):  # noqa: N802
        icon_path = os.path.join(os.path.dirname(__file__), "icon.svg")
        icon = QIcon(icon_path) if os.path.exists(icon_path) else QIcon()
        self.action = QAction(icon, "Gridclick (DGGS cell picker)", self.iface.mainWindow())
        self.action.setCheckable(True)
        self.action.setToolTip("Left-click: add DGGS cell feature; right-click: remove it; "
                            "+/- change resolution; 1-9 choose label class, 0 for the next nine")
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
        self.tool.presetSelected.connect(self._select_preset)
        self.tool.presetPageNext.connect(self._next_preset_page)
        # the canvas only gets key events while it has focus, which it often
        # does not when a class is chosen; watch the application as well
        self.hotkeys = HotkeyFilter(self._select_preset, self._next_preset_page,
                                    self._labelling, self.iface.mainWindow())
        self.tool.deactivated.connect(lambda: self.dock.set_active(False))
        self.dock.settingsChanged.connect(self._refresh_preview_colour)
        self.canvas.mapToolSet.connect(self._on_map_tool_set)
        self._refresh_preview_colour()

    def unload(self):
        if self.hotkeys is not None:
            self.hotkeys.remove()
            self.hotkeys = None
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
            self.canvas.setFocus()          # so +/- reach the tool straight away
            self.dock.set_active(True)
            self._set_hotkeys_active(True)
        elif self.canvas.mapTool() is self.tool:
            self.canvas.unsetMapTool(self.tool)

    def _set_hotkeys_active(self, active: bool):
        if self.hotkeys is None:
            return
        self.hotkeys.install() if active else self.hotkeys.remove()

    def _on_map_tool_set(self, new_tool, _old_tool=None):
        mine = new_tool is self.tool
        self.dock.set_active(mine)
        self._set_hotkeys_active(mine)
        if self.action is not None:
            self.action.setChecked(mine)

    def _announce_preset(self):
        preset = self.dock.active_preset()
        if preset is None:
            return
        page = ""
        if self.dock.palette.page_count() > 1:
            page = f"  (keys 1–9 → page {self.dock.palette.page() + 1} of {self.dock.palette.page_count()})"
        self.iface.messageBar().pushMessage(
            "Gridclick", f"Label class: {preset.name}{page}", level=Qgis.Info, duration=1
        )

    def _refresh_preview_colour(self):
        """Keep the hover preview showing the class a click would apply."""
        if self.tool is None or self.dock is None:
            return
        preset = self.dock.active_preset()
        self.tool.set_preview_colour(preset.colour if preset is not None else None)

    def _labelling(self) -> bool:
        return self.dock is not None and self.dock.schema() is not None

    def _select_preset(self, index) -> bool:
        """True if a class was actually selected — the hotkey filter only
        swallows the key when it meant something."""
        if self.dock is None or self.dock.schema() is None:
            return False
        if not self.dock.select_preset(index):
            self._report_empty_hotkey(index)
            return False
        # selecting the class that was already current emits nothing, so
        # refresh here rather than relying on the change signal
        self._refresh_preview_colour()
        self._announce_preset()
        return True

    def _report_empty_hotkey(self, index):
        """A hotkey with no class behind it used to do nothing at all, which is
        indistinguishable from the key not arriving. Say what the keys reach."""
        palette = self.dock.palette
        total = len(palette.raw_schema().presets)
        lo = palette.page() * P.MAX_HOTKEYS + 1
        hi = min(lo + P.MAX_HOTKEYS - 1, total)
        where = f"keys 1-9 reach classes {lo}-{hi} of {total}"
        if palette.page_count() > 1:
            where += f" — page {palette.page() + 1} of {palette.page_count()}, 0 for the next"
        self.iface.messageBar().pushMessage(
            "Gridclick", f"Key {index + 1}: no class there ({where})",
            level=Qgis.Info, duration=3,
        )

    def _next_preset_page(self) -> bool:
        if self.dock is None or self.dock.schema() is None:
            return False
        if not self.dock.next_preset_page():
            self._report_no_next_page()
            return False
        self._refresh_preview_colour()
        self._announce_preset()
        return True

    def _report_no_next_page(self):
        """There is only one page. Say so — doing nothing silently reads as
        the key being broken."""
        total = len(self.dock.palette.raw_schema().presets)
        if total == 0:
            detail = "the palette has no classes yet"
        elif total == 1:
            detail = "the palette has one class, already on key 1"
        else:
            detail = f"all {total} classes are already on keys 1-{total}"
        self.iface.messageBar().pushMessage(
            "Gridclick", f"Key 0 moves to the next nine classes — {detail}.",
            level=Qgis.Info, duration=3,
        )

    def _on_cell_clicked(self, cell):
        mode = self.dock.mode()
        schema = self.dock.schema()
        attrs = self.dock.click_attributes()
        if schema is not None and not attrs:
            self.iface.messageBar().pushWarning(
                "Gridclick", "Labelling is on but no class is selected — pick one in the dock."
            )
            return
        layer = self.dock.target_layer()
        if layer is None:
            layer = L.find_scratch_layer(cell.dggs, mode)
            if layer is None:
                layer = L.create_scratch_layer(cell.dggs, mode, schema)
            else:
                # an existing scratch layer may predate the current palette
                self.dock.sync_scratch_schema(layer)
        ok, reason, action = L.add_cell(
            layer, cell, mode, attrs, schema, self.dock.on_existing()
        )
        if not ok:
            self.iface.messageBar().pushWarning("Gridclick", reason)
            return
        verb = {"added": "Added", "updated": "Re-labelled", "skipped": "Already present:"}[action]
        preset = self.dock.active_preset()
        as_txt = f" as {preset.name}" if preset is not None else ""
        self.iface.messageBar().pushMessage(
            "Gridclick", f"{verb} {cell.id_str}{as_txt} → {layer.name()}",
            level=Qgis.Info, duration=2,
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
