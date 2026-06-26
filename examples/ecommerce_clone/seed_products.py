"""Seed 50 random products on startup if the database is empty."""

import asyncio
import contextlib
import importlib
import os
import traceback

os.environ.setdefault("OPENVIPER_SETTINGS_MODULE", "ecommerce_clone.settings")

import openviper  # noqa: E402

openviper.setup()

with contextlib.suppress(ImportError, ModuleNotFoundError):
    for app in ("products", "cart", "orders", "reviews", "users", "chat"):
        importlib.import_module(f"{app}.models")

from cart.models import Cart, CartItem  # noqa: E402
from orders.models import Order, OrderItem  # noqa: E402
from products.models import Category, Product  # noqa: E402
from reviews.models import Review  # noqa: E402
from users.models import User  # noqa: E402

from openviper.db.executor import build_table  # noqa: E402

for model in (User, Category, Product, Review, Cart, CartItem, Order, OrderItem):
    build_table(model._table_name, model)

from ecommerce_clone.management.commands.generate_products import (  # noqa: E402
    init_db,
    seed_data,
)


async def main() -> None:
    count = await Product.objects.count()
    if count == 0:
        print("No products found, generating 50 random products...")
        await init_db()
        try:
            await seed_data(
                num_products=50,
                num_users=5,
                stdout=print,
                style_success=lambda s: print(s),
                style_notice=lambda s: print(s),
            )
            print("Product generation complete.")
        except Exception:
            traceback.print_exc()
            print("Seed data generation failed, continuing startup.")
    else:
        print(f"{count} products already exist, skipping generation.")


asyncio.run(main())
