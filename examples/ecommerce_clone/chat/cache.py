"""Chat answer cache — normalise, hash, look up, store."""

from __future__ import annotations

import hashlib

from .models import ChatCache


def _hash(question: str) -> str:
    return hashlib.sha256(question.strip().lower().encode()).hexdigest()


async def get_cached_answer(question: str) -> str | None:
    cached = await ChatCache.objects.filter(question_hash=_hash(question)).first()
    return cached.answer if cached else None


async def store_answer(question: str, answer: str) -> None:
    entry = ChatCache(
        question_hash=_hash(question),
        question=question,
        answer=answer,
    )
    try:
        await entry.save()
    except Exception:
        pass  # duplicate hash on concurrent requests — harmless
