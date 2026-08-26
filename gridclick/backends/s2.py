from __future__ import annotations

from .base import BackendUnavailable, CellInfo, DggsBackend, close_ring

try:
    import s2sphere as _s2
except ImportError:  # pragma: no cover
    _s2 = None

_SEGMENTS_PER_EDGE = 8


class S2Backend(DggsBackend):
    name = "s2"
    label = "S2"
    pip_name = "s2sphere"
    min_res = 0
    max_res = 30
    supports_int_id = True

    def __init__(self):
        if _s2 is None:
            raise BackendUnavailable("s2sphere is not installed (pip install s2sphere)")

    @staticmethod
    def _lonlat(point):
        ll = _s2.LatLng.from_point(point)
        return (ll.lng().degrees, ll.lat().degrees)

    def cell_at(self, lon, lat, res):
        level = self.clamp(res)
        leaf = _s2.CellId.from_lat_lng(_s2.LatLng.from_degrees(lat, lon))
        cid = leaf.parent(level) if level < _s2.CellId.MAX_LEVEL else leaf
        cell = _s2.Cell(cid)
        verts = [cell.get_vertex(i) for i in range(4)]
        ring = []
        # densify edges along great circles so large cells draw correctly
        for i in range(4):
            a, b = verts[i], verts[(i + 1) % 4]
            for k in range(_SEGMENTS_PER_EDGE):
                t = k / _SEGMENTS_PER_EDGE
                p = _s2.Point(
                    a[0] * (1 - t) + b[0] * t,
                    a[1] * (1 - t) + b[1] * t,
                    a[2] * (1 - t) + b[2] * t,
                ).normalize()
                ring.append(self._lonlat(p))
        ll = cid.to_lat_lng()
        return CellInfo(
            dggs=self.name,
            id_str=cid.to_token(),
            id_int=cid.id(),
            resolution=cid.level(),
            centre=(ll.lng().degrees, ll.lat().degrees),
            boundary=close_ring(ring),
        )
