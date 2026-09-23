"""Photo thumbnails (TZ 33: Thumbnail).

The ``media.thumb_path`` column existed but nothing ever wrote it — every
gallery render re-downloaded the original. ``ensure_thumbnail`` generates a
320px JPEG once and stores it under the storage dir. It must never raise:
a missing thumbnail degrades gracefully, a relay crash does not.
"""

from __future__ import annotations

import io

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.message import Media
from app.services.telegram_gateway import TelegramGateway

logger = get_logger(__name__)

THUMB_MAX_SIDE = 320
MIN_BYTES = 64  # smaller than this is not a real image


def make_thumbnail(data: bytes, max_side: int = THUMB_MAX_SIDE) -> bytes | None:
    """320px JPEG preview bytes, or None when Pillow cannot read the input."""
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            image = image.convert("RGB")
            image.thumbnail((max_side, max_side))
            out = io.BytesIO()
            image.save(out, format="JPEG", quality=80)
            return out.getvalue()
    except Exception as exc:  # noqa: BLE001 - never let decoration crash the flow
        logger.warning("thumbnail generation failed: %s", exc)
        return None


async def ensure_thumbnail(
    session: AsyncSession, media: Media, gateway: TelegramGateway
) -> str | None:
    """Generate and persist a thumbnail path for a photo media row."""
    if media.kind != "photo" or media.thumb_path:
        return media.thumb_path
    try:
        data = await gateway.get_file(media.file_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("thumbnail download failed file=%s: %s", media.file_id, exc)
        return None
    if not data or len(data) < MIN_BYTES:
        return None
    thumb = make_thumbnail(data)
    if thumb is None:
        return None
    from app.services.storage import media_path

    relative = media_path(media.file_id, "jpg")
    try:
        target = await _write(relative, thumb)
    except Exception as exc:  # noqa: BLE001
        logger.warning("thumbnail write failed: %s", exc)
        return None
    media.thumb_path = target
    await session.flush()
    return target


async def _write(relative: str, data: bytes, directory: str | None = None) -> str:
    from pathlib import Path

    base = Path(directory or "data/storage")
    base.mkdir(parents=True, exist_ok=True)
    path = base / Path(relative).name
    path.write_bytes(data)
    return str(path)
