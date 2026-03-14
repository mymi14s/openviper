"""User authentication views."""

from __future__ import annotations

from datetime import UTC, datetime

from openviper.auth import get_user_model
from openviper.auth.jwt import create_access_token
from openviper.http import JSONResponse, Request, Response
from openviper.http.views import View

from .serializers import UserLoginSerializer, UserRegistrationSerializer, UserResponseSerializer

User = get_user_model()


def _user_to_dict(user: object) -> dict:
    return UserResponseSerializer(
        id=user.id,
        username=user.username,
        email=user.email,
        name=getattr(user, "name", None),
        address=getattr(user, "address", None),
        is_active=bool(user.is_active),
        created_at=user.created_at.isoformat() if getattr(user, "created_at", None) else None,
    ).serialize()


class RegisterView(View):
    """User registration endpoint."""

    async def post(self, request: Request) -> Response:
        data = await request.json()
        serializer = UserRegistrationSerializer.validate(data)

        if await User.objects.filter(username=serializer.username).first():
            return JSONResponse({"error": "Username already exists"}, status_code=400)

        if await User.objects.filter(email=serializer.email).first():
            return JSONResponse({"error": "Email already exists"}, status_code=400)

        user = User(
            username=serializer.username,
            email=serializer.email,
            name=getattr(serializer, "name", None),
            address=getattr(serializer, "address", None),
            is_active=True,
        )
        await user.set_password(serializer.password)
        await user.save()

        token = create_access_token(user.id, {"username": user.username})
        return JSONResponse(
            {"access_token": token, "token_type": "Bearer", "user": _user_to_dict(user)},
            status_code=201,
        )


class LoginView(View):
    """User login endpoint."""

    async def post(self, request: Request) -> Response:
        data = await request.json()
        serializer = UserLoginSerializer.validate(data)

        user = await User.objects.filter(username=serializer.username).first()
        if not user or not await user.check_password(serializer.password):
            return JSONResponse({"error": "Invalid credentials"}, status_code=401)

        if not user.is_active:
            return JSONResponse({"error": "Account is disabled"}, status_code=403)

        user.last_login = datetime.now(UTC)
        await user.save()

        token = create_access_token(user.id, {"username": user.username})
        return JSONResponse(
            {"access_token": token, "token_type": "Bearer", "user": _user_to_dict(user)}
        )


class ProfileView(View):
    """Get current user profile."""

    async def get(self, request: Request) -> Response:
        if not getattr(request, "user", None) or not request.user.is_authenticated:
            return JSONResponse({"error": "Authentication required"}, status_code=401)
        return JSONResponse(_user_to_dict(request.user))
