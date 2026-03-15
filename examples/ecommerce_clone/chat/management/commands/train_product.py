"""train-product management command.

Fetches all products, generates an AI summary for each, and stores
them in the chat_product_summary table for fast retrieval.

Usage::

    python viperctl.py train-product
    python viperctl.py train-product --clear
"""

from __future__ import annotations

import argparse
import asyncio

from products.models import Product

from chat.ai_service import _get_router
from chat.models import ProductSummary
from openviper.core.management.base import BaseCommand
from openviper.db import init_db


class Command(BaseCommand):
    name = "train-product"
    help = "Generate AI summaries for all products to improve chat responses."

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Delete existing summaries before regenerating.",
        )

    def handle(self, *args, **kwargs) -> None:  # type: ignore[override]
        asyncio.run(self._run(clear=kwargs.get("clear", False)))

    async def _run(self, clear: bool = False) -> None:
        await init_db()

        if clear:
            deleted = 0
            async for batch in ProductSummary.objects.all().batch(size=500):
                for s in batch:
                    await s.delete()
                    deleted += 1
            self.stdout(f"  cleared {deleted} existing summaries")

        total = 0
        trained = 0
        router = _get_router()

        async for batch in Product.objects.all().batch(size=200):
            for product in batch:
                total += 1
                if not clear:
                    existing = await ProductSummary.objects.filter(
                        product_id=str(product.id)
                    ).first()
                    if existing:
                        continue

                summary_text = _build_product_context(product)

                try:
                    prompt = f"Write a concise 1-sentence product summary for:\n{summary_text}"
                    summary_text = await router.generate(prompt)
                except Exception as exc:
                    self.stdout(f"  [warn] AI failed for {product.name}: {exc}")

                summary = ProductSummary(
                    product_id=str(product.id),
                    summary=summary_text,
                )
                await summary.save()
                trained += 1
                self.stdout(f"  ✓ {product.name}")

        if total == 0:
            self.stdout("No products found. Run generate-products first.")
            return

        self.stdout(f"\n✅ Trained {trained} of {total} products.")


def _build_product_context(product) -> str:
    cat = str(product.category_id) if product.category_id else "Uncategorised"
    return (
        f"Product: {product.name}\n"
        f"Price: ${product.price}\n"
        f"Category: {cat}\n"
        f"Description: {product.description or 'No description'}"
    )
