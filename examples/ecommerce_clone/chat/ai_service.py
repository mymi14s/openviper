"""AI service — product retrieval, prompt building, and generation."""

from __future__ import annotations

import logging
import random

from openviper.ai.router import ModelRouter

from products.models import Product

log = logging.getLogger(__name__)

_MODEL = "qwen3:4b"

_PROMPT_TEMPLATE = """\
You are a helpful ecommerce shopping assistant.

Customer question:
{message}

Available products:
{products}

Respond helpfully in 2-4 sentences. Recommend relevant products by name when appropriate.
"""

# Module-level router — initialised once, reused for all requests
_router: ModelRouter | None = None


def _get_router() -> ModelRouter:
    global _router
    if _router is None:
        _router = ModelRouter()
        try:
            _router.set_model(_MODEL)
            _router._get_provider()
            log.info("Chat AI: using model '%s'", _MODEL)
        except Exception as exc:
            log.warning("Chat AI: model '%s' not available — %s", _MODEL, exc)
    return _router


async def _get_relevant_products(message: str, limit: int = 5) -> list:
    """Search products by keywords extracted from the message."""
    words = [w for w in message.lower().split() if len(w) > 3]
    found: list = []

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
    unique: list = []
    for p in found:
        pid = str(p.id)
        if pid not in seen:
            seen.add(pid)
            unique.append(p)
    return unique[:limit]


def _format_products(products: list) -> str:
    if not products:
        return "No products available."
    return "\n".join(f"- {p.name} (${p.price}): {(p.description or '')[:80]}" for p in products)


async def generate_reply(message: str) -> tuple[str, list]:
    """Return (reply_text, related_products_list)."""
    products = await _get_relevant_products(message)
    router = _get_router()

    prompt = _PROMPT_TEMPLATE.format(
        message=message,
        products=_format_products(products),
    )

    try:
        reply = await router.generate(prompt)
    except Exception as exc:
        log.error("Chat AI generation error: %s", exc)
        reply = (
            "Hi! I'm your shopping assistant. "
            "I'm having trouble connecting to the AI right now — "
            "but here are some products you might like!"
        )

    return reply, products
