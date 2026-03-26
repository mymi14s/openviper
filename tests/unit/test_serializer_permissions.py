from unittest.mock import MagicMock

import pytest

from openviper.exceptions import PermissionDenied
from openviper.http.permissions import BasePermission
from openviper.serializers import Serializer


class DenyAll(BasePermission):
    async def has_permission(self, request, view):
        return False


class AllowAll(BasePermission):
    async def has_permission(self, request, view):
        return True


class MockSerializer(Serializer):
    name: str


@pytest.mark.asyncio
class TestSerializerPermissions:
    async def test_permission_denied(self):
        class RestrictedSerializer(MockSerializer):
            permission_classes = [DenyAll]

        serializer = RestrictedSerializer(name="test", _context={"request": MagicMock()})
        with pytest.raises(PermissionDenied):
            await serializer.check_permissions()

    async def test_permission_allowed(self):
        class OpenSerializer(MockSerializer):
            permission_classes = [AllowAll]

        serializer = OpenSerializer(name="test", _context={"request": MagicMock()})
        await serializer.check_permissions()  # Should not raise

    async def test_validate_with_context(self):
        # Verify that context is correctly passed through validate
        context = {"request": "fake_request"}
        serializer = MockSerializer.validate({"name": "test"}, context=context)
        assert serializer.context == context

    async def test_check_permissions_without_request(self):
        # Should fallback to current_user context if request is missing
        class RestrictedSerializer(MockSerializer):
            permission_classes = [DenyAll]

        from openviper.core.context import current_user

        fake_user = MagicMock()
        token = current_user.set(fake_user)
        try:
            serializer = RestrictedSerializer(name="test")
            with pytest.raises(PermissionDenied):
                await serializer.check_permissions()
        finally:
            current_user.reset(token)
