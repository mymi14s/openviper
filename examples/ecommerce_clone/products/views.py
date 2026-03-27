"""Product views."""

from __future__ import annotations

import asyncio
from urllib.parse import urlencode

from openviper.http import JSONResponse, Request, Response
from openviper.http.views import View

from .models import Category, Product
from .serializers import CategorySerializer, ProductSerializer


class ProductListView(View):
    """List and search products with pagination."""

    async def get(self, request: Request) -> Response:
        qs = Product.objects.all()
        category = request.query_params.get("category")
        search = request.query_params.get("search")
        page_size = int(request.query_params.get("page_size", 12))
        page = max(1, int(request.query_params.get("page", 1)))

        if category:
            qs = qs.filter(category_id=category)
        if search:
            qs = qs.filter(name__icontains=search)

        # Calculate offset from page number
        offset = (page - 1) * page_size

        # Apply ordering, limit, and offset
        ordered_qs = qs.order_by("name", "id").limit(page_size).offset(offset)

        # Run count and fetch concurrently for better performance (~2x faster)
        total_count, items = await asyncio.gather(
            qs.count(),
            ordered_qs.all(),
        )

        # Serialize the items
        serialized_items = await ProductSerializer.serialize_many(items)

        # Build pagination URLs
        base_params = {"page_size": page_size}
        if category:
            base_params["category"] = category
        if search:
            base_params["search"] = search

        next_url = None
        if page * page_size < total_count:
            next_params = {**base_params, "page": page + 1}
            next_url = f"/products?{urlencode(next_params)}"

        prev_url = None
        if page > 1:
            prev_params = {**base_params, "page": page - 1}
            prev_url = f"/products?{urlencode(prev_params)}"

        return JSONResponse(
            {
                "count": total_count,
                "next": next_url,
                "previous": prev_url,
                "results": serialized_items,
            }
        )


class ProductDetailView(View):
    """Get a single product."""

    async def get(self, request: Request, product_id: str) -> Response:
        product = await Product.objects.get_or_none(id=product_id)
        if not product:
            return JSONResponse({"error": "Product not found"}, status_code=404)
        return JSONResponse(ProductSerializer.from_orm(product).serialize())


class CategoryListView(View):
    """List categories."""

    async def get(self, request: Request) -> Response:
        categories = await Category.objects.all()
        return JSONResponse(await CategorySerializer.serialize_many(categories))
