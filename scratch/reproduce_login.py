import asyncio

from openviper.auth.models import User
from openviper.db.connection import get_metadata
from openviper.db.models import Q
from tests.factories.db import create_test_engine


async def reproduce():
    # Setup test DB
    engine = await create_test_engine()
    metadata = get_metadata()
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)

    # Create admin user
    admin = User(
        username="admin",
        email="admin@example.com",
        is_active=True,
        is_superuser=True,
        is_staff=True,
    )
    await admin.set_password("admin")
    await admin.save()

    print(f"Admin created: {admin.pk}")

    # Try to authenticate
    from openviper.auth.backends import authenticate

    user = await authenticate("admin", "admin")
    print(f"Authenticated user: {user}")

    if user is None:
        print("AUTHENTICATION FAILED!")
        # Debug why
        u = await User.objects.filter(
            Q(username="admin") | Q(email="admin"),
            is_active=True,
            ignore_permissions=True,
        ).first()
        print(f"Manual lookup result: {u}")
    else:
        print("AUTHENTICATION SUCCESSFUL!")


if __name__ == "__main__":
    asyncio.run(reproduce())
