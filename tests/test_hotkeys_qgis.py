"""Tests for the application-level label hotkeys.

These exist because the earlier tests emitted the tool's signals directly and
so never checked that a key press actually reaches the palette — which it did
not, whenever the map canvas lacked keyboard focus.
Run:  QT_QPA_PLATFORM=offscreen python -m pytest tests/test_hotkeys_qgis.py
"""
import os, sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
pytest.importorskip("qgis.gui")
from qgis.PyQt.QtCore import QEvent, Qt  # noqa: E402
from qgis.PyQt.QtGui import QKeyEvent  # noqa: E402
from qgis.PyQt.QtWidgets import (  # noqa: E402
    QComboBox, QDialog, QLineEdit, QPlainTextEdit, QPushButton, QSpinBox,
)

from gridclick.hotkeys import HotkeyFilter, is_text_entry  # noqa: E402


def press(key, modifiers=Qt.NoModifier):
    return QKeyEvent(QEvent.KeyPress, key, modifiers)


def release(key):
    return QKeyEvent(QEvent.KeyRelease, key, Qt.NoModifier)


def recorder():
    calls = {"digit": [], "page": 0}

    def on_digit(i):
        calls["digit"].append(i)
        return True

    def on_page():
        calls["page"] += 1
        return True

    return HotkeyFilter(on_digit, on_page), calls


# --------------------------------------------------------------------------- #
def test_digits_where_a_digit_cannot_be_typed(qgis_app):
    filt, calls = recorder()
    button = QPushButton()
    assert filt.eventFilter(button, press(Qt.Key_1))
    assert filt.eventFilter(button, press(Qt.Key_9))
    assert calls["digit"] == [0, 8]
    assert filt.eventFilter(button, press(Qt.Key_0))
    assert calls["page"] == 1


def test_keypad_digits_count_too(qgis_app):
    filt, calls = recorder()
    assert filt.eventFilter(QPushButton(), press(Qt.Key_4, Qt.KeypadModifier))
    assert calls["digit"] == [3]


@pytest.mark.parametrize("widget_type", [QLineEdit, QSpinBox, QPlainTextEdit])
def test_typing_a_number_is_left_alone(qgis_app, widget_type):
    filt, calls = recorder()
    widget = widget_type()
    assert is_text_entry(widget)
    assert not filt.eventFilter(widget, press(Qt.Key_3))
    assert calls["digit"] == []


def test_editable_combo_is_text_entry_but_a_plain_one_is_not(qgis_app):
    plain, editable = QComboBox(), QComboBox()
    editable.setEditable(True)
    assert not is_text_entry(plain) and is_text_entry(editable)
    filt, calls = recorder()
    assert not filt.eventFilter(editable, press(Qt.Key_3))
    assert filt.eventFilter(plain, press(Qt.Key_3))
    assert calls["digit"] == [2]


def test_the_class_table_itself_is_not_text_entry(qgis_app):
    """Focus normally sits in the palette table once you have edited it, so
    the digits must still get through from there."""
    from gridclick.presetui import PalettePanel
    panel = PalettePanel()
    assert not is_text_entry(panel.table)
    filt, calls = recorder()
    assert filt.eventFilter(panel.table, press(Qt.Key_0))
    assert filt.eventFilter(panel.table, press(Qt.Key_2))
    assert calls["page"] == 1 and calls["digit"] == [1]


def test_modified_digits_are_left_to_qgis(qgis_app):
    filt, calls = recorder()
    button = QPushButton()
    for mods in (Qt.ControlModifier, Qt.AltModifier, Qt.ShiftModifier,
                 Qt.ControlModifier | Qt.ShiftModifier):
        assert not filt.eventFilter(button, press(Qt.Key_2, mods))
    assert calls["digit"] == []


def test_non_digit_and_non_press_events_pass_through(qgis_app):
    filt, calls = recorder()
    button = QPushButton()
    assert not filt.eventFilter(button, press(Qt.Key_A))
    assert not filt.eventFilter(button, press(Qt.Key_Plus))
    assert not filt.eventFilter(button, release(Qt.Key_3))
    assert calls["digit"] == []


def test_a_modal_dialog_keeps_its_keys(qgis_app):
    dialog = QDialog()
    dialog.setModal(True)
    dialog.show()
    try:
        from qgis.PyQt.QtWidgets import QApplication
        if QApplication.activeModalWidget() is None:
            pytest.skip("no modal stack in this offscreen session")
        filt, calls = recorder()
        assert not filt.eventFilter(QPushButton(), press(Qt.Key_3))
        assert calls["digit"] == []
    finally:
        dialog.close()


def test_the_key_is_only_swallowed_when_it_meant_something(qgis_app):
    """A digit past the end of the palette must still reach QGIS."""
    filt = HotkeyFilter(lambda _i: False, lambda: False)
    assert not filt.eventFilter(QPushButton(), press(Qt.Key_7))
    assert not filt.eventFilter(QPushButton(), press(Qt.Key_0))


def test_install_and_remove_are_idempotent(qgis_app):
    filt, _ = recorder()
    filt.install(); filt.install()
    filt.remove(); filt.remove()


# --------------------------------------------------------------------------- #
# competing shortcuts
# --------------------------------------------------------------------------- #
def test_shortcut_override_is_claimed_for_our_digits(qgis_app):
    filt, calls = recorder()
    event = QKeyEvent(QEvent.ShortcutOverride, Qt.Key_3, Qt.NoModifier)
    assert filt.eventFilter(QPushButton(), event)
    assert event.isAccepted()
    assert calls["digit"] == []      # the override only claims; the KeyPress acts


def test_shortcut_override_is_declined_when_labelling_is_off(qgis_app):
    filt = HotkeyFilter(lambda _i: True, lambda: True, lambda: False)
    event = QKeyEvent(QEvent.ShortcutOverride, Qt.Key_3, Qt.NoModifier)
    assert not filt.eventFilter(QPushButton(), event)


def test_shortcut_override_obeys_the_same_guards(qgis_app):
    filt, _ = recorder()
    for widget, key, mods in [
        (QLineEdit(), Qt.Key_3, Qt.NoModifier),
        (QPushButton(), Qt.Key_3, Qt.ControlModifier),
        (QPushButton(), Qt.Key_A, Qt.NoModifier),
    ]:
        event = QKeyEvent(QEvent.ShortcutOverride, key, mods)
        assert not filt.eventFilter(widget, event)


def test_a_bare_digit_shortcut_cannot_steal_the_key(qgis_app):
    """Regression: a QAction bound to a bare digit makes Qt fire the shortcut
    and never deliver a KeyPress, so no event filter ever sees the key. This
    is what left 1-9 dead while 0 (bound to nothing) worked."""
    from qgis.PyQt.QtGui import QKeySequence
    from qgis.PyQt.QtTest import QTest
    from qgis.PyQt.QtWidgets import QAction, QApplication, QMainWindow

    win = QMainWindow()
    button = QPushButton(win)
    win.setCentralWidget(button)
    fired = []
    rival = QAction("rival", win)
    rival.setShortcut(QKeySequence("3"))
    rival.triggered.connect(lambda: fired.append(1))
    win.addAction(rival)
    win.show()
    QApplication.setActiveWindow(win)
    QTest.qWaitForWindowExposed(win)
    qgis_app.processEvents()
    button.setFocus()

    # first, with labelling off: the rival shortcut must still work. This also
    # proves the shortcut really is live here, so the next half means something
    off = HotkeyFilter(lambda _i: True, lambda: True, lambda: False)
    off.install()
    try:
        QTest.keyClick(button, Qt.Key_3)
        qgis_app.processEvents()
    finally:
        off.remove()
    if not fired:
        pytest.skip("shortcuts do not activate in this offscreen session")

    # now with labelling on: the palette wins
    filt, calls = recorder()
    fired.clear()
    filt.install()
    try:
        QTest.keyClick(button, Qt.Key_3)
        qgis_app.processEvents()
    finally:
        filt.remove()
        win.close()
    assert calls["digit"] == [2]
    assert not fired
