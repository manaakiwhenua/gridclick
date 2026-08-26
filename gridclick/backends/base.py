"""Common backend abstraction for Gridclick DGGS backends.

Every backend normalises to:
  * coordinates as (lon, lat) tuples in degrees (EPSG:4326)
  * a *closed* boundary ring (first vertex repeated at the end)
  * integer and string cell identifiers where the DGGS supports them
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Tuple

LonLat = Tuple[float, float]


@dataclass(frozen=True)
class CellInfo:
    dggs: str
    id_str: str
    id_int: Optional[int]
    resolution: int
    centre: LonLat
    boundary: List[LonLat]  # closed ring


class BackendUnavailable(RuntimeError):
    """Raised when the Python library for a backend is not importable."""


class DggsBackend(ABC):
    #: machine name, also stored in the `dggs` field
    name: str = ""
    #: human label for UI
    label: str = ""
    #: pip package providing the library (for error messages)
    pip_name: str = ""
    min_res: int = 0
    max_res: int = 0
    supports_int_id: bool = False

    @abstractmethod
    def cell_at(self, lon: float, lat: float, res: int) -> CellInfo:
        """Return the cell containing (lon, lat) at resolution `res`."""

    def clamp(self, res: int) -> int:
        return max(self.min_res, min(self.max_res, int(res)))


def close_ring(ring: List[LonLat]) -> List[LonLat]:
    ring = [(float(x), float(y)) for x, y in ring]
    if ring and ring[0] != ring[-1]:
        ring.append(ring[0])
    return ring
