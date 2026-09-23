"""TZ 15 — the Event Gallery card drawn *onto* the photo.

A caption under a picture reads as metadata; drawing the card into the image is
what makes the channel post a gallery. The hard requirement here is that the
overlay is pure decoration: every failure path must fall back to the plain
photo, never raise, and never cost the user their message.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.enums import ChannelPostType, MessageContentType
from app.models.message import ChannelPost
from app.services import image_card
from app.services.bot_service import SoulChatBot
from app.services.event_service import ChannelService, GalleryCard
from app.services.image_card import render_overlay
from app.services.relay import IncomingMessage
from tests.conftest import make_topic

PIL = pytest.importorskip("PIL")
Image = PIL.Image


def jpeg(width: int = 900, height: int = 1200, colour=(40, 90, 170)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(buffer, format="JPEG")
    return buffer.getvalue()


def card(**overrides) -> GalleryCard:
    base = {
        "topic_code": "A-0001",
        "owner_name": "Akbar",
        "partner_name": None,
        "caption": "Bugun juda yaxshi kun",
        "location": "Toshkent",
        "when": datetime(2026, 9, 22, 21, 40, tzinfo=UTC),
    }
    base.update(overrides)
    return GalleryCard(**base)


def photo_of(call) -> object:
    """``FakeGateway._record`` stores chat_id and the photo *positionally*."""
    if "photo" in call.kwargs:
        return call.kwargs["photo"]
    return call.args[1]


def _changed_pixels(a: bytes, b: bytes, size=(90, 120)) -> int:
    first = Image.open(io.BytesIO(a)).convert("RGB").resize(size).load()
    second = Image.open(io.BytesIO(b)).convert("RGB").resize(size).load()
    return sum(1 for y in range(size[1]) for x in range(size[0]) if first[x, y] != second[x, y])


# ------------------------------------------------------------- the renderer
def test_overlay_returns_a_valid_jpeg_of_the_same_size():
    payload = jpeg()

    rendered = render_overlay(
        payload, code="A-0001", caption="Salom", location="Toshkent", when="22.09  21:40"
    )

    assert rendered is not None
    image = Image.open(io.BytesIO(rendered))
    assert image.format == "JPEG"
    assert image.size == (900, 1200)
    assert _changed_pixels(payload, rendered) > 500  # the band really was drawn


def test_overlay_leaves_the_top_of_the_photo_alone():
    """The gradient is a bottom band; the user's picture must stay visible."""
    payload = jpeg()

    rendered = render_overlay(payload, code="A-0001")

    top_original = Image.open(io.BytesIO(payload)).convert("RGB").crop((0, 0, 900, 300))
    top_rendered = Image.open(io.BytesIO(rendered)).convert("RGB").crop((0, 0, 900, 300))
    assert list(top_original.getdata()) == list(top_rendered.getdata())


def test_overlay_downscales_a_huge_photo():
    rendered = render_overlay(jpeg(3000, 4000), code="A-0001", max_side=1280)

    assert Image.open(io.BytesIO(rendered)).size == (960, 1280)


def test_overlay_skips_a_thumbnail_too_small_for_the_card():
    assert render_overlay(jpeg(120, 120), code="A-0001") is None


@pytest.mark.parametrize("payload", [b"", b"not-an-image", b"\xff\xd8\xff\xe0broken"])
def test_overlay_never_raises_on_a_bad_payload(payload):
    """A corrupt download must degrade, not blow up the channel post."""
    assert render_overlay(payload, code="A-0001") is None


def test_overlay_strips_emoji_the_font_cannot_draw():
    """DejaVu has no emoji glyphs — they would render as empty boxes."""
    from app.services.image_card import _clean

    assert _clean("🌸 Bugun yaxshi") == "Bugun yaxshi"
    assert _clean("   ko'p    bo'shliq  ") == "ko'p bo'shliq"
    assert _clean(None) == ""


def test_overlay_is_skipped_entirely_without_pillow(monkeypatch):
    monkeypatch.setattr(image_card, "_PIL_AVAILABLE", False)

    assert render_overlay(jpeg(), code="A-0001") is None
    assert image_card.pillow_available() is False


# ------------------------------------------------------------ the channel
@pytest.fixture
def service(session, gateway, monkeypatch):
    monkeypatch.setattr(settings, "channel_id", -100999)
    monkeypatch.setattr(settings, "channel_show_gallery", True)
    monkeypatch.setattr(settings, "channel_gallery_overlay", True)
    monkeypatch.setattr(settings, "channel_show_names", False)
    return ChannelService(session, gateway)


async def test_gallery_post_sends_the_rendered_image(service, session, owner, gateway):
    topic = await make_topic(session, owner)
    gateway.files["AgADBA"] = jpeg()

    message_id = await service.publish_gallery(topic, owner, None, "AgADBA", card())

    assert message_id
    sent = gateway.sent("send_photo")
    assert len(sent) == 1
    photo = photo_of(sent[0])
    assert isinstance(photo, bytes), "expected the rendered image, not the file_id"
    assert Image.open(io.BytesIO(photo)).format == "JPEG"
    assert gateway.downloads == ["AgADBA"]


async def test_overlay_is_opt_out(service, session, owner, gateway):
    from app.models.log import Setting

    session.add(Setting(key="channel.gallery_overlay", value="false", value_type="bool"))
    await session.flush()
    service.settings.invalidate()
    topic = await make_topic(session, owner)
    gateway.files["AgADBA"] = jpeg()

    await service.publish_gallery(topic, owner, None, "AgADBA", card())

    assert photo_of(gateway.sent("send_photo")[0]) == "AgADBA"
    assert gateway.downloads == []  # never even fetched


async def test_gallery_falls_back_when_the_download_is_empty(service, session, owner, gateway):
    topic = await make_topic(session, owner)
    # nothing registered in gateway.files -> get_file returns None

    message_id = await service.publish_gallery(topic, owner, None, "AgADBA", card())

    assert message_id
    assert photo_of(gateway.sent("send_photo")[0]) == "AgADBA"


async def test_gallery_falls_back_when_the_file_is_corrupt(service, session, owner, gateway):
    topic = await make_topic(session, owner)
    gateway.files["AgADBA"] = b"this is not a jpeg"

    message_id = await service.publish_gallery(topic, owner, None, "AgADBA", card())

    assert message_id
    assert photo_of(gateway.sent("send_photo")[0]) == "AgADBA"


async def test_gallery_records_no_file_id_for_a_rendered_image(service, session, owner, gateway):
    """A re-encoded upload has no Telegram file_id to point at."""
    topic = await make_topic(session, owner)
    gateway.files["AgADBA"] = jpeg()

    await service.publish_gallery(topic, owner, None, "AgADBA", card())

    row = (await session.execute(select(ChannelPost))).scalar_one()
    assert row.kind == ChannelPostType.GALLERY.value
    assert not row.media_file_ids


async def test_gallery_still_records_the_file_id_without_the_overlay(service, session, owner, gateway):
    from app.models.log import Setting

    session.add(Setting(key="channel.gallery_overlay", value="false", value_type="bool"))
    await session.flush()
    service.settings.invalidate()
    topic = await make_topic(session, owner)

    await service.publish_gallery(topic, owner, None, "AgADBA", card())

    row = (await session.execute(select(ChannelPost))).scalar_one()
    assert row.media_file_ids == ["AgADBA"]


async def test_names_are_not_drawn_by_default(service, session, owner, gateway):
    """TZ 10 — the channel is public, so the card carries the code only."""
    topic = await make_topic(session, owner)
    gateway.files["AgADBA"] = jpeg()

    await service.publish_gallery(topic, owner, None, "AgADBA", card(partner_name="Salima"))

    sent = gateway.sent("send_photo")[0]
    photo = photo_of(sent)
    caption = sent.kwargs["caption"]
    assert b"Akbar" not in photo  # not that bytes prove much, the caption does:
    assert "Akbar" not in caption
    assert "Salima" not in caption


# --------------------------------------------------------------- end to end
@pytest.fixture
def bot(session, gateway, monkeypatch):
    monkeypatch.setattr(settings, "subscription_required", False)
    monkeypatch.setattr(settings, "forum_chat_id", -100123)
    monkeypatch.setattr(settings, "channel_id", -100999)
    monkeypatch.setattr(settings, "channel_gallery_overlay", True)
    return SoulChatBot(session, gateway)


async def test_a_photo_relayed_by_a_user_reaches_the_channel_with_an_overlay(
    bot, session, gateway
):
    await bot.start(111, username="akbar", first_name="Akbar")
    await bot.new_topic(111)
    gateway.files["AgADBA"] = jpeg()

    await bot.handle_private_message(
        IncomingMessage(
            user_id=111,
            chat_id=111,
            content_type=MessageContentType.PHOTO.value,
            file_id="AgADBA",
            caption="Toshkent",
        )
    )

    posts = gateway.sent("send_photo")
    assert len(posts) == 2  # the topic copy and the channel gallery
    channel_post = posts[-1]
    assert channel_post.args[0] == -100999
    assert isinstance(photo_of(channel_post), bytes)