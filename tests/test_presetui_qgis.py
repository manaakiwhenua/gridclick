"""Headless tests for the label palette table. Modal dialogs are patched out
so validation can be exercised without a user.
Run:  QT_QPA_PLATFORM=offscreen python -m pytest tests/test_presetui_qgis.py
"""
import os, sys
from contextlib import contextmanager

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
pytest.importorskip("qgis.gui")
from qgis.PyQt.QtCore import Qt  # noqa: E402
from qgis.PyQt.QtWidgets import QMessageBox  # noqa: E402

from gridclick import presets as P  # noqa: E402
from gridclick import presetui as UI  # noqa: E402


@contextmanager
def no_warnings():
    """Swallow the modal warnings so validation can be checked headlessly."""
    seen = []
    original = UI.QMessageBox.warning
    UI.QMessageBox.warning = staticmethod(lambda *a, **k: seen.append(a[2] if len(a) > 2 else ""))
    try:
        yield seen
    finally:
        UI.QMessageBox.warning = original


@contextmanager
def answer_prompt(text, accepted=True):
    original = UI.QInputDialog.getText
    UI.QInputDialog.getText = staticmethod(lambda *a, **k: (text, accepted))
    try:
        yield
    finally:
        UI.QInputDialog.getText = original


@contextmanager
def pick_colour(name):
    from qgis.PyQt.QtGui import QColor
    original = UI.QColorDialog.getColor
    UI.QColorDialog.getColor = staticmethod(lambda *a, **k: QColor(name))
    try:
        yield
    finally:
        UI.QColorDialog.getColor = original


@contextmanager
def confirm_all():
    original = UI.QMessageBox.question
    UI.QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
    try:
        yield
    finally:
        UI.QMessageBox.question = original


def schema():
    return P.PresetSchema(
        label_field="class",
        fields=["confidence", "source"],
        presets=[
            P.Preset("schools", "#E69F00", {"confidence": "high", "source": "imagery"}),
            P.Preset("absent", "#56B4E9", {"confidence": "high"}),
        ],
    )


def big_schema(n=23):
    return P.PresetSchema(label_field="class",
                          presets=[P.Preset(f"c{i:02d}") for i in range(1, n + 1)])


def panel_with(s, enable=True):
    panel = UI.PalettePanel()
    panel.set_schema(s, enable=enable)
    return panel


def cell(panel, row, col):
    item = panel.table.item(row, col)
    return item.text() if item is not None else None


# --------------------------------------------------------------------------- #
# the table shape
# --------------------------------------------------------------------------- #
def test_a_column_per_field_and_a_row_per_class(qgis_app):
    panel = panel_with(schema())
    assert panel.table.rowCount() == 2
    assert panel.table.columnCount() == 3            # Class + two attributes
    headers = [panel.table.horizontalHeaderItem(c).text()
               for c in range(panel.table.columnCount())]
    assert headers == ["Class", "confidence", "source"]
    assert cell(panel, 0, 0) == "schools"
    assert cell(panel, 0, 2) == "imagery"
    assert cell(panel, 1, 2) == ""                   # blank -> NULL for "absent"


def test_adding_an_attribute_adds_it_for_every_class(qgis_app):
    panel = panel_with(schema())
    seen = []
    panel.schemaChanged.connect(lambda: seen.append(1))
    assert panel.add_field("name")
    assert panel.raw_schema().fields == ["confidence", "source", "name"]
    assert panel.table.columnCount() == 4
    for row in range(panel.table.rowCount()):
        assert cell(panel, row, 3) == ""             # null until filled in
    assert panel.raw_schema().field_names() == [
        "class", "confidence", "source", "name", P.F_CREATED, P.F_AUTHOR]
    assert seen


def test_the_add_attribute_button_prompts_for_a_name(qgis_app):
    """Regression: Qt hands a clicked handler the button's `checked` state, so
    an optional-argument slot receives False instead of the name and skips the
    prompt entirely. Drive the button, not the method behind it."""
    panel = panel_with(schema())
    with answer_prompt("name"):
        panel.add_field_btn.click()
    assert panel.raw_schema().fields == ["confidence", "source", "name"]
    assert panel.table.columnCount() == 4

    with answer_prompt("cancelled", accepted=False):
        panel.add_field_btn.click()
    assert panel.raw_schema().fields == ["confidence", "source", "name"]


def test_every_palette_button_survives_being_clicked(qgis_app):
    """Every button goes through Qt's clicked(bool) signature; none of them
    may choke on the argument or on an empty selection."""
    panel = panel_with(schema())
    buttons = [panel.add_btn, panel.remove_btn, panel.colour_btn, panel.up_btn,
               panel.down_btn, panel.add_field_btn, panel.rename_field_btn,
               panel.remove_field_btn]
    for select_something in (True, False):
        for button in buttons:
            if select_something:
                panel.select_index(0)
                panel.table.setCurrentCell(0, 1)
            else:
                panel.table.setCurrentCell(-1, -1)
            with answer_prompt("extra"), pick_colour("#123456"), confirm_all(), no_warnings():
                button.click()          # must not raise


def test_an_attribute_cannot_shadow_our_fields_or_the_label(qgis_app):
    panel = panel_with(schema())
    for bad in ["cell_id", "dggs", "class", "confidence", "  "]:
        with no_warnings() as told:
            assert not panel.add_field(bad)
        assert told
    assert panel.raw_schema().fields == ["confidence", "source"]


def test_removing_an_attribute_drops_it_from_every_class(qgis_app):
    panel = panel_with(schema())
    panel.table.setCurrentCell(0, 1)                 # the "confidence" column
    with confirm_all():
        panel.remove_current_field()
    assert panel.raw_schema().fields == ["source"]
    assert all("confidence" not in p.values for p in panel.raw_schema().presets)
    assert panel.table.columnCount() == 2


def test_the_class_column_is_not_an_attribute(qgis_app):
    panel = panel_with(schema())
    panel.table.setCurrentCell(0, UI.CLASS_COLUMN)
    assert not panel.remove_field_btn.isEnabled()
    with confirm_all():
        panel.remove_current_field()                 # must be a no-op
    assert panel.raw_schema().fields == ["confidence", "source"]


def test_renaming_a_column_carries_the_values(qgis_app):
    panel = panel_with(schema())
    panel.table.setCurrentCell(0, 2)                 # the "source" column
    with answer_prompt("origin"):
        assert panel.rename_field_btn.click() is None
    assert panel.raw_schema().fields == ["confidence", "origin"]
    assert panel.raw_schema().get("schools").values["origin"] == "imagery"
    assert cell(panel, 0, 2) == "imagery"


def test_renaming_a_column_to_a_taken_name_is_refused(qgis_app):
    panel = panel_with(schema())
    panel.table.setCurrentCell(0, 2)
    with answer_prompt("confidence"), no_warnings() as told:
        panel.rename_current_field()
    assert told and panel.raw_schema().fields == ["confidence", "source"]


# --------------------------------------------------------------------------- #
# sorting
# --------------------------------------------------------------------------- #
def sortable():
    return P.PresetSchema(
        label_field="class",
        fields=["confidence"],
        presets=[
            P.Preset("water", "#1", {"confidence": "low"}),
            P.Preset("class 10", "#2", {}),
            P.Preset("Alpine", "#3", {"confidence": "high"}),
            P.Preset("class 2", "#4", {"confidence": "medium"}),
        ],
    )


def names(panel):
    return [p.name for p in panel.raw_schema().presets]


def test_clicking_a_heading_sorts_the_classes(qgis_app):
    panel = panel_with(sortable())
    panel.table.horizontalHeader().sectionClicked.emit(UI.CLASS_COLUMN)
    assert names(panel) == ["Alpine", "class 2", "class 10", "water"]
    assert cell(panel, 0, 0) == "Alpine"


def test_a_real_click_on_the_heading_sorts(qgis_app):
    """Emitting sectionClicked only proves the connection; this proves Qt will
    emit it, i.e. that the header is actually clickable."""
    from qgis.PyQt.QtCore import QPoint
    from qgis.PyQt.QtTest import QTest

    panel = panel_with(sortable())
    panel.resize(600, 300)
    panel.show()
    QTest.qWaitForWindowExposed(panel)
    header = panel.table.horizontalHeader()
    assert header.sectionsClickable()
    x = header.sectionPosition(UI.CLASS_COLUMN) + header.sectionSize(UI.CLASS_COLUMN) // 2
    try:
        QTest.mouseClick(header.viewport(), Qt.LeftButton, Qt.NoModifier,
                         QPoint(x, header.height() // 2))
    finally:
        panel.close()
    assert names(panel) == ["Alpine", "class 2", "class 10", "water"]


def test_sorting_is_case_insensitive_and_reads_numbers_as_numbers(qgis_app):
    panel = panel_with(sortable())
    panel.sort_by_column(UI.CLASS_COLUMN)
    # "Alpine" before "water" despite the capital; "class 2" before "class 10"
    assert names(panel) == ["Alpine", "class 2", "class 10", "water"]


def test_clicking_the_same_heading_reverses_it(qgis_app):
    panel = panel_with(sortable())
    header = panel.table.horizontalHeader()
    header.sectionClicked.emit(UI.CLASS_COLUMN)
    header.sectionClicked.emit(UI.CLASS_COLUMN)
    assert names(panel) == ["water", "class 10", "class 2", "Alpine"]
    assert header.sortIndicatorOrder() == Qt.DescendingOrder
    header.sectionClicked.emit(UI.CLASS_COLUMN)
    assert names(panel) == ["Alpine", "class 2", "class 10", "water"]
    assert header.sortIndicatorOrder() == Qt.AscendingOrder


def test_sorting_a_different_column_starts_ascending(qgis_app):
    panel = panel_with(sortable())
    header = panel.table.horizontalHeader()
    header.sectionClicked.emit(UI.CLASS_COLUMN)
    header.sectionClicked.emit(UI.CLASS_COLUMN)      # now descending
    header.sectionClicked.emit(1)                    # a different column
    assert header.sortIndicatorOrder() == Qt.AscendingOrder
    assert header.sortIndicatorSection() == 1


def test_classes_with_no_value_sort_last_either_way(qgis_app):
    panel = panel_with(sortable())
    panel.sort_by_column(1)                          # "confidence"
    assert names(panel) == ["Alpine", "water", "class 2", "class 10"]
    panel.sort_by_column(1, descending=True)
    # "class 10" is the only blank; it stays at the end, not flipped to front
    assert names(panel)[-1] == "class 10"
    assert names(panel)[:3] == ["class 2", "water", "Alpine"]


def test_sorting_remaps_the_hotkeys(qgis_app):
    panel = panel_with(sortable())
    assert panel.select_hotkey(0) and panel.active_preset().name == "water"
    panel.sort_by_column(UI.CLASS_COLUMN)
    # key 1 now reaches whatever sorted to the top
    assert panel.select_hotkey(0) and panel.active_preset().name == "Alpine"
    assert panel.select_hotkey(3) and panel.active_preset().name == "water"


def test_sorting_keeps_you_on_the_class_you_were_on(qgis_app):
    panel = panel_with(sortable())
    panel.select_index(0)
    assert panel.active_preset().name == "water"
    panel.sort_by_column(UI.CLASS_COLUMN)
    assert panel.active_preset().name == "water"     # moved to row 3, still current
    assert panel.table.currentRow() == 3


def test_sorting_is_a_palette_change(qgis_app):
    """The order is persisted with the layer, so it has to be announced."""
    panel = panel_with(sortable())
    seen = []
    panel.schemaChanged.connect(lambda: seen.append(1))
    panel.sort_by_column(UI.CLASS_COLUMN)
    assert seen


def test_sorting_an_empty_or_bad_column_is_a_no_op(qgis_app):
    panel = panel_with(sortable())
    assert not panel.sort_by_column(9)
    empty = UI.PalettePanel()
    empty._schema.presets = []
    assert not empty.sort_by_column(UI.CLASS_COLUMN)


# --------------------------------------------------------------------------- #
# column widths
# --------------------------------------------------------------------------- #
def shown(panel):
    """A panel laid out wide enough for column widths to mean something."""
    panel.resize(700, 300)
    panel.show()
    return panel


def test_columns_can_be_dragged_wider(qgis_app):
    panel = shown(panel_with(schema()))
    header = panel.table.horizontalHeader()
    try:
        last = panel.table.columnCount() - 1
        for column in range(panel.table.columnCount()):
            assert header.sectionResizeMode(column) == UI.QHeaderView.Interactive
        # every column is draggable, the last one included
        assert not header.stretchLastSection()
        panel.table.setColumnWidth(last, 160)
        assert panel.table.columnWidth(last) == 160
        assert not header.sectionsMovable()       # column order is the schema's
    finally:
        panel.close()


def test_a_width_the_user_set_survives_an_edit(qgis_app):
    """Every edit rebuilds the table. Widths must come back either way — Qt
    carries section sizes over, and the panel restores them explicitly rather
    than depending on that."""
    panel = shown(panel_with(schema()))
    try:
        panel.table.setColumnWidth(1, 210)        # as if dragged
        assert panel._column_widths["confidence"] == 210
        panel.table.item(0, 0).setText("school grounds")   # triggers a rebuild
        assert panel.table.columnWidth(1) == 210
        panel.add_field("name")                   # and a structural change
        assert panel.table.columnWidth(1) == 210
        panel.sort_by_column(UI.CLASS_COLUMN)     # and a sort
        assert panel.table.columnWidth(1) == 210
        panel.set_schema(schema(), enable=True)   # and reloading the palette
        assert panel.table.columnWidth(1) == 210
        panel.table.setCurrentCell(0, 2)
        with confirm_all():
            panel.remove_current_field()          # and dropping another column
        assert panel.table.columnWidth(1) == 210
    finally:
        panel.close()


def test_a_renamed_column_keeps_its_width(qgis_app):
    panel = shown(panel_with(schema()))
    try:
        panel.table.setColumnWidth(1, 175)
        panel.table.setCurrentCell(0, 1)
        with answer_prompt("certainty"):
            panel.rename_current_field()
        assert panel.raw_schema().fields == ["certainty", "source"]
        assert panel.table.columnWidth(1) == 175
    finally:
        panel.close()


def test_a_new_column_gets_a_default_width(qgis_app):
    panel = shown(panel_with(schema()))
    try:
        panel.add_field("name")
        assert "name" not in panel._column_widths
        assert panel.table.columnWidth(1) == UI.DEFAULT_FIELD_WIDTH
        assert panel.table.columnWidth(UI.CLASS_COLUMN) == UI.DEFAULT_CLASS_WIDTH
    finally:
        panel.close()


# --------------------------------------------------------------------------- #
# editing cells
# --------------------------------------------------------------------------- #
def test_typing_in_a_cell_updates_the_class(qgis_app):
    panel = panel_with(schema())
    panel.table.item(1, 2).setText("field survey")
    assert panel.raw_schema().get("absent").values["source"] == "field survey"


def test_renaming_a_class_in_place(qgis_app):
    panel = panel_with(schema())
    panel.table.item(0, 0).setText("school grounds")
    assert [p.name for p in panel.raw_schema().presets] == ["school grounds", "absent"]


def test_a_blank_or_duplicate_class_name_is_refused(qgis_app):
    panel = panel_with(schema())
    with no_warnings() as told:
        panel.table.item(0, 0).setText("   ")
    assert told and panel.raw_schema().presets[0].name == "schools"
    assert cell(panel, 0, 0) == "schools"            # the cell is put back
    with no_warnings() as told:
        panel.table.item(0, 0).setText("absent")
    assert told and panel.raw_schema().presets[0].name == "schools"


# --------------------------------------------------------------------------- #
# the panel as a whole
# --------------------------------------------------------------------------- #
def test_panel_is_off_until_enabled(qgis_app):
    panel = UI.PalettePanel()
    assert panel.schema() is None
    assert panel.active_preset() is None
    assert not panel.raw_schema().is_empty()
    panel.set_schema(schema(), enable=True)
    assert panel.schema() is not None
    assert panel.active_preset().name == "schools"


def test_loading_a_palette_announces_the_active_class(qgis_app):
    panel = UI.PalettePanel()
    seen = []
    panel.activeChanged.connect(lambda: seen.append(1))
    panel.set_schema(schema(), enable=True)
    assert seen
    assert panel.active_preset().name == "schools"


def test_add_remove_and_reorder_classes(qgis_app):
    panel = panel_with(schema())
    panel.add_preset()
    assert len(panel.raw_schema().presets) == 3
    assert panel.active_preset() is panel.raw_schema().presets[2]
    panel.select_index(0)
    panel.remove_current()
    assert [p.name for p in panel.raw_schema().presets][0] == "absent"
    panel.select_index(1)
    panel._move(-1)
    assert [p.name for p in panel.raw_schema().presets][0] != "absent"


def test_label_field_cannot_clash(qgis_app):
    panel = panel_with(schema())
    for bad in ["cell_id", "confidence", ""]:
        panel.field_edit.setText(bad)
        with no_warnings() as told:
            panel._on_label_field_edited()
        assert told
        assert panel.raw_schema().label_field == "class"
        assert panel.field_edit.text() == "class"
    panel.field_edit.setText("land_cover")
    panel._on_label_field_edited()
    assert panel.raw_schema().label_field == "land_cover"


# --------------------------------------------------------------------------- #
# more classes than hotkeys
# --------------------------------------------------------------------------- #
def test_one_page_when_nine_or_fewer(qgis_app):
    panel = panel_with(big_schema(9))
    assert panel.page_count() == 1
    assert panel.page_label.isHidden()
    assert not panel.next_page()
    assert panel.active_preset().name == "c01"


def test_hotkeys_address_the_current_page(qgis_app):
    panel = panel_with(big_schema(23))
    assert panel.page_count() == 3
    assert panel.select_hotkey(0) and panel.active_preset().name == "c01"
    assert panel.select_hotkey(8) and panel.active_preset().name == "c09"
    panel.next_page()
    assert panel.page() == 1 and panel.active_preset().name == "c10"
    assert panel.select_hotkey(3) and panel.active_preset().name == "c13"
    panel.next_page()
    assert panel.page() == 2 and panel.active_preset().name == "c19"
    assert panel.select_hotkey(4) and panel.active_preset().name == "c23"
    assert not panel.select_hotkey(5)
    assert panel.active_preset().name == "c23"
    panel.next_page()
    assert panel.page() == 0 and panel.active_preset().name == "c01"


def test_row_headers_show_which_nine_the_keys_reach(qgis_app):
    panel = panel_with(big_schema(23))
    def header(i):
        return panel.table.verticalHeaderItem(i).text()
    assert header(0) == "1" and header(8) == "9"
    assert header(9) == "·"
    panel.next_page()
    assert header(0) == "·" and header(9) == "1" and header(17) == "9"
    assert "classes 10–18" in panel.page_label.text()
    assert "page 2 of 3" in panel.page_label.text()
    assert not panel.page_label.isHidden()


def test_page_follows_a_click_in_the_table(qgis_app):
    panel = panel_with(big_schema(23))
    panel.select_index(20)
    assert panel.active_preset().name == "c21" and panel.page() == 2
    assert panel.select_hotkey(0) and panel.active_preset().name == "c19"


def test_page_is_clamped_when_classes_are_removed(qgis_app):
    panel = panel_with(big_schema(10))
    panel.next_page()
    assert panel.page() == 1 and panel.active_preset().name == "c10"
    panel.remove_current()
    assert panel.page_count() == 1 and panel.page() == 0
    assert panel.table.verticalHeaderItem(0).text() == "1"
    assert panel.page_label.isHidden()
