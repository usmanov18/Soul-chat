"""Telegram transport abstraction.

The service layer never talks to aiogram directly — it talks to
:class:`TelegramGateway`. That keeps every business rule unit-testable with
:class:`FakeGateway`, which records the exact API calls that *would* have been
sent to Telegram.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class TelegramGateway(Protocol):
    """Subset of the Bot API the platform relies on."""

    async def send_message(
        self, chat_id: int, text: str, *, thread_id: int | None = None, **kwargs: Any
    ) -> int: ...

    async def send_photo(
        self, chat_id: int, photo: Any, caption: str | None = None, *, thread_id: int | None = None, **kwargs: Any
    ) -> int: ...

    async def send_video(
        self, chat_id: int, video: Any, caption: str | None = None, *, thread_id: int | None = None, **kwargs: Any
    ) -> int: ...

    async def send_voice(
        self, chat_id: int, voice: Any, caption: str | None = None, *, thread_id: int | None = None, **kwargs: Any
    ) -> int: ...

    async def send_document(
        self, chat_id: int, document: Any, caption: str | None = None, *, thread_id: int | None = None, **kwargs: Any
    ) -> int: ...

    async def send_audio(
        self, chat_id: int, audio: Any, caption: str | None = None, *, thread_id: int | None = None, **kwargs: Any
    ) -> int: ...

    async def send_animation(
        self, chat_id: int, animation: Any, caption: str | None = None, *, thread_id: int | None = None, **kwargs: Any
    ) -> int: ...

    async def send_video_note(
        self, chat_id: int, video_note: Any, *, thread_id: int | None = None, **kwargs: Any
    ) -> int: ...

    async def send_sticker(
        self, chat_id: int, sticker: Any, *, thread_id: int | None = None, **kwargs: Any
    ) -> int: ...

    async def send_location(
        self, chat_id: int, latitude: float, longitude: float, *, thread_id: int | None = None, **kwargs: Any
    ) -> int: ...

    async def copy_message(
        self, chat_id: int, from_chat_id: int, message_id: int, *, thread_id: int | None = None
    ) -> int: ...

    async def create_forum_topic(
        self, chat_id: int, name: str, *, icon_color: int | None = None
    ) -> int: ...

    async def edit_forum_topic(
        self, chat_id: int, thread_id: int, *, name: str | None = None, icon_color: int | None = None
    ) -> bool: ...

    async def close_forum_topic(self, chat_id: int, thread_id: int) -> bool: ...

    async def reopen_forum_topic(self, chat_id: int, thread_id: int) -> bool: ...

    async def delete_forum_topic(self, chat_id: int, thread_id: int) -> bool: ...

    async def delete_message(self, chat_id: int, message_id: int) -> bool: ...

    async def restrict_chat_member(
        self, chat_id: int, user_id: int, permissions: dict[str, bool], until: int | None = None
    ) -> bool: ...

    async def get_chat_member(self, chat_id: int, user_id: int) -> Any: ...

    async def get_me(self) -> dict[str, Any]: ...


# ---------------------------------------------------------------------------
# Real implementation
# ---------------------------------------------------------------------------


class AiogramGateway:
    """Thin adapter over ``aiogram.Bot``."""

    def __init__(self, bot: Any) -> None:
        self.bot = bot
        self._next_id = 0

    async def _send(self, method: str, **kwargs: Any) -> int:
        result = await getattr(self.bot, method)(**kwargs)
        return int(getattr(result, "message_id", 0) or 0)

    async def send_message(self, chat_id: int, text: str, *, thread_id: int | None = None, **kw: Any) -> int:
        return await self._send(
            "send_message",
            chat_id=chat_id,
            text=text,
            message_thread_id=thread_id,
            **kw,
        )

    async def send_photo(self, chat_id: int, photo: Any, caption: str | None = None, *, thread_id: int | None = None, **kw: Any) -> int:
        return await self._send(
            "send_photo", chat_id=chat_id, photo=photo, caption=caption, message_thread_id=thread_id, **kw
        )

    async def send_video(self, chat_id: int, video: Any, caption: str | None = None, *, thread_id: int | None = None, **kw: Any) -> int:
        return await self._send(
            "send_video", chat_id=chat_id, video=video, caption=caption, message_thread_id=thread_id, **kw
        )

    async def send_voice(self, chat_id: int, voice: Any, caption: str | None = None, *, thread_id: int | None = None, **kw: Any) -> int:
        return await self._send(
            "send_voice", chat_id=chat_id, voice=voice, caption=caption, message_thread_id=thread_id, **kw
        )

    async def send_document(self, chat_id: int, document: Any, caption: str | None = None, *, thread_id: int | None = None, **kw: Any) -> int:
        return await self._send(
            "send_document", chat_id=chat_id, document=document, caption=caption, message_thread_id=thread_id, **kw
        )

    async def send_audio(self, chat_id: int, audio: Any, caption: str | None = None, *, thread_id: int | None = None, **kw: Any) -> int:
        return await self._send(
            "send_audio", chat_id=chat_id, audio=audio, caption=caption, message_thread_id=thread_id, **kw
        )

    async def send_animation(self, chat_id: int, animation: Any, caption: str | None = None, *, thread_id: int | None = None, **kw: Any) -> int:
        return await self._send(
            "send_animation", chat_id=chat_id, animation=animation, caption=caption, message_thread_id=thread_id, **kw
        )

    async def send_video_note(self, chat_id: int, video_note: Any, *, thread_id: int | None = None, **kw: Any) -> int:
        return await self._send(
            "send_video_note", chat_id=chat_id, video_note=video_note, message_thread_id=thread_id, **kw
        )

    async def send_sticker(self, chat_id: int, sticker: Any, *, thread_id: int | None = None, **kw: Any) -> int:
        return await self._send("send_sticker", chat_id=chat_id, sticker=sticker, message_thread_id=thread_id, **kw)

    async def send_location(self, chat_id: int, latitude: float, longitude: float, *, thread_id: int | None = None, **kw: Any) -> int:
        return await self._send(
            "send_location",
            chat_id=chat_id,
            latitude=latitude,
            longitude=longitude,
            message_thread_id=thread_id,
            **kw,
        )

    async def copy_message(self, chat_id: int, from_chat_id: int, message_id: int, *, thread_id: int | None = None) -> int:
        result = await self.bot.copy_message(
            chat_id=chat_id, from_chat_id=from_chat_id, message_id=message_id, message_thread_id=thread_id
        )
        return int(getattr(result, "message_id", 0) or 0)

    async def create_forum_topic(self, chat_id: int, name: str, *, icon_color: int | None = None) -> int:
        topic = await self.bot.create_forum_topic(chat_id=chat_id, name=name, icon_color=icon_color)
        return int(topic.message_thread_id)

    async def edit_forum_topic(self, chat_id: int, thread_id: int, *, name: str | None = None, icon_color: int | None = None) -> bool:
        return bool(await self.bot.edit_forum_topic(chat_id=chat_id, message_thread_id=thread_id, name=name, icon_color=icon_color))

    async def close_forum_topic(self, chat_id: int, thread_id: int) -> bool:
        try:
            return bool(await self.bot.close_forum_topic(chat_id=chat_id, message_thread_id=thread_id))
        except Exception:  # TOPIC_NOT_MODIFIED and friends are not fatal
            return False

    async def reopen_forum_topic(self, chat_id: int, thread_id: int) -> bool:
        try:
            return bool(await self.bot.reopen_forum_topic(chat_id=chat_id, message_thread_id=thread_id))
        except Exception:
            return False

    async def delete_forum_topic(self, chat_id: int, thread_id: int) -> bool:
        return bool(await self.bot.delete_forum_topic(chat_id=chat_id, message_thread_id=thread_id))

    async def delete_message(self, chat_id: int, message_id: int) -> bool:
        try:
            return bool(await self.bot.delete_message(chat_id=chat_id, message_id=message_id))
        except Exception:
            return False

    async def restrict_chat_member(self, chat_id: int, user_id: int, permissions: dict[str, bool], until: int | None = None) -> bool:
        from aiogram.types import ChatPermissions

        return bool(
            await self.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=ChatPermissions(**permissions),
                until_date=until,
            )
        )

    async def get_chat_member(self, chat_id: int, user_id: int) -> Any:
        return await self.bot.get_chat_member(chat_id=chat_id, user_id=user_id)

    async def get_me(self) -> dict[str, Any]:
        me = await self.bot.get_me()
        return {"id": me.id, "username": me.username, "first_name": me.first_name}


# ---------------------------------------------------------------------------
# Test double
# ---------------------------------------------------------------------------


@dataclass
class Call:
    """A recorded gateway call.

    ``Call("send_message", chat_id, text="hi")`` is accepted because ``__init__``
    is hand written to mirror a normal method signature.
    """

    method: str = field(init=False)
    args: tuple[Any, ...] = field(init=False)
    kwargs: dict[str, Any] = field(init=False)

    def __init__(self, method: str, *args: Any, **kwargs: Any) -> None:
        self.method = method
        self.args = args
        self.kwargs = kwargs

    @property
    def text(self) -> str | None:
        return self.kwargs.get("text") or self.kwargs.get("caption")

    @property
    def chat_id(self) -> Any:
        return self.args[0] if self.args else self.kwargs.get("chat_id")

    @property
    def thread_id(self) -> int | None:
        return self.kwargs.get("thread_id")


@dataclass
class FakeMember:
    status: str = "member"
    user_id: int = 0


class FakeGateway:
    """In-memory gateway: records calls, fakes message ids."""

    def __init__(self) -> None:
        self.calls: list[Call] = []
        self.members: dict[tuple[int, int], str] = {}
        self.topics_created: list[tuple[int, str, int | None]] = []
        self.closed_topics: list[tuple[int, int]] = []
        self.reopened_topics: list[tuple[int, int]] = []
        self.deleted_topics: list[tuple[int, int]] = []
        self.deleted_messages: list[tuple[int, int]] = []
        self.restrictions: list[tuple[int, int, dict[str, bool], int | None]] = []
        self.fail_on: set[str] = set()
        self._seq = 1000
        self.me = {"id": 42, "username": "SoulChatBot", "first_name": "SoulChat"}

    # -- helpers ---------------------------------------------------------
    def sent(self, method: str) -> list[Call]:
        return [c for c in self.calls if c.method == method]

    def texts(self, method: str = "send_message") -> list[str]:
        return [c.kwargs.get("text") or "" for c in self.sent(method)]

    def set_member(self, chat_id: int, user_id: int, status: str) -> None:
        self.members[(chat_id, user_id)] = status

    def _record(self, method: str, *args: Any, **kwargs: Any) -> Any:
        if method in self.fail_on:
            raise RuntimeError(f"telegram api failure: {method}")
        self.calls.append(Call(method, *args, **kwargs))
        self._seq += 1
        return self._seq

    # -- gateway ---------------------------------------------------------
    async def send_message(self, chat_id: int, text: str, *, thread_id: int | None = None, **kw: Any) -> int:
        return int(self._record("send_message", chat_id, text, thread_id=thread_id, **kw))

    async def send_photo(self, chat_id: int, photo: Any, caption: str | None = None, *, thread_id: int | None = None, **kw: Any) -> int:
        return int(self._record("send_photo", chat_id, photo, thread_id=thread_id, caption=caption, **kw))

    async def send_video(self, chat_id: int, video: Any, caption: str | None = None, *, thread_id: int | None = None, **kw: Any) -> int:
        return int(self._record("send_video", chat_id, video, thread_id=thread_id, caption=caption, **kw))

    async def send_voice(self, chat_id: int, voice: Any, caption: str | None = None, *, thread_id: int | None = None, **kw: Any) -> int:
        return int(self._record("send_voice", chat_id, voice, thread_id=thread_id, caption=caption, **kw))

    async def send_document(self, chat_id: int, document: Any, caption: str | None = None, *, thread_id: int | None = None, **kw: Any) -> int:
        return int(self._record("send_document", chat_id, document, thread_id=thread_id, caption=caption, **kw))

    async def send_audio(self, chat_id: int, audio: Any, caption: str | None = None, *, thread_id: int | None = None, **kw: Any) -> int:
        return int(self._record("send_audio", chat_id, audio, thread_id=thread_id, caption=caption, **kw))

    async def send_animation(self, chat_id: int, animation: Any, caption: str | None = None, *, thread_id: int | None = None, **kw: Any) -> int:
        return int(self._record("send_animation", chat_id, animation, thread_id=thread_id, caption=caption, **kw))

    async def send_video_note(self, chat_id: int, video_note: Any, *, thread_id: int | None = None, **kw: Any) -> int:
        return int(self._record("send_video_note", chat_id, video_note, thread_id=thread_id, **kw))

    async def send_sticker(self, chat_id: int, sticker: Any, *, thread_id: int | None = None, **kw: Any) -> int:
        return int(self._record("send_sticker", chat_id, sticker, thread_id=thread_id, **kw))

    async def send_location(self, chat_id: int, latitude: float, longitude: float, *, thread_id: int | None = None, **kw: Any) -> int:
        return int(
            self._record("send_location", chat_id, thread_id=thread_id, latitude=latitude, longitude=longitude)
        )

    async def copy_message(self, chat_id: int, from_chat_id: int, message_id: int, *, thread_id: int | None = None) -> int:
        return int(self._record("copy_message", chat_id, thread_id=thread_id, from_chat_id=from_chat_id, message_id=message_id))

    async def create_forum_topic(self, chat_id: int, name: str, *, icon_color: int | None = None) -> int:
        self.topics_created.append((chat_id, name, icon_color))
        self.calls.append(Call("create_forum_topic", chat_id, name=name, icon_color=icon_color))
        self._seq += 1
        return self._seq

    async def edit_forum_topic(self, chat_id: int, thread_id: int, *, name: str | None = None, icon_color: int | None = None) -> bool:
        self.calls.append(Call("edit_forum_topic", chat_id, thread_id=thread_id, name=name, icon_color=icon_color))
        return True

    async def close_forum_topic(self, chat_id: int, thread_id: int) -> bool:
        self.closed_topics.append((chat_id, thread_id))
        self.calls.append(Call("close_forum_topic", chat_id, thread_id=thread_id))
        return True

    async def reopen_forum_topic(self, chat_id: int, thread_id: int) -> bool:
        self.reopened_topics.append((chat_id, thread_id))
        self.calls.append(Call("reopen_forum_topic", chat_id, thread_id=thread_id))
        return True

    async def delete_forum_topic(self, chat_id: int, thread_id: int) -> bool:
        self.deleted_topics.append((chat_id, thread_id))
        self.calls.append(Call("delete_forum_topic", chat_id, thread_id=thread_id))
        return True

    async def delete_message(self, chat_id: int, message_id: int) -> bool:
        self.deleted_messages.append((chat_id, message_id))
        self.calls.append(Call("delete_message", chat_id, message_id=message_id))
        return True

    async def restrict_chat_member(self, chat_id: int, user_id: int, permissions: dict[str, bool], until: int | None = None) -> bool:
        self.restrictions.append((chat_id, user_id, permissions, until))
        self.calls.append(Call("restrict_chat_member", chat_id, user_id=user_id, permissions=permissions, until=until))
        return True

    async def get_chat_member(self, chat_id: int, user_id: int) -> Any:
        status = self.members.get((chat_id, user_id), "member")
        return FakeMember(status=status, user_id=user_id)

    async def get_me(self) -> dict[str, Any]:
        return dict(self.me)
