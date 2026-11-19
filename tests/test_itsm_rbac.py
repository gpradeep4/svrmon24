"""ITSM RBAC matrix extensions (additive itsm:* permissions)."""

from __future__ import annotations

from app.permissions import (
    ALL_PERMISSIONS,
    PERM_ITSM_APPROVAL_DECIDE,
    PERM_ITSM_APPROVAL_READ,
    PERM_ITSM_CHANGE_READ,
    PERM_ITSM_CHANGE_WRITE,
    PERM_ITSM_DASHBOARD_READ,
    PERM_ITSM_INCIDENT_READ,
    PERM_ITSM_INCIDENT_WRITE,
    PERM_ITSM_PROBLEM_READ,
    PERM_ITSM_PROBLEM_WRITE,
    PERM_ITSM_WORKFLOW_ADMIN,
    PERM_ITSM_WORKFLOW_READ,
    permissions_for_role,
)
from app.tenancy import (
    MEMBERSHIP_ROLE_ADMIN,
    MEMBERSHIP_ROLE_MEMBER,
    MEMBERSHIP_ROLE_OWNER,
    MEMBERSHIP_ROLE_VIEWER,
)


def test_itsm_permissions_in_catalog() -> None:
    assert PERM_ITSM_INCIDENT_READ in ALL_PERMISSIONS
    assert PERM_ITSM_INCIDENT_WRITE in ALL_PERMISSIONS
    assert PERM_ITSM_CHANGE_READ in ALL_PERMISSIONS
    assert PERM_ITSM_CHANGE_WRITE in ALL_PERMISSIONS
    assert PERM_ITSM_PROBLEM_READ in ALL_PERMISSIONS
    assert PERM_ITSM_PROBLEM_WRITE in ALL_PERMISSIONS
    assert PERM_ITSM_DASHBOARD_READ in ALL_PERMISSIONS
    assert PERM_ITSM_WORKFLOW_ADMIN in ALL_PERMISSIONS
    assert PERM_ITSM_WORKFLOW_READ in ALL_PERMISSIONS
    assert PERM_ITSM_APPROVAL_READ in ALL_PERMISSIONS
    assert PERM_ITSM_APPROVAL_DECIDE in ALL_PERMISSIONS


def test_role_grants_for_itsm() -> None:
    viewer = permissions_for_role(MEMBERSHIP_ROLE_VIEWER)
    member = permissions_for_role(MEMBERSHIP_ROLE_MEMBER)
    admin = permissions_for_role(MEMBERSHIP_ROLE_ADMIN)
    owner = permissions_for_role(MEMBERSHIP_ROLE_OWNER)

    assert PERM_ITSM_INCIDENT_READ in viewer
    assert PERM_ITSM_CHANGE_READ in viewer
    assert PERM_ITSM_PROBLEM_READ in viewer
    assert PERM_ITSM_APPROVAL_READ in viewer
    assert PERM_ITSM_WORKFLOW_READ in viewer
    assert PERM_ITSM_INCIDENT_WRITE not in viewer
    assert PERM_ITSM_CHANGE_WRITE not in viewer
    assert PERM_ITSM_PROBLEM_WRITE not in viewer
    assert PERM_ITSM_APPROVAL_DECIDE not in viewer
    assert PERM_ITSM_DASHBOARD_READ in viewer

    assert PERM_ITSM_INCIDENT_WRITE in member
    assert PERM_ITSM_CHANGE_WRITE in member
    assert PERM_ITSM_PROBLEM_WRITE in member
    assert PERM_ITSM_APPROVAL_DECIDE in member
    assert PERM_ITSM_WORKFLOW_ADMIN not in member

    assert PERM_ITSM_WORKFLOW_ADMIN in admin
    assert PERM_ITSM_WORKFLOW_ADMIN in owner
    assert PERM_ITSM_APPROVAL_DECIDE in admin
