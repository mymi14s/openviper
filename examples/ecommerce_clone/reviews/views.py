"""Review views."""

from __future__ import annotations

from openviper.http import JSONResponse, Request, Response
from openviper.http.views import View

from .models import Review


def _require_auth(request: Request) -> bool:
    return getattr(request, "user", None) and request.user.is_authenticated


def _coerce(val):
    """Coerce LazyFK or other non-primitive FK values to str."""
    if val is None or isinstance(val, (str, int, float, bool)):
        return val
    return str(val)


def _review_to_dict(r: object) -> dict:
    return {
        "id": str(r.id) if r.id else None,
        "user_id": _coerce(r.user_id),
        "product_id": _coerce(r.product_id),
        "rating": r.rating,
        "comment": r.comment,
        "created_at": r.created_at.isoformat() if getattr(r, "created_at", None) else None,
    }


class ReviewCreateView(View):
    """Create a product review."""

    async def post(self, request: Request) -> Response:
        if not _require_auth(request):
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
        return JSONResponse(_review_to_dict(review), status_code=201)


class ProductReviewsView(View):
    """List reviews for a product."""

    async def get(self, request: Request, product_id: str) -> Response:
        reviews = await Review.objects.filter(product_id=product_id).all()
        return JSONResponse([_review_to_dict(r) for r in reviews])
