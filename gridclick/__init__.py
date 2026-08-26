"""Gridclick — click the map to create DGGS cell features (QGIS plugin)."""


def classFactory(iface):  # noqa: N802  (QGIS entry point)
    from .plugin import GridclickPlugin

    return GridclickPlugin(iface)
