"""OpenViper miniapp - Todo app with user authentication.

Run (from this directory)::

    openviper run app

On first startup a demo account is created automatically:

    username : demo
    password : demo1234
"""

from __future__ import annotations

# ── Bootstrap - must precede all OpenViper imports ────────────────────────────
import os
import sys
from functools import wraps
from importlib import import_module

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("OPENVIPER_SETTINGS_MODULE", "settings")

import openviper

openviper.setup(force=True)

# Register models with the admin panel (imports admin.py side-effects).
import_module("admin")

# Register Todo in SQLAlchemy metadata before init_db() runs.
import_module("models")
from models import Todo

# ── OpenViper imports (settings already loaded) ───────────────────────────────
from openviper import OpenViper
from openviper.admin import get_admin_site
from openviper.auth import authenticate, get_user_model, login, logout
from openviper.db import init_db
from openviper.exceptions import AuthenticationFailed
from openviper.http.request import Request  # noqa: TC001
from openviper.http.response import HTMLResponse, RedirectResponse

UserModel = get_user_model()

# ── App ───────────────────────────────────────────────────────────────────────

app = OpenViper(title="Miniapp - Todo", version="1.0.0")

app.include_router(get_admin_site(), prefix="/admin")


# ── Startup ───────────────────────────────────────────────────────────────────


@app.on_startup
async def startup() -> None:
    """Create tables and seed a demo user on first start."""
    await init_db()

    existing = await UserModel.objects.get_or_none(username="demo")
    if existing is None:
        user = UserModel(username="demo", email="demo@example.com")
        await user.set_password("demo1234")
        await user.save()
        print("[miniapp] Demo user created - username: demo  password: demo1234")


# ── Helpers ───────────────────────────────────────────────────────────────────


def is_authenticated_request(request: Request) -> bool:
    return getattr(request.user, "is_authenticated", False)


def redirect_to_login(next_url: str = "/todos") -> RedirectResponse:
    return RedirectResponse(url=f"/login?next={next_url}", status_code=303)


def require_auth(redirect_url: str = "/todos"):
    """Decorator that redirects unauthenticated requests to the login page."""

    def decorator(func):
        @wraps(func)
        async def wrapper(request: Request, **kwargs):
            if not is_authenticated_request(request):
                return redirect_to_login(redirect_url)
            return await func(request, **kwargs)

        return wrapper

    return decorator


# ── Root ──────────────────────────────────────────────────────────────────────


@app.get("/")
async def index(request: Request) -> RedirectResponse:
    if is_authenticated_request(request):
        return RedirectResponse(url="/todos", status_code=303)
    return RedirectResponse(url="/login", status_code=303)


# ── Auth ──────────────────────────────────────────────────────────────────────


@app.get("/login")
async def login_page(request: Request) -> HTMLResponse | RedirectResponse:
    if is_authenticated_request(request):
        return RedirectResponse(url="/todos", status_code=303)
    return HTMLResponse(
        template="login.html",
        context={
            "error": request.query_params.get("error", ""),
            "next": request.query_params.get("next", "/todos"),
        },
    )


@app.post("/login")
async def login_submit(request: Request) -> RedirectResponse:
    form = await request.form()
    username = str(form.get("username") or "").strip()
    password = str(form.get("password") or "")
    next_url = str(form.get("next") or "/todos")

    try:
        user = await authenticate(username=username, password=password)
    except AuthenticationFailed:
        user = None

    if user is None:
        return RedirectResponse(
            url="/login?error=Invalid+username+or+password",
            status_code=303,
        )

    response = RedirectResponse(url=next_url, status_code=303)
    await login(request, user, response)
    return response


@app.post("/logout")
async def logout_view(request: Request) -> RedirectResponse:
    await logout(request)
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("sessionid")
    return response


# ── Todos ─────────────────────────────────────────────────────────────────────


@app.get("/todos")
@require_auth("/todos")
async def todo_list(request: Request) -> HTMLResponse:
    todos = await Todo.objects.filter(owner_id=request.user.id).all()
    return HTMLResponse(
        template="todos.html",
        context={"user": request.user, "todos": todos},
    )


@app.post("/todos")
@require_auth("/todos")
async def todo_create(request: Request) -> RedirectResponse:
    form = await request.form()
    title = str(form.get("title") or "").strip()
    if title:
        await Todo(title=title, done=False, owner_id=request.user.id).save()
    return RedirectResponse(url="/todos", status_code=303)


@app.post("/todos/{todo_id}/toggle")
@require_auth("/todos")
async def todo_toggle(request: Request, todo_id: int) -> RedirectResponse:
    todo = await Todo.objects.get_or_none(id=todo_id, owner_id=request.user.id)
    if todo is not None:
        todo.done = not todo.done
        await todo.save()
    return RedirectResponse(url="/todos", status_code=303)


@app.post("/todos/{todo_id}/delete")
@require_auth("/todos")
async def todo_delete(request: Request, todo_id: int) -> RedirectResponse:
    todo = await Todo.objects.get_or_none(id=todo_id, owner_id=request.user.id)
    if todo is not None:
        await todo.delete()
    return RedirectResponse(url="/todos", status_code=303)
