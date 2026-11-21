"""CMDB package move (slice 2L / 0.43.0) — import shims and route mount."""

from __future__ import annotations

from app import __version__
from app.cmdb.diagnostics.profiles import BASIC_HEALTH_PROFILE as canon_profile
from app.cmdb.models.components import ComponentCreate as canon_model
from app.cmdb.routers.components import router as canon_router
from app.cmdb.services.components import list_components as canon_list
from app.cmdb.services.file_monitoring import module_meta as canon_meta
from app.diagnostics.profiles import BASIC_HEALTH_PROFILE as shim_profile
from app.main import create_app
from app.models import ComponentCreate as barrel_model
from app.models.components import ComponentCreate as shim_model
from app.routers.components import router as shim_router
from app.services.components import list_components as shim_list
from app.services.file_monitoring import module_meta as shim_meta


def test_version_bump_for_cmdb_package_move() -> None:
    assert __version__ == "0.43.0"


def test_cmdb_import_shims_resolve_to_canonical_modules() -> None:
    """Historical import paths stay bound to the app.cmdb implementation."""
    assert shim_list is canon_list
    assert shim_model is canon_model is barrel_model
    assert shim_router is canon_router
    assert shim_router.prefix == "/api/components"
    assert shim_profile is canon_profile
    assert shim_profile["profile_name"] == "basic-health"
    assert shim_meta is canon_meta
    assert shim_meta()["execution_mode"] == "SIMULATED"


def test_cmdb_routes_remain_mounted() -> None:
    """Moving packages does not drop CMDB HTTP routes."""
    app = create_app()
    assert app.version == "0.43.0"
    paths = set(app.openapi()["paths"])
    for prefix in (
        "/api/components",
        "/api/relationships",
        "/api/diagnostics",
        "/api/file-monitoring",
        "/api/dependencies",
        "/api/entity-refs",
        "/api/itsm/incidents",
    ):
        assert any(path.startswith(prefix) for path in paths), prefix
