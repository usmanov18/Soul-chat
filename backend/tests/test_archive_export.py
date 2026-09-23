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


# ---------------------------------------------------------------------------
# TZ 20 — the media itself, not just a transcript that says "photo"
# ---------------------------------------------------------------------------
async def _seed_media(session, topic, owner, specs):
    """specs: list of (kind, file_id, size). Returns the created Media rows."""
    created = []
    for index, (kind, file_id, size) in enumerate(specs):
        row = Message(
            topic_id=topic.id, tg_message_id=2000 + index, sender_id=owner.id,
            content_type=kind, has_media=True, file_id=file_id,
        )
        session.add(row)
        await session.flush()
        item = Media(
            topic_id=topic.id, message_id=row.id, kind=kind, file_id=file_id,
            file_size=size, mime_type="image/jpeg" if kind == "photo" else None,
        )
        session.add(item)
        created.append(item)
    await session.flush()
    return created


async def test_media_files_are_bundled_into_the_zip(session, owner, gateway, tmp_path, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "archive_dir", str(tmp_path))
    monkeypatch.setattr(settings, "archive_include_media", True)
    gateway.files = {
        "AgADphoto": b"\xff\xd8\xffphoto-bytes",
        "AwADvoice": b"OggSvoice-bytes",
    }

    topic = await make_topic(session, owner, code="A-0070")
    await _seed_media(session, topic, owner, [("photo", "AgADphoto", 1024),
                                              ("voice", "AwADvoice", 2048)])

    result = await ArchiveService(session, gateway).export(topic, owner)

    assert result.media_bundled == 2
    assert result.media_skipped == 0
    with zipfile.ZipFile(result.path) as bundle:
        media_entries = [name for name in bundle.namelist() if name.startswith("media/")]
        assert len(media_entries) == 2
        assert bundle.read(media_entries[0]) == b"\xff\xd8\xffphoto-bytes"
        # extension comes from the media kind, not from a stored file name
        assert any(name.endswith(".jpg") for name in media_entries)
        assert any(name.endswith(".ogg") for name in media_entries)


async def test_without_a_gateway_the_transcript_still_works(session, owner, tmp_path, monkeypatch):
    """No transport must not fail the archive — only the media is missing."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "archive_dir", str(tmp_path))
    topic = await make_topic(session, owner, code="A-0071")
    await _seed_media(session, topic, owner, [("photo", "AgADx", 1024)])

    result = await ArchiveService(session).export(topic, owner)

    assert result.media_bundled == 0
    assert result.media_skipped == 0          # not skipped: never attempted
    with zipfile.ZipFile(result.path) as bundle:
        assert not [n for n in bundle.namelist() if n.startswith("media/")]
        assert any(n.endswith(".json") for n in bundle.namelist())


async def test_media_can_be_switched_off(session, owner, gateway, tmp_path, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "archive_dir", str(tmp_path))
    monkeypatch.setattr(settings, "archive_include_media", False)
    gateway.download_all = True

    topic = await make_topic(session, owner, code="A-0072")
    await _seed_media(session, topic, owner, [("photo", "AgADoff", 1024)])

    result = await ArchiveService(session, gateway).export(topic, owner)

    assert result.media_bundled == 0
    assert gateway.downloads == []            # never even asked Telegram


async def test_oversized_file_is_skipped_with_a_reason(session, owner, gateway, tmp_path, monkeypatch):
    """Telegram caps bot downloads at 20 MB — say so instead of failing."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "archive_dir", str(tmp_path))
    gateway.download_all = True

    topic = await make_topic(session, owner, code="A-0073")
    await _seed_media(session, topic, owner, [
        ("photo", "AgADsmall", 1024),
        ("video", "AgADhuge", settings.telegram_max_download_bytes + 1),
    ])

    result = await ArchiveService(session, gateway).export(topic, owner)

    assert result.media_bundled == 1
    assert result.media_skipped == 1
    assert any("chegara" in reason for reason in result.skipped_reasons)
    assert "AgADhuge" not in gateway.downloads


async def test_budget_stops_the_bundle_but_keeps_the_archive(session, owner, gateway, tmp_path, monkeypatch):
    """The budget is checked against the *downloaded* size, not file_size.

    ``media.file_size`` is frequently 0 (nothing forces a caller to record it),
    so a budget that trusted it alone was a no-op.
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "archive_dir", str(tmp_path))
    monkeypatch.setattr(settings, "archive_media_budget_bytes", 150)
    gateway.files = {
        "AgADa": b"a" * 100,
        "AgADb": b"b" * 100,          # 100 + 100 > 150 once the first lands
    }

    topic = await make_topic(session, owner, code="A-0074")
    await _seed_media(session, topic, owner, [
        ("photo", "AgADa", 100),
        ("photo", "AgADb", 100),
    ])

    result = await ArchiveService(session, gateway).export(topic, owner)

    assert result.media_bundled == 1
    assert result.media_skipped == 1
    assert any("hajmi chegarasi" in reason for reason in result.skipped_reasons)
    # the archive still exists and still holds the transcript
    with zipfile.ZipFile(result.path) as bundle:
        assert any(n.endswith(".json") for n in bundle.namelist())


async def test_budget_works_even_when_file_size_is_unknown(session, owner, gateway, tmp_path, monkeypatch):
    """file_size=0 (the common case) must not disable the limit."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "archive_dir", str(tmp_path))
    monkeypatch.setattr(settings, "archive_media_budget_bytes", 10)
    gateway.files = {"AgADone": b"x" * 5, "AgADtwo": b"y" * 20}

    topic = await make_topic(session, owner, code="A-0077")
    await _seed_media(session, topic, owner, [
        ("photo", "AgADone", 0),      # size unknown, 5 bytes -> fits
        ("photo", "AgADtwo", 0),      # size unknown, 20 bytes -> over budget
    ])

    result = await ArchiveService(session, gateway).export(topic, owner)

    assert result.media_bundled == 1
    assert result.media_skipped == 1


async def test_undownloadable_file_is_skipped_not_fatal(session, owner, gateway, tmp_path, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "archive_dir", str(tmp_path))
    gateway.files = {"AgADgood": b"ok"}        # the other id is simply unknown

    topic = await make_topic(session, owner, code="A-0075")
    await _seed_media(session, topic, owner, [("photo", "AgADgood", 10),
                                              ("photo", "AgADmissing", 10)])

    result = await ArchiveService(session, gateway).export(topic, owner)

    assert result.media_bundled == 1
    assert result.media_skipped == 1
    assert any("yuklab olib bo'lmadi" in reason for reason in result.skipped_reasons)


def test_media_names_are_ordered_and_collision_free():
    from app.models.message import Media
    from app.services.archive_service import ArchiveService

    first = ArchiveService._media_name(
        Media(kind="photo", file_id="AgADBAxyz", file_size=1), 3
    )
    second = ArchiveService._media_name(
        Media(kind="photo", file_id="AgADBAxyz", file_size=1), 4
    )
    assert first != second                    # same file_id, still unique
    assert first.startswith("003_")
    assert first.endswith(".jpg")


async def test_sweeper_archive_includes_media(session, owner, gateway, tmp_path, monkeypatch):
    """The 96h sweep is the last chance to keep the photos — it must bundle them."""

    from app.core.config import settings

    monkeypatch.setattr(settings, "archive_dir", str(tmp_path))
    gateway.download_all = True

    topic = await make_topic(session, owner, code="A-0076")
    await _seed_media(session, topic, owner, [("photo", "AgADsweep", 512)])
    await session.commit()

    service = ArchiveService(session, gateway)
    result = await service.export(topic)
    assert result.media_bundled == 1

    with zipfile.ZipFile(result.path) as bundle:
        assert [n for n in bundle.namelist() if n.startswith("media/")]