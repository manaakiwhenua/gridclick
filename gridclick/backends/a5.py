from __future__ import annotations

from .base import BackendUnavailable, CellInfo, DggsBackend, close_ring

try:
    import a5 as _a5
except ImportError:  # pragma: no cover
    _a5 = None


class A5Backend(DggsBackend):
    name = "a5"
    label = "A5"
    pip_name = "pya5"
    min_res = 0
    supports_int_id = True

    def __init__(self):
        if _a5 is None:
            raise BackendUnavailable("A5 is not installed (pip install pya5)")
        self.max_res = int(getattr(_a5, "MAX_RESOLUTION", 30))

    def cell_at(self, lon, lat, res):
        cell = _a5.lonlat_to_cell((lon, lat), self.clamp(res))
        clon, clat = _a5.cell_to_lonlat(cell)
        try:
            ring = _a5.cell_to_boundary(cell, closed_ring=True)
        except TypeError:
            ring = _a5.cell_to_boundary(cell)
        # A5 returns "unwrapped" longitudes for continuity; shift the whole
        # ring by multiples of 360 so the centre sits in [-180, 180] while the
        # ring stays continuous (it may then extend slightly past +/-180).
        shift = 0.0
        while clon + shift > 180.0:
            shift -= 360.0
        while clon + shift < -180.0:
            shift += 360.0
        ring = [(float(p[0]) + shift, float(p[1])) for p in ring]
        return CellInfo(
            dggs=self.name,
            id_str=_a5.u64_to_hex(cell),
            id_int=int(cell),
            resolution=_a5.get_resolution(cell),
            centre=(float(clon) + shift, float(clat)),
            boundary=close_ring(ring),
        )
