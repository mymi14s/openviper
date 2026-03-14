"""Product views."""

from __future__ import annotations

from openviper.http import JSONResponse, Request, Response
from openviper.http.views import View

from .models import Category, Product


def _product_to_dict(p: object) -> dict:
    raw_cat = p.category_id
    # category_id may be a LazyFK descriptor object — coerce to plain string
    if raw_cat is not None and not isinstance(raw_cat, str):
        raw_cat = str(raw_cat)
    return {
        "id": str(p.id) if p.id else None,
        "name": p.name,
        "description": p.description,
        "price": str(p.price),
        "stock": p.stock,
        "category_id": raw_cat,
        "image": p.image,
        "image_url": p.image_url,
        "created_at": p.created_at.isoformat() if getattr(p, "created_at", None) else None,
    }


def _category_to_dict(c: object) -> dict:
    return {
        "id": c.name,
        "name": c.name,
        "created_at": c.created_at.isoformat() if getattr(c, "created_at", None) else None,
    }


class ProductListView(View):
    """List and search products with pagination."""

    async def get(self, request: Request) -> Response:
        qs = Product.objects.all()
        category = request.query_params.get("category")
        search = request.query_params.get("search")
        page = int(request.query_params.get("page", 1))
        page_size = int(request.query_params.get("page_size", 12))
        page = max(1, page)
        page_size = min(max(1, page_size), 100)

        if category:
            qs = qs.filter(category_id=category)
        if search:
            qs = qs.filter(name__icontains=search)

        total = await qs.count()
        pages = max(1, (total + page_size - 1) // page_size)
        offset = (page - 1) * page_size

        products = await qs.order_by("name").limit(page_size).offset(offset).all()
        return JSONResponse(
            {
                "items": [_product_to_dict(p) for p in products],
                "total": total,
                "page": page,
                "page_size": page_size,
                "pages": pages,
            }
        )


class ProductDetailView(View):
    """Get a single product."""

    async def get(self, request: Request, product_id: str) -> Response:
        product = await Product.objects.get_or_none(id=product_id)
        if not product:
            return JSONResponse({"error": "Product not found"}, status_code=404)
        return JSONResponse(_product_to_dict(product))


class CategoryListView(View):
    """List categories."""

    async def get(self, request: Request) -> Response:
        categories = await Category.objects.all()
        return JSONResponse([_category_to_dict(c) for c in categories])
