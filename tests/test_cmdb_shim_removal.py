"""CMDB shim removal (0.44.0) — canonical imports only; routes still mounted."""

from __future__ import annotations

import importlib
import sys

import pytest

from app import __version__
from app.cmdb.diagnostics.profiles import BASIC_HEALTH_PROFILE
from app.cmdb.models.components import ComponentCreate
from app.cmdb.routers.components import router as components_router
from app.cmdb.services.components import list_components
from app.cmdb.services.file_monitoring import module_meta
from app.main import create_app


# Historical shim modules removed in 0.44.0.
_REMOVED_SHIM_MODULES = (
    "app.routers.components",
    "app.routers.relationships",
    "app.routers.diagnostics",
    "app.routers.file_monitoring",
    "app.routers.dashboard",
    "app.services.components",
    "app.services.ai_analysis",
    "app.services.cmdb_migrate",
    "app.services.cmdb_collections",
    "app.services.field_defs_migrate",
    "app.models.components",
    "app.models.relationships",
    "app.diagnostics",
    "app.diagnostics.profiles",
    "app.diagnostics.simulator",
)


def test_version_bump_for_cmdb_shim_removal() -> None:
    assert __version__ == "0.44.0"


def test_canonical_cmdb_imports_work() -> None:
    assert components_router.prefix == "/api/components"
    assert callable(list_components)
    assert ComponentCreate.__name__ == "ComponentCreate"
    assert BASIC_HEALTH_PROFILE["profile_name"] == "basic-health"
    assert module_meta()["execution_mode"] == "SIMULATED"


@pytest.mark.parametrize("module_name", _REMOVED_SHIM_MODULES)
def test_cmdb_compatibility_shims_removed(module_name: str) -> None:
    sys.modules.pop(module_name, None)
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(module_name)


def test_cmdb_routes_remain_mounted() -> None:
    app = create_app()
    assert app.version == "0.44.0"
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


def test_platform_modules_remain_at_app_root() -> None:
    """Shim removal must not delete shared platform packages."""
    import app.routers.auth_routes  # noqa: F401
    import app.routers.tenants  # noqa: F401
    import app.services.bootstrap  # noqa: F401
    import app.services.ollama_client  # noqa: F401
    import app.models.tenants  # noqa: F401
