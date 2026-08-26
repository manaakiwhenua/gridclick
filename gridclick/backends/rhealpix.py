from __future__ import annotations

from .base import BackendUnavailable, CellInfo, DggsBackend, close_ring

try:
    from rhealpixdggs.dggs import WGS84_003 as _DGGS
except ImportError:  # pragma: no cover
    _DGGS = None

_POINTS_PER_EDGE = 6


class RHEALPixBackend(DggsBackend):
    name = "rhealpix"
    label = "rHEALPix (WGS84, N_side=3)"
    pip_name = "rhealpixdggs"
    min_res = 0
    supports_int_id = False

    def __init__(self):
        if _DGGS is None:
            raise BackendUnavailable("rhealpixdggs is not installed (pip install rhealpixdggs)")
        self.dggs = _DGGS
        self.max_res = int(min(self.dggs.max_resolution, 15))

    def cell_at(self, lon, lat, res):
        r = self.clamp(res)
        cell = self.dggs.cell_from_point(r, (lon, lat), plane=False)
        if cell is None:
            raise ValueError("point outside rHEALPix domain")
        try:
            ring = list(cell.boundary(n=_POINTS_PER_EDGE, plane=False))
        except Exception:
            ring = list(cell.vertices(plane=False))
        cx, cy = cell.centroid(plane=False)
        return CellInfo(
            dggs=self.name,
            id_str=str(cell),
            id_int=None,
            resolution=r,
            centre=(float(cx), float(cy)),
            boundary=close_ring(ring),
        )
