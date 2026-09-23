"""Relationship timeline and topic memories (TZ 27).

Both features read the couple's own data back to them: the timeline folds
events and daily activity into one view, memories are short facts a writer
saves on purpose (``/remember``). Nothing here calls an external model —
these are deterministic services, which keeps them testable and honest.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.message import Event, Memory, Message
from app.models.topic import Topic


class RelationshipService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def timeline(self, topic: Topic, *, max_events: int = 10) -> dict:
        """A compact relationship timeline: milestones + activity shape."""
        event_rows = (
            (
                await self.session.execute(
                    select(Event)
                    .where(Event.topic_id == topic.id)
                    .order_by(Event.due_at.is_(None), Event.due_at)
                    .limit(max_events)
                )
            )
            .scalars()
            .all()
        )

        total = await self.session.scalar(
            select(func.count()).select_from(Message).where(Message.topic_id == topic.id)
        )
        media_total = await self.session.scalar(
            select(func.count())
            .select_from(Message)
            .where(Message.topic_id == topic.id, Message.has_media.is_(True))
        )
        first = await self.session.scalar(
            select(func.min(Message.created_at)).where(Message.topic_id == topic.id)
        )
        last = await self.session.scalar(
            select(func.max(Message.created_at)).where(Message.topic_id == topic.id)
        )
        return {
            "code": topic.code,
            "total_messages": int(total or 0),
            "total_media": int(media_total or 0),
            "first_message": first.isoformat() if first else None,
            "last_message": last.isoformat() if last else None,
            "events": [
                {
                    "kind": e.kind,
                    "title": e.title,
                    "due_at": e.due_at.isoformat() if e.due_at else None,
                    "location": e.location,
                    "status": e.status,
                }
                for e in event_rows
            ],
        }

    def render_timeline(self, data: dict, lang_lines: dict[str, str] | None = None) -> str:
        """Human-readable version for the bot reply."""
        if not data["total_messages"]:
            return "Hozircha suhbat tarixi yo'q."
        lines = [f"🕰 <b>{data['code']}</b> — vaqt shkalasi:"]
        lines.append(f"• {data['total_messages']} xabar, {data['total_media']} media")
        if data["first_message"]:
            lines.append(f"• Boshlanishi: {data['first_message'][:10]}")
        for event in data["events"]:
            marker = {"date": "📅", "reminder": "⏰", "location": "📍", "checklist": "☑️",
                      "deadline": "⏳", "photo": "📷", "video": "🎬"}.get(event["kind"], "•")
            when = f" — {event['due_at'][:16].replace('T', ' ')}" if event["due_at"] else ""
            where = f" @ {event['location']}" if event["location"] else ""
            lines.append(f"{marker} {event['title']}{when}{where}")
        return "\n".join(lines)


class MemoryService:
    """Per-topic memories the writers save on purpose (TZ 27: Automatic Memory).

    Kept explicit instead of inferred: the couple decides what to remember, the
    platform guarantees it is not lost when the topic closes (archive reads the
    same table).
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, topic: Topic, user_id: int, text: str) -> Memory:
        row = Memory(topic_id=topic.id, created_by=user_id, text=text.strip()[:1000])
        self.session.add(row)
        await self.session.flush()
        return row

    async def list_for(self, topic: Topic, limit: int = 30) -> list[Memory]:
        rows = (
            await self.session.execute(
                select(Memory)
                .where(Memory.topic_id == topic.id)
                .order_by(Memory.id.desc())
                .limit(limit)
            )
        ).scalars().all()
        return list(rows)

    async def forget(self, topic: Topic, memory_id: int, user_id: int) -> bool:
        """A writer may delete only their own memory."""
        row = (
            await self.session.execute(
                select(Memory).where(
                    Memory.id == memory_id,
                    Memory.topic_id == topic.id,
                    Memory.created_by == user_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return False
        await self.session.delete(row)
        await self.session.flush()
        return True
