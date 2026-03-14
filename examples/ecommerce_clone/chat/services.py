"""Chat service — orchestrates cache, AI, and response assembly."""

from __future__ import annotations

from .ai_service import generate_reply
from .cache import get_cached_answer, store_answer


async def handle_chat(message: str) -> dict:
    """Process a chat message and return reply + related products."""
    message = message.strip()

    # Return cached answer for previously seen questions
    cached = await get_cached_answer(message)
    if cached:
        return {"reply": cached, "cached": True, "related_products": []}

    reply, products = await generate_reply(message)

    # Persist answer for future identical queries
    await store_answer(message, reply)

    related = [
        {
            "id": str(p.id),
            "name": p.name,
            "price": float(p.price),
            "url": f"/products/{p.id}",
            "image_url": p.image_url or None,
        }
        for p in products[:3]
    ]

    return {"reply": reply, "cached": False, "related_products": related}
