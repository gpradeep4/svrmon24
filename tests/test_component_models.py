"""CMDB model validation tests — type-specific fields and inventory columns."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.components import (
    ComponentCreate,
    ComponentType,
    ComponentUpdate,
    display_or_dash,
    to_inventory_row,
)


def test_server_accepts_os_fields_separately() -> None:
    payload = ComponentCreate(
        component_type=ComponentType.SERVER,
        name="web-01",
        environment="prod",
        hostname="web-01.example.com",
        os_family="RHEL",
        os_version="9.4",
    )
    assert payload.os_family == "RHEL"
    assert payload.os_version == "9.4"
    assert payload.os_family != payload.os_version


def test_middleware_accepts_product_fields_separately() -> None:
    payload = ComponentCreate(
        component_type=ComponentType.MIDDLEWARE,
        name="wls-admin",
        environment="nonprod",
        product_type="WebLogic",
        product_version="14.1.1",
        instance_name="AdminServer",
        listen_port=7001,
    )
    assert payload.product_type == "WebLogic"
    assert payload.product_version == "14.1.1"


def test_server_rejects_middleware_only_fields() -> None:
    with pytest.raises(ValidationError) as exc:
        ComponentCreate(
            component_type=ComponentType.SERVER,
            name="bad",
            environment="prod",
            hostname="h1",
            domain_home="/opt/wls",
        )
    assert "domain_home" in str(exc.value)


def test_application_rejects_os_fields() -> None:
    with pytest.raises(ValidationError):
        ComponentCreate(
            component_type=ComponentType.APPLICATION,
            name="portal",
            environment="prod",
            application_name="portal",
            os_family="Windows",
        )


def test_inventory_row_keeps_os_and_product_columns_separate() -> None:
    row = to_inventory_row(
        {
            "component_id": "srv-1",
            "component_type": "Server",
            "name": "web-01",
            "hostname": "web-01",
            "os_family": "RHEL",
            "os_version": "9.4",
            "product_type": None,
            "product_version": None,
            "environment": "prod",
            "status": "active",
        }
    )
    assert row.os_family == "RHEL"
    assert row.os_version == "9.4"
    assert row.product_type == "—"
    assert row.product_version == "—"
    # Never combined into a single field
    assert not hasattr(row, "os")
    assert not hasattr(row, "product")


def test_inventory_row_uses_dash_for_na() -> None:
    assert display_or_dash(None) == "—"
    assert display_or_dash("") == "—"
    assert display_or_dash("RHEL") == "RHEL"


def test_component_update_forbids_unknown_extra() -> None:
    with pytest.raises(ValidationError):
        ComponentUpdate.model_validate({"name": "x", "bogus": 1})
