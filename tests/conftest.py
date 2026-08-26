"""Shared pytest fixtures. A QgsApplication may only be created once per
process, so it is session-scoped here and used by every QGIS-dependent test."""
import os
import pytest

try:
    from qgis.core import QgsApplication
except ImportError:  # QGIS not importable: QGIS tests will importorskip
    QgsApplication = None


@pytest.fixture(scope="session")
def qgis_app():
    if QgsApplication is None:
        pytest.skip("qgis not importable")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QgsApplication.setPrefixPath("/usr", True)
    app = QgsApplication([], True)
    app.initQgis()
    yield app
    app.exitQgis()
