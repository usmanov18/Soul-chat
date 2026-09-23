"""The admin panel switches must actually switch something.

Every key in ``DEFAULTS`` is rendered as a toggle in the admin panel. Until
this was tested, nothing consumed those rows: the services read
``app.core.config`` directly, so an operator could flip ``channel.show_names``
off, see it saved, and the channel would keep publishing real names — the exact
thing TZ 10 promises against. ``SETTINGS_META`` even labelled it "enforced".

These tests drive the switch the way the panel does (write the row) and assert
on what actually leaves the bot.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime

import pytest

from app.core.config import settings as env_settings
from app.enums import SettingType
from app.models.log import Setting
from app.services.event_service import ChannelService, GalleryCard
from app.services.settings_service import DEFAULTS, SETTINGS_META, SettingsService
from tests.conftest import make_topic

PIL = pytest.importorskip("PIL")
Image = PIL.Image


def jpeg(width: int = 900, height: int = 1200) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (40, 90, 170)).save(buffer, format="JPEG")
    return buffer.getvalue()


async def panel_switch(session, key: str, value: bool) -> None:
    """What ``PUT /settings`` does: upsert the row, then drop the cache."""
    service = SettingsService(session)
    await service.set(key, value, actor=None)


def card() -> GalleryCard:
    return GalleryCard("A-0001", "Akbar", "Salima", "Bugun yaxshi", "Toshkent",
                       datetime(2026, 9, 22, 21, 40, tzinfo=UTC))


# ------------------------------------------------------------- show_names
async def test_panel_switch_hides_names_from_the_channel(session, owner, partner, gateway, monkeypatch):
    """The regression: env said True, the panel said False, the panel lost."""
    monkeypatch.setattr(env_settings, "channel_show_names", True)
    await panel_switch(session, "channel.show_names", False)
    topic = await make_topic(session, owner, code="A-0029")

    await ChannelService(session, gateway).announce_topic(topic, owner, partner)

    text = gateway.sent("send_message")[0].args[1]
    assert "Akbar" not in text
    assert "Salima" not in text
    assert "A-0029" in text


async def test_panel_switch_can_turn_names_on(session, owner, partner, gateway, monkeypatch):
    monkeypatch.setattr(env_settings, "channel_show_names", False)
    await panel_switch(session, "channel.show_names", True)
    topic = await make_topic(session, owner, code="A-0030")

    await ChannelService(session, gateway).announce_topic(topic, owner, partner)

    text = gateway.sent("send_message")[0].args[1]
    assert "Akbar Karimov" in text
    assert "Salima Yusupova" in text


async def test_panel_switch_hides_names_from_the_drawn_card(session, owner, partner, gateway, monkeypatch):
    """The overlay must respect the same switch as the caption (TZ 10)."""
    monkeypatch.setattr(env_settings, "channel_show_names", True)
    await panel_switch(session, "channel.show_names", False)
    topic = await make_topic(session, owner)
    gateway.files["AgADBA"] = jpeg()

    await ChannelService(session, gateway).publish_gallery(topic, owner, partner, "AgADBA", card())

    caption = gateway.sent("send_photo")[0].kwargs["caption"]
    assert "Akbar" not in caption
    assert "Salima" not in caption


# ----------------------------------------------------------- show_gallery
async def test_panel_switch_stops_gallery_posts(session, owner, gateway, monkeypatch):
    monkeypatch.setattr(env_settings, "channel_show_gallery", True)
    await panel_switch(session, "channel.show_gallery", False)
    topic = await make_topic(session, owner)
    gateway.files["AgADBA"] = jpeg()

    result = await ChannelService(session, gateway).publish_gallery(
        topic, owner, None, "AgADBA", card()
    )

    assert result is None
    assert gateway.sent("send_photo") == []


# --------------------------------------------------------- gallery_overlay
async def test_panel_switch_turns_the_overlay_off(session, owner, gateway, monkeypatch):
    monkeypatch.setattr(env_settings, "channel_gallery_overlay", True)
    await panel_switch(session, "channel.gallery_overlay", False)
    topic = await make_topic(session, owner)
    gateway.files["AgADBA"] = jpeg()

    await ChannelService(session, gateway).publish_gallery(topic, owner, None, "AgADBA", card())

    assert gateway.sent("send_photo")[0].args[1] == "AgADBA"
    assert gateway.downloads == []  # not even fetched


async def test_panel_switch_turns_the_overlay_on_again(session, owner, gateway, monkeypatch):
    monkeypatch.setattr(env_settings, "channel_gallery_overlay", False)
    await panel_switch(session, "channel.gallery_overlay", True)
    topic = await make_topic(session, owner)
    gateway.files["AgADBA"] = jpeg()

    await ChannelService(session, gateway).publish_gallery(topic, owner, None, "AgADBA", card())

    assert isinstance(gateway.sent("send_photo")[0].args[1], bytes)


# ---------------------------------------------------------------- caching
async def test_a_setting_change_takes_effect_without_a_restart(session, owner, gateway):
    """The cache is per-service, and set() must invalidate it."""
    topic = await make_topic(session, owner, code="A-0031")
    service = ChannelService(session, gateway)

    await panel_switch(session, "channel.show_names", False)
    await service.announce_topic(topic, owner, None)
    assert "Akbar" not in gateway.sent("send_message")[-1].args[1]

    await panel_switch(session, "channel.show_names", True)
    await service.announce_topic(topic, owner, None)
    assert "Akbar Karimov" in gateway.sent("send_message")[-1].args[1]


async def test_get_bool_caches_until_the_next_write(session):
    service = SettingsService(session)

    first = await service.get_bool("channel.show_names", True)
    # a raw row bypasses set(), so the cache does not know about it
    session.add(Setting(key="channel.show_names", value="false", value_type=SettingType.BOOL.value))
    await session.flush()
    assert await service.get_bool("channel.show_names", True) is first  # still cached

    service.invalidate()
    assert await service.get_bool("channel.show_names", True) is False


async def test_a_write_through_the_panel_is_seen_by_an_existing_service(session):
    """Panel writes go through set(), which bumps the shared generation.

    The service instance outlives the write — that is the real shape of the bug:
    a long-lived service holding a value the panel had already changed.
    """
    service = SettingsService(session)

    await panel_switch(session, "channel.show_names", True)
    assert await service.get_bool("channel.show_names", False) is True

    await panel_switch(session, "channel.show_names", False)
    assert await service.get_bool("channel.show_names", True) is False


@pytest.mark.parametrize("raw,expected", [("true", True), ("false", False), ("1", True),
                                          ("0", False), ("yes", True), ("no", False)])
async def test_get_bool_parses_whatever_the_row_holds(session, raw, expected):
    from app.services.settings_service import _as_bool

    assert _as_bool(raw, fallback=not expected) is expected


async def test_get_bool_precedence_is_row_then_defaults_then_env(session):
    """Documented chain: stored row -> DEFAULTS -> the caller's env default."""
    service = SettingsService(session)

    # no row: DEFAULTS is derived from app.core.config, so it wins over the
    # argument, which is why both calls below agree.
    from app.services.settings_service import DEFAULTS

    registered_default = DEFAULTS["channel.show_names"][1]
    assert await service.get_bool("channel.show_names", not registered_default) is bool(
        registered_default
    )

    # an unknown key has no DEFAULTS entry, so the env default decides
    assert await service.get_bool("channel.does_not_exist", True) is True
    assert await service.get_bool("channel.does_not_exist", False) is False


# ---------------------------------------------------- registry consistency
def test_every_channel_switch_has_operator_metadata():
    """A toggle with no label reads as a raw key and has no enforcement badge."""
    for key in DEFAULTS:
        if key.startswith("channel."):
            assert key in SETTINGS_META, f"{key} is a toggle without metadata"
            assert SETTINGS_META[key]["enforcement"] in {"enforced", "reactive", "advisory"}


def test_metadata_never_claims_enforcement_for_an_unread_setting():
    """Guards the original bug from the other side.

    Anything labelled "enforced" must be read at runtime. The channel flags are
    the ones that were wrong; if a new one is added without wiring, this fails.
    """
    import inspect

    import app.services.event_service as event_service

    source = inspect.getsource(event_service)
    for key, meta in SETTINGS_META.items():
        if not key.startswith("channel."):
            continue
        if meta["enforcement"] != "enforced":
            continue
        assert f'"{key}"' in source, f"{key} claims 'enforced' but nothing reads it"