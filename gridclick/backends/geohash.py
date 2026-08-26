from __future__ import annotations

from .base import BackendUnavailable, CellInfo, DggsBackend, close_ring

try:
    import pygeohash as _pgh
except ImportError:  # pragma: no cover
    _pgh = None


class GeohashBackend(DggsBackend):
    name = "geohash"
    label = "Geohash"
    pip_name = "pygeohash"
    min_res = 1
    max_res = 12
    supports_int_id = False

    def __init__(self):
        if _pgh is None:
            raise BackendUnavailable("pygeohash is not installed (pip install pygeohash)")

    def cell_at(self, lon, lat, res):
        precision = self.clamp(res)
        gh = _pgh.encode(lat, lon, precision=precision)
        bb = _pgh.get_bounding_box(gh)
        # pygeohash >=3 returns a BoundingBox(min_lat, min_lon, max_lat, max_lon)
        min_lat, min_lon, max_lat, max_lon = (
            bb.min_lat, bb.min_lon, bb.max_lat, bb.max_lon
        ) if hasattr(bb, "min_lat") else bb
        ring = [
            (min_lon, min_lat), (max_lon, min_lat),
            (max_lon, max_lat), (min_lon, max_lat),
        ]
        return CellInfo(
            dggs=self.name,
            id_str=gh,
            id_int=None,
            resolution=precision,
            centre=((min_lon + max_lon) / 2.0, (min_lat + max_lat) / 2.0),
            boundary=close_ring(ring),
        )
