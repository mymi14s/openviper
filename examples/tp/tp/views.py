"""Views for tp."""

from openviper.http.response import HTMLResponse, JSONResponse
from openviper.routing import Router


async def home(request):
    """Home page view."""
    context = {
        "title": "Welcome to tp",
        "project_name": "tp",
        "message": "Your OpenViper project is running successfully.",
    }
    return HTMLResponse(template="home.html", context=context)


async def api_index(request):
    """API endpoint view that handles both GET and POST."""
    if request.method == "GET":
        return JSONResponse({"message": "Welcome to tp API!", "status": "success"})
    elif request.method == "POST":
        return JSONResponse({"message": "Data received", "status": "success", "method": "POST"})
    else:
        return JSONResponse({"error": "Method not allowed", "status": "error"}, status_code=405)


# Routes for apps should be in each app's routes.py file
router = Router()

# Default routes for tp
router.add("/home", home, namespace="home-view")
router.add("/api", api_index, namespace="api-view", methods=["GET", "POST"])
