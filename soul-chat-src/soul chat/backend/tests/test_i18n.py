"""Bot reply translations (TZ 24 — interface language follows the user)."""

from __future__ import annotations

import pytest

from app.core.i18n import (
    CATALOGUES,
    DEFAULT_LANGUAGE,
    SUPPORTED_LANGUAGES,
    available_keys,
    missing_keys,
    normalise_language,
    t,
)


def test_catalogues_are_complete():
    """No half-translated language ships: every Uzbek key exists everywhere."""
    assert missing_keys() == {}
    assert available_keys()


@pytest.mark.parametrize("language", SUPPORTED_LANGUAGES)
def test_every_key_renders_in_every_language(language: str):
    for key in available_keys():
        assert t(key, language).strip(), f"{key} is empty in {language}"


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("uz", "uz"),
        ("ru", "ru"),
        ("en", "en"),
        ("ru-RU", "ru"),
        ("en_US", "en"),
        ("RU", "ru"),
        ("  en-GB ", "en"),
        (None, DEFAULT_LANGUAGE),
        ("", DEFAULT_LANGUAGE),
        ("kk", DEFAULT_LANGUAGE),   # unsupported -> Uzbek, not a crash
        ("de", DEFAULT_LANGUAGE),
    ],
)
def test_language_normalisation(raw: str | None, expected: str):
    assert normalise_language(raw) == expected


def test_each_language_actually_differs():
    """Guards against a catalogue being copy-pasted from another."""
    bodies = {lang: t("help.body", lang) for lang in SUPPORTED_LANGUAGES}
    assert len(set(bodies.values())) == len(SUPPORTED_LANGUAGES)


def test_parameters_are_interpolated():
    assert t("invite.slot_limit", "uz", count=2, limit=1) == (
        "Siz allaqachon 2 ta suhbatda sheriksiniz (limit 1)."
    )
    assert t("topic.created", "en", code="A-0001") == "✅ Your conversation is open: <code>A-0001</code>"


def test_unknown_key_returns_the_key_rather_than_raising():
    assert t("no.such.key", "ru") == "no.such.key"


def test_parameter_mismatch_does_not_raise():
    """A template/param mismatch must never break a relay."""
    assert t("invite.slot_limit", "uz", count=1) == CATALOGUES["uz"]["invite.slot_limit"]


async def test_help_reply_follows_the_accounts_language(session, owner, gateway):
    from app.services.bot_service import SoulChatBot

    owner.language_code = "ru"
    await session.flush()
    assert "Команды" in (await SoulChatBot(session, gateway).help(owner.tg_id)).text

    owner.language_code = "en"
    await session.flush()
    assert "Commands" in (await SoulChatBot(session, gateway).help(owner.tg_id)).text


async def test_help_reply_falls_back_to_uzbek_for_unknown_languages(session, owner, gateway):
    """``users.language_code`` is NOT NULL, so the fallback path is an
    unsupported code (Telegram sends 'kk', 'uk', 'tr' …), not NULL."""
    from app.services.bot_service import SoulChatBot

    owner.language_code = "kk"
    await session.flush()
    assert "Buyruqlar" in (await SoulChatBot(session, gateway).help(owner.tg_id)).text