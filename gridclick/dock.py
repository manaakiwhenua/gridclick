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
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import backends
from . import layers as L
from . import presets as P
from .backends.base import CellInfo
from .presetui import PalettePanel

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

        # target layer
        self.layer_combo = QComboBox()
        form.addRow("Target layer", self.layer_combo)
        self.binding_label = QLabel("")
        self.binding_label.setWordWrap(True)
        form.addRow("", self.binding_label)
        self.fixfields_btn = QPushButton("Add the missing fields to this layer")
        self.fixfields_btn.setVisible(False)
        form.addRow("", self.fixfields_btn)

        root.addLayout(form)

        # label palette
        self.palette = PalettePanel()
        group = QGroupBox("Labels")
        gl = QVBoxLayout(group)
        gl.setContentsMargins(6, 6, 6, 6)
        gl.addWidget(self.palette)
        root.addWidget(group, 1)      # takes the slack, so the table fills down

        # readout
        self.readout = QLabel("")
        self.readout.setWordWrap(True)
        self.readout.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.readout.setStyleSheet("font-family: monospace;")
        root.addWidget(self.readout)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(w)
        self.setWidget(scroll)

    def _wire(self):
        self.activate_btn.toggled.connect(self.activateToggled)
        self.dggs_combo.currentIndexChanged.connect(self._on_dggs_changed)
        self.res_spin.valueChanged.connect(self._on_res_changed)
        self.res_plus.clicked.connect(lambda: self.step_resolution(+1))
        self.res_minus.clicked.connect(lambda: self.step_resolution(-1))
        self.mode_group.buttonClicked.connect(self._on_mode_changed)
        self.layer_combo.currentIndexChanged.connect(self._on_layer_changed)
        self.palette.schemaChanged.connect(self._on_schema_changed)
        self.palette.activeChanged.connect(self.settingsChanged)
        self.fixfields_btn.clicked.connect(self._add_missing_fields)
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
        self._pending_res = int(s.value(_SETTINGS + "res", 5))
        schema = P.PresetSchema.from_json(s.value(_SETTINGS + "presets", ""))
        labelling = str(s.value(_SETTINGS + "labelling", "false")).lower() == "true"
        self.palette.set_schema(schema, enable=labelling)

    def _save_settings(self):
        s = QgsSettings()
        s.setValue(_SETTINGS + "dggs", self.backend_name())
        s.setValue(_SETTINGS + "mode", self.mode())
        s.setValue(_SETTINGS + "res", self.resolution())
        s.setValue(_SETTINGS + "presets", self.palette.raw_schema().to_json())
        s.setValue(_SETTINGS + "labelling", self.palette.enabled())

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

    def schema(self):
        """Active label schema, or None when labelling is off."""
        return self.palette.schema()

    def active_preset(self):
        return self.palette.active_preset()

    def click_attributes(self) -> dict:
        """field -> value that the next click should write."""
        return P.attributes_for(self.schema(), self.active_preset())

    def on_existing(self) -> str:
        """Labelling keeps one feature per cell, so a repeat click re-labels;
        plain picking appends as before."""
        return L.ON_UPDATE if self.schema() is not None else L.ON_ADD

    def select_preset(self, index: int) -> bool:
        """Select the class behind hotkey `index + 1` on the current page."""
        return self.palette.select_hotkey(index)

    def next_preset_page(self) -> bool:
        """Point the 1-9 hotkeys at the next nine classes."""
        return self.palette.next_page()

    def effective_layer(self) -> Optional[QgsVectorLayer]:
        """The layer a click would land in, if it already exists."""
        layer = self.target_layer()
        if layer is not None:
            return layer
        return L.find_scratch_layer(self.backend_name(), self.mode())

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
            stored = P.load_schema(layer)
            if stored is not None and not stored.is_empty():
                # the schema belongs to the dataset: follow it, don't overwrite
                self.palette.set_schema(stored, enable=True)
                self._save_settings()
                self.iface.messageBar().pushInfo(
                    "Gridclick", f"Loaded label classes from '{layer.name()}'."
                )
        self._update_binding_label()
        self.settingsChanged.emit()

    def _on_schema_changed(self):
        self._save_settings()
        self.sync_scratch_schema()
        self._update_binding_label()
        self.settingsChanged.emit()

    def sync_scratch_schema(self, layer: Optional[QgsVectorLayer] = None):
        """Keep a Gridclick scratch layer in step with the palette: its fields,
        its stored schema and its categorised style. Layers the user brought
        are left alone — see `_add_missing_fields` for those."""
        layer = layer if layer is not None else self.effective_layer()
        if layer is None or not L.is_scratch_layer(layer):
            return
        schema = self.schema()
        if schema is None:
            # labelling switched off: stop writing labels, but leave the
            # layer's stored palette and categorised style alone — the data
            # it already holds still needs them to be readable
            return
        P.add_missing_fields(layer, schema)
        P.save_schema(layer, schema)
        L.style_scratch_layer(layer, self.backend_name(), self.mode(), schema)

    def _add_missing_fields(self):
        layer = self.target_layer()
        schema = self.schema()
        if layer is None or schema is None:
            return
        missing = P.missing_fields(layer, schema)
        if not missing:
            return
        answer = QMessageBox.question(
            self,
            "Gridclick — add fields",
            f"Add the field(s) {', '.join(missing)} to layer '{layer.name()}'?\n\n"
            "This changes the layer's structure.",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if answer != QMessageBox.Yes:
            return
        added, err = P.add_missing_fields(layer, schema)
        if err:
            self.iface.messageBar().pushWarning("Gridclick", err)
        else:
            self.iface.messageBar().pushInfo(
                "Gridclick", f"Added {', '.join(added)} to '{layer.name()}'."
            )
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
        schema = self.schema()
        if layer is None:
            # targeting the scratch layer: the combo already says so
            self.fixfields_btn.setVisible(False)
            self.binding_label.setText("")
            self.binding_label.setStyleSheet("")
            return
        self.fixfields_btn.setVisible(bool(P.missing_fields(layer, schema)))
        bound = L.layer_dggs(layer)
        ok, reason = L.check_lock(layer, self.backend_name(), self.mode(), schema)
        if ok:
            self.binding_label.setText(f"→ “{layer.name()}” [{backends.LABELS.get(bound, bound) if bound else 'unbound → ' + name}]")
            self.binding_label.setStyleSheet("")
        else:
            self.binding_label.setText("⚠ " + reason)
            self.binding_label.setStyleSheet("color: #b00;")

    # ------------------------------------------------------------------ #
    def show_cell(self, cell: Optional[CellInfo]):
        if cell is None:
            self.readout.setText("")
            return
        try:
            area = self._area.measureArea(L.polygon_geometry(cell))
            area_txt = QgsDistanceArea.formatArea(area, 3, QgsUnitTypes.AreaSquareMeters, True)
        except Exception:
            area_txt = "?"
        int_txt = f"\nint: {cell.id_int}" if cell.id_int is not None else ""
        preset = self.active_preset()
        label_txt = f"\nlabel: {preset.name}" if preset is not None else ""
        self.readout.setText(
            f"{backends.LABELS.get(cell.dggs, cell.dggs)} res {cell.resolution}\n"
            f"id:  {cell.id_str}{int_txt}\n"
            f"centre: {cell.centre[0]:.6f}, {cell.centre[1]:.6f}\n"
            f"area ≈ {area_txt}{label_txt}"
        )

    def set_active(self, active: bool):
        self.activate_btn.blockSignals(True)
        self.activate_btn.setChecked(active)
        self.activate_btn.blockSignals(False)
