"""Views for robotwit."""

from openviper.http.response import HTMLResponse, JSONResponse
from openviper.routing import Router


async def home(request):
    context = {
        "title": "Welcome to robotwit",
        "project_name": "robotwit",
        "message": "Your OpenViper project is running successfully.",
    }
    return HTMLResponse(template="home.html", context=context)


async def api_index(request):
    if request.method == "GET":
        return JSONResponse({"message": "Welcome to robotwit API!", "status": "success"})
    elif request.method == "POST":
        return JSONResponse({"message": "Data received", "status": "success", "method": "POST"})
    return JSONResponse({"error": "Method not allowed", "status": "error"}, status_code=405)


async def spa_index(request):
    return HTMLResponse(template="index.html")


router = Router()
router.add("/", spa_index, namespace="spa-index")
router.add("/home", home, namespace="home-view")
router.add("/api", api_index, namespace="api-view", methods=["GET", "POST"])
router.add("/{path:path}", spa_index, namespace="spa-catch-all")
