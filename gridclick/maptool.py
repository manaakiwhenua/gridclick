"""Map tool: hover preview of the DGGS cell under the cursor, click to emit."""
from __future__ import annotations

from typing import Callable, Optional

import traceback

from qgis.core import (
    Qgis,
    QgsMessageLog,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsWkbTypes,
)
from qgis.gui import QgsMapToolEmitPoint, QgsRubberBand, QgsVertexMarker
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor

from .backends.base import CellInfo, DggsBackend
from . import layers as L

_WGS84 = QgsCoordinateReferenceSystem("EPSG:4326")


class GridclickTool(QgsMapToolEmitPoint):
    #: emitted with a CellInfo (or None when the cursor leaves / lookup fails)
    cellHovered = pyqtSignal(object)
    #: emitted with the CellInfo when the user left-clicks
    cellClicked = pyqtSignal(object)
    #: emitted with the CellInfo when the user right-clicks (remove)
    cellRightClicked = pyqtSignal(object)
    #: emitted with +1 / -1 when the user presses +/- or Ctrl+wheel
    resolutionStep = pyqtSignal(int)

    def __init__(self, canvas, resolution_provider: Callable[[], int]):
        super().__init__(canvas)
        self.canvas = canvas
        self._resolution = resolution_provider
        self.backend: Optional[DggsBackend] = None
        self._last_map_point: Optional[QgsPointXY] = None
        self._last_id: Optional[str] = None
        self._cell: Optional[CellInfo] = None

        self.band = QgsRubberBand(canvas, QgsWkbTypes.PolygonGeometry)
        self.band.setStrokeColor(QColor(255, 80, 0, 220))
        self.band.setFillColor(QColor(255, 80, 0, 40))
        self.band.setWidth(2)

        self.marker = QgsVertexMarker(canvas)
        self.marker.setIconType(QgsVertexMarker.ICON_CROSS)
        self.marker.setColor(QColor(255, 80, 0, 255))
        self.marker.setIconSize(12)
        self.marker.setPenWidth(2)
        self.marker.hide()

        self.setCursor(Qt.CrossCursor)

    # ------------------------------------------------------------------ #
    def set_backend(self, backend: Optional[DggsBackend]):
        self.backend = backend
        self._last_id = None
        self.refresh()

    def _to_wgs84(self):
        return QgsCoordinateTransform(
            self.canvas.mapSettings().destinationCrs(), _WGS84, QgsProject.instance()
        )

    def _from_wgs84(self):
        return QgsCoordinateTransform(
            _WGS84, self.canvas.mapSettings().destinationCrs(), QgsProject.instance()
        )

    def clear(self):
        self.band.reset(QgsWkbTypes.PolygonGeometry)
        self.marker.hide()
        self._last_id = None
        self._cell = None
        self.cellHovered.emit(None)

    def refresh(self):
        """Recompute the preview at the last cursor position (e.g. after the
        resolution or backend changed)."""
        if self._last_map_point is not None:
            self._last_id = None
            self._update(self._last_map_point)

    # ------------------------------------------------------------------ #
    def _update(self, map_point: QgsPointXY):
        self._last_map_point = map_point
        if self.backend is None:
            self.clear()
            return
        try:
            ll = self._to_wgs84().transform(map_point)
            cell = self.backend.cell_at(ll.x(), ll.y(), self._resolution())
        except Exception:
            self._report("cell lookup failed", traceback.format_exc())
            self.clear()
            return
        if cell.id_str == self._last_id:
            return
        self._last_id = cell.id_str
        self._cell = cell
        xform = self._from_wgs84()
        try:
            poly = L.polygon_geometry(cell)
            poly.transform(xform)
            self.band.setToGeometry(poly, None)
            centre = xform.transform(QgsPointXY(*cell.centre))
            self.marker.setCenter(centre)
            self.marker.show()
        except Exception:
            self._report("preview drawing failed", traceback.format_exc())
            self.band.reset(QgsWkbTypes.PolygonGeometry)
            self.marker.hide()
        self.cellHovered.emit(cell)

    _reported = False

    def _report(self, what, detail):
        QgsMessageLog.logMessage(f"{what}:\n{detail}", "Gridclick", Qgis.Warning)
        if not GridclickTool._reported:
            GridclickTool._reported = True
            from qgis.utils import iface
            if iface:
                iface.messageBar().pushWarning(
                    "Gridclick", f"{what} — see Log Messages panel, 'Gridclick' tab"
                )

    # ------------------------------------------------------------------ #
    # Qt / QGIS events
    def canvasMoveEvent(self, event):
        self._update(self.toMapCoordinates(event.pos()))

    def canvasReleaseEvent(self, event):
        if event.button() not in (Qt.LeftButton, Qt.RightButton):
            return
        self._last_id = None
        self._update(self.toMapCoordinates(event.pos()))
        if self._cell is None:
            return
        if event.button() == Qt.LeftButton:
            self.cellClicked.emit(self._cell)
        else:
            self.cellRightClicked.emit(self._cell)

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key_Plus, Qt.Key_Equal, Qt.Key_Up, Qt.Key_PageUp):
            self.resolutionStep.emit(+1)
            event.accept()
        elif key in (Qt.Key_Minus, Qt.Key_Underscore, Qt.Key_Down, Qt.Key_PageDown):
            self.resolutionStep.emit(-1)
            event.accept()
        else:
            super().keyPressEvent(event)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            if delta:
                self.resolutionStep.emit(+1 if delta > 0 else -1)
            event.accept()
        else:
            super().wheelEvent(event)

    def deactivate(self):
        self.clear()
        super().deactivate()
        self.deactivated.emit()

    def cleanup(self):
        """Remove canvas items (call on plugin unload)."""
        self.canvas.scene().removeItem(self.band)
        self.canvas.scene().removeItem(self.marker)
