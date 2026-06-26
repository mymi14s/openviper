"""Views for ecommerce_clone."""

from openviper.http.response import HTMLResponse
from openviper.routing import Router


async def index(request, **kwargs):
    """Serve the React SPA for all frontend routes."""
    return HTMLResponse(template="index.html", context={})


router = Router()

# Serve React SPA for root and any non-API path (catch-all for SPA routing)
router.add("", index, namespace="index", methods=["GET"])
router.add("{path:path}", index, namespace="spa_catchall", methods=["GET"])
