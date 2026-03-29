"""Example: API views for UserProfile with CountryField.

Demonstrates:
  - Listing all profiles filtered by country.
  - Returning a country code lookup.
  - OpenAPI schema for the country field.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from openviper.contrib.countries import CountryField, search_country
from openviper.http.response import JSONResponse
from openviper.http.views import View
from openviper.routing import Router

if TYPE_CHECKING:
    from openviper.http.request import Request

router = Router(prefix="/profiles")

_country_field = CountryField(null=True)


class ProfileListView(View):
    """List user profiles, optionally filtered by country code."""

    async def get(self, request: Request) -> JSONResponse:
        country_code = request.query_params.get("country")
        profiles: list[dict] = []
        if country_code:
            from openviper.contrib.countries import validate_country

            if not validate_country(country_code):
                return JSONResponse({"error": "Invalid country code."}, status_code=400)
            from examples.country_field.models import UserProfile

            rows = await UserProfile.objects.filter(country=country_code.upper()).all()
            for row in rows:
                profiles.append(
                    {
                        "id": row.id,
                        "name": row.name,
                        "country": _country_field.to_representation(row.country, full=True),
                    }
                )
        return JSONResponse({"profiles": profiles})


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
