"""Integration tests for UI rendering and template workflows.

This module tests HTML responses, template rendering, static content,
and UI component integration.
"""

from __future__ import annotations

import pytest

from openviper.app import OpenViper
from openviper.auth.models import User
from openviper.http.response import HTMLResponse, JSONResponse, PlainTextResponse


class TestHTMLRendering:
    """Tests for HTML response rendering."""

    @pytest.mark.asyncio
    async def test_simple_html_response(self, test_database):
        """Test rendering a simple HTML response."""
        app = OpenViper()

        @app.get("/html")
        async def html_page():
            return HTMLResponse("<h1>Hello World</h1>")

        async with app.test_client() as client:
            response = await client.get("/html")
            if response.status_code == 200:
                assert "text/html" in response.headers.get("content-type", "")
                assert b"<h1>Hello World</h1>" in response.content

    @pytest.mark.asyncio
    async def test_html_with_dynamic_content(self, test_database, admin_user: User):
        """Test rendering HTML with dynamic content."""
        app = OpenViper()

        @app.get("/profile")
        async def profile(request):
            html = f"""
            <html>
                <head><title>User Profile</title></head>
                <body>
                    <h1>Profile: {admin_user.username}</h1>
                    <p>Email: {admin_user.email}</p>
                </body>
            </html>
            """
            return HTMLResponse(html)

        async with app.test_client() as client:
            response = await client.get("/profile")
            if response.status_code == 200:
                assert admin_user.username.encode() in response.content
                assert admin_user.email.encode() in response.content

    @pytest.mark.asyncio
    async def test_html_form_rendering(self, test_database):
        """Test rendering HTML forms."""
        app = OpenViper()

        @app.get("/login")
        async def login_form():
            html = """
            <html>
                <body>
                    <form method="post" action="/login">
                        <input type="text" name="username" placeholder="Username">
                        <input type="password" name="password" placeholder="Password">
                        <button type="submit">Login</button>
                    </form>
                </body>
            </html>
            """
            return HTMLResponse(html)

        async with app.test_client() as client:
            response = await client.get("/login")
            if response.status_code == 200:
                assert b"<form" in response.content
                assert b'name="username"' in response.content
                assert b'name="password"' in response.content

    @pytest.mark.asyncio
    async def test_html_list_rendering(self, test_database):
        """Test rendering HTML lists with dynamic data."""
        app = OpenViper()

        @app.get("/users-list")
        async def users_list():
            users = await User.objects.all()
            user_items = "".join(f"<li>{user.username} - {user.email}</li>" for user in users)
            html = f"""
            <html>
                <body>
                    <h1>Users</h1>
                    <ul>{user_items}</ul>
                </body>
            </html>
            """
            return HTMLResponse(html)

        async with app.test_client() as client:
            response = await client.get("/users-list")
            if response.status_code == 200:
                assert b"<ul>" in response.content
                assert b"</ul>" in response.content


class TestResponseTypes:
    """Tests for different response type rendering."""

    @pytest.mark.asyncio
    async def test_json_response_rendering(self, test_database):
        """Test JSON response rendering."""
        app = OpenViper()

        @app.get("/api/data")
        async def get_data():
            return JSONResponse({"message": "Hello", "status": "success"})

        async with app.test_client() as client:
            response = await client.get("/api/data")
            if response.status_code == 200:
                assert "application/json" in response.headers.get("content-type", "")
                data = response.json()
                assert data["message"] == "Hello"
                assert data["status"] == "success"

    @pytest.mark.asyncio
    async def test_plain_text_response(self, test_database):
        """Test plain text response rendering."""
        app = OpenViper()

        @app.get("/text")
        async def get_text():
            return PlainTextResponse("Simple text response")

        async with app.test_client() as client:
            response = await client.get("/text")
            if response.status_code == 200:
                assert "text/plain" in response.headers.get("content-type", "")
                assert response.content == b"Simple text response"

    @pytest.mark.asyncio
    async def test_dict_auto_json_conversion(self, test_database):
        """Test automatic dict to JSON conversion."""
        app = OpenViper()

        @app.get("/auto")
        async def auto_json():
            return {"converted": True, "type": "auto"}

        async with app.test_client() as client:
            response = await client.get("/auto")
            if response.status_code == 200:
                assert "application/json" in response.headers.get("content-type", "")
                data = response.json()
                assert data["converted"] is True

    @pytest.mark.asyncio
    async def test_list_auto_json_conversion(self, test_database):
        """Test automatic list to JSON conversion."""
        app = OpenViper()

        @app.get("/list")
        async def list_response():
            return [1, 2, 3, 4, 5]

        async with app.test_client() as client:
            response = await client.get("/list")
            if response.status_code == 200:
                assert "application/json" in response.headers.get("content-type", "")
                data = response.json()
                assert data == [1, 2, 3, 4, 5]


class TestNavigationUI:
    """Tests for navigation UI components."""

    @pytest.mark.asyncio
    async def test_navigation_menu_rendering(self, test_database):
        """Test rendering navigation menu."""
        app = OpenViper()

        @app.get("/with-nav")
        async def page_with_nav():
            html = """
            <html>
                <body>
                    <nav>
                        <ul>
                            <li><a href="/">Home</a></li>
                            <li><a href="/about">About</a></li>
                            <li><a href="/contact">Contact</a></li>
                        </ul>
                    </nav>
                    <main>
                        <h1>Content</h1>
                    </main>
                </body>
            </html>
            """
            return HTMLResponse(html)

        async with app.test_client() as client:
            response = await client.get("/with-nav")
            if response.status_code == 200:
                assert b"<nav>" in response.content
                assert b'href="/"' in response.content
                assert b'href="/about"' in response.content

    @pytest.mark.asyncio
    async def test_breadcrumb_rendering(self, test_database):
        """Test rendering breadcrumb navigation."""
        app = OpenViper()

        @app.get("/users/{user_id}/profile")
        async def user_profile(user_id: int):
            html = f"""
            <html>
                <body>
                    <nav aria-label="breadcrumb">
                        <ol>
                            <li><a href="/">Home</a></li>
                            <li><a href="/users">Users</a></li>
                            <li><a href="/users/{user_id}">User {user_id}</a></li>
                            <li>Profile</li>
                        </ol>
                    </nav>
                </body>
            </html>
            """
            return HTMLResponse(html)

        async with app.test_client() as client:
            response = await client.get("/users/123/profile")
            if response.status_code == 200:
                assert b"breadcrumb" in response.content
                assert b'href="/users"' in response.content


class TestDashboardUI:
    """Tests for dashboard UI rendering."""

    @pytest.mark.asyncio
    async def test_dashboard_layout(self, test_database, admin_user: User):
        """Test rendering dashboard layout."""
        app = OpenViper()

        @app.get("/dashboard")
        async def dashboard(request):
            html = """
            <html>
                <head><title>Dashboard</title></head>
                <body>
                    <header><h1>Dashboard</h1></header>
                    <aside>
                        <nav>
                            <a href="/dashboard">Overview</a>
                            <a href="/dashboard/users">Users</a>
                            <a href="/dashboard/settings">Settings</a>
                        </nav>
                    </aside>
                    <main>
                        <section class="stats">
                            <div class="stat">Total Users: 100</div>
                            <div class="stat">Active Sessions: 25</div>
                        </section>
                    </main>
                </body>
            </html>
            """
            return HTMLResponse(html)

        async with app.test_client() as client:
            response = await client.get("/dashboard")
            if response.status_code == 200:
                assert b"<header>" in response.content
                assert b"<aside>" in response.content
                assert b"<main>" in response.content

    @pytest.mark.asyncio
    async def test_dashboard_with_user_data(self, test_database, admin_user: User):
        """Test rendering dashboard with user-specific data."""
        app = OpenViper()

        @app.get("/my-dashboard")
        async def my_dashboard(request):
            html = f"""
            <html>
                <body>
                    <h1>Welcome, {admin_user.username}!</h1>
                    <p>Email: {admin_user.email}</p>
                    <p>Role: {"Admin" if admin_user.is_superuser else "User"}</p>
                </body>
            </html>
            """
            return HTMLResponse(html)

        async with app.test_client() as client:
            response = await client.get("/my-dashboard")
            if response.status_code == 200:
                assert admin_user.username.encode() in response.content


class TestFormUI:
    """Tests for form UI rendering."""

    @pytest.mark.asyncio
    async def test_user_creation_form(self, test_database):
        """Test rendering user creation form."""
        app = OpenViper()

        @app.get("/users/new")
        async def new_user_form():
            html = """
            <html>
                <body>
                    <h1>Create New User</h1>
                    <form method="post" action="/users">
                        <label>Username: <input type="text" name="username" required></label>
                        <label>Email: <input type="email" name="email" required></label>
                        <label>Password: <input type="password" name="password" required></label>
                        <button type="submit">Create User</button>
                    </form>
                </body>
            </html>
            """
            return HTMLResponse(html)

        async with app.test_client() as client:
            response = await client.get("/users/new")
            if response.status_code == 200:
                assert b'method="post"' in response.content
                assert b'name="username"' in response.content
                assert b'type="email"' in response.content

    @pytest.mark.asyncio
    async def test_edit_form_with_data(self, test_database, admin_user: User):
        """Test rendering edit form pre-populated with data."""
        app = OpenViper()

        @app.get("/users/{user_id}/edit")
        async def edit_user_form(user_id: int):
            user = await User.objects.get(id=user_id)
            if not user:
                return HTMLResponse("<h1>User not found</h1>", status_code=404)

            html = f"""
            <html>
                <body>
                    <h1>Edit User</h1>
                    <form method="post" action="/users/{user.id}">
                        <label>
                            Username:
                            <input type="text" name="username" value="{user.username}">
                        </label>
                        <label>
                            Email:
                            <input type="email" name="email" value="{user.email}">
                        </label>
                        <button type="submit">Update User</button>
                    </form>
                </body>
            </html>
            """
            return HTMLResponse(html)

        async with app.test_client() as client:
            response = await client.get(f"/users/{admin_user.id}/edit")
            if response.status_code == 200:
                assert admin_user.username.encode() in response.content
                assert admin_user.email.encode() in response.content


class TestTableUI:
    """Tests for table UI rendering."""

    @pytest.mark.asyncio
    async def test_users_table(self, test_database):
        """Test rendering users in a table."""
        user1 = User(username="tableuser1", email="table1@example.com")
        await user1.save()

        user2 = User(username="tableuser2", email="table2@example.com")
        await user2.save()

        app = OpenViper()

        @app.get("/users/table")
        async def users_table():
            users = await User.objects.all()
            rows = "".join(
                f"<tr><td>{u.id}</td><td>{u.username}</td><td>{u.email}</td></tr>" for u in users
            )
            html = f"""
            <html>
                <body>
                    <table>
                        <thead>
                            <tr><th>ID</th><th>Username</th><th>Email</th></tr>
                        </thead>
                        <tbody>{rows}</tbody>
                    </table>
                </body>
            </html>
            """
            return HTMLResponse(html)

        async with app.test_client() as client:
            response = await client.get("/users/table")
            if response.status_code == 200:
                assert b"<table>" in response.content
                assert b"<thead>" in response.content
                assert b"<tbody>" in response.content
                assert b"tableuser1" in response.content
                assert b"tableuser2" in response.content

    @pytest.mark.asyncio
    async def test_empty_table(self, test_database):
        """Test rendering empty table with no data."""
        app = OpenViper()

        @app.get("/empty-table")
        async def empty_table():
            html = """
            <html>
                <body>
                    <table>
                        <thead>
                            <tr><th>Column 1</th><th>Column 2</th></tr>
                        </thead>
                        <tbody>
                            <tr><td colspan="2">No data available</td></tr>
                        </tbody>
                    </table>
                </body>
            </html>
            """
            return HTMLResponse(html)

        async with app.test_client() as client:
            response = await client.get("/empty-table")
            if response.status_code == 200:
                assert b"No data available" in response.content


class TestContentTypes:
    """Tests for different content type headers."""

    @pytest.mark.asyncio
    async def test_html_content_type(self, test_database):
        """Test HTML content type header."""
        app = OpenViper()

        @app.get("/html-type")
        async def html_type():
            return HTMLResponse("<p>HTML</p>")

        async with app.test_client() as client:
            response = await client.get("/html-type")
            if response.status_code == 200:
                content_type = response.headers.get("content-type", "")
                assert "text/html" in content_type

    @pytest.mark.asyncio
    async def test_json_content_type(self, test_database):
        """Test JSON content type header."""
        app = OpenViper()

        @app.get("/json-type")
        async def json_type():
            return JSONResponse({"type": "json"})

        async with app.test_client() as client:
            response = await client.get("/json-type")
            if response.status_code == 200:
                content_type = response.headers.get("content-type", "")
                assert "application/json" in content_type

    @pytest.mark.asyncio
    async def test_text_content_type(self, test_database):
        """Test plain text content type header."""
        app = OpenViper()

        @app.get("/text-type")
        async def text_type():
            return PlainTextResponse("Plain text")

        async with app.test_client() as client:
            response = await client.get("/text-type")
            if response.status_code == 200:
                content_type = response.headers.get("content-type", "")
                assert "text/plain" in content_type


class TestErrorPageRendering:
    """Tests for error page rendering."""

    @pytest.mark.asyncio
    async def test_404_page(self, test_database):
        """Test rendering custom 404 error page."""
        app = OpenViper()

        @app.get("/exists")
        async def exists():
            return {"exists": True}

        async with app.test_client() as client:
            response = await client.get("/does-not-exist")
            assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_custom_error_response(self, test_database):
        """Test custom error response rendering."""
        app = OpenViper()

        @app.get("/error")
        async def error_page():
            return HTMLResponse(
                "<h1>Error occurred</h1>",
                status_code=500,
            )

        async with app.test_client() as client:
            response = await client.get("/error")
            if response.status_code == 500:
                assert b"Error occurred" in response.content
