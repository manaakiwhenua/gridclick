"""The label palette widget: a table of classes, one row each, with a column
per attribute field.

Fields belong to the palette rather than to individual classes, so the editor
is a grid: adding a column adds it for every class at once, and a blank cell
means NULL for that class. That keeps field names consistent — the previous
per-class key/value editor let a typo invent a whole extra column — and it
looks like the attribute table the labels end up in.
"""
from __future__ import annotations

import re
from typing import List, Optional

from qgis.PyQt.QtCore import QSize, Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor, QIcon, QPixmap
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QColorDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import presets as P

#: fields Gridclick owns; a palette column may not shadow them
RESERVED = {"dggs", "resolution", "cell_id", "cell_id_int"}

CLASS_COLUMN = 0

#: starting column widths, in pixels; the user's own widths win after that
DEFAULT_CLASS_WIDTH = 130
DEFAULT_FIELD_WIDTH = 100

_DIGITS = re.compile(r"(\d+)")


def natural_key(text: str):
    """Sort key that reads embedded numbers as numbers, so "class 2" comes
    before "class 10" rather than after it."""
    parts = [p for p in _DIGITS.split((text or "").strip().casefold()) if p != ""]
    return tuple((1, int(p)) if p.isdigit() else (0, p) for p in parts)


def colour_icon(colour: str, size: int = 14) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(QColor(colour))
    return QIcon(pm)


def field_name_problem(name, existing: List[str], label_field: str) -> str:
    """Why `name` cannot be an attribute column, or "" if it can."""
    if not isinstance(name, str):
        return "An attribute needs a name."
    name = name.strip()
    if not name:
        return "An attribute needs a name."
    if name in RESERVED:
        return f"“{name}” is one of Gridclick's own fields."
    if name == label_field:
        return f"“{name}” is already the label field."
    if name in existing:
        return f"There is already an attribute called “{name}”."
    return ""


class PalettePanel(QWidget):
    """The class table in the dock: pick the active class, edit the palette."""

    #: the palette itself changed (classes, columns, colours, on/off)
    schemaChanged = pyqtSignal()
    #: only the active class changed
    activeChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._schema = P.default_schema()
        #: hotkeys address nine classes at a time; this is which nine
        self._page = 0
        #: suppresses itemChanged while the table is being rebuilt
        self._loading = False
        #: which column the palette is ordered by, and which way
        self._sort_column = -1
        self._sort_descending = False
        #: column widths by column name. Qt happens to carry section sizes
        #: through the rebuild each edit causes, but relying on that is relying
        #: on an implementation detail; holding them here makes the widths
        #: deliberate and gives a new column a sensible starting size.
        self._column_widths = {}
        self._build_ui()
        self._reload()

    # ------------------------------------------------------------------ #
    # construction
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self.enable_cb = QCheckBox("Label cells on click")
        self.enable_cb.setToolTip(
            "Write the selected class (and its attributes) with every cell.\n"
            "Clicking a cell that is already labelled re-labels it."
        )
        self.enable_cb.toggled.connect(self._on_enabled)
        root.addWidget(self.enable_cb)

        self.body = QWidget()
        body = QVBoxLayout(self.body)
        body.setContentsMargins(0, 0, 0, 0)

        field_row = QHBoxLayout()
        field_row.addWidget(QLabel("Label field"))
        self.field_edit = QLineEdit(self._schema.label_field)
        self.field_edit.setToolTip("Field the class name is written to")
        self.field_edit.editingFinished.connect(self._on_label_field_edited)
        field_row.addWidget(self.field_edit, 1)
        body.addLayout(field_row)

        self.table = QTableWidget(0, 1)
        self.table.setToolTip(
            "One row per class, one column per attribute.\n"
            "A blank cell writes NULL for that class.\n"
            "Keys 1–9 select a class while the pick tool is active; "
            "0 moves to the next nine.\n"
            "Click a column heading to sort by it — this reorders the classes, "
            "so the hotkeys move with them."
        )
        self.table.setIconSize(QSize(14, 14))
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        # deliberately NOT setSortingEnabled(True): Qt's own sort reorders the
        # view only, and row position is the hotkey — and the index every edit
        # is written back through. Sorting the palette itself keeps them one
        # and the same thing.
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)   # drag to resize
        # not stretchLastSection: that would make the last column the one
        # column the user cannot size, and with two or three columns that is
        # most of the table
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(48)
        header.setSectionsMovable(False)   # column order is the schema's order
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(True)
        header.sectionClicked.connect(self._on_header_clicked)
        header.sectionResized.connect(self._on_section_resized)
        self.table.currentCellChanged.connect(self._on_current_cell_changed)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.setMinimumHeight(140)
        body.addWidget(self.table, 1)

        self.page_label = QLabel("")
        self.page_label.setWordWrap(True)
        self.page_label.setStyleSheet("color: palette(mid);")
        self.page_label.setVisible(False)
        body.addWidget(self.page_label)

        buttons = QGridLayout()
        self.add_btn = QPushButton("Add class")
        self.remove_btn = QPushButton("Remove class")
        self.colour_btn = QPushButton("Colour…")
        self.up_btn = QToolButton(); self.up_btn.setText("↑")
        self.up_btn.setToolTip("Move up (changes its hotkey)")
        self.down_btn = QToolButton(); self.down_btn.setText("↓")
        self.down_btn.setToolTip("Move down (changes its hotkey)")
        self.add_field_btn = QPushButton("Add attribute")
        self.add_field_btn.setToolTip("Add a column — every class gets the field")
        self.rename_field_btn = QPushButton("Rename attribute")
        self.rename_field_btn.setToolTip("Rename the selected column, keeping its values")
        self.remove_field_btn = QPushButton("Remove attribute")
        self.remove_field_btn.setToolTip("Drop the selected column from every class")
        self.add_btn.clicked.connect(self.add_preset)
        self.remove_btn.clicked.connect(self.remove_current)
        self.colour_btn.clicked.connect(self.pick_colour)
        self.up_btn.clicked.connect(lambda: self._move(-1))
        self.down_btn.clicked.connect(lambda: self._move(+1))
        self.add_field_btn.clicked.connect(self._prompt_add_field)
        self.rename_field_btn.clicked.connect(self.rename_current_field)
        self.remove_field_btn.clicked.connect(self.remove_current_field)
        buttons.addWidget(self.add_btn, 0, 0)
        buttons.addWidget(self.remove_btn, 0, 1)
        buttons.addWidget(self.colour_btn, 0, 2)
        buttons.addWidget(self.up_btn, 0, 3)
        buttons.addWidget(self.down_btn, 0, 4)
        buttons.addWidget(self.add_field_btn, 1, 0, 1, 2)
        buttons.addWidget(self.rename_field_btn, 1, 2, 1, 2)
        buttons.addWidget(self.remove_field_btn, 1, 4, 1, 1)
        body.addLayout(buttons)

        self.provenance_cb = QCheckBox("Record author and time")
        self.provenance_cb.setToolTip(
            f"Add “{P.F_CREATED}” and “{P.F_AUTHOR}” fields, stamped on every label"
        )
        self.provenance_cb.setChecked(self._schema.provenance)
        self.provenance_cb.toggled.connect(self._on_provenance)
        body.addWidget(self.provenance_cb)

        root.addWidget(self.body, 1)
        self.body.setEnabled(False)

    # ------------------------------------------------------------------ #
    # state
    def enabled(self) -> bool:
        return self.enable_cb.isChecked()

    def schema(self) -> Optional[P.PresetSchema]:
        """The active palette, or None when labelling is off."""
        if not self.enabled() or self._schema.is_empty():
            return None
        return self._schema

    def raw_schema(self) -> P.PresetSchema:
        """The edited palette regardless of whether labelling is on."""
        return self._schema

    def set_schema(self, schema: Optional[P.PresetSchema], enable: Optional[bool] = None):
        if schema is not None and not schema.is_empty():
            self._schema = schema.copy()
        blocked = self.enable_cb.blockSignals(True)
        if enable is not None:
            self.enable_cb.setChecked(enable)
        self.enable_cb.blockSignals(blocked)
        self.body.setEnabled(self.enable_cb.isChecked())
        self.field_edit.setText(self._schema.label_field)
        blocked = self.provenance_cb.blockSignals(True)
        self.provenance_cb.setChecked(self._schema.provenance)
        self.provenance_cb.blockSignals(blocked)
        self._reload()
        # loading a palette changes which class is active, even when the row
        # index happens to be the same one
        self.activeChanged.emit()

    def active_preset(self) -> Optional[P.Preset]:
        if not self.enabled():
            return None
        row = self.table.currentRow()
        if 0 <= row < len(self._schema.presets):
            return self._schema.presets[row]
        return None

    # ------------------------------------------------------------------ #
    # paging
    def page_count(self) -> int:
        return max(1, -(-len(self._schema.presets) // P.MAX_HOTKEYS))

    def page(self) -> int:
        return self._page

    def select_index(self, index: int) -> bool:
        """Select the index'th class (0-based, across all pages). The hotkey
        page follows the selection, so the keys always address the nine
        classes around whatever was last picked."""
        if not (0 <= index < len(self._schema.presets)):
            return False
        self.table.setCurrentCell(index, CLASS_COLUMN)
        return True

    def select_hotkey(self, digit: int) -> bool:
        """Select the class behind key `digit + 1` on the current page."""
        if not (0 <= digit < P.MAX_HOTKEYS):
            return False
        return self.select_index(self._page * P.MAX_HOTKEYS + digit)

    def next_page(self) -> bool:
        """Move the hotkeys to the next nine classes and select the first of
        them. False when every class already fits on one page."""
        if self.page_count() <= 1:
            return False
        return self.select_index(((self._page + 1) % self.page_count()) * P.MAX_HOTKEYS)

    # ------------------------------------------------------------------ #
    # painting the table
    def _reload(self):
        row = self.table.currentRow()
        self._loading = True
        self.table.clear()
        self.table.setColumnCount(1 + len(self._schema.fields))
        self.table.setHorizontalHeaderLabels(["Class"] + list(self._schema.fields))
        self.table.setRowCount(len(self._schema.presets))
        self._apply_column_widths()
        for i, preset in enumerate(self._schema.presets):
            name_item = QTableWidgetItem(preset.name)
            name_item.setIcon(colour_icon(preset.colour))
            self.table.setItem(i, CLASS_COLUMN, name_item)
            for col, field_name in enumerate(self._schema.fields, start=1):
                self.table.setItem(i, col, QTableWidgetItem(preset.value(field_name)))
        self._loading = False
        if self._schema.presets:
            self.table.setCurrentCell(
                min(max(row, 0), len(self._schema.presets) - 1), CLASS_COLUMN)
            self._page = self.table.currentRow() // P.MAX_HOTKEYS
        self._page = min(self._page, self.page_count() - 1)
        if 0 <= self._sort_column < self.table.columnCount():
            self.table.horizontalHeader().setSortIndicator(
                self._sort_column,
                Qt.DescendingOrder if self._sort_descending else Qt.AscendingOrder)
        self._renumber()
        self._update_buttons()

    def _column_name(self, column: int) -> Optional[str]:
        if column == CLASS_COLUMN:
            return "Class"
        if 1 <= column <= len(self._schema.fields):
            return self._schema.fields[column - 1]
        return None

    def _apply_column_widths(self):
        for column in range(self.table.columnCount()):
            name = self._column_name(column)
            default = DEFAULT_CLASS_WIDTH if column == CLASS_COLUMN else DEFAULT_FIELD_WIDTH
            self.table.setColumnWidth(column, self._column_widths.get(name, default))

    def _on_section_resized(self, column, _old, new):
        if self._loading:
            return                      # the rebuild restoring them, not the user
        name = self._column_name(column)
        if name is not None:
            self._column_widths[name] = new

    def _renumber(self):
        """Row headers show which nine the keys currently reach."""
        labels = []
        for i in range(len(self._schema.presets)):
            on_page = i // P.MAX_HOTKEYS == self._page
            labels.append(str(i % P.MAX_HOTKEYS + 1) if on_page else "·")
        self.table.setVerticalHeaderLabels(labels)
        self._update_page_label()

    def _update_page_label(self):
        pages = self.page_count()
        if pages <= 1:
            self.page_label.setVisible(False)
            return
        lo = self._page * P.MAX_HOTKEYS + 1
        hi = min(lo + P.MAX_HOTKEYS - 1, len(self._schema.presets))
        self.page_label.setText(
            f"Keys 1–9 → classes {lo}–{hi} (page {self._page + 1} of {pages}); "
            f"key 0 for the next nine"
        )
        self.page_label.setVisible(True)

    def _update_buttons(self):
        row = self.table.currentRow()
        has_row = 0 <= row < len(self._schema.presets)
        self.remove_btn.setEnabled(has_row)
        self.colour_btn.setEnabled(has_row)
        self.up_btn.setEnabled(has_row and row > 0)
        self.down_btn.setEnabled(has_row and row < len(self._schema.presets) - 1)
        on_attribute = self.table.currentColumn() > CLASS_COLUMN
        self.remove_field_btn.setEnabled(on_attribute)
        self.rename_field_btn.setEnabled(on_attribute)

    def _changed(self):
        self._reload()
        self.schemaChanged.emit()

    # ------------------------------------------------------------------ #
    # edits from the table itself
    def _on_item_changed(self, item):
        if self._loading:
            return
        row, col = item.row(), item.column()
        if not (0 <= row < len(self._schema.presets)):
            return
        preset = self._schema.presets[row]
        if col == CLASS_COLUMN:
            name = item.text().strip()
            taken = [p.name for i, p in enumerate(self._schema.presets) if i != row]
            if not name or name in taken:
                QMessageBox.warning(
                    self, "Gridclick",
                    "A class needs a name, and no two classes may share one.")
                self._loading = True
                item.setText(preset.name)
                self._loading = False
                return
            preset.name = name
        else:
            field_name = self._schema.fields[col - 1]
            preset.values[field_name] = item.text().strip()
        self.schemaChanged.emit()

    def _on_current_cell_changed(self, row, _col, prev_row, _prev_col):
        # the hotkeys follow the selection: pick class 23 from the table and
        # 1-9 then address 19-27
        if row >= 0:
            page = row // P.MAX_HOTKEYS
            if page != self._page:
                self._page = page
                self._renumber()
        self._update_buttons()
        if row != prev_row:
            self.activeChanged.emit()

    def _on_header_clicked(self, column):
        """Clicking a heading again reverses it."""
        descending = (column == self._sort_column) and not self._sort_descending
        self.sort_by_column(column, descending)

    def _column_value(self, column: int):
        if column == CLASS_COLUMN:
            return lambda preset: preset.name
        name = self._schema.fields[column - 1]
        return lambda preset: preset.value(name)

    def sort_by_column(self, column: int, descending: bool = False) -> bool:
        """Order the classes by a column. This reorders the palette itself,
        not just the view, so the hotkeys move with the rows — which is the
        point: sorting is how you group the classes you are about to use onto
        the first nine keys. Classes with no value for the column go last
        either way, since they are the NULLs."""
        if not self._schema.presets or not (0 <= column < 1 + len(self._schema.fields)):
            return False
        value_of = self._column_value(column)
        row = self.table.currentRow()
        keep = (self._schema.presets[row]
                if 0 <= row < len(self._schema.presets) else None)

        filled, blank = [], []
        for preset in self._schema.presets:
            (filled if (value_of(preset) or "").strip() else blank).append(preset)
        filled.sort(key=lambda p: natural_key(value_of(p)), reverse=descending)
        self._schema.presets = filled + blank

        self._sort_column, self._sort_descending = column, descending
        self._changed()
        if keep is not None:
            # stay on the class the user was on; its hotkey has moved
            self.select_index(next(i for i, p in enumerate(self._schema.presets)
                                   if p is keep))
        return True

    def rename_current_field(self):
        col = self.table.currentColumn()
        if col <= CLASS_COLUMN or col - 1 >= len(self._schema.fields):
            return False
        old = self._schema.fields[col - 1]
        new, ok = QInputDialog.getText(self, "Gridclick — rename attribute",
                                       "Attribute name:", text=old)
        if not ok or not isinstance(new, str) or new.strip() == old:
            return False
        problem = field_name_problem(new, self._schema.fields, self._schema.label_field)
        if problem:
            QMessageBox.warning(self, "Gridclick", problem)
            return False
        if old in self._column_widths:
            self._column_widths[new.strip()] = self._column_widths.pop(old)
        self._schema.rename_field(old, new)
        self._changed()
        return True

    # ------------------------------------------------------------------ #
    # buttons
    def _on_enabled(self, on: bool):
        self.body.setEnabled(on)
        self.schemaChanged.emit()

    def _on_provenance(self, on: bool):
        self._schema.provenance = on
        self.schemaChanged.emit()

    def _on_label_field_edited(self):
        name = self.field_edit.text().strip()
        if not name or name in RESERVED or name in self._schema.fields:
            QMessageBox.warning(
                self, "Gridclick",
                "The label field must be named, and must not be one of Gridclick's "
                "own fields (" + ", ".join(sorted(RESERVED)) + ") or an attribute "
                "column.",
            )
            self.field_edit.setText(self._schema.label_field)
            return
        if name == self._schema.label_field:
            return
        self._schema.label_field = name
        self.schemaChanged.emit()

    def add_preset(self):
        self._schema.presets.append(
            P.Preset(self._schema.unique_name(), self._schema.next_colour()))
        self._changed()
        self.select_index(len(self._schema.presets) - 1)

    def remove_current(self):
        row = self.table.currentRow()
        if not (0 <= row < len(self._schema.presets)):
            return
        del self._schema.presets[row]
        self._changed()

    def pick_colour(self):
        row = self.table.currentRow()
        if not (0 <= row < len(self._schema.presets)):
            return
        preset = self._schema.presets[row]
        chosen = QColorDialog.getColor(QColor(preset.colour), self, "Class colour")
        if not chosen.isValid():
            return
        preset.colour = chosen.name()
        self._changed()
        self.select_index(row)

    def _move(self, delta: int):
        row = self.table.currentRow()
        new = row + delta
        n = len(self._schema.presets)
        if not (0 <= row < n) or not (0 <= new < n):
            return
        ps = self._schema.presets
        ps[row], ps[new] = ps[new], ps[row]
        self._changed()
        self.select_index(new)

    def _prompt_add_field(self):
        """Button slot. Kept separate from `add_field` because Qt passes the
        button's `checked` state to a clicked handler, and an optional-argument
        slot silently receives that bool instead of the name."""
        name, ok = QInputDialog.getText(self, "Gridclick — add attribute",
                                        "Attribute name:")
        if not ok:
            return False
        return self.add_field(name)

    def add_field(self, name: str) -> bool:
        """Add an attribute column. Every class gains the field; the ones that
        leave it blank write NULL."""
        problem = field_name_problem(name, self._schema.fields, self._schema.label_field)
        if problem:
            QMessageBox.warning(self, "Gridclick", problem)
            return False
        self._schema.add_field(name)
        self._changed()
        return True

    def remove_current_field(self):
        col = self.table.currentColumn()
        if col <= CLASS_COLUMN or col - 1 >= len(self._schema.fields):
            return
        name = self._schema.fields[col - 1]
        answer = QMessageBox.question(
            self, "Gridclick — remove attribute",
            f"Remove the attribute “{name}” from every class?\n\n"
            "Values already written to the layer are left alone.",
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel,
        )
        if answer != QMessageBox.Yes:
            return
        self._schema.remove_field(name)
        self._changed()
