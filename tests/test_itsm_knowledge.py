"""ITSM Knowledge Management — functional coverage for 0.41.0."""

from __future__ import annotations

from app import __version__
from app.db import get_itsm_database
from app.permissions import (
    ALL_PERMISSIONS,
    PERM_ITSM_KNOWLEDGE_READ,
    PERM_ITSM_KNOWLEDGE_WRITE,
    permissions_for_role,
)
from app.tenancy import MEMBERSHIP_ROLE_MEMBER, MEMBERSHIP_ROLE_VIEWER
from fastapi.testclient import TestClient

from tests.frontend_paths import FRONTEND_INDEX


def test_version_bump_for_knowledge_slice() -> None:
    assert __version__ == "0.41.0"


def test_knowledge_permissions_in_catalog() -> None:
    assert PERM_ITSM_KNOWLEDGE_READ in ALL_PERMISSIONS
    assert PERM_ITSM_KNOWLEDGE_WRITE in ALL_PERMISSIONS
    viewer = permissions_for_role(MEMBERSHIP_ROLE_VIEWER)
    member = permissions_for_role(MEMBERSHIP_ROLE_MEMBER)
    assert PERM_ITSM_KNOWLEDGE_READ in viewer
    assert PERM_ITSM_KNOWLEDGE_WRITE not in viewer
    assert PERM_ITSM_KNOWLEDGE_WRITE in member


def _article_payload(**overrides):
    body = {
        "title": "Restart edge VPN gateway",
        "body": "1. Drain traffic\n2. Restart service\n3. Verify tunnels",
        "status": "draft",
        "category": "network",
        "tags": ["vpn", "gateway", "outage"],
        "related_incident_ids": [],
        "related_problem_ids": [],
        "related_component_ids": ["edge-gw-01"],
    }
    body.update(overrides)
    return body


def test_knowledge_crud_publish_retire_and_search(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    created = client.post(
        "/api/itsm/knowledge/articles",
        headers=auth_headers,
        json=_article_payload(
            related_incident_ids=["INC-DEMO01"],
            related_problem_ids=["PRB-DEMO01"],
        ),
    )
    assert created.status_code == 201, created.text
    article = created.json()
    assert article["article_id"].startswith("KB-")
    assert article["number_display"].startswith("KB-")
    assert article["status"] == "draft"
    assert article["tags"] == ["vpn", "gateway", "outage"]
    assert article["related_component_ids"] == ["edge-gw-01"]
    assert article["related_incident_ids"] == ["INC-DEMO01"]
    article_id = article["article_id"]

    listed_all = client.get("/api/itsm/knowledge/articles", headers=auth_headers)
    assert listed_all.status_code == 200, listed_all.text
    assert listed_all.json()["total"] >= 1

    # Draft not visible when filtering published only.
    listed_pub = client.get(
        "/api/itsm/knowledge/articles?status=published",
        headers=auth_headers,
    )
    assert listed_pub.status_code == 200
    assert all(row["status"] == "published" for row in listed_pub.json()["items"])

    patched = client.patch(
        f"/api/itsm/knowledge/articles/{article_id}",
        headers=auth_headers,
        json={"title": "Restart edge VPN gateway (revised)", "tags": ["vpn", "ha"]},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["title"].endswith("(revised)")
    assert patched.json()["tags"] == ["vpn", "ha"]

    published = client.post(
        f"/api/itsm/knowledge/articles/{article_id}/transition",
        headers=auth_headers,
        json={"status": "published", "comment": "Ready for ops"},
    )
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "published"
    assert published.json()["published_at"] is not None

    searched = client.get(
        "/api/itsm/knowledge/articles?q=VPN&category=network&tag=vpn",
        headers=auth_headers,
    )
    assert searched.status_code == 200, searched.text
    assert searched.json()["total"] >= 1
    assert any(row["article_id"] == article_id for row in searched.json()["items"])

    by_incident = client.get(
        "/api/itsm/knowledge/articles?related_incident_id=INC-DEMO01",
        headers=auth_headers,
    )
    assert by_incident.status_code == 200
    assert any(row["article_id"] == article_id for row in by_incident.json()["items"])

    activities = client.get(
        f"/api/itsm/knowledge/articles/{article_id}/activities",
        headers=auth_headers,
    )
    assert activities.status_code == 200, activities.text
    types = {row["activity_type"] for row in activities.json()["items"]}
    assert "created" in types
    assert "status_change" in types

    retired = client.post(
        f"/api/itsm/knowledge/articles/{article_id}/transition",
        headers=auth_headers,
        json={"status": "retired"},
    )
    assert retired.status_code == 200, retired.text
    assert retired.json()["status"] == "retired"
    assert retired.json()["retired_at"] is not None

    # Illegal transition from retired → published.
    bad = client.post(
        f"/api/itsm/knowledge/articles/{article_id}/transition",
        headers=auth_headers,
        json={"status": "published"},
    )
    assert bad.status_code == 400

    itsm = get_itsm_database()
    assert itsm is not None
    assert itsm["itsm_knowledge_articles"].count_documents({}) >= 1


def test_knowledge_suggest_by_category_and_tags(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    a = client.post(
        "/api/itsm/knowledge/articles",
        headers=auth_headers,
        json=_article_payload(
            title="Network outage playbook",
            category="network",
            tags=["outage", "vpn"],
            status="draft",
        ),
    )
    assert a.status_code == 201, a.text
    a_id = a.json()["article_id"]
    pub = client.post(
        f"/api/itsm/knowledge/articles/{a_id}/transition",
        headers=auth_headers,
        json={"status": "published"},
    )
    assert pub.status_code == 200, pub.text

    b = client.post(
        "/api/itsm/knowledge/articles",
        headers=auth_headers,
        json=_article_payload(
            title="Storage rebuild steps",
            category="storage",
            tags=["disk", "raid"],
            status="draft",
        ),
    )
    assert b.status_code == 201, b.text
    b_id = b.json()["article_id"]
    client.post(
        f"/api/itsm/knowledge/articles/{b_id}/transition",
        headers=auth_headers,
        json={"status": "published"},
    )

    suggested = client.get(
        "/api/itsm/knowledge/articles/suggest?category=network&tags=vpn,outage&limit=5",
        headers=auth_headers,
    )
    assert suggested.status_code == 200, suggested.text
    items = suggested.json()["items"]
    assert items
    assert items[0]["article_id"] == a_id
    assert items[0]["match_score"] >= 10
    assert all(row["status"] == "published" for row in items)
    assert all(row["article_id"] != b_id or row["match_score"] == 0 for row in items)
    assert not any(row["article_id"] == b_id for row in items)


def test_knowledge_tenant_isolation(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    created = client.post(
        "/api/itsm/knowledge/articles",
        headers=auth_headers,
        json=_article_payload(title="Tenant scoped KB"),
    )
    assert created.status_code == 201, created.text
    article_id = created.json()["article_id"]
    tenant_id = created.json()["tenant_id"]

    foreign = dict(
        get_itsm_database()["itsm_knowledge_articles"].find_one(
            {"article_id": article_id}
        )
    )
    foreign.pop("_id", None)
    foreign["tenant_id"] = "tenant-other-org"
    foreign["article_id"] = "KB-FOREIGN01"
    foreign["number"] = 999001
    foreign["number_display"] = "KB-999001"
    get_itsm_database()["itsm_knowledge_articles"].insert_one(foreign)

    missing = client.get("/api/itsm/knowledge/articles/KB-FOREIGN01", headers=auth_headers)
    assert missing.status_code == 404

    own = client.get(f"/api/itsm/knowledge/articles/{article_id}", headers=auth_headers)
    assert own.status_code == 200
    assert own.json()["tenant_id"] == tenant_id


def test_frontend_knowledge_markers() -> None:
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'content="0.41.0"' in html
    assert 'data-tab="itsm-knowledge"' in html
    assert 'id="tab-itsm-knowledge"' in html
    assert "itsm/knowledge.js?v=0.41.0" in html
    assert 'id="itsmKnowledgeModal"' in html
    assert 'id="itsmIncKbSuggest"' in html
