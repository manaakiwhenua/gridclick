"""Backend registry. Import errors are captured so the plugin can load with
whatever DGGS libraries happen to be installed."""
from __future__ import annotations

import importlib
from typing import Dict, Optional

from .base import BackendUnavailable, CellInfo, DggsBackend  # noqa: F401

# name -> (module, class)
_REGISTRY = {
    "h3": ("h3", "H3Backend"),
    "s2": ("s2", "S2Backend"),
    "a5": ("a5", "A5Backend"),
    "rhealpix": ("rhealpix", "RHEALPixBackend"),
    "geohash": ("geohash", "GeohashBackend"),
}

# pip package names for error messages, keyed by backend name
PIP_NAMES = {
    "h3": "h3", "s2": "s2sphere", "a5": "pya5",
    "rhealpix": "rhealpixdggs", "geohash": "pygeohash",
}
LABELS = {
    "h3": "H3", "s2": "S2", "a5": "A5",
    "rhealpix": "rHEALPix", "geohash": "Geohash",
}
ORDER = ["h3", "s2", "a5", "rhealpix", "geohash"]

_instances: Dict[str, DggsBackend] = {}
_errors: Dict[str, str] = {}


def get(name: str) -> DggsBackend:
    """Return a (cached) backend instance, raising BackendUnavailable if its
    library is missing."""
    if name in _instances:
        return _instances[name]
    if name in _errors:
        raise BackendUnavailable(_errors[name])
    mod_name, cls_name = _REGISTRY[name]
    try:
        mod = importlib.import_module(f"{__name__}.{mod_name}")
        inst = getattr(mod, cls_name)()
    except Exception as exc:  # ImportError, BackendUnavailable, or lib quirks
        _errors[name] = f"{LABELS[name]} unavailable: {exc} (pip install {PIP_NAMES[name]})"
        raise BackendUnavailable(_errors[name]) from exc
    _instances[name] = inst
    return inst


def availability() -> Dict[str, Optional[str]]:
    """name -> None if available else error message."""
    out = {}
    for name in ORDER:
        try:
            get(name)
            out[name] = None
        except BackendUnavailable as exc:
            out[name] = str(exc)
    return out
