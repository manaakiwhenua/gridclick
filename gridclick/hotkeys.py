"""Application-wide routing of the 0-9 label hotkeys.

Two things get between a digit and the palette:

* The map canvas is only sent key events while it holds keyboard focus, but the
  natural way to use the palette — activate the tool, then choose a class
  before the first click — leaves focus in the dock, so the canvas never sees
  the digit. Watching the application instead makes the keys work wherever the
  user last clicked, except where a digit is genuinely being typed.
* If any QAction is bound to a bare digit — QGIS itself, another plugin, or the
  user's own shortcut — Qt fires that shortcut and *never delivers a KeyPress
  at all*, so no event filter can see it. The only way to win is to accept the
  QEvent.ShortcutOverride Qt sends first, which tells it to deliver the key
  normally instead.
"""
from __future__ import annotations

from qgis.PyQt.QtCore import QEvent, QObject, Qt
from qgis.PyQt.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QLineEdit,
    QPlainTextEdit,
    QTextEdit,
)

#: widgets where a digit means "the character 3", not "class 3"
TEXT_ENTRY = (QLineEdit, QAbstractSpinBox, QTextEdit, QPlainTextEdit)


def is_text_entry(widget) -> bool:
    if isinstance(widget, TEXT_ENTRY):
        return True
    return isinstance(widget, QComboBox) and widget.isEditable()


class HotkeyFilter(QObject):
    """Turns 1-9 into `on_digit(n - 1)` and 0 into `on_page()`.

    Both callbacks return True if they acted; only then is the key swallowed,
    so a digit that means nothing to the palette still reaches QGIS.
    """

    def __init__(self, on_digit, on_page, active=None, parent=None):
        super().__init__(parent)
        self._on_digit = on_digit
        self._on_page = on_page
        #: whether the digits belong to the palette at all right now
        self._active = active if active is not None else (lambda: True)
        self._installed = False

    # ------------------------------------------------------------------ #
    def install(self):
        app = QApplication.instance()
        if app is not None and not self._installed:
            app.installEventFilter(self)
            self._installed = True

    def remove(self):
        app = QApplication.instance()
        if app is not None and self._installed:
            app.removeEventFilter(self)
        self._installed = False

    # ------------------------------------------------------------------ #
    def handles(self, obj, event) -> bool:
        """Whether this key event is ours to act on."""
        if event.type() not in (QEvent.KeyPress, QEvent.ShortcutOverride):
            return False
        if not (Qt.Key_0 <= event.key() <= Qt.Key_9):
            return False
        # leave Ctrl+1, Alt+2 and friends to QGIS; the keypad is still a digit
        if event.modifiers() & ~Qt.KeypadModifier:
            return False
        if QApplication.activeModalWidget() is not None:
            return False            # a dialog is up — e.g. the class editor
        # for a key event `obj` is the widget the event is delivered to
        return not is_text_entry(obj)

    def eventFilter(self, obj, event):
        if not self.handles(obj, event):
            return False
        if event.type() == QEvent.ShortcutOverride:
            # claim the key from any QAction bound to a bare digit, so that Qt
            # delivers a KeyPress we can act on below
            if not self._active():
                return False
            event.accept()
            return True
        key = event.key()
        acted = self._on_page() if key == Qt.Key_0 else self._on_digit(key - Qt.Key_1)
        return bool(acted)
