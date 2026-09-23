"""TZ 30 — REST API, JWT auth, role guards, metrics."""

from __future__ import annotations

import pytest

from app.core.security import create_access_token
from tests.conftest import make_topic


@pytest.fixture
async def topic(session, owner):
    return await make_topic(session, owner, code="A-0042")


async def test_health(client):
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["tables"] >= 24
    assert body["cache"] in {"memory", "redis"}


async def test_metrics_exposes_prometheus_text(client, topic):
    response = await client.get("/api/v1/metrics")
    assert response.status_code == 200
    assert "soulchat_topics_total 1" in response.text
    assert response.headers["content-type"].startswith("text/plain")


async def test_openapi_is_served(client):
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    assert "SoulChat" in response.json()["info"]["title"]


async def test_unauthenticated_request_is_rejected(client, admin):
    client.headers.pop("Authorization")
    response = await client.get("/api/v1/topics")
    assert response.status_code == 401


async def test_regular_user_cannot_reach_staff_endpoints(client, owner):
    client.headers["Authorization"] = f"Bearer {create_access_token(owner.id, {'role': owner.role})}"
    response = await client.get("/api/v1/topics")
    assert response.status_code == 403


async def test_me_returns_the_current_user(client, admin):
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 200
    assert response.json()["username"] == "admin"


async def test_topic_list_and_detail(client, topic):
    listing = await client.get("/api/v1/topics")
    assert listing.status_code == 200
    body = listing.json()
    assert body["total"] == 1
    assert body["items"][0]["code"] == "A-0042"

    detail = await client.get("/api/v1/topics/A-0042")
    assert detail.status_code == 200
    assert detail.json()["title"] == "A-0042"


async def test_topic_status_filter(client, session, topic):
    response = await client.get("/api/v1/topics", params={"status": "deleted"})
    assert response.status_code == 200
    assert response.json()["total"] == 0


async def test_freeze_block_restore_roundtrip(client, topic):
    frozen = await client.post("/api/v1/topics/A-0042/freeze", json={"reason": "spam"})
    assert frozen.status_code == 200
    assert frozen.json()["status"] == "frozen"

    restored = await client.post("/api/v1/topics/A-0042/restore", json={})
    assert restored.status_code == 200
    assert restored.json()["status"] == "active"

    blocked = await client.post("/api/v1/topics/A-0042/block", json={"reason": "moderation"})
    assert blocked.status_code == 200
    assert blocked.json()["status"] == "delete_pending"
    assert blocked.json()["delete_at"] is not None


async def test_illegal_transition_returns_409(client, session, topic):
    await client.delete("/api/v1/topics/A-0042")
    response = await client.post("/api/v1/topics/A-0042/restore", json={})
    assert response.status_code == 409


async def test_archive_download_is_a_zip(client, session, owner, topic):
    from app.models.message import Message

    session.add(Message(topic_id=topic.id, sender_id=owner.id, content_type="text", text="salom"))
    await session.flush()

    response = await client.get("/api/v1/topics/A-0042/archive")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert response.content[:2] == b"PK"
    assert "X-Archive-Checksum" in response.headers


async def test_moderation_action_and_audit_trail(client, session, owner, topic):
    warned = await client.post(
        "/api/v1/moderation/action", json={"action": "warn", "tg_id": owner.tg_id, "reason": "spam"}
    )
    assert warned.status_code == 200
    assert warned.json()["warns"] == 1

    audit = await client.get("/api/v1/moderation/audit")
    assert audit.status_code == 200
    actions = [row["action"] for row in audit.json()]
    assert "moderation.warn" in actions


async def test_ban_requires_admin_not_moderator(client, session, owner, moderator):
    client.headers["Authorization"] = f"Bearer {create_access_token(moderator.id, {'role': moderator.role})}"
    response = await client.post(
        "/api/v1/moderation/action", json={"action": "ban", "tg_id": owner.tg_id}
    )
    assert response.status_code == 403


async def test_analytics_dashboard(client, session, owner, topic):
    response = await client.get("/api/v1/analytics/dashboard")
    assert response.status_code == 200
    body = response.json()
    assert body["stats"]["total_topics"] == 1
    assert len(body["daily"]) == 30
    assert len(body["weekly"]) == 12


async def test_search_endpoint(client, session, owner, topic):
    response = await client.post("/api/v1/analytics/search", json={"query": "A-0042"})
    assert response.status_code == 200
    assert len(response.json()["topics"]) == 1


async def test_settings_roundtrip(client, session, admin):
    listing = await client.get("/api/v1/settings")
    assert listing.status_code == 200
    assert "code.scheme" in listing.json()["items"]

    updated = await client.put("/api/v1/settings", json={"key": "topic.max_per_user", "value": 7})
    assert updated.status_code == 200
    assert updated.json()["value"] == "7"


async def test_moderator_cannot_read_settings(client, session, moderator):
    client.headers["Authorization"] = f"Bearer {create_access_token(moderator.id, {'role': moderator.role})}"
    assert (await client.get("/api/v1/settings")).status_code == 403


async def test_users_endpoints(client, session, owner):
    listing = await client.get("/api/v1/users")
    assert listing.status_code == 200
    assert any(row["tg_id"] == owner.tg_id for row in listing.json())

    counts = await client.get("/api/v1/users/count")
    assert counts.json()["total"] >= 2

    detail = await client.get(f"/api/v1/users/{owner.tg_id}")
    assert detail.json()["username"] == "akbar"


async def test_role_update_and_invalid_role(client, session, owner):
    ok = await client.patch(f"/api/v1/users/{owner.tg_id}", json={"role": "moderator"})
    assert ok.status_code == 200
    assert ok.json()["role"] == "moderator"

    bad = await client.patch(f"/api/v1/users/{owner.tg_id}", json={"role": "wizard"})
    assert bad.status_code == 422


async def test_webhook_is_logged(client, session):
    response = await client.post("/api/v1/webhook", json={"event": "payment.succeeded", "payload": {"id": 1}})
    assert response.status_code == 200
    audit = await client.get("/api/v1/moderation/audit")
    assert any(row["message"] == "event=payment.succeeded" for row in audit.json())


async def test_login_rejects_unknown_user(client, session):
    response = await client.post("/api/v1/auth/login", json={"username": "ghost", "password": "x"})
    assert response.status_code == 401