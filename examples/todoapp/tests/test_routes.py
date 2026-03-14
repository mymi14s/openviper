"""Integration tests — all HTTP routes (100 % branch coverage)."""

from __future__ import annotations

import pytest
from models import Todo

# ── GET / ─────────────────────────────────────────────────────────────────────


async def test_root_unauthenticated(client):
    resp = await client.get("/", follow_redirects=False)
    assert resp.status_code == 303
    assert "/login" in resp.headers["location"]


async def test_root_authenticated(auth_client):
    resp = await auth_client.get("/", follow_redirects=False)
    assert resp.status_code == 303
    assert "/todos" in resp.headers["location"]


# ── GET /login ────────────────────────────────────────────────────────────────


async def test_login_page_unauthenticated(client):
    resp = await client.get("/login")
    assert resp.status_code == 200


async def test_login_page_with_query_params(client):
    """error= and next= params are rendered without raising."""
    resp = await client.get("/login?error=bad+credentials&next=/todos")
    assert resp.status_code == 200


async def test_login_page_authenticated_redirects(auth_client):
    resp = await auth_client.get("/login", follow_redirects=False)
    assert resp.status_code == 303
    assert "/todos" in resp.headers["location"]


# ── POST /login ───────────────────────────────────────────────────────────────


async def test_login_success_sets_cookie(client, user):
    resp = await client.post(
        "/login",
        data={"username": "testuser", "password": "pass1234"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "/todos" in resp.headers["location"]
    assert "sessionid" in resp.cookies


async def test_login_success_custom_next(client, user):
    resp = await client.post(
        "/login",
        data={"username": "testuser", "password": "pass1234", "next": "/todos"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "/todos" in resp.headers["location"]


async def test_login_bad_credentials_redirects_with_error(client):
    resp = await client.post(
        "/login",
        data={"username": "nobody", "password": "wrong"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "error" in resp.headers["location"]


# ── POST /logout ──────────────────────────────────────────────────────────────


async def test_logout_redirects_to_login(auth_client):
    resp = await auth_client.post("/logout", follow_redirects=False)
    assert resp.status_code == 303
    assert "/login" in resp.headers["location"]


# ── Protected routes — unauthenticated ────────────────────────────────────────


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/todos"),
        ("post", "/todos"),
        ("post", "/todos/1/toggle"),
        ("post", "/todos/1/delete"),
    ],
)
async def test_protected_routes_redirect_unauthenticated(client, method, path):
    resp = await getattr(client, method)(path, follow_redirects=False)
    assert resp.status_code == 303
    assert "/login" in resp.headers["location"]


# ── GET /todos ────────────────────────────────────────────────────────────────


async def test_todo_list_empty(auth_client):
    resp = await auth_client.get("/todos")
    assert resp.status_code == 200


async def test_todo_list_with_items(auth_client, user):
    await Todo(title="Existing item", done=False, owner_id=user.id).save()
    resp = await auth_client.get("/todos")
    assert resp.status_code == 200


# ── POST /todos (create) ──────────────────────────────────────────────────────


async def test_todo_create_valid_title(auth_client, user):
    resp = await auth_client.post("/todos", data={"title": "Do laundry"}, follow_redirects=False)
    assert resp.status_code == 303
    todos = await Todo.objects.filter(owner_id=user.id).all()
    assert len(todos) == 1
    assert todos[0].title == "Do laundry"


async def test_todo_create_empty_title_no_insert(auth_client, user):
    resp = await auth_client.post("/todos", data={"title": "   "}, follow_redirects=False)
    assert resp.status_code == 303
    todos = await Todo.objects.filter(owner_id=user.id).all()
    assert len(todos) == 0


# ── POST /todos/{id}/toggle ───────────────────────────────────────────────────


async def test_todo_toggle_found(auth_client, user):
    await Todo(title="Toggle me", done=False, owner_id=user.id).save()
    todo = (await Todo.objects.filter(owner_id=user.id).all())[0]

    resp = await auth_client.post(f"/todos/{todo.id}/toggle", follow_redirects=False)
    assert resp.status_code == 303
    updated = await Todo.objects.get_or_none(id=todo.id)
    assert updated.done is True

    # Toggle back
    resp = await auth_client.post(f"/todos/{todo.id}/toggle", follow_redirects=False)
    assert resp.status_code == 303
    updated = await Todo.objects.get_or_none(id=todo.id)
    assert updated.done is False


async def test_todo_toggle_not_found_is_safe(auth_client):
    resp = await auth_client.post("/todos/99999/toggle", follow_redirects=False)
    assert resp.status_code == 303


# ── POST /todos/{id}/delete ───────────────────────────────────────────────────


async def test_todo_delete_found(auth_client, user):
    await Todo(title="Delete me", done=False, owner_id=user.id).save()
    todo = (await Todo.objects.filter(owner_id=user.id).all())[0]

    resp = await auth_client.post(f"/todos/{todo.id}/delete", follow_redirects=False)
    assert resp.status_code == 303
    assert await Todo.objects.get_or_none(id=todo.id) is None


async def test_todo_delete_not_found_is_safe(auth_client):
    resp = await auth_client.post("/todos/99999/delete", follow_redirects=False)
    assert resp.status_code == 303
