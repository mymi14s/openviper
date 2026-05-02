import asyncio

from openviper.auth.utils import get_user_model


async def check_admin_user():
    # Ensure database is connected
    # Usually this is handled by the app startup, but we need it for the script
    # We'll try to use the default settings

    user_model = get_user_model()

    # Initialize DB if not already initialized
    # This depends on how OpenViper handles DB initialization
    # Let's try to just query first

    try:
        user = await user_model.objects.filter(username="admin").first()
        if user:
            print(f"User found: {user.username}")
            print(f"Is active: {user.is_active}")
            print(f"Is staff: {getattr(user, 'is_staff', 'N/A')}")
            print(f"Is superuser: {getattr(user, 'is_superuser', 'N/A')}")
            # We can't easily check password here without knowing the hasher,
            # but we can see if it's there
            print(f"Has password: {bool(user.password)}")
        else:
            print("User 'admin' not found.")
    except Exception as e:
        print(f"Error checking user: {e}")


if __name__ == "__main__":
    # We might need to set up the environment first
    # This is a bit tricky depending on how the app is configured
    # Let's try running it with viperctl or similar if available
    asyncio.run(check_admin_user())
