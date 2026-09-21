"""TZ 20 — archive export in JSON / HTML / TXT / PDF inside a ZIP."""

from __future__ import annotations

import io
import json
import zipfile

from app.enums import MessageContentType
from app.models.message import Media, Message
from app.services.archive_service import ArchiveService
from app.services.pdf_writer import PdfDocument
from tests.conftest import make_topic


async def _seed_messages(session, topic, owner):
    for index, kind in enumerate([MessageContentType.TEXT.value, MessageContentType.PHOTO.value,
                                  MessageContentType.VOICE.value, MessageContentType.LOCATION.value]):
        row = Message(
            topic_id=topic.id, tg_message_id=1000 + index, sender_id=owner.id, content_type=kind,
            text=f"xabar {index}" if kind == MessageContentType.TEXT.value else None,
            caption="rasm osti" if kind == MessageContentType.PHOTO.value else None,
            file_id=f"file-{index}" if kind != MessageContentType.TEXT.value else None,
            has_media=kind != MessageContentType.TEXT.value,
        )
        session.add(row)
        await session.flush()
        if row.has_media:
            session.add(Media(topic_id=topic.id, message_id=row.id, kind=kind,
                              file_id=row.file_id, file_size=1024))
    await session.flush()


async def test_zip_contains_every_requested_format(session, owner, gateway, tmp_path, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "archive_dir", str(tmp_path))
    topic = await make_topic(session, owner, code="A-0007")
    await _seed_messages(session, topic, owner)

    result = await ArchiveService(session).export(topic, owner)

    assert result.message_count == 4
    assert result.media_count == 3
    with zipfile.ZipFile(io.BytesIO(open(result.path, "rb").read())) as bundle:
        names = bundle.namelist()
        assert any(name.endswith(".json") for name in names)
        assert any(name.endswith(".html") for name in names)
        assert any(name.endswith(".txt") for name in names)
        assert any(name.endswith(".pdf") for name in names)
        payload = json.loads(bundle.read([n for n in names if n.endswith(".json")][0]))
        assert payload["topic"]["code"] == "A-0007"
        assert len(payload["messages"]) == 4
        assert payload["messages"][1]["media"][0]["file_id"] == "file-1"


async def test_archive_row_is_persisted_with_checksum(session, owner, gateway, tmp_path, monkeypatch):
    from sqlalchemy import select

    from app.core.config import settings
    from app.models.security import Archive

    monkeypatch.setattr(settings, "archive_dir", str(tmp_path))
    topic = await make_topic(session, owner)
    await _seed_messages(session, topic, owner)

    result = await ArchiveService(session).export(topic, owner)

    row = (await session.execute(select(Archive))).scalar_one()
    assert row.id == result.row.id
    assert row.checksum == result.checksum
    assert row.size == result.size > 0


async def test_pdf_is_a_valid_document():
    payload = PdfDocument(title="Test").build()
    assert payload.startswith(b"%PDF-1.4")
    assert payload.rstrip().endswith(b"%%EOF")
    assert b"/Type /Catalog" in payload
    assert b"startxref" in payload


def test_pdf_paginates_and_wraps():
    doc = PdfDocument(title="long")
    for index in range(300):
        doc.add(f"satr {index} " + "uzun matn " * 12)
    payload = doc.build()
    assert payload.count(b"/Type /Page ") >= 2


def test_pdf_transliterates_unsupported_glyphs():
    import re
    import zlib

    doc = PdfDocument()
    doc.add("❤ A001 — Toshkent … “salom”")
    payload = doc.build()

    streams = re.findall(rb"stream\n(.*?)\nendstream", payload, re.S)
    text = b"".join(zlib.decompress(stream) for stream in streams).decode("latin-1")
    assert "<3 A001 - Toshkent ... \"salom\"" in text


async def test_html_export_escapes_html(session, owner, gateway, tmp_path, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "archive_dir", str(tmp_path))
    topic = await make_topic(session, owner)
    session.add(Message(topic_id=topic.id, sender_id=owner.id, content_type="text",
                        text="<script>alert(1)</script>"))
    await session.flush()

    result = await ArchiveService(session).export(topic, owner, formats=["html"])
    with zipfile.ZipFile(result.path) as bundle:
        html = bundle.read([n for n in bundle.namelist() if n.endswith(".html")][0]).decode()
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
