"""Order views."""

from __future__ import annotations

from decimal import Decimal

from cart.models import Cart, CartItem
from products.models import Product

from openviper.http import JSONResponse, Request, Response
from openviper.http.views import View

from .models import Order, OrderItem


def _require_auth(request: Request) -> bool:
    return getattr(request, "user", None) and request.user.is_authenticated


def _coerce(val):
    """Coerce LazyFK or other non-primitive FK values to str."""
    if val is None or isinstance(val, (str, int, float, bool)):
        return val
    return str(val)


def _order_to_dict(order: object, items: list | None = None) -> dict:
    d = {
        "id": str(order.id) if order.id else None,
        "user_id": _coerce(order.user_id),
        "total_price": str(order.total_price),
        "shipping_address": order.shipping_address,
        "status": order.status,
        "created_at": order.created_at.isoformat() if getattr(order, "created_at", None) else None,
    }
    if items is not None:
        d["items"] = [
            {
                "id": str(i.id) if i.id else None,
                "product_id": _coerce(i.product_id),
                "quantity": i.quantity,
                "price": str(i.price),
            }
            for i in items
        ]
    return d


class CheckoutView(View):
    """Create an order from the user's cart."""

    async def post(self, request: Request) -> Response:
        if not _require_auth(request):
            return JSONResponse({"error": "Authentication required"}, status_code=401)

        data = await request.json()
        shipping_address = data.get("shipping_address", "")

        if not shipping_address:
            return JSONResponse({"error": "shipping_address is required"}, status_code=400)

        cart = await Cart.objects.filter(user_id=request.user.id).first()
        if not cart:
            return JSONResponse({"error": "Cart is empty"}, status_code=400)

        cart_items = await CartItem.objects.filter(cart_id=cart.id).all()
        if not cart_items:
            return JSONResponse({"error": "Cart is empty"}, status_code=400)

        total = Decimal("0")
        order_items_data = []

        for item in cart_items:
            product = await Product.objects.get_or_none(id=item.product_id)
            if not product:
                continue
            item_price = product.price * item.quantity
            total += item_price
            order_items_data.append((product, item.quantity, product.price))

        order = Order(
            user_id=request.user.id,
            total_price=total,
            shipping_address=shipping_address,
            status="pending",
        )
        await order.save()

        created_items = []
        for product, quantity, price in order_items_data:
            oi = OrderItem(
                order_id=str(order.id),
                product_id=str(product.id),
                quantity=quantity,
                price=price,
            )
            await oi.save()
            created_items.append(oi)

        # Clear cart
        for item in cart_items:
            await item.delete()

        return JSONResponse(_order_to_dict(order, created_items), status_code=201)


class OrderListView(View):
    """List user's orders."""

    async def get(self, request: Request) -> Response:
        if not _require_auth(request):
            return JSONResponse({"error": "Authentication required"}, status_code=401)

        orders = await Order.objects.filter(user_id=request.user.id).all()
        return JSONResponse([_order_to_dict(o) for o in orders])


class OrderDetailView(View):
    """Get order details."""

    async def get(self, request: Request, order_id: str) -> Response:
        if not _require_auth(request):
            return JSONResponse({"error": "Authentication required"}, status_code=401)

        order = await Order.objects.get_or_none(id=order_id, user_id=request.user.id)
        if not order:
            return JSONResponse({"error": "Order not found"}, status_code=404)

        items = await OrderItem.objects.filter(order_id=order.id).all()
        return JSONResponse(_order_to_dict(order, items))
