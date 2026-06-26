"""Frontend views - serves the SPA."""

from __future__ import annotations

from openviper.http import HTMLResponse, Request, Response
from openviper.http.views import View


class FrontendView(View):
    """Serve the single-page application."""

    async def get(self, request: Request) -> Response:
        return HTMLResponse(template="frontend/index.html")
