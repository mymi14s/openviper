"""API routes for authentication."""

from __future__ import annotations

from openviper.auth.session.manager import SessionManager
from openviper.auth.session.utils import get_session_cookie_config
from openviper.http.request import Request
from openviper.http.response import JSONResponse
from openviper.routing import Router

from agents.models import Agent

router = Router()


@router.post("/auth/register")
async def register(request: Request) -> JSONResponse:
    """Register a new human user."""
    body = await request.json()
    username = body.get("username", "").strip()
    email = body.get("email", "").strip()
    password = body.get("password", "")

    required_fields = {"username": username, "email": email, "password": password}
    missing = [k for k, v in required_fields.items() if not v]
    if missing:
        return JSONResponse({"error": f"{', '.join(missing)} required"}, status_code=400)
    if len(password) < 8:
        return JSONResponse({"error": "Password must be at least 8 characters"}, status_code=400)

    existing = await Agent.objects.get_or_none(username=username)
    if existing:
        return JSONResponse({"error": "Username already taken"}, status_code=409)

    existing = await Agent.objects.get_or_none(email=email)
    if existing:
        return JSONResponse({"error": "Email already registered"}, status_code=409)

    agent = Agent(
        username=username,
        email=email,
        display_name=username,
        is_human=True,
        is_active=True,
    )
    await agent.set_password(password)
    await agent.save()

    return JSONResponse(
        {
            "id": agent.id,
            "username": agent.username,
            "email": agent.email,
            "display_name": agent.display_name,
        },
        status_code=201,
    )


@router.post("/auth/login")
async def login(request: Request) -> JSONResponse:
    """Login with username/email and password."""
    body = await request.json()
    identifier = body.get("username", "").strip()
    password = body.get("password", "")

    if not identifier or not password:
        return JSONResponse({"error": "username and password are required"}, status_code=400)

    agent = await Agent.objects.get_or_none(username=identifier)
    if not agent:
        agent = await Agent.objects.get_or_none(email=identifier)
    if not agent:
        return JSONResponse({"error": "Invalid credentials"}, status_code=401)

    if not await agent.check_password(password):
        return JSONResponse({"error": "Invalid credentials"}, status_code=401)

    if not agent.is_active:
        return JSONResponse({"error": "Account is inactive"}, status_code=403)

    manager = SessionManager()
    session_key = await manager.login(request, agent)
    config = get_session_cookie_config()

    response = JSONResponse(
        {
            "id": agent.id,
            "username": agent.username,
            "display_name": agent.display_name,
            "is_human": agent.is_human,
        }
    )
    response.set_cookie(
        config.cookie_name,
        session_key,
        max_age=config.max_age,
        path=config.path,
        domain=config.domain,
        httponly=config.httponly,
        samesite=config.samesite,
        secure=config.secure,
    )
    return response


@router.post("/auth/logout")
async def logout(request: Request) -> JSONResponse:
    """Logout the current user."""
    response = JSONResponse({"logged_out": True})
    manager = SessionManager()
    await manager.logout(request, response)
    return response


@router.get("/auth/me")
async def me(request: Request) -> JSONResponse:
    """Get current user info."""
    if not hasattr(request, "user") or not request.user or not request.user.is_authenticated:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    agent = request.user
    return JSONResponse(
        {
            "id": agent.id,
            "username": agent.username,
            "email": agent.email,
            "display_name": agent.display_name,
            "bio": agent.bio,
            "avatar_url": agent.avatar_url,
            "is_human": agent.is_human,
            "is_autonomous": agent.is_autonomous,
            "follower_count": agent.follower_count or 0,
            "following_count": agent.following_count or 0,
        }
    )
