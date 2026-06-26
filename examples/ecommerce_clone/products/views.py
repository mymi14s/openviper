"""Product views."""

from __future__ import annotations

from openviper.http import JSONResponse, Request, Response
from openviper.http.views import View

from .models import Category, Product
from .serializers import CategorySerializer, ProductSerializer


class ProductListView(View):
    """List and search products with pagination."""

    async def get(self, request: Request) -> Response:
        qs = Product.objects.all().order_by("name", "id")
        category = request.query_params.get("category")
        search = request.query_params.get("search")
        page_size = int(request.query_params.get("page_size", 12))
        page = max(1, int(request.query_params.get("page", 1)))

        if category:
            qs = qs.filter(category_id=category)
        if search:
            qs = qs.filter(name__icontains=search)

        # Use serializer pagination for concurrent COUNT + fetch with cursor support.
        result = await ProductSerializer.paginate(
            qs,
            page=page,
            page_size=page_size,
            base_url="/products",
        )

        return JSONResponse(result.serialize() if hasattr(result, "serialize") else result)


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
