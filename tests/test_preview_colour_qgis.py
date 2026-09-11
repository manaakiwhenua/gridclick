"""The hover preview shows the class a click would apply.
Run:  QT_QPA_PLATFORM=offscreen python -m pytest tests/test_preview_colour_qgis.py
"""
import os, sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
pytest.importorskip("qgis.gui")
from qgis.PyQt.QtGui import QColor  # noqa: E402

from gridclick.maptool import PREVIEW_DEFAULT  # noqa: E402


@pytest.fixture
def tool(qgis_app):
    from qgis.core import QgsCoordinateReferenceSystem, QgsRectangle
    from qgis.gui import QgsMapCanvas
    from gridclick.maptool import GridclickTool
    canvas = QgsMapCanvas()
    canvas.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
    canvas.setExtent(QgsRectangle(19000000, -5100000, 19600000, -4900000))
    t = GridclickTool(canvas, lambda: 5)
    yield t
    t.cleanup()


def test_default_is_the_neutral_colour(tool):
    assert tool.preview_colour == QColor(PREVIEW_DEFAULT)
    assert tool.band.strokeColor().rgb() == QColor(PREVIEW_DEFAULT).rgb()


def test_the_class_colour_is_used_exactly(tool):
    tool.set_preview_colour("#009E73")
    assert tool.preview_colour.name() == "#009e73"
    # the hue must not be nudged for contrast — the preview would then lie
    assert tool.band.strokeColor().name() == "#009e73"
    assert tool.band.fillColor().name() == "#009e73"
    assert tool.marker.color().name() == "#009e73"


def test_outline_is_solid_and_the_fill_is_see_through(tool):
    tool.set_preview_colour("#0072B2")
    assert tool.band.strokeColor().alpha() > 200
    assert tool.band.fillColor().alpha() < 64


def test_a_halo_keeps_pale_classes_readable(tool):
    tool.set_preview_colour("#FFF6A0")               # near-white
    halo = tool.band.secondaryStrokeColor()
    assert halo.lightnessF() < 0.5 and halo.alpha() > 0   # dark halo under it
    tool.set_preview_colour("#0072B2")               # dark
    halo = tool.band.secondaryStrokeColor()
    assert halo.lightnessF() > 0.5 and halo.alpha() > 0   # light halo under it


def test_none_restores_the_neutral_colour(tool):
    tool.set_preview_colour("#CC79A7")
    tool.set_preview_colour(None)
    assert tool.preview_colour == QColor(PREVIEW_DEFAULT)


def test_an_unreadable_colour_falls_back(tool):
    tool.set_preview_colour("not a colour")
    assert tool.preview_colour == QColor(PREVIEW_DEFAULT)
