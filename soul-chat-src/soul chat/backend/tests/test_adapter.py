"""Bot adapter helpers (pure functions, no aiogram I/O)."""

from __future__ import annotations

from types import SimpleNamespace

from app.bot.adapter import (
    command_arg,
    content_type_of,
    deep_link_payload,
    event_args,
    extract_file,
    keyboard_of,
    media_dimensions,
    moderate_args,
    schedule_args,
)
from app.enums import MessageContentType
from app.services.bot_service import BotReply, Button


def test_content_type_maps_every_media_kind():
    for raw, expected in {
        "photo": MessageContentType.PHOTO.value,
        "video": MessageContentType.VIDEO.value,
        "voice": MessageContentType.VOICE.value,
        "document": MessageContentType.DOCUMENT.value,
        "audio": MessageContentType.AUDIO.value,
        "animation": MessageContentType.ANIMATION.value,
        "sticker": MessageContentType.STICKER.value,
        "video_note": MessageContentType.VIDEO_NOTE.value,
        "location": MessageContentType.LOCATION.value,
        "venue": MessageContentType.VENUE.value,
    }.items():
        assert content_type_of(SimpleNamespace(content_type=raw)) == expected


def test_unknown_content_type_falls_back_to_text():
    assert content_type_of(SimpleNamespace(content_type="dice")) == MessageContentType.TEXT.value
    assert content_type_of(SimpleNamespace(content_type=None)) == MessageContentType.TEXT.value


def test_photo_picks_the_largest_size():
    sizes = [
        SimpleNamespace(file_id="small", file_unique_id="u1", file_size=100, width=90, height=90,
                        duration=None, mime_type="image/jpeg"),
        SimpleNamespace(file_id="big", file_unique_id="u2", file_size=90_000, width=1280, height=960,
                        duration=None, mime_type="image/jpeg"),
        SimpleNamespace(file_id="mid", file_unique_id="u3", file_size=5_000, width=320, height=240,
                        duration=None, mime_type="image/jpeg"),
    ]
    file_id, unique_id, size = extract_file(SimpleNamespace(photo=sizes))
    assert (file_id, unique_id, size) == ("big", "u2", 90_000)
    width, height, duration, mime = media_dimensions(SimpleNamespace(photo=sizes))
    assert (width, height, mime) == (1280, 960, "image/jpeg")


def test_voice_extracts_duration_and_size():
    voice = SimpleNamespace(file_id="AwAD", file_unique_id="uw", file_size=4096,
                            duration=17, mime_type="audio/ogg", width=None, height=None)
    assert extract_file(SimpleNamespace(voice=voice, photo=None)) == ("AwAD", "uw", 4096)
    assert media_dimensions(SimpleNamespace(voice=voice, photo=None))[2] == 17


def test_text_message_has_no_file():
    message = SimpleNamespace(photo=None, video=None, voice=None, document=None, audio=None,
                              animation=None, sticker=None, video_note=None)
    assert extract_file(message) == (None, None, 0)


def test_keyboard_renders_rows():
    reply = BotReply(text="x")
    reply.row(Button("A", "a"), Button("B", "b"))
    reply.row(Button("C", "c"))
    keyboard = keyboard_of(reply)
    assert keyboard is not None
    assert [button.text for button in keyboard.inline_keyboard[0]] == ["A", "B"]
    assert [button.callback_data for button in keyboard.inline_keyboard[1]] == ["c"]


def test_empty_reply_has_no_keyboard():
    assert keyboard_of(BotReply(text="x")) is None


def test_deep_link_payload():
    assert deep_link_payload("inv_ABC123") == "inv_ABC123"
    assert deep_link_payload("  inv_X  ") == "inv_X"
    assert deep_link_payload(None) == ""


def test_schedule_args_parsing():
    assert schedule_args("1,3,5 20:00 22:00") == ([1, 3, 5], "20:00", "22:00")
    assert schedule_args("0 09:00 10:30") == ([0], "09:00", "10:30")
    assert schedule_args("1,3 20:00") is None
    assert schedule_args("mon,wed 20:00 22:00") is None
    assert schedule_args(None) is None


def test_event_args_parsing():
    assert event_args("Uchrashuv | 2026-12-31 19:00 | Toshkent") == (
        "Uchrashuv", "2026-12-31 19:00", "Toshkent"
    )
    assert event_args("Faqat sarlavha") == ("Faqat sarlavha", None, None)
    assert event_args("Nomi |  | Toshkent") == ("Nomi", None, "Toshkent")
    assert event_args("   ") is None


def test_moderate_args_parsing():
    assert moderate_args("warn 123456 spam") == ("warn", 123456, "spam")
    assert moderate_args("ban 123456") == ("ban", 123456, "")
    assert moderate_args("warn notanumber") is None
    assert moderate_args("warn") is None
    assert moderate_args(None) is None


def test_command_arg_strips():
    assert command_arg("  A-0042  ") == "A-0042"
    assert command_arg(None) == ""