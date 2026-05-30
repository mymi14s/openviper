"""Example: API views for UserProfile with CountryField.

Demonstrates:
  - Listing all profiles filtered by country.
  - Returning a country code lookup.
  - OpenAPI schema for the country field.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from openviper.contrib.countries import CountryField, search_country, validate_country
from openviper.http.response import JSONResponse
from openviper.http.views import View
from openviper.routing import Router

from .models import UserProfile
from .serializers import ProfileFullSerializer

if TYPE_CHECKING:
    from openviper.http.request import Request

router = Router(prefix="/profiles")

_country_field = CountryField(null=True)


class ProfileListView(View):
    """List user profiles, optionally filtered by country code."""

    async def get(self, request: Request) -> JSONResponse:
        country_code = request.query_params.get("country")
        if country_code:
            if not validate_country(country_code):
                return JSONResponse({"error": "Invalid country code."}, status_code=400)

            qs = UserProfile.objects.filter(country=country_code.upper()).order_by("name", "id")
            rows = await qs.all()
            profiles = [ProfileFullSerializer.from_orm(row).serialize() for row in rows]
            return JSONResponse({"profiles": profiles})

        # No filter - return all profiles using serializer pagination.
        qs = UserProfile.objects.all().order_by("name", "id")
        result = await ProfileFullSerializer.paginate(
            qs,
            page=1,
            page_size=50,
            base_url="/profiles",
        )
        return JSONResponse(result.serialize() if hasattr(result, "serialize") else result)


class CountrySearchView(View):
    """Search available countries by name or code."""

    async def get(self, request: Request) -> JSONResponse:
        query = request.query_params.get("q", "")
        results = search_country(query)
        return JSONResponse({"countries": results})


class CountrySchemaView(View):
    """Return the OpenAPI JSON Schema for the CountryField."""

    async def get(self, request: Request) -> JSONResponse:
        return JSONResponse(CountryField.openapi_schema())


ProfileListView.register(router, "/")
CountrySearchView.register(router, "/country-search/")
CountrySchemaView.register(router, "/country-schema/")
