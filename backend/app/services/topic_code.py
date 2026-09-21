"""Topic code generator (TZ 7, 8, 9).

Three schemes are supported and selectable from the admin panel:

* ``sequential`` — one shared counter, letters rotate: ``A-0001, B-0002, C-0003``
* ``gender``     — separate letter pools per gender (default: male ``A-M``,
  female ``N-Z``), counter is shared so codes never collide
* ``random``     — a random letter from the active pool, e.g. ``L-0042``

Codes are unique, short and collision free: the counter row is locked with
``SELECT ... FOR UPDATE`` on PostgreSQL (a plain read-modify-write on SQLite).
"""

from __future__ import annotations

import secrets
import string
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.enums import CodeScheme, Gender
from app.models.topic import CodePrefix

DEFAULT_MALE = "ABCDEFGHIJKLM"
DEFAULT_FEMALE = "NOPQRSTUVWXYZ"


@dataclass(frozen=True)
class GeneratedCode:
    code: str          # A-0001
    display: str       # ❤ A001  (emoji + no separator)
    letter: str        # A
    sequence: int      # 1
    prefix_id: int


class TopicCodeGenerator:
    """Creates the next code for a topic.

    ``session`` is passed explicitly (instead of using a global) so the same
    object works in the bot, in REST handlers and in unit tests.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------- setup
    async def ensure_default_prefixes(self) -> list[CodePrefix]:
        """Seed the default scheme on first boot (idempotent)."""
        existing = (await self.session.execute(select(CodePrefix))).scalars().all()
        if existing:
            return list(existing)

        scheme = settings.default_code_scheme
        created: list[CodePrefix] = []
        if scheme == CodeScheme.GENDER:
            pools = ((Gender.MALE.value, settings.male_prefix_letters or DEFAULT_MALE),
                     (Gender.FEMALE.value, settings.female_prefix_letters or DEFAULT_FEMALE))
        else:
            pools = ((None, string.ascii_uppercase[:13]),)

        for gender, letters in pools:
            prefix = CodePrefix(
                letters=letters.upper(),
                gender=gender,
                mode=CodeScheme.GENDER.value if gender else CodeScheme.SEQUENTIAL.value,
                separator=settings.code_separator,
                pad=settings.code_zero_pad,
                emoji=settings.code_emoji,
            )
            self.session.add(prefix)
            created.append(prefix)
        await self.session.flush()
        return created

    # ------------------------------------------------------------ public
    async def next_code(self, gender: str | None = None) -> GeneratedCode:
        """Allocate the next unique code for ``gender`` (``male``/``female``/None)."""
        prefixes = await self.ensure_default_prefixes()
        prefix = self._pick_prefix(prefixes, gender)

        if settings.is_sqlite:
            prefix.counter = (prefix.counter or 0) + 1
        else:  # pragma: no cover - exercised on PostgreSQL only
            locked = await self.session.execute(
                select(CodePrefix).where(CodePrefix.id == prefix.id).with_for_update()
            )
            prefix = locked.scalar_one()
            prefix.counter = (prefix.counter or 0) + 1

        await self.session.flush()

        sequence = prefix.counter
        if prefix.mode == CodeScheme.RANDOM.value:
            letter = secrets.choice(prefix.letters)
        else:
            letter = prefix.letter_for(sequence - 1)

        number = str(sequence).zfill(max(0, prefix.pad or 0))
        code = f"{letter}{prefix.separator}{number}" if prefix.separator else f"{letter}{number}"
        display = f"{prefix.emoji} {letter}{number}".strip() if prefix.emoji else code
        return GeneratedCode(
            code=code, display=display, letter=letter, sequence=sequence, prefix_id=prefix.id
        )

    async def is_unique(self, code: str) -> bool:
        from app.models.topic import Topic

        result = await self.session.execute(select(func.count()).select_from(Topic).where(Topic.code == code))
        return int(result.scalar_one() or 0) == 0

    # ----------------------------------------------------------- private
    def _pick_prefix(self, prefixes: list[CodePrefix], gender: str | None) -> CodePrefix:
        active = [p for p in prefixes if p.active] or prefixes
        if not active:  # pragma: no cover - defensive
            raise RuntimeError("no active code prefixes configured")

        if settings.default_code_scheme == CodeScheme.GENDER.value:
            wanted = Gender(gender).value if gender in {g.value for g in Gender} else None
            for prefix in active:
                if prefix.gender and prefix.gender == wanted:
                    return prefix
            for prefix in active:
                if prefix.gender is None:
                    return prefix
        return active[0]

    # ------------------------------------------------------ presentation
    @staticmethod
    def prettify(code: str, emoji: str = "❤") -> str:
        """``A-0001`` -> ``❤ A001`` style label used in channel posts."""
        if "-" not in code:
            return f"{emoji} {code}".strip() if emoji else code
        letter, _, number = code.partition("-")
        compact = f"{letter}{number.lstrip('0').rjust(3, '0')}"
        return f"{emoji} {compact}".strip() if emoji else compact
