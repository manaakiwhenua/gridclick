"""Pure-Python backend tests (no QGIS required).

Run:  python -m pytest tests/
Backends whose library is missing are skipped, not failed.
"""
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from gridclick import backends  # noqa: E402
from gridclick.backends import BackendUnavailable  # noqa: E402

SAMPLE_POINTS = [
    (174.77, -41.29),   # Wellington
    (0.0, 0.0),
    (-73.98, 40.75),    # New York
    (179.9, 10.0),      # near antimeridian
    (-179.9, -10.0),
    (10.0, 85.0),       # near north pole
    (10.0, -85.0),      # near south pole
]


def _backend(name):
    try:
        return backends.get(name)
    except BackendUnavailable as exc:
        pytest.skip(str(exc))


def _in_bbox(pt, ring, tol):
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    return (min(xs) - tol <= pt[0] <= max(xs) + tol) and (
        min(ys) - tol <= pt[1] <= max(ys) + tol
    )


@pytest.mark.parametrize("name", backends.ORDER)
def test_metadata(name):
    b = _backend(name)
    assert b.name == name
    assert b.min_res <= b.max_res
    assert b.clamp(b.max_res + 100) == b.max_res
    assert b.clamp(b.min_res - 100) == b.min_res


@pytest.mark.parametrize("name", backends.ORDER)
@pytest.mark.parametrize("lon,lat", SAMPLE_POINTS)
def test_cell_shape(name, lon, lat):
    b = _backend(name)
    for res in sorted({b.min_res, (b.min_res + b.max_res) // 2, min(b.max_res, 9)}):
        c = b.cell_at(lon, lat, res)
        assert c.dggs == name
        assert c.resolution == res
        assert isinstance(c.id_str, str) and c.id_str
        if b.supports_int_id:
            assert isinstance(c.id_int, int)
        else:
            assert c.id_int is None
        ring = c.boundary
        assert len(ring) >= 4
        assert ring[0] == ring[-1], "ring must be closed"
        for x, y in ring:
            # rings may be unwrapped across the antimeridian for continuity
            assert -540.0 <= x <= 540.0 and -90.0001 <= y <= 90.0001
            assert not (math.isnan(x) or math.isnan(y))
        # centre must lie roughly inside the bbox unless the cell wraps
        xs = [p[0] for p in ring]
        wraps = (max(xs) - min(xs)) > 180 or abs(lat) > 80
        if not wraps:
            assert _in_bbox(c.centre, ring, tol=1e-6)


@pytest.mark.parametrize("name", backends.ORDER)
def test_hierarchy_shrinks(name):
    """Finer resolution -> smaller bbox around the same point."""
    b = _backend(name)
    lon, lat = 174.77, -41.29
    prev = None
    for res in range(b.min_res, min(b.max_res, 8) + 1):
        c = b.cell_at(lon, lat, res)
        xs = [p[0] for p in c.boundary]
        ys = [p[1] for p in c.boundary]
        size = (max(xs) - min(xs)) * (max(ys) - min(ys))
        if prev is not None and size > 0:
            assert size <= prev * 1.01
        prev = size


@pytest.mark.parametrize("name", backends.ORDER)
def test_deterministic(name):
    b = _backend(name)
    a = b.cell_at(174.77, -41.29, 5)
    c = b.cell_at(174.77, -41.29, 5)
    assert a == c
