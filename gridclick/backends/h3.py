from __future__ import annotations

from .base import BackendUnavailable, CellInfo, DggsBackend, close_ring

try:
    import h3 as _h3
except ImportError:  # pragma: no cover
    _h3 = None


class H3Backend(DggsBackend):
    name = "h3"
    label = "H3"
    pip_name = "h3"
    min_res = 0
    max_res = 15
    supports_int_id = True

    def __init__(self):
        if _h3 is None:
            raise BackendUnavailable("h3 is not installed (pip install h3)")

    def cell_at(self, lon, lat, res):
        cell = _h3.latlng_to_cell(lat, lon, self.clamp(res))
        clat, clon = _h3.cell_to_latlng(cell)
        ring = [(lng, lt) for lt, lng in _h3.cell_to_boundary(cell)]
        return CellInfo(
            dggs=self.name,
            id_str=cell,
            id_int=_h3.str_to_int(cell),
            resolution=_h3.get_resolution(cell),
            centre=(clon, clat),
            boundary=close_ring(ring),
        )
