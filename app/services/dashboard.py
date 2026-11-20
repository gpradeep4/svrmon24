"""Compatibility shim. Canonical module: app.cmdb.services.dashboard."""

from __future__ import annotations

import importlib as _importlib

_canonical = _importlib.import_module("app.cmdb.services.dashboard")


def __getattr__(name: str):
    return getattr(_canonical, name)


def __dir__() -> list[str]:
    return sorted(dir(_canonical))


globals().update({k: v for k, v in vars(_canonical).items() if not k.startswith("__")})
__all__ = getattr(_canonical, "__all__", [k for k in vars(_canonical) if not k.startswith("_")])
