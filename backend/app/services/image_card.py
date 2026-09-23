"""Event Gallery overlay — draws the conversation card *onto* the photo (TZ 15).

TZ 14/15 ask for aesthetic media posts in the public channel. A caption under
the picture reads as metadata; drawing the card into the image reads as a
*gallery*, which is what the section is called.

Design rules, all of them deliberate:

* **Never raise.** ``render_overlay`` returns ``None`` on any failure and the
  caller falls back to the plain photo. A channel post is decoration — it must
  never cost a user their message.
* **No emoji in the image.** The bundled DejaVu font has no emoji glyphs, so
  they render as empty boxes. Emoji stay in the HTML caption; only plain text
  is drawn here.
* **Everything scales off the image width**, so a 320px thumbnail and a 2560px
  photo get the same look.
* **Anonymity first.** Names are drawn only when ``show_names`` is set, matching
  ``render_gallery_caption`` — TZ 10 keeps names out of the open by default.
"""

from __future__ import annotations

import io

from app.core.logging import get_logger

logger = get_logger(__name__)

try:  # pragma: no cover - exercised by test_image_card.missing_pillow
    from PIL import Image, ImageDraw, ImageFont

    _PIL_AVAILABLE = True
except ImportError:  # pragma: no cover
    Image = None  # type: ignore[assignment]
    ImageDraw = None  # type: ignore[assignment]
    ImageFont = None  # type: ignore[assignment]
    _PIL_AVAILABLE = False


# DejaVu ships with Pillow on every platform; falling back to the bitmap
# default font keeps the card legible if the file layout ever changes.
_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)

_GRADIENT_TOP = (10, 10, 32)
_GRADIENT_BOTTOM = (46, 16, 84)
_TEXT = (255, 255, 255)
_TEXT_DIM = (226, 222, 255)


def pillow_available() -> bool:
    return _PIL_AVAILABLE


def _font(size: int):
    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def _clean(value: str | None) -> str:
    """Drop emoji and collapse whitespace — the font cannot draw them."""
    if not value:
        return ""
    keep = [ch for ch in value if ord(ch) < 0x2100 and not ch.isspace() or ch == " "]
    return " ".join("".join(keep).split())[:48]


def _gradient(width: int, height: int) -> Image.Image:
    """Vertical indigo→violet gradient, top transparent so the photo shows."""
    ramp = Image.new("L", (1, height))
    for y in range(height):
        ramp.putpixel((0, y), int(215 * (y / max(height - 1, 1)) ** 1.6))
    colour = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(colour)
    for y in range(height):
        t = y / max(height - 1, 1)
        draw.line(
            [(0, y), (width, y)],
            fill=tuple(int(a + (b - a) * t) for a, b in zip(_GRADIENT_TOP, _GRADIENT_BOTTOM, strict=True)),
        )
    mask = ramp.resize((width, height))
    colour.putalpha(mask)
    return colour


def render_overlay(
    payload: bytes,
    *,
    code: str,
    caption: str | None = None,
    location: str | None = None,
    when: str | None = None,
    names: str | None = None,
    max_side: int = 1280,
) -> bytes | None:
    """Return JPEG bytes with the card drawn in, or ``None`` if it cannot.

    ``when`` and ``names`` are pre-formatted strings: the caller owns i18n and
    the anonymity decision, this module only lays pixels.
    """
    if not _PIL_AVAILABLE:
        logger.warning("overlay skipped: Pillow is not installed")
        return None
    try:
        image = Image.open(io.BytesIO(payload)).convert("RGB")
        image.thumbnail((max_side, max_side))
        width, height = image.size
        if width < 240 or height < 240:
            # too small for the card to be legible; the plain photo is better
            return None

        band_height = max(int(height * 0.34), 150)
        band = _gradient(width, band_height)
        image.paste(band, (0, height - band_height), band)

        draw = ImageDraw.Draw(image)
        pad = max(int(width * 0.055), 22)
        y = height - band_height + int(band_height * 0.26)

        code_font = _font(max(int(width * 0.062), 26))
        draw.text((pad, y), _clean(code) or "—", font=code_font, fill=_TEXT)
        y += int(code_font.size * 1.5)

        detail_font = _font(max(int(width * 0.036), 17))
        for line in (names, _clean(caption), _clean(location), when):
            text = _clean(line) if line is not names else (line or "").strip()
            if not text:
                continue
            draw.text((pad, y), text[:64], font=detail_font, fill=_TEXT_DIM)
            y += int(detail_font.size * 1.55)

        # a thin hairline where the band starts, so the fade has an edge
        draw.line(
            [(0, height - band_height), (width, height - band_height)],
            fill=(255, 255, 255, 40),
            width=1,
        )

        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=88, optimize=True)
        return buffer.getvalue()
    except Exception as exc:  # pragma: no cover - defensive, logged
        logger.warning("overlay render failed: %s", exc)
        return None