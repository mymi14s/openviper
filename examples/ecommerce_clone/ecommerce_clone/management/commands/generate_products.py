"""generate-products management command.

Populates the database with fake categories, products, users, carts,
orders and reviews so you can explore the ecommerce clone without
manually entering data.

Usage::

    python viperctl.py generate-products
    python viperctl.py generate-products --products 50 --users 10
    python viperctl.py generate-products --clear
"""

from __future__ import annotations

import argparse
import asyncio
import random
from decimal import Decimal

from cart.models import Cart, CartItem
from faker import Faker
from orders.models import Order, OrderItem
from products.models import Category, Product
from reviews.models import Review
from users.models import User

from openviper.core.management.base import BaseCommand, CommandError
from openviper.db import init_db

_fake = Faker()


# ── Seed data ──────────────────────────────────────────────────────────────

CATEGORIES = [
    "Electronics",
    "Clothing",
    "Books",
    "Home & Kitchen",
    "Sports & Outdoors",
    "Beauty & Personal Care",
    "Toys & Games",
    "Automotive",
    "Grocery & Food",
    "Office Supplies",
]

# Picsum Photos — stable, free, licence-free images. Format: /id/{id}/400/400
_PICSUM = "https://picsum.photos/id/{id}/400/400"

CATEGORY_IMAGES: dict[str, list[str]] = {
    "Electronics": [_PICSUM.format(id=x) for x in [0, 48, 119, 180, 225, 367, 442, 484]],
    "Clothing": [_PICSUM.format(id=x) for x in [64, 96, 177, 219, 326, 398, 453, 470]],
    "Books": [_PICSUM.format(id=x) for x in [24, 159, 240, 382, 415, 501, 513, 525]],
    "Home & Kitchen": [_PICSUM.format(id=x) for x in [30, 137, 196, 213, 431, 452, 461, 478]],
    "Sports & Outdoors": [_PICSUM.format(id=x) for x in [9, 76, 168, 257, 338, 362, 374, 387]],
    "Beauty & Personal Care": [
        _PICSUM.format(id=x) for x in [26, 103, 191, 274, 355, 402, 416, 429]
    ],
    "Toys & Games": [_PICSUM.format(id=x) for x in [37, 117, 203, 292, 371, 393, 421, 437]],
    "Automotive": [_PICSUM.format(id=x) for x in [42, 133, 214, 307, 390, 405, 419, 446]],
    "Grocery & Food": [_PICSUM.format(id=x) for x in [56, 145, 229, 312, 429, 449, 463, 476]],
    "Office Supplies": [_PICSUM.format(id=x) for x in [20, 110, 185, 268, 349, 381, 408, 433]],
}

# Adjectives and nouns per category used for Faker-style product name generation
_CATEGORY_ADJECTIVES: dict[str, list[str]] = {
    "Electronics": ["Smart", "Wireless", "Portable", "Ultra", "Pro", "Mini", "Digital", "Advanced"],
    "Clothing": [
        "Slim-Fit",
        "Classic",
        "Premium",
        "Vintage",
        "Casual",
        "Elegant",
        "Organic",
        "Thermal",
    ],
    "Books": [
        "Essential",
        "Complete",
        "Practical",
        "Advanced",
        "Beginner's",
        "Modern",
        "Ultimate",
        "Expert",
    ],
    "Home & Kitchen": [
        "Stainless",
        "Bamboo",
        "Premium",
        "Non-Stick",
        "Electric",
        "Compact",
        "Heavy-Duty",
        "Eco",
    ],
    "Sports & Outdoors": [
        "Pro",
        "Lightweight",
        "Heavy-Duty",
        "Waterproof",
        "Adjustable",
        "Foldable",
        "Breathable",
        "Durable",
    ],
    "Beauty & Personal Care": [
        "Organic",
        "Natural",
        "Hydrating",
        "Anti-Aging",
        "Brightening",
        "Gentle",
        "Vegan",
        "Luxury",
    ],
    "Toys & Games": [
        "Creative",
        "Educational",
        "Interactive",
        "STEM",
        "Classic",
        "Deluxe",
        "Junior",
        "Magnetic",
    ],
    "Automotive": [
        "Universal",
        "Heavy-Duty",
        "Wireless",
        "Waterproof",
        "Compact",
        "Digital",
        "Premium",
        "Portable",
    ],
    "Grocery & Food": [
        "Organic",
        "Premium",
        "Natural",
        "Artisan",
        "Sugar-Free",
        "Gluten-Free",
        "Vegan",
        "Raw",
    ],
    "Office Supplies": [
        "Ergonomic",
        "Adjustable",
        "Compact",
        "Premium",
        "Smart",
        "Wireless",
        "Bamboo",
        "Heavy-Duty",
    ],
}

_CATEGORY_NOUNS: dict[str, list[str]] = {
    "Electronics": [
        "Headphones",
        "Speaker",
        "Keyboard",
        "Mouse",
        "Webcam",
        "Charger",
        "Hub",
        "Monitor",
        "Earbuds",
        "Lamp",
    ],
    "Clothing": [
        "Shirt",
        "Pants",
        "Jacket",
        "Sweater",
        "Shorts",
        "Sneakers",
        "Hoodie",
        "Dress",
        "Coat",
        "Boots",
    ],
    "Books": [
        "Guide",
        "Handbook",
        "Manual",
        "Workbook",
        "Reference",
        "Collection",
        "Edition",
        "Anthology",
        "Journal",
    ],
    "Home & Kitchen": [
        "Cookware Set",
        "Coffee Maker",
        "Air Purifier",
        "Cutting Board",
        "Kettle",
        "Skillet",
        "Blender",
        "Toaster",
    ],
    "Sports & Outdoors": [
        "Yoga Mat",
        "Resistance Bands",
        "Dumbbells",
        "Running Belt",
        "Foam Roller",
        "Tent",
        "Backpack",
        "Gloves",
    ],
    "Beauty & Personal Care": [
        "Serum",
        "Face Cleanser",
        "Lip Balm",
        "Beard Kit",
        "Hair Mask",
        "Moisturizer",
        "Toner",
        "Sunscreen",
    ],
    "Toys & Games": [
        "Building Blocks",
        "Board Game",
        "RC Car",
        "Puzzle",
        "Paint Set",
        "Action Figure",
        "Drone",
        "Kite",
    ],
    "Automotive": [
        "Phone Mount",
        "Tire Inflator",
        "Car Vacuum",
        "Dash Cam",
        "Seat Organizer",
        "Jump Starter",
        "Inverter",
        "LED Lights",
    ],
    "Grocery & Food": [
        "Green Tea",
        "Mixed Nuts",
        "Olive Oil",
        "Protein Bar",
        "Hot Sauce",
        "Honey",
        "Granola",
        "Spice Set",
    ],
    "Office Supplies": [
        "Ergonomic Mouse",
        "Monitor Stand",
        "Pen Set",
        "Sticky Notes",
        "Desk Organizer",
        "Stapler",
        "Notebook",
        "Tape",
    ],
}


def _fake_product_name(category: str, existing_names: set[str]) -> str:
    """Generate a unique product name for the given category using Faker adjectives/nouns."""
    adjs = _CATEGORY_ADJECTIVES.get(category, ["Premium", "Quality", "Deluxe"])
    nouns = _CATEGORY_NOUNS.get(category, ["Product", "Item", "Good"])
    for _ in range(50):
        name = f"{random.choice(adjs)} {random.choice(nouns)}"
        if name not in existing_names:
            existing_names.add(name)
            return name
    # Fallback: append a random number to guarantee uniqueness
    base = f"{random.choice(adjs)} {random.choice(nouns)}"
    unique = f"{base} {random.randint(100, 9999)}"
    existing_names.add(unique)
    return unique


def _fake_description(category: str, name: str) -> str:
    """Generate a realistic product description using Faker."""
    sentence = _fake.sentence(nb_words=random.randint(10, 18))
    feature = _fake.sentence(nb_words=random.randint(6, 12))
    return f"{sentence} {feature}"


def _fake_price(category: str) -> Decimal:
    price_ranges = {
        "Electronics": (9.99, 299.99),
        "Clothing": (14.99, 149.99),
        "Books": (7.99, 59.99),
        "Home & Kitchen": (9.99, 199.99),
        "Sports & Outdoors": (9.99, 149.99),
        "Beauty & Personal Care": (7.99, 89.99),
        "Toys & Games": (9.99, 99.99),
        "Automotive": (9.99, 149.99),
        "Grocery & Food": (4.99, 49.99),
        "Office Supplies": (4.99, 79.99),
    }
    lo, hi = price_ranges.get(category, (9.99, 99.99))
    return Decimal(f"{random.uniform(lo, hi):.2f}")


REVIEW_COMMENTS = [
    "Really happy with this purchase. Excellent quality!",
    "Fast shipping and exactly as described. Will buy again.",
    "Good value for money. Does exactly what it says.",
    "Exceeded my expectations. Highly recommend!",
    "Solid product, well built. Very satisfied.",
    "Works great! Setup was simple and intuitive.",
    "Great product but packaging could be better.",
    "Very good quality. Arrived ahead of schedule.",
    "Not bad, but I expected slightly better quality for the price.",
    "Amazing! This is my second purchase. Always reliable.",
    "Decent product. Gets the job done.",
    "Five stars — would definitely recommend to friends.",
]


# ── Async seed logic ────────────────────────────────────────────────────────


async def _clear_data(stdout) -> None:
    """Delete all seeded records."""
    stdout("  Clearing existing data...")
    for model in (Review, OrderItem, Order, CartItem, Cart, Product, Category):
        items = await model.objects.all()
        for item in items:
            await item.delete()
    stdout("  Done clearing.")


async def _seed(
    num_products: int,
    num_users: int,
    stdout,
    style_success,
    style_notice,
) -> None:
    # 1. Categories
    stdout(style_notice("Creating categories..."))
    categories: list[object] = []
    for name in CATEGORIES:
        existing = await Category.objects.filter(id=name).first()
        if existing:
            categories.append(existing)
            continue
        cat = Category(id=name)
        await cat.save()
        categories.append(cat)
    stdout(style_success(f"  ✓ {len(categories)} categories ready"))

    # 2. Products — generate exactly num_products using Faker
    stdout(style_notice(f"Creating {num_products} products..."))
    products: list[object] = []
    created = 0

    # Track existing names globally to avoid duplicates within this run
    existing_names: set[str] = set()
    existing_db = await Product.objects.all()
    for p in existing_db:
        existing_names.add(p.name)
        products.append(p)

    # Distribute products evenly across categories (round-robin)
    cat_cycle = categories.copy()
    cat_index = 0
    while created < num_products:
        cat = cat_cycle[cat_index % len(cat_cycle)]
        cat_index += 1
        cat_name = cat.name
        images = CATEGORY_IMAGES.get(cat_name, [])

        name = _fake_product_name(cat_name, existing_names)
        description = _fake_description(cat_name, name)
        price = _fake_price(cat_name)
        image_url = images[(created) % len(images)] if images else None

        product = Product(
            name=name,
            description=description,
            price=price,
            stock=random.randint(5, 100),
            category_id=cat.name,
            image_url=image_url,
        )
        await product.save()
        products.append(product)
        created += 1

    stdout(style_success(f"  ✓ {created} products created ({len(products)} total)"))

    # 3. Users
    stdout(style_notice("Creating users..."))
    users: list[object] = []
    for i in range(num_users):
        first = _fake.first_name()
        last = _fake.last_name()
        username = f"{first.lower()}.{last.lower()}{i}"
        email = _fake.unique.email()
        existing = await User.objects.filter(username=username).first()
        if existing:
            users.append(existing)
            continue
        user = User(
            username=username,
            email=email,
            name=f"{first} {last}",
            is_active=True,
        )
        await user.set_password("password123")
        await user.save()
        users.append(user)
    stdout(style_success(f"  ✓ {len(users)} users ready"))

    if not users or not products:
        stdout("  No users or products — skipping orders/reviews.")
        return

    # 4. Reviews
    stdout(style_notice("Creating reviews..."))
    review_count = 0
    for product in random.sample(products, min(len(products), max(1, len(products) * 2 // 3))):
        num_reviews = random.randint(1, min(4, len(users)))
        reviewers = random.sample(users, num_reviews)
        for user in reviewers:
            existing = await Review.objects.filter(
                product_id=str(product.id), user_id=str(user.id)
            ).first()
            if existing:
                continue
            review = Review(
                user_id=str(user.id),
                product_id=str(product.id),
                rating=random.randint(3, 5),
                comment=(
                    random.choice(REVIEW_COMMENTS)
                    if random.random() < 0.5
                    else _fake.sentence(nb_words=12)
                ),
            )
            await review.save()
            review_count += 1
    stdout(style_success(f"  ✓ {review_count} reviews created"))

    # 5. Carts with items
    stdout(style_notice("Creating carts..."))
    cart_count = 0
    for user in users:
        existing_cart = await Cart.objects.filter(user_id=str(user.id)).first()
        if existing_cart:
            continue
        cart = Cart(user_id=str(user.id))
        await cart.save()
        for product in random.sample(products, random.randint(1, 3)):
            item = CartItem(
                cart_id=str(cart.id),
                product_id=str(product.id),
                quantity=random.randint(1, 3),
            )
            await item.save()
        cart_count += 1
    stdout(style_success(f"  ✓ {cart_count} carts created"))

    # 6. Orders
    stdout(style_notice("Creating orders..."))
    order_count = 0
    statuses = ["pending", "processing", "shipped", "delivered", "cancelled"]
    for user in users:
        num_orders = random.randint(1, 3)
        for _ in range(num_orders):
            order_products = random.sample(products, random.randint(1, 4))
            total = Decimal("0")
            items_data = []
            for p in order_products:
                qty = random.randint(1, 2)
                items_data.append((p, qty, p.price))
                total += p.price * qty

            order = Order(
                user_id=str(user.id),
                total_price=total,
                shipping_address=_fake.address().replace("\n", ", "),
                status=random.choice(statuses),
            )
            await order.save()

            for p, qty, price in items_data:
                oi = OrderItem(
                    order_id=str(order.id),
                    product_id=str(p.id),
                    quantity=qty,
                    price=price,
                )
                await oi.save()
            order_count += 1
    stdout(style_success(f"  ✓ {order_count} orders created"))


# ── Command ─────────────────────────────────────────────────────────────────


class Command(BaseCommand):
    help = "Populate the database with fake ecommerce data (categories, products, users, orders, reviews)."  # noqa: E501

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--products",
            type=int,
            default=40,
            help="Exact number of products to create (default: 40)",
        )
        parser.add_argument(
            "--users",
            type=int,
            default=5,
            help="Number of fake users to create (default: 5)",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Delete existing products/categories/orders before seeding",
        )

    def handle(self, **options) -> None:  # type: ignore[override]
        num_products = options.get("products", 40)
        num_users = options.get("users", 5)
        clear = options.get("clear", False)

        async def run() -> None:
            await init_db()
            if clear:
                await _clear_data(self.stdout)
            await _seed(
                num_products=num_products,
                num_users=num_users,
                stdout=self.stdout,
                style_success=self.style_success,
                style_notice=self.style_notice,
            )

        self.stdout(self.style_bold("\n🛒 Ecommerce Fake Data Generator\n"))
        try:
            asyncio.run(run())
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        self.stdout(self.style_success("\n✅ Seed complete!\n"))
