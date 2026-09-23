"""The sixth-round power features, end to end.

Rate limit (TZ 30), unban/unmute + fake-account score (TZ 22/27), birthday
sweep (TZ 24), hashtag search (TZ 23), export + backup file/verify (TZ 28/31),
summary/timeline/suggest/remember commands (TZ 27), thumbnails (TZ 33).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.security import create_access_token
from app.enums import (
    EventKind,
    MediaKind,
    NotificationKind,
)
from app.models.log import Notification
from app.models.message import Event, Media, Memory, Message
from app.models.security import SpamEvent
from app.models.user import User
from app.services.notification import NotificationService
from app.services.security_service import SecurityService
from app.services.telegram_gateway import FakeGateway
from tests.conftest import make_topic


@pytest.fixture
async def topic(session, owner):
    return await make_topic(session, owner, code="A-0900")


# ----------------------------------------------------------------- rate limit
async def test_api_rate_limit_returns_429(client, monkeypatch):
    monkeypatch.setattr(settings, "api_rate_limit_per_minute", 3)
    codes = []
    for _ in range(5):
        response = await client.get("/api/v1/auth/me")
        codes.append(response.status_code)
    assert codes[:3] == [200, 200, 200]
    assert codes[3] == 429
    assert codes[4] == 429
    assert "Retry-After" in response.headers


async def test_health_is_exempt_from_rate_limit(client, monkeypatch):
    monkeypatch.setattr(settings, "api_rate_limit_per_minute", 1)
    first = await client.get("/api/v1/health")
    second = await client.get("/api/v1/health")
    assert first.status_code == 200
    assert second.status_code == 200  # health never 429s (monitors poll it)


# ------------------------------------------------------------- unban / unmute
async def test_unban_lifts_a_ban_with_audit(client, session, admin, owner):
    security = SecurityService(session)
    banned = await security.ban(owner.tg_id, admin, "spam")
    assert banned.is_banned

    response = await client.post(
        "/api/v1/moderation/action",
        json={"tg_id": owner.tg_id, "action": "unban", "reason": "apellyatsiya"},
    )
    assert response.status_code == 200
    await session.refresh(owner)
    assert owner.is_banned is False


async def test_moderator_cannot_unban(client, moderator, session, admin):
    from tests.conftest import make_topic  # noqa: F401

    target = User(tg_id=555, first_name="Zo'r", username="zorr")
    session.add(target)
    await session.flush()
    session.add(User(tg_id=902, username="admin2", first_name="A2", role="admin"))
    await session.flush()

    client.headers["Authorization"] = f"Bearer {create_access_token(moderator.id, {'role': moderator.role})}"
    response = await client.post(
        "/api/v1/moderation/action",
        json={"tg_id": 555, "action": "unban", "reason": "x"},
    )
    assert response.status_code == 403


async def test_unmute_clears_the_flag(client, session, admin, owner):
    security = SecurityService(session)
    muted = await security.mute(owner.tg_id, 30, "flood")
    assert muted.is_muted

    response = await client.post(
        "/api/v1/moderation/action",
        json={"tg_id": owner.tg_id, "action": "unmute", "reason": "va'da"},
    )
    assert response.status_code == 200
    await session.refresh(owner)
    assert owner.is_muted is False


# ------------------------------------------------------------- fake accounts
async def test_fake_account_score_signals(session, owner, outsider):
    security = SecurityService(session)
    clean_score, clean_signals = await security.fake_account_score(owner)
    assert clean_score == 0
    assert clean_signals == []

    junk = User(tg_id=777, username="a1234")  # no display name at all
    session.add(junk)
    await session.flush()
    session.add(SpamEvent(user_id=junk.id, kind="spam", score=90, action="blocked"))
    session.add(SpamEvent(user_id=junk.id, kind="flood", score=60, action="blocked"))
    await session.flush()
    score, signals = await security.fake_account_score(junk)
    assert score >= 50  # profile signals (30) + recent spam history (20)
    assert "machine_username" in signals
    assert "no_name" in signals


async def test_fake_accounts_endpoint_lists_suspicious(client, session, owner):
    junk = User(tg_id=778, username="9999", first_name="9999")
    session.add(junk)
    await session.flush()
    response = await client.get("/api/v1/moderation/fake-accounts")
    assert response.status_code == 200
    rows = response.json()
    assert any(row["tg_id"] == 778 and row["score"] > 0 for row in rows)


# ----------------------------------------------------------------- birthdays
async def test_birthday_sweep_congratulates_once(session, gateway):
    today = datetime.now(UTC)
    user = User(
        tg_id=888, first_name="Tug'ilgan", username="bday",
        birthday=datetime(today.year - 25, today.month, today.day, tzinfo=UTC),
    )
    session.add(user)
    await session.flush()

    service = NotificationService(session, gateway)
    first = await service.birthday_sweep()
    assert first == {"birthdays": 1, "congratulated": 1}

    second = await service.birthday_sweep()
    assert second == {"birthdays": 1, "congratulated": 0}  # duplicate guard

    notes = (
        (await session.execute(select(Notification).where(Notification.user_id == user.id)))
        .scalars()
        .all()
    )
    assert len(notes) == 1
    assert notes[0].kind == NotificationKind.BIRTHDAY.value


async def test_birthday_sweep_ignores_other_days(session, gateway):
    user = User(
        tg_id=889, first_name="Oddiy", username="oddiy",
        birthday=datetime.now(UTC) - timedelta(days=3),
    )
    session.add(user)
    await session.flush()
    result = await NotificationService(session, gateway).birthday_sweep()
    assert result == {"birthdays": 0, "congratulated": 0}


# ----------------------------------------------------------------- hashtag
async def test_hashtag_search_filters_whole_tags(client, session, topic):
    session.add(Message(topic_id=topic.id, sender_id=111, text="bugun #sayohat rejasi"))
    session.add(Message(topic_id=topic.id, sender_id=111, text="#sayohatlar yomon"))
    await session.flush()
    response = await client.post(
        "/api/v1/analytics/search", json={"hashtag": "sayohat"}
    )
    assert response.status_code == 200
    messages = response.json()["messages"]
    assert len(messages) == 1
    assert "#sayohat " in messages[0]["text"] or messages[0]["text"].startswith("#sayohat")


# ----------------------------------------------------------------- export
async def test_export_users_csv(client, owner):
    response = await client.get("/api/v1/export/users")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    body = response.text
    assert body.splitlines()[0].startswith("id,tg_id")
    assert "akbar" in body


async def test_export_topics_json(client, topic):
    response = await client.get("/api/v1/export/topics", params={"fmt": "json"})
    assert response.status_code == 200
    import json

    rows = json.loads(response.text)
    assert rows[0]["code"] == "A-0900"


async def test_export_requires_staff(client, owner):
    client.headers["Authorization"] = f"Bearer {create_access_token(owner.id, {'role': owner.role})}"
    response = await client.get("/api/v1/export/users")
    assert response.status_code == 403


# --------------------------------------------------------- backup file/verify
async def test_backup_verify_reports_checksum_status(client, session, tmp_path, monkeypatch):
    from app.models.security import BackupHistory

    target = tmp_path / "dump.sql.gz"
    target.write_bytes(b"soulchat-backup-bytes")
    row = BackupHistory(
        target="local", path=str(target), size=target.stat().st_size,
        status="success", started_at=datetime.now(UTC),
        checksum=hashlib.sha256(target.read_bytes()).hexdigest(),
    )
    session.add(row)
    await session.flush()

    ok = await client.post("/api/v1/backup/verify", json={"id": row.id})
    assert ok.status_code == 200
    assert ok.json()["status"] == "ok"

    target.write_bytes(b"tampered")
    bad = await client.post("/api/v1/backup/verify", json={"id": row.id})
    assert bad.json()["status"] == "mismatch"


async def test_backup_file_streams_or_404s(client, session, tmp_path):
    from app.models.security import BackupHistory

    response = await client.get("/api/v1/backup/999/file")
    assert response.status_code == 404

    target = tmp_path / "dump2.sql.gz"
    target.write_bytes(b"payload")
    row = BackupHistory(
        target="local", path=str(target), size=7, status="success",
        started_at=datetime.now(UTC),
    )
    session.add(row)
    await session.flush()
    found = await client.get(f"/api/v1/backup/{row.id}/file")
    assert found.status_code == 200
    assert found.content == b"payload"


# ------------------------------------------------------ summary/timeline/etc
async def _seed_messages(session, topic, texts):
    for text in texts:
        session.add(Message(topic_id=topic.id, sender_id=111, text=text))
    await session.flush()


async def test_summary_command_answers(session, owner, gateway, monkeypatch):
    from app.services.bot_service import SoulChatBot

    topic = await make_topic(session, owner, code="A-0777")
    await _seed_messages(session, topic, ["Bugun chorbog'ordik", "Zo'r bo'ldi!", "Ertaga ham boramizmi?"])
    bot = SoulChatBot(session, gateway)
    reply = await bot.summary(111)
    assert "Xulosa" in reply.text


async def test_summary_without_topic(session, owner, gateway):
    from app.services.bot_service import SoulChatBot

    bot = SoulChatBot(session, gateway)
    reply = await bot.summary(111)
    assert "topilmadi" in reply.text


async def test_timeline_renders_events(session, owner, gateway):
    from app.services.bot_service import SoulChatBot

    topic = await make_topic(session, owner, code="A-0778")
    session.add(
        Event(
            topic_id=topic.id, created_by=owner.id, kind=EventKind.DATE.value,
            title="Ilk uchrashuv", due_at=datetime.now(UTC) + timedelta(days=2),
            location="Toshkent",
        )
    )
    await _seed_messages(session, topic, ["salom", "salom!"])
    await session.flush()
    bot = SoulChatBot(session, gateway)
    reply = await bot.timeline(111)
    assert "vaqt shkalasi" in reply.text
    assert "Ilk uchrashuv" in reply.text
    assert "Toshkent" in reply.text


async def test_suggest_returns_three_options(session, owner, gateway):
    from app.services.bot_service import SoulChatBot

    topic = await make_topic(session, owner, code="A-0779")
    await _seed_messages(session, topic, ["Ertaga kinoga boramizmi?"])
    bot = SoulChatBot(session, gateway)
    reply = await bot.suggest(111)
    assert reply.text.count("\n") >= 2  # 3 numbered options


async def test_memory_add_list_forget_flow(session, owner, gateway):
    from app.services.bot_service import SoulChatBot

    await make_topic(session, owner, code="A-0780")
    bot = SoulChatBot(session, gateway)

    saved = await bot.remember(111, "Sevimli kafe: Bon")
    assert "Eslatib qo'yildi" in saved.text
    assert "remember matn" not in saved.text

    listed = await bot.memory(111)
    assert "Bon" in listed.text

    all_rows = (await session.execute(select(Memory))).scalars().all()
    assert len(all_rows) == 1

    # a partner cannot delete someone else's memory
    outsider = User(tg_id=333, first_name="Begona")
    session.add(outsider)
    await session.flush()
    denied = await bot.forget(333, all_rows[0].id)
    assert "topilmadi" in denied.text

    ok = await bot.forget(111, all_rows[0].id)
    assert "O'chirildi" in ok.text


async def test_remember_requires_active_topic(session, owner, gateway):
    from app.services.bot_service import SoulChatBot

    bot = SoulChatBot(session, gateway)
    reply = await bot.remember(111, "hech narsa")
    assert "faol suhbat" in reply.text


# ----------------------------------------------------------------- thumbnails
async def test_thumbnail_generated_for_photos(session, topic, gateway):
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (800, 600), (120, 40, 200)).save(buffer, format="JPEG")
    gateway.files["photo-1"] = buffer.getvalue()

    message = Message(topic_id=topic.id, sender_id=111, has_media=True)
    session.add(message)
    await session.flush()
    media = Media(
        topic_id=topic.id, message_id=message.id, kind=MediaKind.PHOTO.value,
        file_id="photo-1", file_size=len(buffer.getvalue()),
    )
    session.add(media)
    await session.flush()

    from app.services.thumbs import ensure_thumbnail

    thumb_path = await ensure_thumbnail(session, media, gateway)
    assert thumb_path is not None
    assert media.thumb_path == thumb_path

    thumb_bytes = __import__("pathlib").Path(thumb_path).read_bytes()
    with Image.open(io.BytesIO(thumb_bytes)) as thumb:
        assert max(thumb.size) <= 320


async def test_thumbnail_skips_non_photos_and_crashy_gateways(session, topic):
    from app.services.thumbs import ensure_thumbnail

    media = Media(topic_id=topic.id, kind=MediaKind.VIDEO.value, file_id="v1")
    session.add(media)
    await session.flush()
    assert await ensure_thumbnail(session, media, FakeGateway()) is None

    class Boom(FakeGateway):
        async def get_file(self, file_id: str) -> bytes | None:
            raise RuntimeError("network down")

    photo = Media(topic_id=topic.id, kind=MediaKind.PHOTO.value, file_id="p-boom")
    session.add(photo)
    await session.flush()
    assert await ensure_thumbnail(session, photo, Boom()) is None  # never raises
