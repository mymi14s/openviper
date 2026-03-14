"""Standard OpenViper example — decorator-based routing.

Run::

    openviper run app
"""

from openviper import JSONResponse, OpenViper
from openviper.exceptions import NotFound
from openviper.http.request import Request

app = OpenViper(title="Standard Example API", version="1.0.0")

# ── In-memory store ───────────────────────────────────────────────────────────

_USERS: dict[int, dict] = {
    1: {"id": 1, "name": "Alice", "email": "alice@example.com"},
    2: {"id": 2, "name": "Bob", "email": "bob@example.com"},
}
_NEXT_ID = 3


# ── Lifecycle ─────────────────────────────────────────────────────────────────


@app.on_startup
async def startup() -> None:
    print("App started.")


# ── Routes ────────────────────────────────────────────────────────────────────


@app.get("/")
async def index(request: Request) -> JSONResponse:
    return JSONResponse({"message": "Hello, OpenViper!"})


@app.get("/health")
async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


@app.get("/users")
async def list_users(request: Request) -> JSONResponse:
    return JSONResponse({"users": list(_USERS.values())})


@app.get("/users/{user_id}")
async def get_user(request: Request, user_id: int) -> JSONResponse:
    user = _USERS.get(user_id)
    if not user:
        raise NotFound(f"User {user_id} not found.")
    return JSONResponse(user)


@app.post("/users")
async def create_user(request: Request) -> JSONResponse:
    global _NEXT_ID
    body = await request.json()
    user = {"id": _NEXT_ID, **body}
    _USERS[_NEXT_ID] = user
    _NEXT_ID += 1
    return JSONResponse(user, status_code=201)


@app.patch("/users/{user_id}")
async def update_user(request: Request, user_id: int) -> JSONResponse:
    user = _USERS.get(user_id)
    if not user:
        raise NotFound(f"User {user_id} not found.")
    user.update(await request.json())
    return JSONResponse(user)


@app.delete("/users/{user_id}")
async def delete_user(request: Request, user_id: int) -> JSONResponse:
    if user_id not in _USERS:
        raise NotFound(f"User {user_id} not found.")
    del _USERS[user_id]
    return JSONResponse({"deleted": True, "id": user_id})
