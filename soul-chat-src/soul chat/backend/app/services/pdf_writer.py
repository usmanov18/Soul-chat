"""Minimal, dependency-free PDF writer.

The archive export needs a printable transcript (TZ 20) and pulling in
reportlab/weasyprint just for a text PDF is not worth it. This writes a valid
PDF 1.4 file with one Helvetica font, automatic pagination and text wrapping.

Only WinAnsi characters are supported; anything else is transliterated, because
PDF base-14 fonts cannot render Cyrillic/Arabic scripts without an embedded TTF.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass, field

_PAGE_WIDTH = 595.28  # A4 portrait, points
_PAGE_HEIGHT = 841.89
_MARGIN = 56.0
_FONT_SIZE = 11.0
_LEADING = 15.0
_CHAR_WIDTH = _FONT_SIZE * 0.5  # Helvetica average advance

_TRANSLITERATION = {
    "‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", "…": "...",
    " ": " ", "\u200b": "", "❤": "<3", "✨": "*", "🌸": "*",
}


def _sanitize(text: str) -> str:
    out: list[str] = []
    for char in text:
        if char in _TRANSLITERATION:
            out.append(_TRANSLITERATION[char])
            continue
        code = ord(char)
        if 32 <= code <= 126 or code in (161, 163, 169, 171, 172, 174, 176, 177, 181, 182, 183, 187, 191):
            out.append(char)
        elif 0xC0 <= code <= 0xFF:  # latin-1 supplement (ä ö ñ ...)
            out.append(char)
        else:
            out.append("?")
    return "".join(out)


def _escape_pdf(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _wrap(text: str, width: float = _PAGE_WIDTH - 2 * _MARGIN) -> list[str]:
    max_chars = max(10, int(width / _CHAR_WIDTH))
    lines: list[str] = []
    for paragraph in text.split("\n"):
        if not paragraph:
            lines.append("")
            continue
        current = ""
        for word in paragraph.split(" "):
            candidate = f"{current} {word}".strip() if current else word
            if len(candidate) <= max_chars:
                current = candidate
            else:
                if current:
                    lines.append(current)
                # a single very long token gets hard-split
                while len(word) > max_chars:
                    lines.append(word[:max_chars])
                    word = word[max_chars:]
                current = word
        if current:
            lines.append(current)
    return lines


@dataclass
class PdfDocument:
    title: str = "SoulChat archive"
    lines: list[str] = field(default_factory=list)

    def add(self, text: str = "") -> None:
        self.lines.extend(_wrap(_sanitize(text)))

    def add_heading(self, text: str) -> None:
        self.lines.append("")
        self.lines.extend(_wrap(_sanitize(text.upper())))
        self.lines.append("")

    # ------------------------------------------------------------------
    def build(self) -> bytes:
        pages: list[list[str]] = []
        current: list[str] = []
        usable = _PAGE_HEIGHT - 2 * _MARGIN
        per_page = int(usable / _LEADING)
        for line in self.lines or [""]:
            current.append(line)
            if len(current) >= per_page:
                pages.append(current)
                current = []
        if current or not pages:
            pages.append(current or [""])

        objects: list[bytes] = []

        def add(body: bytes) -> int:
            objects.append(body)
            return len(objects)

        font_id_placeholder = 0  # resolved after we know the numbering
        # 1 = Catalog, 2 = Pages, 3 = Font, then (page, content) pairs.
        add(b"")  # catalog placeholder
        add(b"")  # pages placeholder
        font_obj = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
        assert font_id_placeholder == 0
        font_ref = f"{font_obj} 0 R"

        page_ids: list[int] = []
        for page_lines in pages:
            content_lines = ["BT", f"/F1 {_FONT_SIZE:.0f} Tf", f"{_LEADING:.0f} TL",
                             f"{_MARGIN:.2f} {_PAGE_HEIGHT - _MARGIN:.2f} Td"]
            for line in page_lines:
                if line:
                    content_lines.append(f"({_escape_pdf(line)}) Tj T*")
                else:
                    content_lines.append("T*")
            content_lines.append("ET")
            stream = "\n".join(content_lines).encode("latin-1", "replace")
            compressed = zlib.compress(stream)
            content_id = add(
                b"<< /Length " + str(len(compressed)).encode()
                + b" /Filter /FlateDecode >>\nstream\n" + compressed + b"\nendstream"
            )
            page_id = add(
                (
                    f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {_PAGE_WIDTH:.2f} {_PAGE_HEIGHT:.2f}] "
                    f"/Resources << /Font << /F1 {font_ref} >> >> /Contents {content_id} 0 R >>"
                ).encode()
            )
            page_ids.append(page_id)

        objects[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
        objects[1] = (
            b"<< /Type /Pages /Count " + str(len(page_ids)).encode() + b" /Kids ["
            + b" ".join(f"{pid} 0 R".encode() for pid in page_ids)
            + b"] >>"
        )

        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets: list[int] = []
        for index, body in enumerate(objects, start=1):
            offsets.append(len(out))
            out += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"
        xref_pos = len(out)
        out += f"xref\n0 {len(objects) + 1}\n".encode()
        out += b"0000000000 65535 f \n"
        for offset in offsets:
            out += f"{offset:010d} 00000 n \n".encode()
        out += (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R "
            f"/Info << /Title ({_escape_pdf(_sanitize(self.title))}) /Producer (SoulChat AI) >> >>\n"
            f"startxref\n{xref_pos}\n%%EOF\n"
        ).encode()
        return bytes(out)


def build_transcript_pdf(title: str, blocks: list[str]) -> bytes:
    doc = PdfDocument(title=title)
    for block in blocks:
        doc.add(block)
    return doc.build()