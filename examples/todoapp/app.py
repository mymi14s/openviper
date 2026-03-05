"""OpenViper miniapp — Todo app with user authentication.

Run (from this directory)::

    openviper run app

On first startup a demo account is created automatically:

    username : demo
    password : demo1234
"""

from __future__ import annotations

# ── Bootstrap — must precede all OpenViper imports ────────────────────────────
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("OPENVIPER_SETTINGS_MODULE", "settings")

import openviper  # noqa: E402

openviper.setup(force=True)

# Register models with the admin panel (imports admin.py side-effects).
from typing import TYPE_CHECKING  # noqa: E402

import admin  # noqa: E402, F401

# Register Todo in SQLAlchemy metadata before init_db() runs.
import models  # noqa: E402, F401

# ── OpenViper imports (settings already loaded) ───────────────────────────────
from openviper import OpenViper  # noqa: E402
from openviper.admin import get_admin_site  # noqa: E402
from openviper.auth import get_user_model  # noqa: E402
from openviper.auth.backends import authenticate, login, logout  # noqa: E402
from openviper.db import init_db  # noqa: E402
from openviper.exceptions import AuthenticationFailed  # noqa: E402
from openviper.http.response import HTMLResponse, RedirectResponse  # noqa: E402

if TYPE_CHECKING:
    from openviper.http.request import Request

User = get_user_model()

# ── App ───────────────────────────────────────────────────────────────────────

app = OpenViper(title="Miniapp — Todo", version="1.0.0")

app.include_router(get_admin_site(), prefix="/admin")


# ── Startup ───────────────────────────────────────────────────────────────────


@app.on_startup
async def startup() -> None:
    """Create tables and seed a demo user on first start."""
    await init_db()

    existing = await User.objects.get_or_none(username="demo")
    if existing is None:
        user = User(username="demo", email="demo@example.com")
        user.set_password("demo1234")
        await user.save()
        print("[miniapp] Demo user created — username: demo  password: demo1234")


# ── Helpers ───────────────────────────────────────────────────────────────────


def _is_authenticated(request: Request) -> bool:
    return getattr(request.user, "is_authenticated", False)


def _redirect_to_login(next_url: str = "/todos") -> RedirectResponse:
    return RedirectResponse(url=f"/login?next={next_url}", status_code=303)


# ── Root ──────────────────────────────────────────────────────────────────────


@app.get("/")
async def index(request: Request) -> RedirectResponse:
    if _is_authenticated(request):
        return RedirectResponse(url="/todos", status_code=303)
    return RedirectResponse(url="/login", status_code=303)


# ── Auth ──────────────────────────────────────────────────────────────────────


@app.get("/login")
async def login_page(request: Request) -> HTMLResponse | RedirectResponse:
    if _is_authenticated(request):
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
    except (AuthenticationFailed, Exception):
        return RedirectResponse(
            url="/login?error=Invalid+username+or+password",
            status_code=303,
        )

    session_key = await login(request, user)
    response = RedirectResponse(url=next_url, status_code=303)
    response.set_cookie("sessionid", session_key, httponly=True, samesite="lax")
    return response


@app.post("/logout")
async def logout_view(request: Request) -> RedirectResponse:
    await logout(request)
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("sessionid")
    return response


# ── Todos ─────────────────────────────────────────────────────────────────────


@app.get("/todos")
async def todo_list(request: Request) -> HTMLResponse | RedirectResponse:
    if not _is_authenticated(request):
        return _redirect_to_login("/todos")

    from models import Todo

    todos = await Todo.objects.filter(owner_id=request.user.id).all()
    return HTMLResponse(
        template="todos.html",
        context={"user": request.user, "todos": todos},
    )


@app.post("/todos")
async def todo_create(request: Request) -> RedirectResponse:
    if not _is_authenticated(request):
        return _redirect_to_login("/todos")

    form = await request.form()
    title = str(form.get("title") or "").strip()
    if title:
        from models import Todo

        await Todo(title=title, done=False, owner_id=request.user.id).save()
    return RedirectResponse(url="/todos", status_code=303)


@app.post("/todos/{todo_id}/toggle")
async def todo_toggle(request: Request, todo_id: int) -> RedirectResponse:
    if not _is_authenticated(request):
        return _redirect_to_login("/todos")

    from models import Todo

    todo = await Todo.objects.get_or_none(id=todo_id, owner_id=request.user.id)
    if todo is not None:
        todo.done = not todo.done
        await todo.save()
    return RedirectResponse(url="/todos", status_code=303)


@app.post("/todos/{todo_id}/delete")
async def todo_delete(request: Request, todo_id: int) -> RedirectResponse:
    if not _is_authenticated(request):
        return _redirect_to_login("/todos")

    from models import Todo

    todo = await Todo.objects.get_or_none(id=todo_id, owner_id=request.user.id)
    if todo is not None:
        await todo.delete()
    return RedirectResponse(url="/todos", status_code=303)
