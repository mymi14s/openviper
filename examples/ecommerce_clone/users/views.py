"""User authentication views."""

from __future__ import annotations

from datetime import UTC, datetime

from openviper.auth import get_user_model
from openviper.auth.jwt import create_access_token
from openviper.http import JSONResponse, Request, Response
from openviper.http.views import View

from .serializers import UserLoginSerializer, UserRegistrationSerializer, UserResponseSerializer

UserModel = get_user_model()


def user_to_dict(user: object) -> dict[str, object]:
    return UserResponseSerializer.from_orm(user).serialize()


class RegisterView(View):
    """User registration endpoint."""

    async def post(self, request: Request) -> Response:
        data = await request.json()
        serializer = UserRegistrationSerializer.validate(data)

        if await UserModel.objects.filter(username=serializer.username).first():
            return JSONResponse({"error": "Username already exists"}, status_code=400)

        if await UserModel.objects.filter(email=serializer.email).first():
            return JSONResponse({"error": "Email already exists"}, status_code=400)

        user = UserModel(
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
            {"access_token": token, "token_type": "Bearer", "user": user_to_dict(user)},
            status_code=201,
        )


class LoginView(View):
    """User login endpoint."""

    async def post(self, request: Request) -> Response:
        data = await request.json()
        serializer = UserLoginSerializer.validate(data)

        user = await UserModel.objects.filter(username=serializer.username).first()
        if not user or not await user.check_password(serializer.password):
            return JSONResponse({"error": "Invalid credentials"}, status_code=401)

        if not user.is_active:
            return JSONResponse({"error": "Account is disabled"}, status_code=403)

        user.last_login = datetime.now(UTC)
        await user.save()

        token = create_access_token(user.id, {"username": user.username})
        return JSONResponse(
            {"access_token": token, "token_type": "Bearer", "user": user_to_dict(user)}
        )


class ProfileView(View):
    """Get current user profile."""

    async def get(self, request: Request) -> Response:
        if not getattr(request, "user", None) or not request.user.is_authenticated:
            return JSONResponse({"error": "Authentication required"}, status_code=401)
        return JSONResponse(user_to_dict(request.user))
