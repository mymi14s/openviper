"""Cart views."""

from __future__ import annotations

from openviper.http import JSONResponse, Request, Response
from openviper.http.views import View

from products.models import Product
from .models import Cart, CartItem


def _require_auth(request: Request) -> bool:
    return getattr(request, "user", None) and request.user.is_authenticated


def _item_to_dict(item: object) -> dict:
    raw_pid = item.product_id
    if raw_pid is not None and not isinstance(raw_pid, str):
        raw_pid = str(raw_pid)
    return {
        "id": str(item.id) if item.id else None,
        "product_id": raw_pid,
        "product_name": getattr(item, "_product_name", None),
        "quantity": item.quantity,
    }


async def _enrich_items(items: list) -> list:
    """Attach product names to cart items."""
    ids = [str(i.product_id) for i in items if i.product_id]
    if not ids:
        return items
    products = await Product.objects.all()
    name_map = {str(p.id): p.name for p in products}
    for item in items:
        pid = str(item.product_id) if item.product_id else None
        item._product_name = name_map.get(pid)
    return items


async def _get_or_create_cart(user_id: int) -> object:
    cart = await Cart.objects.filter(user_id=user_id).first()
    if not cart:
        cart = Cart(user_id=user_id)
        await cart.save()
    return cart


class CartView(View):
    """Get current user's cart."""

    async def get(self, request: Request) -> Response:
        if not _require_auth(request):
            return JSONResponse({"error": "Authentication required"}, status_code=401)

        cart = await _get_or_create_cart(request.user.id)
        items = await CartItem.objects.filter(cart_id=cart.id).all()
        items = await _enrich_items(list(items))
        return JSONResponse({
            "id": str(cart.id),
            "items": [_item_to_dict(i) for i in items],
            "item_count": sum(i.quantity for i in items),
        })


class CartAddView(View):
    """Add item to cart."""

    async def post(self, request: Request) -> Response:
        if not _require_auth(request):
            return JSONResponse({"error": "Authentication required"}, status_code=401)

        data = await request.json()
        product_id = data.get("product_id")
        quantity = int(data.get("quantity", 1))

        if not product_id:
            return JSONResponse({"error": "product_id is required"}, status_code=400)

        cart = await _get_or_create_cart(request.user.id)

        existing = await CartItem.objects.filter(cart_id=cart.id, product_id=product_id).first()
        if existing:
            existing.quantity += quantity
            await existing.save()
            item = existing
        else:
            item = CartItem(cart_id=cart.id, product_id=product_id, quantity=quantity)
            await item.save()

        return JSONResponse(_item_to_dict(item), status_code=201)


class CartUpdateView(View):
    """Update cart item quantity."""

    async def post(self, request: Request) -> Response:
        if not _require_auth(request):
            return JSONResponse({"error": "Authentication required"}, status_code=401)

        data = await request.json()
        item_id = data.get("item_id")
        quantity = int(data.get("quantity", 1))

        if not item_id:
            return JSONResponse({"error": "item_id is required"}, status_code=400)

        cart = await _get_or_create_cart(request.user.id)
        item = await CartItem.objects.filter(id=item_id, cart_id=cart.id).first()
        if not item:
            return JSONResponse({"error": "Item not found"}, status_code=404)

        if quantity <= 0:
            await item.delete()
            return JSONResponse({"message": "Item removed"})

        item.quantity = quantity
        await item.save()
        return JSONResponse(_item_to_dict(item))


class CartRemoveView(View):
    """Remove item from cart."""

    async def post(self, request: Request) -> Response:
        if not _require_auth(request):
            return JSONResponse({"error": "Authentication required"}, status_code=401)

        data = await request.json()
        item_id = data.get("item_id")

        if not item_id:
            return JSONResponse({"error": "item_id is required"}, status_code=400)

        cart = await _get_or_create_cart(request.user.id)
        item = await CartItem.objects.filter(id=item_id, cart_id=cart.id).first()
        if not item:
            return JSONResponse({"error": "Item not found"}, status_code=404)

        await item.delete()
        return JSONResponse({"message": "Item removed"})
