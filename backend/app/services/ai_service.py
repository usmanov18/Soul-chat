"""AI moderator and insight layer (TZ 27).

Two providers behind one interface:

``builtin``  — deterministic, dependency free heuristics (wordlists + patterns).
               Always available, so moderation never silently disappears.
``openai``   — any OpenAI compatible endpoint, used when ``AI_PROVIDER=openai``
               and a key is configured; falls back to builtin on any error.

The public surface is :meth:`AIModerator.moderate` (per message),
:meth:`AIModerator.summarize` (topic summary) and
:meth:`AIModerator.analyze_emotion` (relationship timeline input).
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.enums import ModerationAction
from app.services.security_service import SecurityService

logger = get_logger(__name__)

SPAM_PATTERNS = [
    r"\b(?:free|bepul)\s+(?:crypto|bitcoin|usdt|ton)\b",
    r"\bearn\s+\d+\$\s+per\s+day\b",
    r"(?i)https?://(?:bit\.ly|tinyurl|t\.me)/\S{4,}",
    r"(?i)\bkazino\b|\bcasino\b|\bpoker\b",
    r"(?i)\bkredit\b.{0,20}\btez\b",
]
INSULT_WORDS = {
    "ahmoq", "tentak", "eshak", "xar", "itbola", "iflos", "shayat", "iblis",
    "idiot", "stupid", "moron", "bitch", "bastard", "scum", "trash",
}
TOXIC_WORDS = {
    "yomon ko'raman", "nafrat", "o'ldiraman", "ket qol", "yo'qol", "g'irrom",
    "i hate you", "kill yourself", "kys", "loser",
}
NSFW_WORDS = {
    "porn", "porno", "xxx", "nsfw", "18+", "sex tape", "nude", "nudes",
}
SPAM_WORDS: set[str] = set()
FAKE_ACCOUNT_SIGNALS = re.compile(r"(?i)(?:bot|test|asdf|qwerty|123456)")

EMOTIONS = {
    "joy": ["baxtli", "xursand", "yaxshi", "yaxshi ko'raman", "happy", "love", "❤"],
    "sadness": ["yig'ladim", "yomon", "xafa", "sovuq", "sad", "miss you", "so'g'indim"],
    "anger": ["jahl", "g'azab", "asabiylash", "angry", "furious"],
    "fear": ["qo'rqdim", "xavotir", "scared", "worried"],
    "neutral": [],
}


@dataclass
class Verdict:
    action: str = ModerationAction.ALLOW.value
    risk: float = 0.0
    labels: list[str] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)
    user_message: str = ""
    provider: str = "builtin"

    def summary(self) -> str:
        labels = ",".join(self.labels) or "-"
        return f"{self.action} risk={self.risk:.2f} labels={labels}"


@dataclass
class Summary:
    text: str
    message_count: int
    top_words: list[tuple[str, int]]
    emotions: dict[str, float]
    peak_hours: list[tuple[int, int]]
    provider: str = "builtin"


class AIModerator:
    def __init__(self, session: AsyncSession, security: SecurityService | None = None) -> None:
        self.session = session
        self.security = security or SecurityService(session)

    # ------------------------------------------------------------------
    async def moderate(self, text: str, *, user_id: int = 0, topic_id: int | None = None) -> Verdict:
        if not text or not text.strip():
            return Verdict()

        if settings.ai_provider == "openai" and settings.openai_api_key:
            verdict = await self._remote_moderate(text)
            if verdict is not None:
                return verdict

        scores = {
            "spam": self._score(text, SPAM_PATTERNS, SPAM_WORDS) / 100,
            "insult": self._word_hit(text, INSULT_WORDS),
            "toxic": self._word_hit(text, TOXIC_WORDS),
            "nsfw": self._word_hit(text, NSFW_WORDS),
            "fake": 1.0 if FAKE_ACCOUNT_SIGNALS.search(text) else 0.0,
            "heuristic_spam": SecurityService.looks_like_spam(text) / 100,
        }
        scores["spam"] = max(scores["spam"], scores["heuristic_spam"])
        risk = max(scores.values())
        labels = [name for name, value in scores.items() if value >= 0.4 and name != "heuristic_spam"]

        if risk >= settings.ai_risk_block_threshold:
            action = ModerationAction.BLOCK.value
            message = "Xabar bloklandi: jamoa qoidalari buzildi."
        elif risk >= settings.ai_risk_review_threshold:
            action = ModerationAction.REVIEW.value
            message = "Xabar moderatsiya navbatiga tushdi."
        else:
            action = ModerationAction.ALLOW.value
            message = ""

        await self.security.record(
            user_id,
            kind=(labels[0] if labels else "ok"),
            score=int(risk * 100),
            action=action,
            topic_id=topic_id,
            excerpt=text[:200],
            detail=scores,
        )
        return Verdict(
            action=action, risk=risk, labels=labels, scores=scores,
            user_message=message, provider="builtin",
        )

    async def _remote_moderate(self, text: str) -> Verdict | None:
        """Call an OpenAI-compatible moderation endpoint. Optional."""
        try:  # pragma: no cover - network dependent
            import httpx

            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(
                    f"{settings.openai_base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                    json={
                        "model": settings.openai_model,
                        "response_format": {"type": "json_object"},
                        "messages": [
                            {
                                "role": "system",
                                "content": (
                                    "You are a chat moderator. Reply with JSON "
                                    '{"risk": 0..1, "labels": [...], "action": "allow|review|delete|block"}.'
                                ),
                            },
                            {"role": "user", "content": text[:2000]},
                        ],
                    },
                )
                response.raise_for_status()
                payload = response.json()["choices"][0]["message"]["content"]
                data = json.loads(payload)
            return Verdict(
                action=str(data.get("action", ModerationAction.ALLOW.value)),
                risk=float(data.get("risk", 0.0)),
                labels=list(data.get("labels", [])),
                scores=data.get("scores", {}),
                provider="openai",
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("openai moderation failed, falling back: %s", exc)
            return None

    # ------------------------------------------------------------------
    async def summarize(self, texts: list[str], timestamps: list[int] | None = None) -> Summary:
        """Conversation summary + emotion mix + active hours (TZ 21, 27)."""
        clean = [t for t in texts if t and t.strip()]
        words = Counter(
            word
            for text in clean
            for word in re.findall(r"[\w'’\-]{3,}", text.lower())
            if not word.isdigit()
        )
        emotions = self.emotion_mix(clean)
        peak: list[tuple[int, int]] = []
        if timestamps:
            hours = Counter(datetime_hour(ts) for ts in timestamps)
            peak = hours.most_common(3)

        if not clean:
            body = "Hozircha xabar yo'q."
        else:
            head = ", ".join(f"{w} ({c})" for w, c in words.most_common(5)) or "—"
            dominant = max(emotions.items(), key=lambda kv: kv[1])[0]
            body = (
                f"{len(clean)} ta xabar tahlil qilindi. Asosiy mavzu so'zlari: {head}. "
                f"Hissiyot ohangi: {dominant}."
            )
            if peak:
                body += " Eng faol soatlar: " + ", ".join(f"{h}:00 ({c})" for h, c in peak) + "."

        return Summary(
            text=body,
            message_count=len(clean),
            top_words=words.most_common(10),
            emotions=emotions,
            peak_hours=peak,
        )

    async def analyze_emotion(self, text: str) -> str:
        mix = self.emotion_mix([text]) if text else {}
        if not mix:
            return "neutral"
        return max(mix.items(), key=lambda kv: kv[1])[0]

    @staticmethod
    def emotion_mix(texts: list[str]) -> dict[str, float]:
        mix: dict[str, float] = {name: 0.0 for name in EMOTIONS}
        if not texts:
            return mix
        blob = " ".join(texts).lower()
        for name, markers in EMOTIONS.items():
            mix[name] = float(sum(blob.count(marker) for marker in markers))
        total = sum(mix.values())
        if total:
            mix = {k: round(v / total, 3) for k, v in mix.items()}
        else:
            mix["neutral"] = 1.0
        return mix

    # ------------------------------------------------------------ helpers
    @staticmethod
    def _score(text: str, patterns: list[str], words: set[str]) -> float:
        lowered = text.lower()
        score = 0.0
        for pattern in patterns:
            if re.search(pattern, lowered):
                score += 50
        for word in words:
            if word in lowered:
                score += 30
        return min(100.0, score)

    @staticmethod
    def _word_hit(text: str, words: set[str]) -> float:
        lowered = text.lower()
        hits = sum(1 for word in words if word in lowered)
        return min(1.0, hits * 0.6)


def datetime_hour(ts: int) -> int:
    from datetime import UTC, datetime

    return datetime.fromtimestamp(ts, UTC).hour
