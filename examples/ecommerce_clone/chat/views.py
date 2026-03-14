"""Chat views."""

from __future__ import annotations

from openviper.http import JSONResponse, Request, Response
from openviper.http.views import View

from .services import handle_chat


class ChatView(View):
    """POST /api/chat — receive a message, return AI reply."""

    async def post(self, request: Request) -> Response:
        try:
            data = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON"}, status_code=400)

        message = (data.get("message") or "").strip()
        if not message:
            return JSONResponse({"error": "message is required"}, status_code=400)

        result = await handle_chat(message)
        return JSONResponse(result)
