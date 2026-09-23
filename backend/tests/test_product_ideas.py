"""The D-block product ideas from docs/07 — self-destruct timer (D1), voice
transcription in archives (D2), ban appeals (D5), QR invites (D6), public
stats (D7) and partner replacement (D8). D3/D4 landed in earlier rounds.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.security import create_access_token
from app.enums import MediaKind, MessageContentType
from app.models.message import Message
from app.models.security import BanAppeal
from app.services.archive_service import ArchiveService
from app.services.bot_service import SoulChatBot
from app.services.invite_service import InviteService
from tests.conftest import make_topic


@pytest.fixture
async def topic(session, owner):
    return await make_topic(session, owner, code="A-0500")


async def _relay_as(session, topic, user, gateway, text="so'z"):
    """Insert a message the way the relay would (sender_id = internal id)."""
    row = Message(
        topic_id=topic.id, sender_id=user.id, tg_message_id=4242 + user.id,
        content_type=MessageContentType.TEXT.value, text=text, relayed=True,
    )
    session.add(row)
    await session.flush()
    return row


# ------------------------------------------------------------------- D1 timer
async def test_timer_marks_the_last_own_message(session, owner, gateway, topic):
    await _relay_as(session, topic, owner, gateway)
    bot = SoulChatBot(session, gateway)
    reply = await bot.timer(111, "24h")
    assert "24h" in reply.text

    row = (
        await session.execute(select(Message).where(Message.topic_id == topic.id))
    ).scalars().first()
    assert row.self_destruct_at is not None
    due = row.self_destruct_at
    if due.tzinfo is None:
        due = due.replace(tzinfo=UTC)  # SQLite stores naive
    remaining = due - datetime.now(UTC)
    assert timedelta(hours=23) < remaining <= timedelta(hours=24)


async def test_timer_parses_minutes_days_and_rejects_junk(session, owner, gateway, topic):
    await _relay_as(session, topic, owner, gateway)
    bot = SoulChatBot(session, gateway)
    assert "30m" in (await bot.timer(111, "30m")).text
    assert "3d" in (await bot.timer(111, "3d")).text
    assert "Foydalanish" in (await bot.timer(111, "banana")).text
    assert "Maksimal" in (await bot.timer(111, "30d")).text


async def test_self_destruct_sweep_deletes_expired(session, owner, gateway, topic, monkeypatch):
    from app.tasks import _self_destruct_sweep

    row = await _relay_as(session, topic, owner, gateway)
    row.self_destruct_at = datetime.now(UTC) - timedelta(minutes=1)
    alive = Message(
        topic_id=topic.id, sender_id=owner.id, tg_message_id=9999,
        content_type=MessageContentType.TEXT.value, text="qoladi", relayed=True,
        self_destruct_at=datetime.now(UTC) + timedelta(hours=1),
    )
    session.add(alive)
    await session.flush()

    # the task opens its own session and gateway; point both at the test's
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def scoped():
        yield session

    async def fake_gateway():
        return gateway

    monkeypatch.setattr("app.core.db.session_scope", scoped)
    monkeypatch.setattr("app.tasks._gateway", fake_gateway)

    await session.commit()

    result = await _self_destruct_sweep()
    assert result["deleted"] == 1
    assert (topic.chat_id, row.tg_message_id) in gateway.deleted_messages

    await session.refresh(alive)
    assert alive.deleted is False


# ------------------------------------------------------- D2 voice transcript
async def test_archive_includes_voice_transcription(session, owner, gateway, topic):
    message = Message(
        topic_id=topic.id, sender_id=owner.id, tg_message_id=77,
        content_type=MessageContentType.VOICE.value, has_media=True,
    )
    session.add(message)
    await session.flush()
    session.add(
        __import__("app.models.message", fromlist=["Media"]).Media(
            topic_id=topic.id, message_id=message.id,
            kind=MediaKind.VOICE.value, file_id="voice-1",
        )
    )
    gateway.files["voice-1"] = b"fake-ogg-bytes"

    async def fake_transcribe(audio: bytes) -> str | None:
        return "Bu ovozli xabar matni"

    service = ArchiveService(session, gateway, transcriber=fake_transcribe)
    await service.export(topic, owner)

    import json
    import zipfile

    from app.core.config import settings as cfg

    zips = sorted(__import__("pathlib").Path(cfg.archive_dir).glob("soulchat-a0500-*.zip"))
    assert zips, "archive zip must exist"
    with zipfile.ZipFile(zips[-1]) as archive:
        payload = json.loads(archive.read([n for n in archive.namelist() if n.endswith(".json")][0]))
    voice_rows = [m for m in payload["messages"] if m["type"] == "voice"]
    assert voice_rows and voice_rows[0]["voice_text"] == "Bu ovozli xabar matni"


async def test_archive_without_transcriber_stays_clean(session, owner, gateway, topic):
    service = ArchiveService(session, gateway)  # no transcriber wired
    assert await service._voice_texts([]) == {}


# ------------------------------------------------------------------ D5 appeals
async def test_banned_user_can_appeal_and_admin_approves(client, session, admin, owner, gateway):
    from app.services.security_service import SecurityService

    await SecurityService(session).ban(owner.tg_id, admin, "spam")
    bot = SoulChatBot(session, gateway)
    reply = await bot.appeal(111, "Kechirim, bu xato edi")
    assert "yuborildi" in reply.text

    # duplicate pending appeal is refused
    again = await bot.appeal(111, "yana")
    assert "allaqachon" in again.text

    listing = await client.get("/api/v1/moderation/appeals")
    assert listing.status_code == 200
    rows = listing.json()
    assert len(rows) == 1
    appeal_id = rows[0]["id"]

    decision = await client.post(
        f"/api/v1/moderation/appeals/{appeal_id}/decision",
        json={"decision": "approve", "note": "haqiqatan ham xato"},
    )
    assert decision.status_code == 200
    await session.refresh(owner)
    assert owner.is_banned is False

    decided = await client.get("/api/v1/moderation/appeals", params={"status": "approved"})
    assert decided.status_code == 200
    assert len(decided.json()) == 1


async def test_appeal_decision_twice_conflicts(client, session, admin, owner, gateway):
    from app.services.security_service import SecurityService

    await SecurityService(session).ban(owner.tg_id, admin, "test")
    bot = SoulChatBot(session, gateway)
    await bot.appeal(111, "murojaat")
    appeal = (await session.execute(select(BanAppeal))).scalars().first()

    first = await client.post(
        f"/api/v1/moderation/appeals/{appeal.id}/decision", json={"decision": "reject"}
    )
    assert first.status_code == 200
    second = await client.post(
        f"/api/v1/moderation/appeals/{appeal.id}/decision", json={"decision": "approve"}
    )
    assert second.status_code == 409


async def test_moderator_cannot_approve_appeal(client, session, moderator, owner, gateway):
    from app.services.security_service import SecurityService

    await SecurityService(session).ban(owner.tg_id, moderator, "test")
    bot = SoulChatBot(session, gateway)
    await bot.appeal(111, "iltimos")
    appeal = (await session.execute(select(BanAppeal))).scalars().first()

    client.headers["Authorization"] = f"Bearer {create_access_token(moderator.id, {'role': moderator.role})}"
    response = await client.post(
        f"/api/v1/moderation/appeals/{appeal.id}/decision", json={"decision": "approve"}
    )
    assert response.status_code == 403


# ------------------------------------------------------------------- D6 QR
async def test_invite_qr_attaches_document(session, owner, gateway, topic):
    bot = SoulChatBot(session, gateway)
    reply = await bot.invite_qr(111)
    assert reply is not None
    assert "Taklif havolasi" in reply.text
    assert reply.document is not None
    payload, filename = reply.document
    assert filename == "invite-qr.png"
    assert payload[:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic


# --------------------------------------------------------------- D7 public
async def test_public_stats_needs_no_token_and_counts(client, session, topic, owner):
    session.add(
        Message(topic_id=topic.id, sender_id=owner.id, text="salom", relayed=True)
    )
    await session.flush()

    headers_backup = dict(client.headers)
    client.headers.pop("Authorization", None)
    response = await client.get("/api/v1/stats/public")
    client.headers.update(headers_backup)
    assert response.status_code == 200
    body = response.json()
    assert body["active_topics"] >= 1
    assert body["messages_today"] >= 1
    assert body["couples"] >= 0
    assert "generated_at" in body


# ------------------------------------------------------- D8 partner replace
async def test_owner_can_reinvite_after_partner_leaves(session, owner, partner, outsider, gateway, topic):
    from app.enums import ParticipantStatus

    service = InviteService(session, "SoulChatBot")
    created = await service.create(topic, owner)
    await service.accept(created.invite.token, partner)
    assert topic.partner_id == partner.id

    # a third user cannot take an used invite
    await service.leave(topic, partner)
    assert topic.partner_id is None

    fresh = await service.create(topic, owner)  # owner invites someone else
    await service.accept(fresh.invite.token, outsider)
    assert topic.partner_id == outsider.id

    participants = (
        await session.execute(
            __import__("app.models.topic", fromlist=["TopicParticipant"]).TopicParticipant.__table__.select()
        )
    ).all()
    statuses = {row.user_id: row.status for row in participants}
    assert statuses[partner.id] == ParticipantStatus.LEFT.value
    assert statuses[outsider.id] == ParticipantStatus.ACTIVE.value


def test_every_handler_command_is_listed_for_users():
    """A command that exists but is never advertised is a support ticket factory."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    handlers = (root / "app" / "bot" / "handlers" / "__init__.py").read_text()
    setup = (root / "app" / "bot" / "setup.py").read_text()

    defined = set(re.findall(r'Command\("([a-z_]+)"\)', handlers))
    advertised = set(re.findall(r'BotCommand\(command="([a-z_]+)"', setup))
    # deliberately hidden from the default menu: /confirm is prompted by the
    # close flow itself; /moderate, /settings and /stats are staff-only and
    # Telegram's default menu cannot be role-scoped.
    hidden = {"confirm", "moderate", "settings", "stats"}
    assert defined - advertised == hidden, (
        f"menu mismatch: missing={sorted(defined - advertised - hidden)} "
        f"stale={sorted(advertised - defined)}"
    )
    assert advertised <= defined, f"menu lists unknown commands: {sorted(advertised - defined)}"
