"""Topic archive / export (TZ 20).

Exports every message of a topic — text, photo, video, voice, document, link,
location, sticker — into JSON / HTML / TXT / PDF, zips them and hands the file
to both participants before the topic is deleted.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core import metrics
from app.core.config import settings
from app.core.logging import get_logger
from app.enums import AuditAction
from app.models.message import Media, Message
from app.models.security import Archive
from app.models.topic import Topic
from app.models.user import User
from app.services.audit import AuditService
from app.services.pdf_writer import build_transcript_pdf
from app.services.telegram_gateway import TelegramGateway

logger = get_logger(__name__)


# file extension per media kind, used when Telegram gives us no file name
_EXTENSION_BY_KIND: dict[str, str] = {
    "photo": ".jpg",
    "video": ".mp4",
    "voice": ".ogg",
    "audio": ".mp3",
    "document": ".bin",
    "animation": ".mp4",
    "video_note": ".mp4",
    "sticker": ".webp",
}


@dataclass
class ArchiveResult:
    row: Archive
    path: str
    size: int
    checksum: str
    formats: list[str]
    message_count: int
    media_count: int
    # how many media files actually made it into the zip, and why the rest did not
    media_bundled: int = 0
    media_skipped: int = 0
    skipped_reasons: list[str] = field(default_factory=list)


class ArchiveService:
    def __init__(
        self, session: AsyncSession, gateway: TelegramGateway | None = None
    ) -> None:
        self.session = session
        self.audit = AuditService(session)
        # without a transport the transcript is still produced, only the media
        # bundle is skipped — the archive must never fail outright
        self.gateway = gateway

    # ------------------------------------------------------------------
    async def export(self, topic: Topic, requested_by: User | None = None,
                     formats: list[str] | None = None) -> ArchiveResult:
        formats = [f.lower() for f in (formats or settings.archive_formats)]
        rows, senders = await self._load(topic)

        os.makedirs(settings.archive_dir, exist_ok=True)
        # Microseconds: two archives of the same topic in one second used to
        # collide on the same zip name and overwrite each other.
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
        slug = topic.code.replace("-", "").lower()
        base = f"soulchat-{slug}-{stamp}"
        zip_path = os.path.join(settings.archive_dir, f"{base}.zip")

        payloads: dict[str, bytes] = {
            "json": self._json(topic, rows, senders).encode("utf-8"),
            "txt": self._txt(topic, rows, senders).encode("utf-8"),
            "html": self._html(topic, rows, senders).encode("utf-8"),
            "pdf": build_transcript_pdf(
                f"SoulChat {topic.code}", self._blocks(topic, rows, senders)
            ),
        }

        # TZ 20 asks for the media itself, not just a transcript that says
        # "photo". Everything is downloaded first so the zip is written once.
        bundled, skipped, reasons = await self._bundle_media(topic, rows)

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for fmt in formats:
                if fmt in payloads:
                    archive.writestr(f"{base}.{fmt}", payloads[fmt])
            archive.writestr("README.txt", self._readme(topic).encode("utf-8"))
            for name, blob in bundled:
                # ZIP_STORED for already-compressed media would only waste CPU;
                # deflate is harmless either way and keeps text transcripts small
                archive.writestr(f"media/{name}", blob)

        size = os.path.getsize(zip_path)
        checksum = _sha256(zip_path)
        media_count = sum(1 for row in rows if row.has_media)

        archive_row = Archive(
            topic_id=topic.id,
            fmt="zip",
            path=zip_path,
            size=size,
            checksum=checksum,
            requested_by=requested_by.id if requested_by else None,
            message_count=len(rows),
            media_count=media_count,
        )
        self.session.add(archive_row)
        await self.audit.log(
            AuditAction.EXPORT,
            actor=requested_by,
            topic=topic,
            message=f"archive {base}.zip ({len(rows)} messages, {size} bytes)",
        )
        await self.session.flush()
        return ArchiveResult(
            row=archive_row,
            path=zip_path,
            size=size,
            checksum=checksum,
            formats=formats,
            message_count=len(rows),
            media_count=media_count,
            media_bundled=len(bundled),
            media_skipped=skipped,
            skipped_reasons=reasons,
        )

    async def _bundle_media(
        self, topic: Topic, rows: list[Message]
    ) -> tuple[list[tuple[str, bytes]], int, list[str]]:
        """Download every media file of the topic, within a byte budget.

        Returns ``(entries, skipped_count, reasons)`` where each entry is
        ``(zip_path, bytes)``. Nothing here raises: a file Telegram will not
        hand over is recorded and the archive still gets written, because an
        incomplete archive is far better than none at all 96 hours before the
        topic is deleted.
        """
        entries: list[tuple[str, bytes]] = []
        if not settings.archive_include_media or self.gateway is None:
            return entries, 0, []

        message_ids = [row.id for row in rows]
        if not message_ids:
            return entries, 0, []

        media_rows = (
            await self.session.execute(
                select(Media)
                .where(Media.topic_id == topic.id, Media.message_id.in_(message_ids))
                .order_by(Media.id)
            )
        ).scalars().all()

        budget = settings.archive_media_budget_bytes
        cap = settings.telegram_max_download_bytes
        used = 0
        skipped = 0
        reasons: list[str] = []
        for index, item in enumerate(media_rows, start=1):
            # Telegram refuses to serve anything over 20 MB to a bot; the
            # recorded size lets us skip it without a wasted round trip, but it
            # is not trusted as the only signal (see the post-download check).
            if item.file_size > cap:
                skipped += 1
                reasons.append(f"{item.kind} {item.file_id}: {item.file_size} bayt > {cap} bayt chegara")
                continue

            blob = await self.gateway.get_file(item.file_id)
            if blob is None:
                skipped += 1
                reasons.append(f"{item.kind} {item.file_id}: yuklab olib bo'lmadi")
                continue

            # Budget against the *actual* size. media.file_size is often 0 —
            # nothing forces a caller to record it — so checking it alone made
            # the limit a no-op.
            if used + len(blob) > budget:
                skipped += 1
                reasons.append(
                    f"{item.kind} {item.file_id}: arxiv hajmi chegarasi "
                    f"({budget} bayt, {len(blob)} bayt kerak edi)"
                )
                continue
            if len(blob) > cap:
                skipped += 1
                reasons.append(f"{item.kind} {item.file_id}: {len(blob)} bayt > {cap} bayt chegara")
                continue

            used += len(blob)
            entries.append((self._media_name(item, index), blob))

        if entries:
            metrics.incr(
                "soulchat_archive_media_bytes_total",
                amount=sum(len(blob) for _, blob in entries),
            )
        if skipped:
            metrics.incr("soulchat_archive_media_skipped_total", amount=float(skipped))
            logger.warning(
                "archive %s: %s media bundled, %s skipped (%s)",
                topic.code, len(entries), skipped, "; ".join(reasons[:5]),
            )
        return entries, skipped, reasons

    @staticmethod
    def _media_name(item: Media, index: int) -> str:
        """``003_photo_AgADBA.jpg`` — ordered, kinded, and collision free."""
        extension = _EXTENSION_BY_KIND.get(item.kind, "")
        if not extension and item.mime_type:
            extension = "." + item.mime_type.split("/")[-1].split("+")[0]
        stem = "".join(c if c.isalnum() else "_" for c in item.file_id)[:24]
        return f"{index:03d}_{item.kind}_{stem}{extension}"

    def read(self, result: ArchiveResult) -> bytes:
        with open(result.path, "rb") as handle:
            return handle.read()

    # ------------------------------------------------------------------
    async def _load(self, topic: Topic) -> tuple[list[Message], dict[int, str]]:
        stmt = (
            select(Message)
            .where(Message.topic_id == topic.id)
            .options(selectinload(Message.media))
            .order_by(Message.id)
        )
        rows = list((await self.session.execute(stmt)).scalars().all())
        senders: dict[int, str] = {}
        for user in (await self.session.execute(select(User))).scalars().all():
            senders[user.id] = user.full_name
        return rows, senders

    # ---------------------------------------------------------- renderers
    def _json(self, topic: Topic, rows: list[Message], senders: dict[int, str]) -> str:
        payload = {
            "topic": {
                "code": topic.code,
                "status": topic.status,
                "created_at": _iso(topic.created_at),
                "closed_at": _iso(topic.closed_at),
                "message_count": topic.message_count,
                "media_count": topic.media_count,
            },
            "participants": [
                {"role": "owner", "id": topic.owner_id, "name": senders.get(topic.owner_id, "")},
                *(
                    [{"role": "partner", "id": topic.partner_id,
                      "name": senders.get(topic.partner_id, "")}]
                    if topic.partner_id else []
                ),
            ],
            "messages": [
                {
                    "id": row.id,
                    "telegram_message_id": row.tg_message_id,
                    "at": _iso(row.created_at),
                    "sender": senders.get(row.sender_id, f"id{row.sender_id}"),
                    "type": row.content_type,
                    "text": row.text,
                    "caption": row.caption,
                    "file_id": row.file_id,
                    "media": [
                        {
                            "kind": media.kind,
                            "file_id": media.file_id,
                            "size": media.file_size,
                            "duration": media.duration,
                        }
                        for media in row.media
                    ],
                    "deleted": row.deleted,
                }
                for row in rows
            ],
            "exported_at": _iso(datetime.now(UTC)),
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _txt(self, topic: Topic, rows: list[Message], senders: dict[int, str]) -> str:
        lines = [
            f"SoulChat arxivi — {topic.code}",
            f"Status: {topic.status}",
            f"Yaratilgan: {_iso(topic.created_at)}",
            f"Yopilgan: {_iso(topic.closed_at) or '-'}",
            f"Xabarlar: {len(rows)}",
            "=" * 60,
            "",
        ]
        for row in rows:
            who = senders.get(row.sender_id, f"id{row.sender_id}")
            stamp = (row.created_at.strftime("%Y-%m-%d %H:%M") if row.created_at else "")
            body = row.text or row.caption or f"[{row.content_type}]"
            lines.append(f"[{stamp}] {who} ({row.content_type}): {body}")
            for media in row.media:
                lines.append(f"    ↳ {media.kind} file_id={media.file_id} size={media.file_size}")
        return "\n".join(lines)

    def _html(self, topic: Topic, rows: list[Message], senders: dict[int, str]) -> str:
        bubbles = []
        for row in rows:
            who = _html_escape(senders.get(row.sender_id, f"id{row.sender_id}"))
            stamp = row.created_at.strftime("%d.%m %H:%M") if row.created_at else ""
            body = _html_escape(row.text or row.caption or f"[{row.content_type}]")
            media_html = "".join(
                f'<div class="media">{_html_escape(m.kind)} · {_html_escape(m.file_id or "")}</div>'
                for m in row.media
            )
            bubbles.append(
                f'<div class="msg"><div class="meta"><b>{who}</b><span>{stamp}</span></div>'
                f'<div class="body">{body}{media_html}</div></div>'
            )
        return f"""<!doctype html>
<html lang="uz"><head><meta charset="utf-8">
<title>SoulChat — {topic.code}</title>
<style>
  :root {{ color-scheme: dark light; }}
  body {{ font-family: -apple-system, "Segoe UI", Roboto, sans-serif; margin: 0;
         background: linear-gradient(160deg,#0f172a,#1e293b); color: #e2e8f0; }}
  .wrap {{ max-width: 760px; margin: 0 auto; padding: 32px 20px 64px; }}
  header {{ padding: 24px; border-radius: 20px; backdrop-filter: blur(12px);
            background: rgba(255,255,255,.06); border: 1px solid rgba(255,255,255,.12); }}
  h1 {{ margin: 0; font-size: 28px; letter-spacing: .5px; }}
  .muted {{ opacity: .7; font-size: 14px; }}
  .msg {{ margin-top: 14px; padding: 14px 16px; border-radius: 18px;
          background: rgba(255,255,255,.05); border: 1px solid rgba(255,255,255,.08); }}
  .meta {{ display: flex; justify-content: space-between; font-size: 12px; opacity: .75; }}
  .body {{ margin-top: 6px; white-space: pre-wrap; }}
  .media {{ margin-top: 6px; font-size: 12px; opacity: .6; }}
</style></head>
<body><div class="wrap">
<header>
  <h1>💬 {topic.code}</h1>
  <div class="muted">Status: {topic.status} · Xabarlar: {len(rows)} ·
  Yaratilgan: {_iso(topic.created_at)}</div>
</header>
{''.join(bubbles)}
</div></body></html>"""

    def _blocks(self, topic: Topic, rows: list[Message], senders: dict[int, str]) -> list[str]:
        header = [
            f"SOULCHAT ARXIVI - {topic.code}",
            f"Status: {topic.status}",
            f"Yaratilgan: {_iso(topic.created_at)}",
            f"Yopilgan: {_iso(topic.closed_at) or '-'}",
            f"Jami xabar: {len(rows)}",
            "-" * 60,
        ]
        body = []
        for row in rows:
            who = senders.get(row.sender_id, f"id{row.sender_id}")
            stamp = row.created_at.strftime("%Y-%m-%d %H:%M") if row.created_at else ""
            body.append(f"[{stamp}] {who} ({row.content_type}): "
                        f"{row.text or row.caption or '[' + row.content_type + ']'}")
        return header + body

    @staticmethod
    def _readme(topic: Topic) -> str:
        return (
            f"SoulChat AI arxivi — {topic.code}\n\n"
            "Fayllar:\n"
            "  .json — to'liq strukturali eksport (API uchun)\n"
            "  .html — glass UI uslubidagi o'qish uchun qulay transkript\n"
            "  .txt  — oddiy matn\n"
            "  .pdf  — chop etish uchun\n\n"
            "Media fayllar Telegram serverida file_id orqali saqlanadi; "
            "json fayldagi file_id bilan bot orqali qayta yuklab olish mumkin.\n"
        )


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


def _html_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def bytes_buffer(data: bytes) -> io.BytesIO:
    return io.BytesIO(data)