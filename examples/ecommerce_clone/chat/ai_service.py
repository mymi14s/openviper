"""AI service - product retrieval, prompt building, and generation."""

from __future__ import annotations

import logging
import random

from products.models import Product

from openviper.ai.router import ModelRouter

log = logging.getLogger(__name__)

MODEL_NAME = "qwen3:4b"

PROMPT_TEMPLATE = """\
You are a helpful ecommerce shopping assistant.

Customer question:
{message}

Available products:
{products}

Respond helpfully in 2-4 sentences. Recommend relevant products by name when appropriate.
"""

router: ModelRouter | None = None


def get_router() -> ModelRouter:
    global router
    if router is None:
        router = ModelRouter()
        try:
            router.set_model(MODEL_NAME)
            router._get_provider()
            log.info("Chat AI: using model '%s'", MODEL_NAME)
        except Exception as exc:
            log.warning("Chat AI: model '%s' not available - %s", MODEL_NAME, exc)
    return router


async def get_relevant_products(message: str, limit: int = 5) -> list[object]:
    """Search products by keywords extracted from the message."""
    words = [w for w in message.lower().split() if len(w) > 3]
    found: list[object] = []

    for word in words[:4]:
        results = await Product.objects.filter(name__icontains=word).all()
        found.extend(results)
        if len(found) >= limit:
            break

    if not found:
        all_products = await Product.objects.all()
        found = random.sample(all_products, min(limit, len(all_products))) if all_products else []

    # Deduplicate preserving order
    seen: set[str] = set()
    unique: list[object] = []
    for p in found:
        pid = str(p.id)
        if pid not in seen:
            seen.add(pid)
            unique.append(p)
    return unique[:limit]


def format_products(products: list[object]) -> str:
    if not products:
        return "No products available."
    return "\n".join(f"- {p.name} (${p.price}): {(p.description or '')[:80]}" for p in products)


async def generate_reply(message: str) -> tuple[str, list[object]]:
    """Return (reply_text, related_products_list)."""
    products = await get_relevant_products(message)
    active_router = get_router()

    prompt = PROMPT_TEMPLATE.format(
        message=message,
        products=format_products(products),
    )

    try:
        reply = await active_router.generate(prompt)
    except Exception as exc:
        log.error("Chat AI generation error: %s", exc)
        reply = (
            "Hi! I'm your shopping assistant. "
            "I'm having trouble connecting to the AI right now - "
            "but here are some products you might like!"
        )

    return reply, products
