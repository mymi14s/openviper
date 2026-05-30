"""Review views."""

from __future__ import annotations

from openviper.http import JSONResponse, Request, Response
from openviper.http.views import View

from .models import Review


def require_auth(request: Request) -> bool:
    return getattr(request, "user", None) and request.user.is_authenticated


def coerce_value(value: object) -> object:
    """Coerce LazyFK or other non-primitive FK values to str."""
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


def review_to_dict(review: object) -> dict[str, object]:
    return {
        "id": str(review.id) if review.id else None,
        "user_id": coerce_value(review.user_id),
        "product_id": coerce_value(review.product_id),
        "rating": review.rating,
        "comment": review.comment,
        "created_at": (
            review.created_at.isoformat() if getattr(review, "created_at", None) else None
        ),
    }


class ReviewCreateView(View):
    """Create a product review."""

    async def post(self, request: Request) -> Response:
        if not require_auth(request):
            return JSONResponse({"error": "Authentication required"}, status_code=401)

        data = await request.json()
        product_id = data.get("product_id")
        rating = data.get("rating")
        comment = data.get("comment")

        if not product_id:
            return JSONResponse({"error": "product_id is required"}, status_code=400)
        if rating is None or not (1 <= int(rating) <= 5):
            return JSONResponse({"error": "rating must be between 1 and 5"}, status_code=400)

        review = Review(
            user_id=request.user.id,
            product_id=product_id,
            rating=int(rating),
            comment=comment,
        )
        await review.save()
        return JSONResponse(review_to_dict(review), status_code=201)


class ProductReviewsView(View):
    """List reviews for a product."""

    async def get(self, request: Request, product_id: str) -> Response:
        reviews = await Review.objects.filter(product_id=product_id).all()
        return JSONResponse([review_to_dict(r) for r in reviews])
