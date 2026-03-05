"""User authentication views."""

from __future__ import annotations

from datetime import UTC, datetime

from openviper.auth import get_user_model
from openviper.auth.jwt import create_access_token
from openviper.auth.models import Role
from openviper.http import JSONResponse, Request, Response
from openviper.http.views import View

from .serializers import (
    UserLoginSerializer,
    UserRegistrationSerializer,
    UserResponseSerializer,
)

User = get_user_model()


class RegisterView(View):
    """User registration endpoint."""

    async def post(self, request: Request) -> Response:
        """Register a new user."""
        data = await request.json()
        serializer = UserRegistrationSerializer.validate(data)

        # Check if username exists
        existing_user = await User.objects.filter(username=serializer.username).first()
        if existing_user:
            return JSONResponse({"error": "Username already exists"}, status_code=400)

        # Check if email exists
        existing_email = await User.objects.filter(email=serializer.email).first()
        if existing_email:
            return JSONResponse({"error": "Email already exists"}, status_code=400)

        # Create user
        user = User(
            username=serializer.username,
            email=serializer.email,
            first_name=getattr(serializer, "first_name", ""),
            last_name=getattr(serializer, "last_name", ""),
            is_active=True,
        )
        user.set_password(serializer.password)
        await user.save()

        # Assign default "user" role

        user_role = await Role.objects.filter(name="user").first()
        if user_role:
            await user.assign_role(user_role)

        # Generate JWT token
        token = create_access_token(user.id, {"username": user.username})

        user_data = UserResponseSerializer(
            id=user.id,
            username=user.username,
            email=user.email,
            first_name=user.first_name or "",
            last_name=user.last_name or "",
            is_active=str(user.is_active),
            created_at=user.created_at.isoformat() if user.created_at else "",
        ).serialize()

        return JSONResponse(
            {
                "access_token": token,
                "token_type": "Bearer",
                "user": user_data,
            },
            status_code=201,
        )


class LoginView(View):
    """User login endpoint."""

    async def post(self, request: Request) -> Response:
        """Authenticate user and return JWT token."""
        data = await request.json()
        serializer = UserLoginSerializer.validate(data)

        # Find user
        user = await User.objects.filter(username=serializer.username).first()
        if not user:
            return JSONResponse({"error": "Invalid credentials"}, status_code=401)

        # Check password
        if not user.check_password(serializer.password):
            return JSONResponse({"error": "Invalid credentials"}, status_code=401)

        # Check if user is active
        if not user.is_active:
            return JSONResponse({"error": "Account is disabled"}, status_code=403)

        # Update last login
        user.last_login = datetime.now(UTC)
        await user.save()

        # Generate JWT token
        token = create_access_token(user.id, {"username": user.username})

        user_data = UserResponseSerializer(
            id=user.id,
            username=user.username,
            email=user.email,
            first_name=user.first_name or "",
            last_name=user.last_name or "",
            is_active=str(user.is_active),
            created_at=user.created_at.isoformat() if user.created_at else "",
        ).serialize()

        return JSONResponse(
            {
                "access_token": token,
                "token_type": "Bearer",
                "user": user_data,
            }
        )


class MeView(View):
    """Get current user information."""

    async def get(self, request: Request) -> Response:
        """Get current authenticated user."""
        if not hasattr(request, "user") or not request.user or not request.user.is_authenticated:
            return JSONResponse({"error": "Authentication required"}, status_code=401)

        user = request.user
        user_data = UserResponseSerializer(
            id=user.id,
            username=user.username,
            email=user.email,
            first_name=user.first_name or "",
            last_name=user.last_name or "",
            is_active=str(user.is_active),
            created_at=user.created_at.isoformat() if user.created_at else "",
        ).serialize()

        return JSONResponse(user_data)
