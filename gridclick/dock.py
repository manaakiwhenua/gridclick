"""Dock panel: DGGS choice, resolution, storage mode, ID format, target layer,
hovered-cell readout. Implements the one-DGGS-per-layer lock in the UI."""
from __future__ import annotations

from typing import Optional

from qgis.core import QgsDistanceArea, QgsProject, QgsSettings, QgsUnitTypes, QgsVectorLayer
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDockWidget,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import backends
from . import layers as L
from .backends.base import CellInfo

_SETTINGS = "gridclick/"
SCRATCH = "__scratch__"


class GridclickDock(QDockWidget):
    backendChanged = pyqtSignal(str)
    resolutionChanged = pyqtSignal(int)
    settingsChanged = pyqtSignal()
    activateToggled = pyqtSignal(bool)

    def __init__(self, iface, parent=None):
        super().__init__("Gridclick", parent)
        self.iface = iface
        self.setObjectName("GridclickDock")
        self._availability = backends.availability()
        self._area = QgsDistanceArea()
        self._area.setEllipsoid("WGS84")
        self._build_ui()
        self._load_settings()
        self._wire()
        self._refresh_layers()
        self._apply_backend_limits()
        self._update_binding_label()

    # ------------------------------------------------------------------ #
    # UI construction
    def _build_ui(self):
        w = QWidget()
        root = QVBoxLayout(w)
        form = QFormLayout()

        self.activate_btn = QPushButton("Activate pick tool")
        self.activate_btn.setCheckable(True)
        root.addWidget(self.activate_btn)

        # DGGS
        self.dggs_combo = QComboBox()
        for name in backends.ORDER:
            err = self._availability.get(name)
            self.dggs_combo.addItem(backends.LABELS[name], name)
            idx = self.dggs_combo.count() - 1
            if err:
                item = self.dggs_combo.model().item(idx)
                item.setEnabled(False)
                item.setToolTip(err)
                self.dggs_combo.setItemText(idx, f"{backends.LABELS[name]}  (missing: pip install {backends.PIP_NAMES[name]})")
        form.addRow("DGGS", self.dggs_combo)

        # resolution
        res_row = QHBoxLayout()
        self.res_minus = QToolButton()
        self.res_minus.setText("−")
        self.res_minus.setToolTip("Coarser (key −)")
        self.res_spin = QSpinBox()
        self.res_spin.setKeyboardTracking(False)
        self.res_plus = QToolButton()
        self.res_plus.setText("+")
        self.res_plus.setToolTip("Finer (key +)")
        res_row.addWidget(self.res_minus)
        res_row.addWidget(self.res_spin, 1)
        res_row.addWidget(self.res_plus)
        self.res_range = QLabel("")
        res_row.addWidget(self.res_range)
        form.addRow("Resolution", res_row)

        # storage mode
        self.mode_group = QButtonGroup(self)
        mode_box = QVBoxLayout()
        self._mode_buttons = {}
        for mode in L.MODES:
            rb = QRadioButton(L.MODE_LABELS[mode])
            self.mode_group.addButton(rb)
            self._mode_buttons[mode] = rb
            mode_box.addWidget(rb)
        form.addRow("Store as", mode_box)

        # id format
        id_row = QHBoxLayout()
        self.id_group = QButtonGroup(self)
        self.id_str_rb = QRadioButton("String")
        self.id_int_rb = QRadioButton("Integer (int64)")
        self.id_group.addButton(self.id_str_rb)
        self.id_group.addButton(self.id_int_rb)
        id_row.addWidget(self.id_str_rb)
        id_row.addWidget(self.id_int_rb)
        form.addRow("Cell ID as", id_row)

        # target layer
        self.layer_combo = QComboBox()
        form.addRow("Target layer", self.layer_combo)
        self.binding_label = QLabel("")
        self.binding_label.setWordWrap(True)
        form.addRow("", self.binding_label)

        root.addLayout(form)

        # readout
        self.readout = QLabel("Hover over the map…")
        self.readout.setWordWrap(True)
        self.readout.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.readout.setStyleSheet("font-family: monospace;")
        root.addWidget(self.readout)
        root.addStretch(1)
        self.setWidget(w)

    def _wire(self):
        self.activate_btn.toggled.connect(self.activateToggled)
        self.dggs_combo.currentIndexChanged.connect(self._on_dggs_changed)
        self.res_spin.valueChanged.connect(self._on_res_changed)
        self.res_plus.clicked.connect(lambda: self.step_resolution(+1))
        self.res_minus.clicked.connect(lambda: self.step_resolution(-1))
        self.mode_group.buttonClicked.connect(self._on_mode_changed)
        self.id_group.buttonClicked.connect(lambda _: self._save_and_emit())
        self.layer_combo.currentIndexChanged.connect(self._on_layer_changed)
        proj = QgsProject.instance()
        self._on_layers_changed = lambda _ids: self._refresh_layers()
        proj.layersAdded.connect(self._on_layers_changed)
        proj.layersRemoved.connect(self._on_layers_changed)

    def cleanup(self):
        """Disconnect project signals (call on plugin unload)."""
        proj = QgsProject.instance()
        for sig in (proj.layersAdded, proj.layersRemoved):
            try:
                sig.disconnect(self._on_layers_changed)
            except (TypeError, RuntimeError):
                pass

    # ------------------------------------------------------------------ #
    # settings
    def _load_settings(self):
        s = QgsSettings()
        name = s.value(_SETTINGS + "dggs", "h3")
        if self._availability.get(name) is not None:
            name = next((n for n in backends.ORDER if self._availability[n] is None), name)
        self._set_combo_data(self.dggs_combo, name)
        mode = s.value(_SETTINGS + "mode", L.POLYGON)
        self._mode_buttons.get(mode, self._mode_buttons[L.POLYGON]).setChecked(True)
        idf = s.value(_SETTINGS + "id_format", L.ID_STR)
        (self.id_int_rb if idf == L.ID_INT else self.id_str_rb).setChecked(True)
        self._pending_res = int(s.value(_SETTINGS + "res", 5))

    def _save_settings(self):
        s = QgsSettings()
        s.setValue(_SETTINGS + "dggs", self.backend_name())
        s.setValue(_SETTINGS + "mode", self.mode())
        s.setValue(_SETTINGS + "id_format", self.id_format())
        s.setValue(_SETTINGS + "res", self.resolution())

    def _save_and_emit(self):
        self._save_settings()
        self.settingsChanged.emit()

    @staticmethod
    def _set_combo_data(combo: QComboBox, data):
        idx = combo.findData(data)
        if idx >= 0:
            combo.blockSignals(True)
            combo.setCurrentIndex(idx)
            combo.blockSignals(False)

    # ------------------------------------------------------------------ #
    # accessors
    def backend_name(self) -> str:
        return self.dggs_combo.currentData()

    def backend(self):
        try:
            return backends.get(self.backend_name())
        except backends.BackendUnavailable:
            return None

    def resolution(self) -> int:
        return self.res_spin.value()

    def mode(self) -> str:
        for mode, rb in self._mode_buttons.items():
            if rb.isChecked():
                return mode
        return L.POLYGON

    def id_format(self) -> str:
        return L.ID_INT if self.id_int_rb.isChecked() else L.ID_STR

    def target_layer(self) -> Optional[QgsVectorLayer]:
        """None means 'use / create the scratch layer'."""
        lid = self.layer_combo.currentData()
        if lid in (None, SCRATCH):
            return None
        layer = QgsProject.instance().mapLayer(lid)
        return layer if isinstance(layer, QgsVectorLayer) else None

    # ------------------------------------------------------------------ #
    # behaviour
    def _apply_backend_limits(self):
        b = self.backend()
        if b is None:
            self.res_spin.setEnabled(False)
            self.res_range.setText("")
            return
        self.res_spin.setEnabled(True)
        self.res_spin.blockSignals(True)
        self.res_spin.setRange(b.min_res, b.max_res)
        target = getattr(self, "_pending_res", None)
        if target is None:
            target = self.res_spin.value()
        self._pending_res = None
        self.res_spin.setValue(b.clamp(target))
        self.res_spin.blockSignals(False)
        self.res_range.setText(f"[{b.min_res}–{b.max_res}]")
        self.id_int_rb.setEnabled(b.supports_int_id)
        self.id_int_rb.setToolTip("" if b.supports_int_id else f"{b.label} has no integer cell IDs; string will be stored")
        if not b.supports_int_id:
            self.id_str_rb.setChecked(True)

    def step_resolution(self, delta: int):
        self.res_spin.setValue(self.res_spin.value() + delta)

    def _on_res_changed(self, value):
        self._save_settings()
        self.resolutionChanged.emit(value)

    def _on_mode_changed(self, _btn):
        self._refresh_layers()
        self._save_and_emit()

    def _on_dggs_changed(self, _idx):
        new = self.backend_name()
        layer = self.target_layer()
        if layer is not None:
            bound = L.layer_dggs(layer)
            if bound and bound != new:
                res = QMessageBox.question(
                    self,
                    "Gridclick — DGGS lock",
                    f"Layer '{layer.name()}' holds {backends.LABELS.get(bound, bound)} cells.\n\n"
                    f"A layer can only contain one DGGS. Switch the target to a new "
                    f"{backends.LABELS.get(new, new)} scratch layer?",
                    QMessageBox.Yes | QMessageBox.Cancel,
                    QMessageBox.Cancel,
                )
                if res != QMessageBox.Yes:
                    self._set_combo_data(self.dggs_combo, bound)
                    return
                self._set_combo_data(self.layer_combo, SCRATCH)
        self._pending_res = self.res_spin.value()
        self._apply_backend_limits()
        self._update_binding_label()
        self._save_settings()
        self.backendChanged.emit(new)
        self.settingsChanged.emit()

    def _on_layer_changed(self, _idx):
        layer = self.target_layer()
        if layer is not None:
            bound = L.layer_dggs(layer)
            if bound and bound != self.backend_name() and self._availability.get(bound) is None:
                # layer wins: follow its DGGS
                self._set_combo_data(self.dggs_combo, bound)
                self._pending_res = self.res_spin.value()
                self._apply_backend_limits()
                self.iface.messageBar().pushInfo(
                    "Gridclick", f"Switched DGGS to {backends.LABELS.get(bound, bound)} to match layer '{layer.name()}'."
                )
                self.backendChanged.emit(bound)
        self._update_binding_label()
        self.settingsChanged.emit()

    def _refresh_layers(self):
        try:
            current = self.layer_combo.currentData()
        except RuntimeError:  # widget already deleted (stale signal)
            self.cleanup()
            return
        self.layer_combo.blockSignals(True)
        self.layer_combo.clear()
        self.layer_combo.addItem("<new / existing Gridclick scratch layer>", SCRATCH)
        for layer in L.compatible_layers(self.mode()):
            bound = L.layer_dggs(layer)
            suffix = f"  [{backends.LABELS.get(bound, bound)}]" if bound else ""
            self.layer_combo.addItem(layer.name() + suffix, layer.id())
        idx = self.layer_combo.findData(current)
        self.layer_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.layer_combo.blockSignals(False)
        self._update_binding_label()

    def _update_binding_label(self):
        layer = self.target_layer()
        name = backends.LABELS.get(self.backend_name(), self.backend_name())
        if layer is None:
            self.binding_label.setText(
                f"→ scratch layer “{L.scratch_layer_name(self.backend_name(), self.mode())}” (one layer per DGGS)"
            )
            return
        bound = L.layer_dggs(layer)
        ok, reason = L.check_lock(layer, self.backend_name(), self.mode())
        if ok:
            self.binding_label.setText(f"→ “{layer.name()}” [{backends.LABELS.get(bound, bound) if bound else 'unbound → ' + name}]")
            self.binding_label.setStyleSheet("")
        else:
            self.binding_label.setText("⚠ " + reason)
            self.binding_label.setStyleSheet("color: #b00;")

    # ------------------------------------------------------------------ #
    def show_cell(self, cell: Optional[CellInfo]):
        if cell is None:
            self.readout.setText("Hover over the map…")
            return
        try:
            area = self._area.measureArea(L.polygon_geometry(cell))
            area_txt = QgsDistanceArea.formatArea(area, 3, QgsUnitTypes.AreaSquareMeters, True)
        except Exception:
            area_txt = "?"
        int_txt = f"\nint: {cell.id_int}" if cell.id_int is not None else ""
        self.readout.setText(
            f"{backends.LABELS.get(cell.dggs, cell.dggs)} res {cell.resolution}\n"
            f"id:  {cell.id_str}{int_txt}\n"
            f"centre: {cell.centre[0]:.6f}, {cell.centre[1]:.6f}\n"
            f"area ≈ {area_txt}"
        )

    def set_active(self, active: bool):
        self.activate_btn.blockSignals(True)
        self.activate_btn.setChecked(active)
        self.activate_btn.blockSignals(False)
