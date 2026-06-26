"""Standard OpenViper example - decorator-based routing.

Run::

    openviper run app
"""

from openviper import JSONResponse, OpenViper
from openviper.exceptions import NotFound
from openviper.http.request import Request  # noqa: TC001

app = OpenViper(title="Standard Example API", version="1.0.0")

USER_FIELDS = frozenset({"name", "email"})

USERS: dict[int, dict[str, object]] = {
    1: {"id": 1, "name": "Alice", "email": "alice@example.com"},
    2: {"id": 2, "name": "Bob", "email": "bob@example.com"},
}
next_user_id = 3


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
    return JSONResponse({"users": list(USERS.values())})


@app.get("/users/{user_id}")
async def get_user(request: Request, user_id: int) -> JSONResponse:
    user = USERS.get(user_id)
    if not user:
        raise NotFound(f"User {user_id} not found.")
    return JSONResponse(user)


@app.post("/users")
async def create_user(request: Request) -> JSONResponse:
    global next_user_id
    body = await request.json()
    user: dict[str, object] = {"id": next_user_id}
    user.update({field: body[field] for field in USER_FIELDS if field in body})
    USERS[next_user_id] = user
    next_user_id += 1
    return JSONResponse(user, status_code=201)


@app.patch("/users/{user_id}")
async def update_user(request: Request, user_id: int) -> JSONResponse:
    user = USERS.get(user_id)
    if not user:
        raise NotFound(f"User {user_id} not found.")
    body = await request.json()
    user.update({field: body[field] for field in USER_FIELDS if field in body})
    return JSONResponse(user)


@app.delete("/users/{user_id}")
async def delete_user(request: Request, user_id: int) -> JSONResponse:
    if user_id not in USERS:
        raise NotFound(f"User {user_id} not found.")
    del USERS[user_id]
    return JSONResponse({"deleted": True, "id": user_id})
