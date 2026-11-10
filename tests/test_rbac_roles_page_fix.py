"""RBAC Roles page + Audit denied UX follow-up (targeted tests only)."""

from __future__ import annotations

from pathlib import Path

from app import __version__


ROOT = Path(__file__).resolve().parents[1]


def test_roles_page_has_no_coming_soon_copy() -> None:
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    js = (ROOT / "app/static/js/cmdb.js").read_text(encoding="utf-8")

    assert "Coming soon" not in html.split('id="tab-roles"')[1].split('id="tab-organizations"')[0]
    assert "RBAC not implemented" not in html
    assert "RBAC not implemented" not in js
    assert "Coming soon — RBAC" not in js
    assert 'data-rbac-signin-cta="1"' in html
    assert 'id="rbacSignInCta"' in html
    assert "Live RBAC role, permissions, and matrix" in js
    assert "renderRolesSignedOut" in js
    assert "loadRolesPanel" in js


def test_audit_page_has_in_page_denied_panel() -> None:
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    js = (ROOT / "app/static/js/cmdb.js").read_text(encoding="utf-8")
    css = (ROOT / "app/static/css/cmdb.css").read_text(encoding="utf-8")

    assert 'data-audit-denied="1"' in html
    assert "Audit Logs require admin access" in html
    assert "showAuditDenied" in js
    assert "rbac-nav-denied" in js
    assert ".audit-denied" in css
    assert "scripts/set_membership_role.py" in html


def test_users_panel_exposes_role_change_controls() -> None:
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    js = (ROOT / "app/static/js/cmdb.js").read_text(encoding="utf-8")

    assert "Change role" in html
    assert "saveMemberRole" in js
    assert "btn-member-role-save" in js
    assert "/members/" in js


def test_set_membership_role_cli_exists() -> None:
    script = ROOT / "scripts/set_membership_role.py"
    assert script.is_file()
    text = script.read_text(encoding="utf-8")
    assert "set a tenant membership role" in text.lower() or "membership role" in text.lower()
    assert "--role" in text
    assert "--username" in text


def test_version_patch_for_rbac_ux_followup() -> None:
    assert __version__ == "0.31.1"
